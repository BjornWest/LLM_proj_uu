"""Trusted runtime resources for the same expanded task factory used by suites.

This module never selects graders from queue data. Registry and evaluator paths
are host configuration; the queue supplies only a pinned task ID and revision.
"""
from pathlib import Path
import hashlib
import json
import subprocess
import os
import sys

from .worker_sites import WorkerSites


def isolated_runtime(env, operation, value=None):
    """Run the new task runtime without replacing the certified legacy loop."""
    root = Path(env['HARNESS_EXPANDED_EXECUTION_ROOT']).resolve(strict=True)
    child_env = {**os.environ, **env, 'PYTHONPATH': str(root), 'HARNESS_PROJECT_ROOT': str(root)}
    child_env.pop('HARNESS_EXPANDED_EXECUTION_ROOT', None)
    result = subprocess.run([sys.executable, '-m', 'intent_browser.expanded_entry', operation],
                            input=json.dumps(value or {}), text=True, cwd=root, env=child_env,
                            stdout=subprocess.PIPE if operation == 'capabilities' else None,
                            check=True, timeout=120 if operation == 'capabilities' else 7200)
    return json.loads(result.stdout) if operation == 'capabilities' else None


def runner_options(row, *, action_timeout_ms=None):
    from .harness import native_tools_profile
    from .actions import validate_action_timeout
    profile = row['profile']
    if profile['name'] != 'core-tools-v3':
        raise ValueError('Unsupported expanded task harness profile')
    result = {'max_steps': profile['max_steps'], 'observation_text_limit': profile['observation_text_limit'],
              'terminal_response_instruction': row['policy_input']['terminal_response_instruction'],
              'harness_profile': native_tools_profile(parallel_tool_calls=None, compact_feedback=True, reasoning_replay='preserve')}
    if action_timeout_ms is not None:
        validate_action_timeout(action_timeout_ms)
        result['action_timeout_ms'] = action_timeout_ms
    return result


def certified_tasks(env):
    """No configured certificate means no advertised expanded capabilities."""
    if not env.get('HARNESS_EXPANDED_CERTIFICATE'):
        return [], None
    from data.curation.worker_integration.bindings import load_registry
    project = Path(env.get('HARNESS_PROJECT_ROOT', Path(__file__).resolve().parents[1])).resolve()
    registry_path = Path(env['HARNESS_EXPANDED_REGISTRY'])
    certificate = json.loads(Path(env['HARNESS_EXPANDED_CERTIFICATE']).read_text())
    sha = hashlib.sha256(registry_path.read_bytes()).hexdigest()
    if (certificate.get('schema') != 'expanded-worker-certification-v1' or certificate.get('registry_sha256') != sha
            or sha != env.get('HARNESS_EXPANDED_REGISTRY_SHA256')):
        raise ValueError('Expanded task certificate/registry mismatch')
    sources = certificate.get('source_sha256', {})
    required = {'intent_browser/runner.py', 'intent_browser/team_worker.py', 'intent_browser/expanded_tasks.py',
                'intent_browser/task_finalization.py', 'data/curation/worker_integration/tasks.py'}
    if not required.issubset(sources):
        raise ValueError('Incomplete expanded worker source certification')
    for name, expected in sources.items():
        path = (project / name).resolve()
        if not path.is_relative_to(project) or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('Expanded worker certified source changed')
    fixture = Path(env['HARNESS_FULL_FIXTURES_DIR']).resolve()
    for name in ('build.json', 'catalog.json'):
        if hashlib.sha256((fixture / name).read_bytes()).hexdigest() != certificate.get('fixture_sha256', {}).get(name):
            raise ValueError('Expanded worker fixture certificate mismatch')
    accepted = certificate.get('tasks', {})
    rows = load_registry(registry_path)['tasks']
    if not isinstance(accepted, dict) or any(not any(row['id'] == task_id and row['revision'] == revision for row in rows)
                                            for task_id, revision in accepted.items()):
        raise ValueError('Unknown certified task revision')
    return [row for row in rows if accepted.get(row['id']) == row['revision']], certificate


