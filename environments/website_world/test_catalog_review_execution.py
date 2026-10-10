from contextlib import contextmanager
import json
from types import SimpleNamespace
import pytest
from environments.website_world import catalog_review_execution as execution


def setup_run(tmp_path, monkeypatch):
    output = tmp_path/'world'; output.mkdir()
    (output/'execution.private.json').write_text(json.dumps({'validation': 'off',
        'runtime_options': {'lazy_publication': True}, 'answer_grading': {'mode': 'subscription-post-run'}}))
    events = []; discovery = object()
    class Episode:
        def __init__(self, *a, **kw):
            self.task = SimpleNamespace(files={}, make_env=lambda: None, site_discovery_callback=discovery)
            self.profile = SimpleNamespace(name='reviews+site-discovery')
        def __enter__(self): return self
        def __exit__(self, *a): events.append('runtime-close')
        def export_private_runtime(self, path): path.mkdir()
    monkeypatch.setattr(execution, 'CatalogReviewEpisode', Episode)
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
        assert kw['inputs']['task'] == output/'catalog-review-task.private.json'
        assert kw['inputs']['reference'] == output/'catalog-review-reference.private.json'
        assert kw['inputs']['site_registry'] == tmp_path/'run/runtime-binding/site-registry.private.json'
        assert 'bindings' not in kw['inputs']
        assert kw['trace'] == tmp_path/'run/runs/actual'
        assert kw['grader_factory'] is execution.PublishedReviewSummaryGrader
        events.append('review-extraction'); return {'structured_claims_correct': True}
    monkeypatch.setattr(execution.task_answer, 'grade_saved_once', grade)
    return output, events, policy, runner


def test_registry_actual_trace_and_once_only_after_policy_close(tmp_path, monkeypatch):
    output, events, policy, runner = setup_run(tmp_path, monkeypatch)
    result = execution.run(output, tmp_path/'run', policy_session=policy, metadata={},
        runner_options={'max_steps': 5, 'max_input_tokens': 100000}, quota_guard=lambda: None,
        extraction_backend_factory=lambda p: object(), runner=runner)
    assert result['answer_grading']['task_completed'] is True
    assert events == ['policy-open', 'policy-result', 'policy-close', 'review-extraction', 'runtime-close']
    with pytest.raises(FileExistsError):
        execution.run(output, tmp_path/'run', policy_session=policy, metadata={},
            runner_options={'max_steps': 5, 'max_input_tokens': 100000}, quota_guard=lambda: None, runner=runner)


@pytest.mark.parametrize('status', ['unsupported_no_manufactured_subject', 'unsupported_no_review_publication'])
def test_unsupported_binding_rejects_before_runtime(tmp_path, monkeypatch, status):
    monkeypatch.setattr(execution.shared, 'load', lambda p: {'recipe': 'website-catalog-review-publication-v1'})
    (tmp_path/'catalog-review-binding.private.json').write_text(json.dumps({'status': status, 'world_repaired': False}))
    import environments.website_world.runtime as runtime
    def forbidden(*a, **kw): raise AssertionError('Runtime must not start')
    monkeypatch.setattr(runtime, 'Runtime', forbidden)
    with pytest.raises(ValueError, match='cannot launch'): execution.CatalogReviewEpisode(tmp_path)


def test_foreign_returned_trace_cannot_grade(tmp_path, monkeypatch):
    output, events, policy, _ = setup_run(tmp_path, monkeypatch)
    def foreign(*a, **kw): return tmp_path/'foreign', {'stop_reason': 'agent_finished'}
    with pytest.raises(ValueError, match='outside this execution'):
        execution.run(output, tmp_path/'run', policy_session=policy, metadata={},
            runner_options={'max_steps': 5, 'max_input_tokens': 100000}, quota_guard=lambda: None, runner=foreign)
    assert 'review-extraction' not in events


def test_publication_projection_preserves_every_native_grade_value():
    from environments.website_world.test_catalog_review_task import fixture, claims_for
    world, task, reference, registry, surrounding, inventory = fixture()
    text, claims = claims_for(task, reference)
    arguments = (world, task, reference, registry)
    native = execution.ReviewSummaryGrader(*arguments, inventory=inventory, surrounding=surrounding).grade(claims, text)
    published = execution.PublishedReviewSummaryGrader(*arguments, inventory=inventory, surrounding=surrounding).grade(claims, text)
    assert published == {**native, 'derivations': [native['derivations']]}

