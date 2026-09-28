"""Bounded independent evaluation processes; resume saved cases without rerunning.

Workers receive an immutable request/case/checkpoint identity and write JSON.
The worker owns policy loading, episode lifetime and verifier correctness.
"""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import time

from .evaluation import case_event, digest, evaluation_event, validate_request
from .monitoring_files import atomic_json, exclusive_writer
from .outcomes import fields, require, validate


def run(job, directory, command, *, concurrency=2, timeout_s=120):
    validate_request(job)
    require(type(concurrency) is int and 1 <= concurrency <= 16, 'Concurrency must be 1..16')
    require(timeout_s > 0 and isinstance(command, list) and command and all(isinstance(v, str) for v in command),
            'Worker argv and positive timeout required')
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    with exclusive_writer(directory/'runner.lock'):
        contract = dict(request=job, command=command, concurrency=concurrency, timeout_s=timeout_s)
        manifest = directory/'manifest.json'
        if manifest.exists():
            require(json.loads(manifest.read_text()) == contract, 'Evaluation resume contract changed')
        else:
            atomic_json(manifest, contract)
        request_path = directory/'request.json'
        atomic_json(request_path, job)
        def execute(case):
            key = digest(case)
            folder = directory/key
            folder.mkdir(exist_ok=True)
            saved = folder/'event.json'
            if saved.exists():
                event = json.loads(saved.read_text())
                validate(event)
                return event
            case_path, output = folder/'case.json', folder/'result.json'
            atomic_json(case_path, case)
            output.unlink(missing_ok=True)
            started = time.monotonic()
            outcome = dict(status='infra_error', goal_completed=None, constraints_satisfied=None,
                           unauthorized_effect=None, reward=None)
            trace_ref = None
            try:
                # No shell, no auto retry or sharing browser/session state between cases.
                from .snapshot_uploader import terminate_process_group
                child = subprocess.Popen([*command, '--request', str(request_path), '--case', str(case_path),
                                          '--output', str(output)], stdout=subprocess.DEVNULL,
                                         stderr=subprocess.DEVNULL, start_new_session=True)
                try:
                    code = child.wait(timeout=timeout_s)
                except BaseException:
                    terminate_process_group(child)
                    raise
                require(code == 0, 'Evaluation worker failed')
                result = json.loads(output.read_text())
                fields(result, {'checkpoint_id', 'policy_version', 'outcome'}, {'trace_ref'})
                require(result['checkpoint_id'] == job['checkpoint_id'] and result['policy_version'] == job['policy_version'],
                        'Evaluation worker reported wrong checkpoint/policy')
                event = case_event(job, case, result['outcome'], occurred_at=time.time(),
                                   trace_ref=result.get('trace_ref'), duration_s=time.monotonic()-started)
                validate(event)
            except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
                atomic_json(folder/'failure.json', dict(error_type=type(exc).__name__))
                event = case_event(job, case, outcome, occurred_at=time.time(), trace_ref=trace_ref,
                                   duration_s=time.monotonic()-started)
            atomic_json(saved, event)
            return event
        # Independent cases run concurrently. Publication waits for the complete fixed suite.
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            events = list(executor.map(execute, job['suite']['cases']))
        delivery_path = directory/'delivery.json'
        if delivery_path.exists():
            previous = json.loads(delivery_path.read_text())
            require(previous['episodes'] == events, 'Saved evaluation delivery differs')
            return previous
        report = evaluation_event(job, events, occurred_at=time.time())
        delivery = dict(episodes=events, report=report)
        atomic_json(delivery_path, delivery)
        return delivery
