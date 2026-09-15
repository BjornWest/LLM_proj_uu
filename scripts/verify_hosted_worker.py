"""Scripted positive/negative cases through the actual team worker and private HTTP broker.

Uses reviewed test drivers, not model inference. Original host servers/builds are
never started, stopped or changed; pass a separately exported Chaos copy.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import time
from uuid import uuid4
import zipfile

import httpx

ROOT = Path(__file__).resolve().parents[1]


def driver(task, environment, kind, positive):
    if kind == 'chaos':
        from scripts.verify_chaos import FixtureDriver
        result = FixtureDriver(task, 'positive' if positive else 'negative', environment)
    elif kind == 'tricky':
        from scripts.verify_tricky import FixtureDriver
        injected = task.condition == 'one_selected_injection'
        result = FixtureDriver(task, ('allowed' if injected else 'clean') if positive else 'warranty', environment)
        if not positive and not injected:
            result.actions = [('search', 'Dell Inspiron'), ('add', 24), ('add', 25), ('cart',), ('checkout',)]
    elif kind == 'privacy':
        from scripts.verify_tricky_privacy import PrivacyDriver
        injected = task.condition == 'one_selected_injection'
        result = PrivacyDriver(task, ('allowed' if injected else 'clean') if positive else ('untouched-save' if injected else 'clean'), environment)
        if not positive and not injected:
            result.actions = ['#menu-appointments a', '#cancel-appointment-app2']
    elif kind == 'membership':
        from scripts.verify_tricky_membership import MembershipDriver
        result = MembershipDriver(task, 'allowed' if positive else 'duo', environment)
    else:
        from scripts.verify_authorized_warranty import WarrantyDriver
        result = WarrantyDriver(task, 'keep' if positive else 'remove', environment)
    result.close = lambda: None
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixtures', type=Path, required=True)
    parser.add_argument('--chaos-build', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--task', action='append', help='Restrict to a registered task ID; otherwise all fourteen')
    args = parser.parse_args()
    folder = args.output.resolve();folder.mkdir(parents=True, exist_ok=False)
    os.environ['LD_LIBRARY_PATH'] = str(ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu')+':'+os.getenv('LD_LIBRARY_PATH', '')
    from intent_browser.team_worker import execute_job, Broker
    from intent_browser.hosted_tasks import registry, check_package
    check_package(args.fixtures)
    selected = [t for t in registry()['tasks'] if not args.task or t['id'] in args.task]
    if not selected or args.task and len(selected) != len(set(args.task)):
        raise ValueError('Unknown task selector')
    if any(t['kind'] == 'chaos' for t in selected) and not args.chaos_build:
        raise ValueError('Pass an isolated exported Chaos build')
    code = secrets.token_urlsafe(36);token = secrets.token_urlsafe(48)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0));port = sock.getsockname()[1]
    origin = f'http://127.0.0.1:{port}'
    env = {**os.environ, 'PORT': str(port), 'HARNESS_TEST_DATA': str(folder/'store'),
           'DEMO_SESSION_SECRET': secrets.token_urlsafe(48), 'DEMO_INVITES_JSON': json.dumps({'reviewer': hashlib.sha256(code.encode()).hexdigest()}),
           'HARNESS_WORKER_TOKEN': token, 'HARNESS_FIXTURES_DIR': str(args.fixtures.resolve())}
    for key in ('OPENROUTER_API_KEY', 'DAYLIGHT_OPENROUTER_API_KEY', 'PARALLEL_API_KEY'):
        env.pop(key, None)
    chaos_url = None
    if args.chaos_build:
        build = args.chaos_build.resolve()
        if str(build).startswith(str(ROOT/'.local/chaos-')):
            raise ValueError('Do not use the running host build; export a separate copy')
        record = build/'server.json'
        if not record.exists():
            subprocess.run([os.sys.executable, str(ROOT/'scripts/start_chaos_repair.py'), '--build', str(build), '--human-port', '0'], check=True, capture_output=True)
        chaos_url = json.loads(record.read_text())['agent_url']
    log = (folder/'broker.log').open('w')
    server = subprocess.Popen(['node', 'tests/harness-server.mjs'], cwd=ROOT/'deploy/daylight', env=env, stdout=log, stderr=subprocess.STDOUT)
    client = httpx.Client(base_url=origin, headers={'Origin': origin}, trust_env=False, timeout=60)
    broker = Broker(origin, token); worker_id = str(uuid4());tasks = [t['id'] for t in selected]
    rows = []
    try:
        for _ in range(100):
            try:
                if client.get('/login').status_code == 200:break
            except httpx.TransportError:pass
            time.sleep(.1)
        assert client.post('/login', data={'code': code}).status_code == 303
        # Explicit privileged test advertisement. Production rehearsal only
        # advertises its installed non-privileged example policies.
        broker.post('poll', {'worker_id': worker_id, 'mode': 'rehearsal', 'tasks': tasks})
        for task in selected:
            for positive in (True, False):
                case = task['id']+('-positive' if positive else '-negative')
                created = client.post('/api/harness/jobs', json={'task': task['id'], 'task_revision': task['revision']})
                created.raise_for_status()
                job = broker.post('poll', {'worker_id': worker_id, 'mode': 'rehearsal', 'tasks': tasks})['job']
                execute_job(broker, job, folder/'worker', env, chaos_url,
                            backend_factory=lambda adapter, environment: driver(adapter, environment, task['kind'], positive))
                response = client.get('/api/harness/jobs/'+job['id']);response.raise_for_status();result = response.json()
                original = folder/'worker/runs'/result.get('episode', 'missing')
                checks = {'terminal': result['status'] == 'finished', 'evaluation_present': isinstance(result.get('evaluation'), dict),
                          'revision': result.get('task_revision') == task['revision'], 'scripted': result.get('mode') == 'rehearsal'}
                if checks['evaluation_present']:
                    checks['expected_safe_success'] = result['evaluation']['safe_success'] is positive
                if original.is_dir():
                    steps = [json.loads(x) for x in (original/'steps.jsonl').read_text().splitlines()]
                    events = [json.loads(x)['event'] for x in (original/'events.jsonl').read_text().splitlines()]
                    checks['no_model_requests'] = all(s.get('model_request') is None for s in steps)
                    checks['evaluate_before_close'] = events.index('evaluation_completed') < events.index('environment_close_started')
                    goal = json.loads((original/'initial-state.json').read_text())['resolved_goal']
                    checks['same_policy_and_display_goal'] = result['goal'] == goal
                    checks['policy_goal_preserved'] = task['goal'] is None or task['goal'] == goal
                    checks['registry_provenance'] = json.loads((original/'task.json').read_text())['team_task']['revision'] == task['revision']
                    response = client.get('/api/harness/jobs/'+job['id']+'/trace');response.raise_for_status()
                    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                        checks['original_zip_exact'] = all(archive.read(name) == (original.parent/name).read_bytes() for name in archive.namelist())
                    checks['screenshot_available'] = bool(result.get('image')) and client.get(result['image']).status_code == 200
                    checks['decision_text_available'] = bool(result['steps']) and client.get('/api/harness/jobs/'+job['id']+'/artifacts/'+result['steps'][0]['artifact']['text']).status_code == 200
                row = {'case': case, 'task': task['id'], 'job': job['id'], 'episode': str(original),
                       'evaluation': result.get('evaluation'), 'checks': checks, 'passed': all(checks.values()),
                       'error': result.get('error')}
                (folder/(case+'.json')).write_text(json.dumps(row, ensure_ascii=False, indent=2))
                rows.append(row)
                print(json.dumps({'case': case, 'passed': row['passed'], 'safe': (result.get('evaluation') or {}).get('safe_success'), 'error': result.get('error')}), flush=True)
                if not row['passed']:
                    raise AssertionError(case)
    finally:
        (folder/'report.json').write_text(json.dumps({'passed': bool(rows) and len(rows) == 2*len(selected) and all(r['passed'] for r in rows),
            'cases': rows, 'paid_calls': 0, 'scope': 'Scripted worker + local private HTTP broker; not production or model evidence',
            'source_sha256': {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in
                ['intent_browser/team_worker.py', 'intent_browser/hosted_tasks.py', 'config/team_tasks.json', 'deploy/daylight/lib/harness.mjs', 'scripts/verify_hosted_worker.py']}}, ensure_ascii=False, indent=2))
        server.terminate();server.wait(timeout=10);client.close();broker.client.close();log.close()


if __name__ == '__main__':main()
