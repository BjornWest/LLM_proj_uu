from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from environments.website_world import catalog_checkout_details_execution as execution


def test_native_grade_consumes_original_raw_capture(tmp_path, monkeypatch):
    original = {'before': {'storage_state': {'original': 'before'}},
                'after': {'storage_state': {'original': 'after'}},
                'effect_journal': None, 'episode_id': 'real', 'main_trace_sha256': 'hash'}
    seals = []
    def seal(trace, summary):
        if seals: raise FileExistsError('sealed')
        seals.append(True)
        return original, True
    def grade(world, task, reference, **kwargs):
        assert kwargs['capsule'] is original
        assert kwargs['capsule']['effect_journal'] is None
        assert kwargs['episode_id'] == 'real' and kwargs['policy_completed']
        return {'verdict': 'inconclusive'}
    monkeypatch.setattr(execution.native, 'grade', grade)
    capture = SimpleNamespace(seal=seal, binding={'actual': 'binding'})
    copy = deepcopy(original)
    result = execution.grade_saved_return(capture, tmp_path, {}, world={}, task={}, reference={}, checkout_domain={})
    assert result['verdict'] == 'inconclusive' and original == copy
    with pytest.raises(FileExistsError):
        execution.grade_saved_return(capture, tmp_path, {}, world={}, task={}, reference={}, checkout_domain={})


@pytest.mark.parametrize('options', [
    {'max_steps': 0, 'max_input_tokens': 20},
    {'max_steps': 20, 'max_input_tokens': True},
    {'max_steps': 20, 'max_input_tokens': 20, 'episode_task': object()},
])
def test_invalid_execution_cannot_open_transport(tmp_path, options):
    def forbidden(**kwargs): raise AssertionError('Transport opened')
    with pytest.raises(ValueError):
        execution.run(tmp_path/'recipe', tmp_path/'run', policy_session=forbidden,
                      metadata={}, runner_options=options)
    assert not (tmp_path/'run').exists()


def test_capture_grade_occurs_once_after_policy_close(tmp_path, monkeypatch):
    events = []
    discovery = object()
    class Episode:
        def __init__(self, *args, **kwargs):
            self.task = SimpleNamespace(files={}, make_env=lambda: None)
            self.profile = object(); self.site_discovery = discovery
            self.runtime = SimpleNamespace(world={}, baskets=SimpleNamespace(domain={}))
            self.capture = object(); self.native_task = {'memories': ['original']}; self.reference = {}
        def __enter__(self): return self
        def __exit__(self, *args): events.append('runtime-close')
        def export_private_runtime(self, path): path.mkdir()
    monkeypatch.setattr(execution, 'CheckoutDetailsEpisode', Episode)
    @contextmanager
    def policy(*, before_dispatch):
        before_dispatch(); events.append('policy-open')
        try: yield object()
        finally: events.append('policy-close')
    def runner(*args, **kwargs):
        assert kwargs['site_discovery'] is discovery
        events.append('policy-request')
        return tmp_path/'trace', {'stop_reason': 'agent_finished'}
    def grade(*args, **kwargs):
        assert events[-1] == 'policy-close'
        assert kwargs['task']['memories'] == ['original']
        events.append('native-state-grade')
        return {'verdict': 'inconclusive'}
    monkeypatch.setattr(execution, 'grade_saved_return', grade)
    result = execution.run(tmp_path/'recipe', tmp_path/'run', policy_session=policy,
        metadata={}, runner_options={'max_steps': 20, 'max_input_tokens': 100000},
        quota_guard=lambda: None, runner=runner)
    assert result['answer_extraction_requests'] == 0
    assert events == ['policy-open', 'policy-request', 'policy-close', 'native-state-grade', 'runtime-close']
    with pytest.raises(FileExistsError):
        execution.run(tmp_path/'recipe', tmp_path/'run', policy_session=policy,
            metadata={}, runner_options={'max_steps': 20, 'max_input_tokens': 100000},
            quota_guard=lambda: None, runner=runner)
    assert events.count('policy-request') == 1
