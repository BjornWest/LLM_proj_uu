"""Controller safety without an aggregate episode duration budget."""
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
import json
import os
import signal
import subprocess
import threading
import time

PROVIDER_MAX_SECONDS = 86400


class ChildFailure(RuntimeError):
    def __init__(self, returncode, log_path):
        self.returncode = returncode
        super().__init__('Child failed with exit '+str(returncode)+'; see '+str(log_path))


def pin(path):
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': sha256(path.read_bytes()).hexdigest()}


def checked(row):
    if set(row) != {'path', 'sha256'} or not Path(row['path']).is_absolute():
        raise ValueError('Exact absolute source/evidence pin required')
    if pin(row['path']) != row:
        raise ValueError('Pinned input changed: '+row['path'])
    return Path(row['path'])


def read(path):
    return json.loads(Path(path).read_bytes())


def save(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write('\n')


def validate_platform(lifetime, *, now=None):
    import math
    if lifetime.get('mode') != 'episode-owned' or lifetime.get('expiry_kind') != 'provider-platform-maximum':
        raise ValueError('Episode-owned provider lifetime required')
    start, expiry, maximum = [lifetime[k] for k in ('started_at_utc','expires_at_utc','provider_max_seconds')]
    if any(type(v) not in (int,float) or not math.isfinite(v) for v in (start,expiry,maximum)):
        raise ValueError('Finite numeric lifetime required')
    if maximum != PROVIDER_MAX_SECONDS or abs(expiry-start-maximum) > .001:
        raise ValueError('Use actual Modal platform maximum, not episode alarm')
    if not start <= (time.time() if now is None else now) < expiry:
        raise ValueError('Actual lifetime is not current')
    return expiry


class Heartbeat:
    def __init__(self, messages, *, interval=15, grace=180):
        self.messages, self.interval = messages, interval
        self.done = threading.Event()
        self.error = None
        self.grace = grace
        self.last_success = time.monotonic()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        while not self.done.is_set():
            try:
                self.messages.put('heartbeat', timeout=5, partition='commands')
                self.last_success = time.monotonic()
                self.error = None
            except Exception as exc:
                self.error = type(exc).__name__
            self.done.wait(self.interval)

    def check(self):
        if self.error is not None and time.monotonic()-self.last_success >= self.grace:
            raise RuntimeError('Serving controller heartbeat failed: '+self.error)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.done.set()
        self.thread.join(timeout=6)


def run_child(command, log_path, *, cwd, env, heartbeat, platform_expiry=None, operation_timeout=None):
    """Only failed-operation/platform watchdogs; healthy episodes have no timer."""
    started = time.monotonic()
    process = None
    with Path(log_path).open('x') as log:
        try:
            process = subprocess.Popen(command, cwd=cwd, env=env, stdout=log,
                                       stderr=subprocess.STDOUT, start_new_session=True)
            while process.poll() is None:
                heartbeat.check()
                if platform_expiry is not None and time.time() >= platform_expiry:
                    raise TimeoutError('Actual provider lifetime expired')
                if operation_timeout is not None and time.monotonic()-started >= operation_timeout:
                    raise TimeoutError('Setup/qualification operation watchdog expired')
                time.sleep(.5)
            heartbeat.check()
            if process.returncode:
                raise ChildFailure(process.returncode, log_path)
        finally:
            if process is not None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
                # The leader may exit before a descendant ignores SIGTERM. Always
                # kill the remaining group; browser descendants also have their own
                # bounded-job cgroup, whose launcher reaps detached processes.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass


@contextmanager
def cleanup_gpu(call, messages, report, report_path):
    """Register cleanup immediately after spawn, including failed receipt writes."""
    try:
        yield
    finally:
        try:
            messages.put('stop', timeout=5, partition='commands')
            report['gpu_report'] = call.get(timeout=120)
        except Exception as exc:
            report['graceful_shutdown_error'] = type(exc).__name__
        finally:
            report['termination_requested'] = True
            try:
                call.cancel(terminate_containers=True)
                report['cancellation_api_accepted'] = True
            except Exception as exc:
                report.update(status='FAIL', cancellation_api_accepted=False,
                              cancellation_error=type(exc).__name__)
            save(report_path, report)
