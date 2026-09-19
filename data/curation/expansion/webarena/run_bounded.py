"""One isolated OS process group per scripted case, with explicit wall-time caps."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from data.curation.expansion.webarena.inventory import BATCH, ROOT


def signal_if_present(target, number, *, group=False):
    try:
        (os.killpg if group else os.kill)(target, number)
    except ProcessLookupError:
        pass


def execute_case(command, log, timeout, *, grace_seconds=5):
    """Child must register SIGUSR1 for diagnostic stacks, or explicitly ignore it."""
    if timeout <= 0 or grace_seconds <= 0:
        raise ValueError('Positive timeout and grace required')
    started = time.time()
    timed_out = False
    with Path(log).open('xb') as stream:
        process = subprocess.Popen(command, cwd=ROOT, stdout=stream,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            signal_if_present(process.pid, signal.SIGUSR1)
            time.sleep(0.1)
            signal_if_present(process.pid, signal.SIGTERM, group=True)
            try:
                code = process.wait(timeout=grace_seconds)
            except subprocess.TimeoutExpired:
                signal_if_present(process.pid, signal.SIGKILL, group=True)
                code = process.wait(timeout=grace_seconds)
            finally:
                # The leader can exit while a descendant ignores SIGTERM.
                signal_if_present(process.pid, signal.SIGKILL, group=True)
    return {'process_id': process.pid, 'started_at_unix': started,
            'ended_at_unix': time.time(), 'timeout_seconds': timeout,
            'timed_out': timed_out, 'returncode': code, 'log': str(log)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--task', type=int, choices=BATCH, action='append')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--case-timeout', type=float, default=120)
    args = parser.parse_args()
    if args.case_timeout <= 0:
        raise ValueError('Positive timeout required')
    args.output.mkdir(parents=True, exist_ok=False)
    cases, tasks = [], []
    script = ROOT / 'data/curation/expansion/webarena/browser_batch.py'
    wrapper_digest = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    for task in args.task or BATCH:
        target = args.output / f'task-{task}'
        digest = hashlib.sha256(script.read_bytes()).hexdigest()
        case = execute_case(
            [sys.executable, str(script), '--task', str(task), '--output', str(target)],
            args.output / f'task-{task}.log', args.case_timeout)
        unchanged = digest == hashlib.sha256(script.read_bytes()).hexdigest()
        report = target / 'report.json'
        case.update(task_id=task, driver_sha256=digest, driver_unchanged=unchanged,
                    wrapper_sha256=wrapper_digest,
                    original_report=str(report) if report.exists() else None)
        cases.append(case)
        if report.exists():
            tasks.extend(json.loads(report.read_text())['tasks'])
        (args.output / f'task-{task}-execution.json').write_text(json.dumps(case, indent=2))
        print(json.dumps(case), flush=True)
        if not unchanged:
            break
    (args.output / 'report.json').write_text(json.dumps({
        'schema': 'webarena-read-only-browser-v1', 'model_calls': 0,
        'scope': 'Bounded per-task processes; timed-out partial cases never inferred successes',
        'executions': cases, 'tasks': tasks}, indent=2))


if __name__ == '__main__':
    main()
