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


def original_zip_exact(archive, original):
    """Require every original file exactly once, with no extra archive members."""
    paths = list(original.rglob('*'))
    if any(path.is_symlink() for path in paths):
        return False
    expected = {str(Path(original.name)/path.relative_to(original)): path
                for path in paths if path.is_file()}
    names = archive.namelist()
    return (bool(expected) and len(names) == len(set(names)) and set(names) == set(expected)
            and all(archive.read(name) == path.read_bytes() for name, path in expected.items()))


class FailingBackend:
    """One intentional local failure; never constructs an inference client."""
    model = 'scripted-backend-failure'

    def complete(self, messages):
        raise RuntimeError('Intentional scripted backend failure before HTTP dispatch')

    def close(self):
        pass


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
    parser.add_argument('--case', action='append', choices=['positive', 'negative', 'backend-failure'],
                        help='Defaults to positive and negative; backend-failure is a separate diagnostic')
    args = parser.parse_args()
    folder = args.output.resolve();folder.mkdir(parents=True, exist_ok=False)
    os.environ['LD_LIBRARY_PATH'] = str(ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu')+':'+os.getenv('LD_LIBRARY_PATH', '')
    from intent_browser.team_worker import execute_job, Broker
    from intent_browser.hosted_tasks import registry, check_package
    check_package(args.fixtures)
    selected = [t for t in registry()['tasks'] if not args.task or t['id'] in args.task]
    variants = list(dict.fromkeys(args.case or ['positive', 'negative']))
    if not selected or args.task and len(selected) != len(set(args.task)):
        raise ValueError('Unknown task selector')
    if 'backend-failure' in variants and [t['id'] for t in selected] != ['tricky-p07-clean']:
        raise ValueError('The backend-failure diagnostic requires --task tricky-p07-clean')
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
            for variant in variants:
                positive = variant == 'positive'
                failing = variant == 'backend-failure'
                case = task['id']+'-'+variant
                created = client.post('/api/harness/jobs', json={'task': task['id'], 'task_revision': task['revision']})
                created.raise_for_status()
                job = broker.post('poll', {'worker_id': worker_id, 'mode': 'rehearsal', 'tasks': tasks})['job']
                execute_job(broker, job, folder/'worker', env, chaos_url,
                            backend_factory=lambda adapter, environment: FailingBackend() if failing else driver(adapter, environment, task['kind'], positive))
                response = client.get('/api/harness/jobs/'+job['id']);response.raise_for_status();result = response.json()
                original = folder/'worker/runs'/result.get('episode', 'missing')
                checks = {'terminal': result['status'] == ('error' if failing else 'finished'), 'evaluation_present': isinstance(result.get('evaluation'), dict),
                          'original_present': original.is_dir(),
                          'revision': result.get('task_revision') == task['revision'], 'scripted': result.get('mode') == 'rehearsal'}
                if checks['evaluation_present']:
                    checks['expected_safe_success'] = result['evaluation']['safe_success'] is (None if failing else positive)
                if original.is_dir():
                    steps = [json.loads(x) for x in (original/'steps.jsonl').read_text().splitlines()]
                    events = [json.loads(x)['event'] for x in (original/'events.jsonl').read_text().splitlines()]
                    checks['no_model_requests'] = all(s.get('model_request') is None for s in steps)
                    state = json.loads((folder/'store/daylight/harness/control-v1.json').read_text())
                    checks['no_reservations'] = state['jobs'][job['id']]['reservations'] == []
                    evaluation = json.loads((original/'evaluation.json').read_text())
                    checks['full_evaluation_preserved'] = (result['evaluation'] == evaluation ==
                        json.loads((original/'episode.json').read_text())['evaluation'])
                    if failing:
                        checks['one_failure_no_action'] = (len(steps) == 1 and steps[0]['action'] is None and
                            steps[0].get('failure_phase') == 'model' and 'tool_started' not in events)
                        checks['technical_error_preserved'] = (result['error'] == evaluation['technical_error'] ==
                            'RuntimeError: Intentional scripted backend failure before HTTP dispatch')
                        checks['failure_snapshot_components_known'] = (evaluation['task_completed'] is False and
                            evaluation['authorization_satisfied'] is True)
                    checks['evaluate_before_close'] = events.index('evaluation_completed') < events.index('environment_close_started')
                    goal = json.loads((original/'initial-state.json').read_text())['resolved_goal']
                    checks['same_policy_and_display_goal'] = result['goal'] == goal
                    checks['policy_goal_preserved'] = task['goal'] is None or task['goal'] == goal
                    checks['registry_provenance'] = json.loads((original/'task.json').read_text())['team_task']['revision'] == task['revision']
                    response = client.get('/api/harness/jobs/'+job['id']+'/trace');response.raise_for_status()
                    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                        checks['original_zip_exact'] = original_zip_exact(archive, original)
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
        (folder/'report.json').write_text(json.dumps({'passed': bool(rows) and len(rows) == len(variants)*len(selected) and all(r['passed'] for r in rows),
            'cases': rows, 'paid_calls': 0, 'scope': 'Scripted worker + local private HTTP broker; not production or model evidence',
            'source_sha256': {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in
                ['intent_browser/team_worker.py', 'intent_browser/hosted_tasks.py', 'config/team_tasks.json', 'deploy/daylight/lib/harness.mjs', 'scripts/verify_hosted_worker.py']}}, ensure_ascii=False, indent=2))
        server.terminate();server.wait(timeout=10);client.close();broker.client.close();log.close()


if __name__ == '__main__':main()
