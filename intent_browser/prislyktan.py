"""Deployment wiring for the original, four-origin synthetic Prislyktan fixture.

The source adapter remains the single setup/grading path. No browser-local
outcome inference and no reset when a human hands the session to Ask.
"""
from data.curation.aggregator_trial.integration import (
    create_runtime, runtime_descriptor, trusted_task_catalog, make_task,
)


def catalog():
    value = trusted_task_catalog()
    return [dict(row, id='prislyktan:' + row['id'], selector=row['id'],
                 title='Prislyktan · ' + row['id'], site_id='prislyktan',
                 collection='synthetic-development', custom_goal=False,
                 development_only=True, training_eligible=False,
                 verification_scope='Original synthetic fixture; private server ledger and delivered terminal answer.')
            for row in value['tasks']]


def entry(task_id):
    matches = [row for row in catalog() if row['id'] == task_id]
    if len(matches) != 1:
        raise ValueError('Unknown Prislyktan task')
    return matches[0]


class PrislyktanTask:
    supported_harness_profiles = ('core-tools-v10-agents',)

    def __init__(self, task_id, revision=None):
        self.row = entry(task_id)
        if revision is not None and revision != self.row['revision']:
            raise ValueError('Prislyktan task revision changed')
        self.task = make_task(self.row['selector'])

    def __getattr__(self, name):
        return getattr(self.task, name)

    def policy_navigation_origins(self):
        return runtime_descriptor(self.task.runtime)['allowed_origins']

    def route(self, route):
        from urllib.parse import urlsplit
        value = urlsplit(route.request.url)
        if value.scheme in ('data', 'blob', 'about') or value.scheme+'://'+value.netloc in self.policy_navigation_origins():
            route.continue_()
        else:
            route.abort()

    def make_env(self, video=None, *, action_mapping, headless=True):
        env = self.task.make_env(video, action_mapping=action_mapping, headless=headless)
        original = env.task_entrypoint
        outer = self
        def guarded(*args, **kwargs):
            task = original(*args, **kwargs)
            setup = task.setup
            def guarded_setup(page):
                page.context.route('**/*', outer.route)
                return setup(page)
            task.setup = guarded_setup
            return task
        env.task_entrypoint = guarded
        env.pw_context_kwargs = {**env.pw_context_kwargs, 'service_workers':'block'}
        return env


def certified_catalog(env):
    """Advertise only the explicitly accepted source closure; no implicit readiness."""
    import hashlib
    import json
    from pathlib import Path
    path=env.get('HARNESS_PRISLYKTAN_CERTIFICATE')
    if not path:return []
    certificate=json.loads(Path(path).read_text())
    root=Path(__file__).resolve().parents[1]
    if certificate.get('schema')!='prislyktan-worker-acceptance-v1':
        raise ValueError('Unsupported Prislyktan acceptance certificate')
    required={'intent_browser/prislyktan.py','intent_browser/team_worker.py','intent_browser/runner.py',
              'data/curation/aggregator_trial/tasks.py','environments/aggregator_trial/server.py'}
    if not required.issubset(certificate.get('source_sha256',{})):
        raise ValueError('Incomplete Prislyktan source acceptance')
    for name,want in certificate['source_sha256'].items():
        source=(root/name).resolve()
        if not source.is_relative_to(root) or hashlib.sha256(source.read_bytes()).hexdigest()!=want:
            raise ValueError('Prislyktan accepted source changed')
    rows=catalog()
    if certificate.get('tasks')!={r['id']:r['revision'] for r in rows}:
        raise ValueError('Prislyktan accepted task revisions changed')
    return rows
