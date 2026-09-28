"""Durable latest-snapshot delivery, independently driven from training.

A pending snapshot survives failure/restart. Newer source snapshots coalesce while
it is pending. Confirm only after remote file/hash AND scalar readback. At-least-once
W&B history is possible after an ambiguous failure: dedup by snapshot_id.
"""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from .publication import publication_run_id
from .monitoring_files import atomic_json
from .monitoring_io import load_snapshot
from .outcomes import require, write_snapshot


def position(value):
    return value['watermark'], value['snapshot_at']


def receipt(value):
    result = {key: value[key] for key in ('run_id', 'synthetic', 'snapshot_id', 'watermark', 'snapshot_at')}
    if value.get('publication'):
        result['publication'] = value['publication']
    return result


class SnapshotUploader:
    """Caller holds exclusive_writer for this directory for the whole process."""
    def __init__(self, directory, *, run_path):
        require(len(run_path.split('/')) == 3 and all(run_path.split('/')), 'Use entity/project/run_id')
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.run_path = run_path
        self.state_path = self.directory / 'status.json'
        self.pending_path = self.directory / 'pending.json'
        self.state = json.loads(self.state_path.read_text()) if self.state_path.exists() else dict(
            run_path=run_path, confirmed=None, failures=0, next_attempt_at=0, status='idle')
        require(self.state['run_path'] == run_path, 'Uploader destination changed')

    def save(self):
        self.state['updated_at'] = time.time()
        atomic_json(self.state_path, self.state)

    def tick(self, source, transport, *, now=None):
        now = time.time() if now is None else now
        value = load_snapshot(source)
        require(publication_run_id(value) == self.run_path.split('/')[-1], 'Source publication run mismatch')
        if not self.pending_path.exists():
            confirmed = self.state['confirmed']
            if confirmed:
                require(value['synthetic'] is confirmed['synthetic'], 'Source classification changed')
                require(position(value) >= position(confirmed), 'Source rolled back; do not overwrite newer remote evidence')
                if value['snapshot_id'] == confirmed['snapshot_id']:
                    self.state['status'] = 'caught_up'
                    self.save()
                    return 'caught_up'
                require(position(value) > position(confirmed), 'Conflicting snapshot at the same position')
            write_snapshot(value, self.pending_path)
        value = load_snapshot(self.pending_path)
        require(publication_run_id(value) == self.run_path.split('/')[-1], 'Pending publication run mismatch')
        if self.state['confirmed'] == receipt(value):
            # Crash after saving confirmation but before deleting pending.
            self.pending_path.unlink()
            return 'confirmed'
        self.state['pending'] = receipt(value)
        if now < self.state['next_attempt_at']:
            return 'backoff'
        self.state.update(status='sending', last_attempt_at=now)
        self.save()
        try:
            remote = transport(self.pending_path, self.run_path, self.directory)
            require(remote == receipt(value), 'Transport did not confirm this exact snapshot')
        except Exception as exc:
            failures = self.state['failures'] + 1
            self.state.update(status='retry_pending', failures=failures,
                              error_type=type(exc).__name__, next_attempt_at=now + min(300, 5 * 2**min(failures-1, 6)))
            self.save()  # No exception strings/URLs/credentials in status.
            return 'retry_pending'
        self.state.update(status='confirmed', confirmed=receipt(value), pending=None,
                          failures=0, next_attempt_at=0, error_type=None, confirmed_at=time.time())
        self.save()  # Confirmation durable BEFORE removing pending.
        self.pending_path.unlink()
        return 'confirmed'


def terminate_process_group(child):
    try:
        os.killpg(child.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    child.wait()


def subprocess_transport(pending, run_path, directory, *, timeout_s=120):
    """SDK/network/finish bounded by an external process-group watchdog."""
    require(timeout_s > 0, 'Positive upload timeout required')
    output = Path(directory) / 'receipt.json'
    output.unlink(missing_ok=True)
    env = os.environ.copy()
    env['PYTHONPATH'] = str(Path(__file__).resolve().parents[1]) + os.pathsep + env.get('PYTHONPATH', '')
    child = subprocess.Popen([sys.executable, '-m', 'browser_training.upload_worker',
                              str(pending), run_path, str(directory), str(output)],
                             env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
    try:
        code = child.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        terminate_process_group(child)
        raise TimeoutError('Upload attempt exceeded time limit') from None
    except BaseException:
        if child.poll() is None:
            terminate_process_group(child)
        raise
    if code:
        raise RuntimeError('Upload worker failed; pending snapshot retained')
    return json.loads(output.read_text())
