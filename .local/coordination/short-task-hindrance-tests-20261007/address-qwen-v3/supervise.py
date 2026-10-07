"""Finite subscribed pair; one fresh browser process/resource scope at a time."""
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import signal
import subprocess
import sys

from episode_events_frozen import Events, flush

OUT = Path(__file__).resolve().parent
ROOT = Path('/home/bjorn/code/LLM_proj_uu')


def pin(path):
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': sha256(path.read_bytes()).hexdigest()}


def save(path, body):
    with Path(path).open('x') as stream:
        json.dump(body, stream, indent=2)
        stream.write('\n')


def verify_ready(ready):
    for entry in ready['inputs'] + [ready['driver'], ready['supervisor'], ready['plan']]:
        if pin(entry['path']) != entry:
            raise ValueError('Changed ready input: ' + entry['path'])
    # Source acceptance is not permission to occupy another agent's slot.
    grant = json.loads(Path(ready['resource_grant']['path']).read_bytes())
    if pin(ready['resource_grant']['path']) != ready['resource_grant']:
        raise ValueError('Resource grant changed')
    if (grant.get('status') != 'granted' or grant.get('suite_id') != 'short-address-qwen-v3'
            or grant.get('episodes') != ['old-address', 'missing-optional-unit']):
        raise ValueError('Explicit finite-pair resource grant missing')


def process_state(code, result, visible, resource, interrupted):
    if interrupted:
        return 'interrupted'
    if (code != 0 or not result or not visible or not resource
            or resource.get('returncode') != 0 or not resource.get('entry_verified')
            or resource.get('interrupt_signals')):
        return 'failed'
    # Actual bounded launcher schema; a missing sample is explicitly unknown.
    sample = resource.get('last_observed', {}).get('job', {})
    if sample.get('memory.events', {}).get('oom_kill', 0):
        return 'failed'
    if (result.get('automatic_grading') is not True
            or result.get('state_grading', {}).get('verdict') not in {'pass', 'fail', 'inconclusive'}
            or visible.get('status') != 'verified_automatic_native_grade_visible'
            or visible.get('native_verdict') != result['state_grading']['verdict']):
        return 'failed'
    return 'succeeded'


def main():
    ready = json.loads((OUT/'ready.json').read_bytes())
    verify_ready(ready)
    plan = json.loads((OUT/'plan.private.json').read_bytes())
    if plan['case_concurrency'] != 1 or plan['automatic_retries'] != 0:
        raise ValueError('Finite resource exception changed')
    # Exclusive claim precedes event initialization or any provider launch.
    save(OUT/'supervisor-start.json', {'pid': os.getpid(), 'ready': pin(OUT/'ready.json'),
         'at': datetime.now(timezone.utc).isoformat(), 'automatic_retries': 0})
    events = Events(OUT/'completion.sqlite')
    ids = [case['case_id'] for case in plan['cases']]
    events.register(plan['suite_id'], ids)
    for case in ids:
        events.subscribe('evaluation-'+case, plan['suite_id'], 'codex:'+plan['thread_id'], episode=case, final=False)
    events.subscribe('evaluation-suite', plan['suite_id'], 'codex:'+plan['thread_id'])
    events.subscribe('human-inbox', plan['suite_id'], 'inbox', milestones=[1])
    current = None
    interruptions = []

    def stop(signum, frame):
        interruptions.append(signum)
        if current is not None:
            try:
                current.send_signal(signal.SIGTERM)
            except ProcessLookupError:
                pass

    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, stop)
    rows = []
    for case in ids:
        evidence = {'ready': pin(OUT/'ready.json'), 'automatic_retries': 0, 'world_draws': 0}
        if interruptions:
            events.finish(plan['suite_id'], case, 'not_started', evidence)
            continue
        events.start(plan['suite_id'], case)
        code = 125
        try:
            verify_ready(ready)
            command = [sys.executable, str(ROOT/'scripts/run_bounded_job.py'),
                       '--memory-mib', '6144', '--receipt', str(OUT/(case+'-bounded')),
                       '--', str(ROOT/'.venv/bin/python'), str(OUT/'run_once.py'), '--case', case]
            with (OUT/(case+'-bounded.log')).open('x') as log:
                current = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
                code = current.wait()
                current = None
        except Exception as error:
            evidence['supervisor_error'] = {'type': type(error).__name__, 'error': str(error)}
        result = visible = resource = None
        for name, path in [('result', OUT/case/'result.json'),
                           ('failure', OUT/case/'failure.json'),
                           ('viewer', OUT/case/'grade-viewer-acceptance.json'),
                           ('resource', OUT/(case+'-bounded/result.json'))]:
            if path.is_file():
                evidence[name] = pin(path)
                try:
                    body = json.loads(path.read_bytes())
                    if name == 'result': result = body
                    elif name == 'viewer': visible = body
                    elif name == 'resource': resource = body
                except (ValueError, OSError) as error:
                    evidence[name+'_read_error'] = str(error)
        if result:
            evidence.update(trace=result.get('trace'), task_verdict=result.get('state_grading', {}).get('verdict'))
        evidence['bounded_exit_code'] = code
        state = process_state(code, result, visible, resource, interruptions)
        rows.append({'case': case, 'state': state, 'evidence': evidence})
        events.finish(plan['suite_id'], case, state, evidence)
        # Completion subscription delivery; no policy trajectory is monitored.
        flush(events)
    save(OUT/'terminal.json', {'at': datetime.now(timezone.utc).isoformat(),
         'ready': pin(OUT/'ready.json'), 'cases': rows, 'episodes': events.snapshot()['episodes'],
         'slot_two': 'returned_to_Inspect_after_Qwen_pair', 'automatic_retries': 0})
    flush(events)
    save(OUT/'notification-delivery.json', {'notices': events.notices()})


if __name__ == '__main__':
    main()
