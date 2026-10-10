from contextlib import contextmanager
import json
from types import SimpleNamespace

import pytest

from environments.website_world import memory_offer_execution as execution


def setup_run(tmp_path, monkeypatch):
    output = tmp_path/'world'; output.mkdir()
    (output/'execution.private.json').write_text(json.dumps({'validation': 'off',
        'runtime_options': {'lazy_publication': True},
        'answer_grading': {'mode': 'subscription-post-run'}}))
    events = []
    discovery = object()
    class Episode:
        def __init__(self, *args, **kwargs):
            self.task = SimpleNamespace(files={}, make_env=lambda: None,
                                        site_discovery_callback=discovery)
            self.profile = SimpleNamespace(name='feature+site-discovery')
        def __enter__(self): return self
        def __exit__(self, *args): events.append('runtime-close')
        def export_private_runtime(self, path): path.mkdir()
    monkeypatch.setattr(execution, 'MemoryOfferEpisode', Episode)
    monkeypatch.setattr(execution.lifecycle.shared, 'load', lambda p: {'source_sha256': {}})
    monkeypatch.setattr(execution.lifecycle, 'provenance', lambda p: {'fixture': True})
    @contextmanager
    def policy_session(*, before_dispatch):
        before_dispatch(); events.append('policy-open')
        try: yield object()
        finally: events.append('policy-close')
    def runner(*args, **kwargs):
        assert kwargs['site_discovery'] is discovery
        events.append('policy-request')
        return tmp_path/'trace', {'stop_reason': 'agent_finished'}
    def grade(**kwargs):
        assert 'policy-close' in events
        assert kwargs['grader_factory'] is execution.MemoryOfferGrader
        assert kwargs['inputs']['task'].name == 'memory-offer-task.private.json'
        assert kwargs['inputs']['reference'].name == 'memory-offer-reference.private.json'
        assert 'site_registry' not in kwargs['inputs']
        assert kwargs['before_model_dispatch']() is None
        events.append('memory-extraction')
        return {'structured_claims_correct': True}
    monkeypatch.setattr(execution.task_answer, 'grade_saved_once', grade)
    return output, events, policy_session, runner


def test_private_feature_bindings_and_discovery_use_accepted_once_lifecycle(tmp_path, monkeypatch):
    output, events, policy, runner = setup_run(tmp_path, monkeypatch)
    result = execution.run(output, tmp_path/'run', policy_session=policy, metadata={},
        runner_options={'max_steps': 40, 'max_input_tokens': 100000},
        quota_guard=lambda: None, extraction_backend_factory=lambda p: object(), runner=runner)
    assert result['schema'] == execution.VERSION
    assert result['answer_grading']['task_completed'] is True
    assert events == ['policy-open', 'policy-request', 'policy-close', 'memory-extraction', 'runtime-close']
    with pytest.raises(FileExistsError):
        execution.run(output, tmp_path/'run', policy_session=policy, metadata={},
            runner_options={'max_steps': 40, 'max_input_tokens': 100000},
            quota_guard=lambda: None, runner=runner)
    assert events.count('policy-request') == 1


def test_malformed_feature_extraction_stays_unknown_without_retry(tmp_path, monkeypatch):
    output, events, policy, runner = setup_run(tmp_path, monkeypatch)
    def fail(**kwargs):
        events.append('failed-extraction'); raise ValueError('malformed')
    monkeypatch.setattr(execution.task_answer, 'grade_saved_once', fail)
    result = execution.run(output, tmp_path/'run', policy_session=policy, metadata={},
        runner_options={'max_steps': 40, 'max_input_tokens': 100000},
        quota_guard=lambda: None, runner=runner)
    assert result['answer_grading']['task_completed'] is None
    assert result['answer_grading']['automatic_retries'] == 0
    assert events.count('failed-extraction') == 1


def test_quota_hold_never_opens_policy_transport(tmp_path, monkeypatch):
    output, events, policy, runner = setup_run(tmp_path, monkeypatch)
    def hold(): raise RuntimeError('quota floor')
    with pytest.raises(RuntimeError, match='quota floor'):
        execution.run(output, tmp_path/'run', policy_session=policy, metadata={},
            runner_options={'max_steps': 40, 'max_input_tokens': 100000},
            quota_guard=hold, runner=runner)
    assert events == ['runtime-close']
