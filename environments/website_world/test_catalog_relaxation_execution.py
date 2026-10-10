from contextlib import contextmanager
import json
from types import SimpleNamespace
import pytest
from environments.website_world import catalog_relaxation_execution as execution


def setup_run(tmp_path, monkeypatch):
    output = tmp_path/'world'; output.mkdir()
    (output/'execution.private.json').write_text(json.dumps({'validation': 'off',
        'runtime_options': {'lazy_publication': True}, 'answer_grading': {'mode': 'subscription-post-run'}}))
    events = []; discovery = object()
    class Episode:
        def __init__(self, *a, **kw):
            self.task = SimpleNamespace(files={}, make_env=lambda: None, site_discovery_callback=discovery)
            self.profile = SimpleNamespace(name='relaxation+site-discovery')
        def __enter__(self): return self
        def __exit__(self, *a): events.append('runtime-close')
        def export_private_runtime(self, path): path.mkdir()
    monkeypatch.setattr(execution, 'CatalogRelaxationEpisode', Episode)
    monkeypatch.setattr(execution.lifecycle.shared, 'load', lambda p: {'source_sha256': {}})
    monkeypatch.setattr(execution.lifecycle, 'provenance', lambda p: {'fixture': True})
    @contextmanager
    def policy(*, before_dispatch):
        before_dispatch(); events.append('policy-open')
        try: yield object()
        finally: events.append('policy-close')
    def runner(*a, **kw):
        assert kw['site_discovery'] is discovery
        trace = kw['output']/'actual'; trace.mkdir(parents=True)
        events.append('policy-result'); return trace, {'stop_reason': 'agent_finished'}
    def grade(**kw):
        assert 'policy-close' in events
        assert kw['inputs']['task'] == output/'catalog-relaxation-task.private.json'
        assert kw['inputs']['reference'] == output/'catalog-relaxation-reference.private.json'
        assert kw['inputs']['bindings'] == tmp_path/'run/runtime-binding/bindings.private.json'
        assert 'site_registry' not in kw['inputs']
        assert kw['trace'] == tmp_path/'run/runs/actual'
        assert kw['grader_factory'] is execution.CatalogRelaxationGrader
        events.append('relaxation-extraction'); return {'structured_claims_correct': True}
    monkeypatch.setattr(execution.task_answer, 'grade_saved_once', grade)
    return output, events, policy, runner


def test_actual_bindings_trace_and_once_only_after_policy_close(tmp_path, monkeypatch):
    output, events, policy, runner = setup_run(tmp_path, monkeypatch)
    kwargs = dict(policy_session=policy, metadata={}, runner_options={'max_steps': 5, 'max_input_tokens': 100000},
        quota_guard=lambda: None, extraction_backend_factory=lambda p: object(), runner=runner)
    result = execution.run(output, tmp_path/'run', **kwargs)
    assert result['answer_grading']['task_completed'] is True
    assert events == ['policy-open', 'policy-result', 'policy-close', 'relaxation-extraction', 'runtime-close']
    with pytest.raises(FileExistsError): execution.run(output, tmp_path/'run', **kwargs)


@pytest.mark.parametrize('bad', ['binding', 'public_task', 'comparison_scope'])
def test_changed_binding_or_scope_rejects_before_runtime(tmp_path, monkeypatch, bad):
    monkeypatch.setattr(execution.shared, 'load', lambda p: {'recipe': 'website-catalog-relaxation-publication-v1'})
    native = {'task_id': 'relaxation', 'user_message': 'Find the first permitted match', 'memories': [], 'comparison_site_id': 'comparison-00'}
    binding = {'status': 'bound', 'world_repaired': False}
    episode = {'task_id': native['task_id'], 'manual_task': {k: native[k] for k in ['user_message', 'memories']}, 'start': {'kind': 'directory'}}
    if bad == 'binding': binding['world_repaired'] = True
    if bad == 'public_task': episode['manual_task']['user_message'] = 'Different task'
    if bad == 'comparison_scope': episode['start'] = {'kind': 'comparison_home', 'comparison_site_id': 'comparison-01'}
    for name, value in [('episode.json', episode), ('catalog-relaxation-task.private.json', native), ('catalog-relaxation-binding.private.json', binding)]:
        (tmp_path/name).write_text(json.dumps(value))
    import environments.website_world.runtime as runtime
    def forbidden(*a, **kw): raise AssertionError('Runtime must not start')
    monkeypatch.setattr(runtime, 'Runtime', forbidden)
    with pytest.raises(ValueError, match='changed'): execution.CatalogRelaxationEpisode(tmp_path)


def test_foreign_returned_trace_cannot_grade(tmp_path, monkeypatch):
    output, events, policy, _ = setup_run(tmp_path, monkeypatch)
    def foreign(*a, **kw): return tmp_path/'foreign', {'stop_reason': 'agent_finished'}
    with pytest.raises(ValueError, match='outside this execution'):
        execution.run(output, tmp_path/'run', policy_session=policy, metadata={},
            runner_options={'max_steps': 5, 'max_input_tokens': 100000}, quota_guard=lambda: None, runner=foreign)
    assert 'relaxation-extraction' not in events
