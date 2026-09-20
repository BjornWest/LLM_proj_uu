"""Scripted expanded-task dispatch/publication check; no model or cloud traffic."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import sys
from uuid import uuid4
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task', default='tricky:AU01')
    parser.add_argument('--negative', action='store_true')
    parser.add_argument('--current-profile', action='store_true', help='Scripted acceptance of the new standard harness')
    parser.add_argument('--backend-failure', action='store_true', help='Retain one scripted transport failure, with unknown safe success')
    parser.add_argument('--wait-after-page-size', action='store_true', help='Separate scripted control: one logged noop after selecting page size')
    parser.add_argument('--service-url')
    parser.add_argument('--token-file', type=Path)
    parser.add_argument('--token-env', default='WORKER_SITE_SERVICE_TOKEN')
    parser.add_argument('--offline-handler-url', help='Local workspace-server.mjs fixture only; fixed offline credentials')
    parser.add_argument('--evaluator-python', type=Path, default=ROOT / '.local/webarena-verified/venv/bin/python')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--registry', type=Path, default=ROOT / '.local/curation-expansion/worker-registry-v2.json')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    os.environ['LD_LIBRARY_PATH'] = str(ROOT / '.local/system-libs/usr/lib/x86_64-linux-gnu') + ':' + os.getenv('LD_LIBRARY_PATH', '')
    from data.curation.worker_integration.bindings import load_registry
    from data.curation.worker_integration.verify_tricky import driver_for
    from intent_browser.team_worker import execute_job
    from scripts.harness_suite_tasks import scripted_backend
    row = next(r for r in load_registry(args.registry)['tasks'] if r['id'] == args.task)
    env = {'HARNESS_EXPANDED_REGISTRY': str(args.registry.resolve()),
           'HARNESS_EXPANDED_REGISTRY_SHA256': hashlib.sha256(args.registry.read_bytes()).hexdigest(),
           'HARNESS_FULL_FIXTURES_DIR': str(ROOT / '.local/tricky-full-v1'),
           'HARNESS_EXPANDED_ACTION_TIMEOUT_MS': '30000'}
    if args.current_profile:env['HARNESS_VALIDATE_CURRENT_PROFILE']='1'
    secrets = []
    if row['family'].startswith('webarena.'):
        if not args.service_url: raise ValueError('Dedicated lease service required')
        token = args.token_file.read_text().strip() if args.token_file else os.environ[args.token_env]
        secrets.append(token.encode())
        env.update(HARNESS_SITE_SERVICE_URL=args.service_url, HARNESS_SITE_SERVICE_TOKEN=token,
                   HARNESS_NATIVE_EVALUATOR_PYTHON=str(args.evaluator_python.absolute()))
    job = {'id': str(uuid4()), 'lease': 'offline-job-lease', 'task': row['id'],
           'goal': row['policy_input']['goal'], 'task_revision': row['revision'], 'mode': 'rehearsal'}
    remote = viewer = None
    if args.offline_handler_url:
        import httpx
        from urllib.parse import urlsplit
        from intent_browser.team_worker import Broker as HTTPBroker
        origin = urlsplit(args.offline_handler_url)
        if origin.scheme != 'http' or origin.hostname != '127.0.0.1':
            raise ValueError('Only isolated localhost fixture is supported')
        remote = HTTPBroker(args.offline_handler_url, 'offline-worker-' * 6)
        capability = {'worker_id': str(uuid4()), 'mode': 'live', 'tasks': [row['id']], 'task_revisions': {row['id']: row['revision']}}
        assert remote.post('poll', capability)['job'] is None
        viewer = httpx.Client(base_url=args.offline_handler_url, headers={'Origin': args.offline_handler_url}, trust_env=False)
        response = viewer.post('/login', json={'code': 'offline-interactive-code-' * 3})
        assert response.status_code == 303
        response = viewer.post('/api/harness/jobs', json={'task': row['id'], 'task_revision': row['revision'],
            'goal': row['policy_input']['goal'], 'interaction_kind': 'task', 'required_execution_mode': 'live'})
        response.raise_for_status()
        job = remote.post('poll', capability)['job']
        assert job['id'] == response.json()['id']
    calls, artifacts = [], {}
    class Broker:
        def post(self, operation, value):
            if operation == 'reserve': raise AssertionError('No inference/reservation permitted')
            if operation == 'artifact':
                raw = base64.b64decode(value['data'])
                assert hashlib.sha256(raw).hexdigest() == value['sha256']
                artifacts[value['name']] = raw
                calls.append({'operation': operation, 'name': value['name'], 'sha256': value['sha256']})
            else: calls.append({'operation': operation, 'value': value})
            return remote.post(operation, value) if remote else {'ok': True}
    def backend_factory(task, holder):
        def adapt(driver):
            if not args.current_profile:return scripted_backend(driver)
            class PrivilegedScript:
                count=0
                def complete(self,messages):
                    # Acceptance driver, not a model. Existing drivers use full AX
                    # to locate prescribed controls; retain this separate evidence.
                    from intent_browser.observation import refresh_observation
                    from intent_browser.runner import observation_text
                    text=observation_text(refresh_observation(holder['env']),limit=1000000)
                    (args.output/f'scripted-driver-context-{self.count:03d}.txt').write_text(text)
                    self.count+=1
                    return driver.complete([{'role':'user','content':text}])
            return scripted_backend(PrivilegedScript())
        proxy = getattr(getattr(task, 'context', None), 'browser_proxy', None)
        if proxy:
            secrets.extend([proxy['password'].encode(), base64.b64encode((proxy['username'] + ':' + proxy['password']).encode())])
        if args.backend_failure:
            from intent_browser.backend import ChatCompletionsBackend
            import httpx
            backend = ChatCompletionsBackend('https://offline.invalid/v1', 'scripted-failure')
            backend.client.close()
            backend.client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(503, json={'error': 'scripted transport failure'})))
            return backend
        if row['family'].startswith('webarena.'):
            from data.curation.worker_integration.verify_webarena import ScriptedDriver
            driver = ScriptedDriver(task, args.negative, wait_for_visible_idle=True)
            class BoundDriver:
                wait_pending = False
                def complete(self, messages):
                    driver.env = holder['env']
                    if self.wait_pending:
                        from intent_browser.backend import Completion
                        self.wait_pending = False
                        return Completion('noop(1000)', {'source': 'explicit-scripted-page-size-wait'})
                    result = driver.complete(messages)
                    self.wait_pending = args.wait_after_page_size and result.text.startswith('select_option(')
                    return result
            return adapt(BoundDriver())
        return adapt(driver_for(task, args.negative, holder))
    original_backend_factory=backend_factory
    def adopted_backend(task,holder):
        backend=original_backend_factory(task,holder)
        if args.current_profile:
            backend.supports_images=True
            backend.requires_browser_thread=True
        return backend
    execute_job(Broker(), job, args.output, env, backend_factory=adopted_backend)
    (args.output / 'publication-events.json').write_text(json.dumps(calls, indent=2) + '\n')
    terminals = [c['value']['snapshot'] for c in calls if c['operation'] == 'update' and c['value']['snapshot'].get('status')]
    assert len(terminals) == 1, 'Exactly one terminal publication required'
    final = terminals[0]
    directory = args.output / 'runs' / final['episode']
    original = json.loads((directory / 'evaluation.json').read_text())
    authoritative = json.loads((directory / 'authoritative-evaluation.json').read_text())
    checks = {'expected_terminal_status': final['status'] == ('error' if args.backend_failure else 'finished'),
              'correct_completion_or_error': (final['evaluation']['safe_success'] is None and bool(final['evaluation']['technical_error'])) if args.backend_failure else final['evaluation']['task_completed'] is (not args.negative),
              'authoritative_exact': final['evaluation'] == authoritative['evaluation'],
              'grading_phase': final['grading_phase'] == row['grading_phase'],
              'runtime_grade_preserved': authoritative['runtime_evaluation_sha256'] == hashlib.sha256((directory / 'evaluation.json').read_bytes()).hexdigest(),
              'exact_goal': final['resolved_goal'] == job['goal'],
              'no_model_calls': not (directory / 'model-transport.jsonl').exists(),
              'no_reservations': not (directory / 'team-reservations.jsonl').exists()}
    archive = args.output / 'published.zip'
    with archive.open('xb') as stream:
        for part in final['trace_parts']: stream.write(artifacts[part])
    with zipfile.ZipFile(archive) as z:
        expected = {str(Path(directory.name) / p.relative_to(directory)): p for p in directory.rglob('*') if p.is_file()}
        checks['exact_zip_members'] = set(z.namelist()) == set(expected) and len(z.namelist()) == len(expected)
        checks['exact_zip_bytes'] = all(z.read(name) == path.read_bytes() for name, path in expected.items())
    metadata = json.loads((directory / 'metadata.json').read_text())
    checks['native_profile'] = metadata['harness_profile']['name'] == ('core-tools-v10-agents' if args.current_profile else row['profile']['name'])
    checks['scripted_driver_label'] = metadata['driver'] == 'scripted-validation'
    checks['recorded_deadline'] = metadata['browser_action_execution']['action_timeout_ms'] == 30000
    summary = json.loads((directory / 'episode.json').read_text())
    checks['no_action_errors'] = summary['action_error_count'] == 0
    checks['control_secret_absent'] = all(not any(secret in path.read_bytes() for secret in secrets) for path in directory.rglob('*') if path.is_file())
    if viewer:
        response = viewer.get('/api/harness/jobs/' + job['id']); response.raise_for_status()
        saved = response.json()
        checks['http_broker_exact_evaluation'] = saved['evaluation'] == final['evaluation']
        checks['http_broker_terminal_status'] = saved['status'] == final['status']
        checks['http_broker_no_reservations'] = not saved.get('reservations')
        viewer.close(); remote.client.close()
    if row['grading_phase'] == 'after_browser_close':
        checks['pre_close_unknown'] = original['safe_success'] is None
        checks['native_result_retained'] = (directory / 'native-evaluator-output.json').exists() if not args.backend_failure else True
    report = {'task': args.task, 'negative': args.negative, 'backend_failure': args.backend_failure,
              'wait_after_page_size': args.wait_after_page_size, 'passed': all(checks.values()), 'checks': checks,
              'trace': str(directory), 'final': final, 'model_calls': 0,
              'registry_sha256': env['HARNESS_EXPANDED_REGISTRY_SHA256']}
    (args.output / 'publication-events.json').write_text(json.dumps(calls, indent=2) + '\n')
    (args.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'passed': report['passed'], 'checks': checks}))
    if not report['passed']: raise SystemExit(1)


if __name__ == '__main__': main()