class ExpandedTaskSession:
    def __init__(self, task_id, revision, session_id, env, *, require_certificate=True):
        from data.curation.worker_integration.bindings import load_registry
        from data.curation.worker_integration.context import RuntimeContext
        from data.curation.worker_integration.tasks import make_task
        path = Path(env['HARNESS_EXPANDED_REGISTRY']).resolve()
        self.registry_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        if self.registry_sha256 != env.get('HARNESS_EXPANDED_REGISTRY_SHA256'):
            raise ValueError('Expanded registry differs from configured snapshot')
        registry = load_registry(path)
        matches = [r for r in registry['tasks'] if r['id'] == task_id and r['revision'] == revision]
        if len(matches) != 1:
            raise ValueError('Unknown expanded task revision')
        self.row = matches[0]
        self.certificate = None
        if require_certificate:
            certified, self.certificate = certified_tasks(env)
            if not any(row['id'] == task_id and row['revision'] == revision for row in certified):
                raise ValueError('Expanded task lacks current worker certification')
        # Only trusted local scripted acceptance may select an uncertified
        # amendment. Production gets its option exclusively from the certificate.
        self.action_timeout_ms = (self.certificate.get('runtime_options', {}).get('action_timeout_ms')
                                  if self.certificate else int(env['HARNESS_EXPANDED_ACTION_TIMEOUT_MS'])
                                  if env.get('HARNESS_EXPANDED_ACTION_TIMEOUT_MS') else None)
        self.service = self.lease = self.task = None
        project = Path(env.get('HARNESS_PROJECT_ROOT', Path(__file__).resolve().parents[1])).resolve()
        context = RuntimeContext(path, project_root=project,
                                 fixture_root=Path(env['HARNESS_FULL_FIXTURES_DIR']) if env.get('HARNESS_FULL_FIXTURES_DIR') else None)
        try:
            if self.row['family'].startswith('webarena.'):
                self.service = WorkerSites(env['HARNESS_SITE_SERVICE_URL'], env['HARNESS_SITE_SERVICE_TOKEN'])
                self.lease = self.service.acquire(task_id, revision, session_id)
                context.origins = {self.row['site']: self.lease.origin}
                context.browser_proxy = self.lease.browser_proxy
                context.attest = self.lease.attest
                context.state_read = self.lease.state_read
                if self.row['grading_phase'] == 'after_browser_close':
                    # Resolving a venv's python symlink selects the base Python
                    # and loses the evaluator's isolated dependencies.
                    evaluator = Path(env['HARNESS_NATIVE_EVALUATOR_PYTHON']).absolute()
                    script = project / 'data/curation/worker_integration/native_grader.py'
                    def native_grade(task_id, response, har_path, origins):
                        directory = Path(har_path).parent
                        request_path, result_path = directory / 'native-evaluator-input.json', directory / 'native-evaluator-output.json'
                        with request_path.open('x') as stream:
                            json.dump(dict(task_id=task_id, response=response, har_path=str(har_path), origins=origins), stream)
                        with (directory / 'native-evaluator.log').open('xb') as log:
                            subprocess.run([str(evaluator), str(script), '--input', str(request_path), '--output', str(result_path)],
                                           check=True, timeout=120, stdout=log, stderr=log, cwd=project)
                        return json.loads(result_path.read_text())
                    context.native_grade = native_grade
            self.task = make_task(task_id, runtime_context=context, revision=revision)
        except Exception:
            self.close()
            raise

    def runner_options(self):
        return runner_options(self.row, action_timeout_ms=self.action_timeout_ms)

    def activity_metadata(self):
        return {'task_id': self.row['id'], 'site_id': self.row['site_id'], 'interaction_kind': 'task',
                'collection': 'trickyarena' if self.row['family'].startswith('tricky.') else 'webarena-verified',
                'expanded_registry_sha256': self.registry_sha256, 'grading_phase': self.row['grading_phase']}

    def checkpoint(self):
        if self.lease:
            self.lease.attest()

    def close(self):
        # Attempt revocation even if adapter cleanup fails. No mutating replay.
        try:
            if self.task:
                task, self.task = self.task, None
                task.close()
        finally:
            try:
                if self.lease:
                    lease, self.lease = self.lease, None
                    lease.close()
            finally:
                if self.service:
                    self.service.close()
                    self.service = None
