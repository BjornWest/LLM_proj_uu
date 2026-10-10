from contextlib import contextmanager
import json
from types import SimpleNamespace

import pytest

from environments.website_world import comparison_stock_execution as execution


def setup_execution(tmp_path, monkeypatch, *, mode='subscription-post-run'):
    output = tmp_path/'world'
    output.mkdir()
    (output/'execution.private.json').write_text(json.dumps({
        'validation': 'off', 'runtime_options': {'lazy_publication': True},
        'answer_grading': {'mode': mode}}))
    events = []
    class Episode:
        def __init__(self, output, *, lazy_publication):
            assert lazy_publication
            self.task = SimpleNamespace(files={}, make_env=lambda: None)
            self.profile = SimpleNamespace(name='fixture')
        def __enter__(self): return self
        def __exit__(self, *args): events.append('runtime-close')
        def export_private_runtime(self, path):
            path.mkdir()
            for name in ('bindings.private.json', 'site-registry.private.json'):
                (path/name).write_text('{}')
    monkeypatch.setattr(execution, 'ComparisonStockEpisode', Episode)
    monkeypatch.setattr(execution.shared, 'load', lambda p: {'source_sha256': {}})
    monkeypatch.setattr(execution, 'provenance', lambda p: {'test': True})
    @contextmanager
    def policy_session(*, before_dispatch):
        events.append('policy-open')
        before_dispatch()
        try: yield object()
        finally: events.append('policy-close')
    def runner(*args, **kwargs):
        events.append('policy-request')
        return tmp_path/'trace', {'stop_reason': 'agent_finished'}
    def grade(**kwargs):
        assert 'policy-close' in events
        assert kwargs['inputs']['task'].name == 'comparison-stock-task.private.json'
        assert kwargs['inputs']['site_registry'].name == 'site-registry.private.json'
        assert kwargs['grader_factory'] is execution.ComparisonStockGrader
        kwargs['before_model_dispatch']()
        events.append('extraction')
        return {'structured_claims_correct': True}
    monkeypatch.setattr(execution.task_answer, 'grade_saved_once', grade)
    return output, events, policy_session, runner


def test_policy_closes_before_task_specific_extraction(tmp_path, monkeypatch):
    output, events, policy_session, runner = setup_execution(tmp_path, monkeypatch)
    result = execution.run(output, tmp_path/'run', policy_session=policy_session,
        metadata={}, runner_options={'max_steps': 40, 'max_input_tokens': 100000},
        quota_guard=lambda: events.append('quota'), extraction_backend_factory=lambda p: object(),
        runner=runner)
    assert events.index('policy-close') < events.index('extraction') < events.index('runtime-close')
    assert events.count('extraction') == 1
    assert result['answer_grading']['task_completed'] is True
    # An existing directory cannot dispatch another policy or formatter.
    with pytest.raises(FileExistsError):
        execution.run(output, tmp_path/'run', policy_session=policy_session,
            metadata={}, runner_options={'max_steps': 40, 'max_input_tokens': 100000},
            quota_guard=lambda: None, runner=runner)
    assert events.count('policy-open') == 1


def test_extraction_failure_is_unknown_without_retry(tmp_path, monkeypatch):
    output, events, policy_session, runner = setup_execution(tmp_path, monkeypatch)
    def failure(**kwargs):
        events.append('failed-extraction')
        raise ValueError('Malformed claims')
    monkeypatch.setattr(execution.task_answer, 'grade_saved_once', failure)
    result = execution.run(output, tmp_path/'run', policy_session=policy_session,
        metadata={}, runner_options={'max_steps': 40, 'max_input_tokens': 100000},
        quota_guard=lambda: None, runner=runner)
    assert result['answer_grading']['status'] == 'failed'
    assert result['answer_grading']['task_completed'] is None
    assert events.count('failed-extraction') == 1


def test_quota_hold_prevents_policy_transport(tmp_path, monkeypatch):
    output, events, policy_session, runner = setup_execution(tmp_path, monkeypatch)
    def held(): raise RuntimeError('quota floor')
    with pytest.raises(RuntimeError, match='quota floor'):
        execution.run(output, tmp_path/'run', policy_session=policy_session,
            metadata={}, runner_options={'max_steps': 40, 'max_input_tokens': 100000},
            quota_guard=held, runner=runner)
    assert 'policy-open' not in events
    assert 'policy-request' not in events


def test_disabled_grading_never_extracts(tmp_path, monkeypatch):
    output, events, policy_session, runner = setup_execution(tmp_path, monkeypatch, mode='off')
    result = execution.run(output, tmp_path/'run', policy_session=policy_session,
        metadata={}, runner_options={'max_steps': 40, 'max_input_tokens': 100000},
        quota_guard=lambda: None, runner=runner)
    assert result['answer_grading']['status'] == 'disabled'
    assert 'extraction' not in events
