from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from environments.website_world import catalog_cart_live_execution as execution


@pytest.mark.parametrize('options', [
    {'max_steps': 0, 'max_input_tokens': 10},
    {'max_steps': True, 'max_input_tokens': 10},
    {'max_steps': 10, 'max_input_tokens': 10, 'episode_task': object()},
    {'max_steps': 10, 'max_input_tokens': 10, 'observation_pipeline': 'foreign'},
])
def test_invalid_limits_cannot_open_policy_or_output(tmp_path, options):
    def forbidden(**kwargs): raise AssertionError('Policy session opened')
    with pytest.raises(ValueError):
        execution.run(tmp_path/'recipe', tmp_path/'run', policy_session=forbidden,
            metadata={}, runner_options=options)
    assert not (tmp_path/'run').exists()


@pytest.mark.parametrize('authority', [None, {'path': 'exact-approval', 'sha256': 'hash'}])
def test_transport_closes_before_once_only_state_grade(tmp_path, monkeypatch, authority):
    events = []; received = []; quota = []
    class Episode:
        def __init__(self, *args, **kwargs):
            assert kwargs['authority_approval'] == authority
            self.task = SimpleNamespace(files={}, make_env=lambda: None)
            self.profile = object(); self.site_discovery = object()
            self.runtime = SimpleNamespace(world={}, baskets=SimpleNamespace(domain={}))
            self.capture = object(); self.native_task = {}; self.reference = {}
        def __enter__(self): return self
        def __exit__(self, *args): events.append('runtime-close')
        def export_private_runtime(self, path): path.mkdir()
    monkeypatch.setattr(execution, 'CartLiveEpisode', Episode)
    @contextmanager
    def session(*, before_dispatch):
        before_dispatch(); events.append('policy-open')
        try: yield object()
        finally: events.append('policy-close')
    def runner(*args, **kwargs):
        trace = kwargs['output']/'actual-episode'; trace.mkdir(parents=True)
        events.append('request'); received.append(trace)
        return trace, {'stop_reason': 'agent_finished'}
    def grade(capture, trace, summary, **kwargs):
        assert events[-1] == 'policy-close' and trace == received[0]
        events.append('state-grade')
        return {'verdict': 'inconclusive' if authority is None else 'pass'}
    monkeypatch.setattr(execution.capture_api, 'grade_saved_return', grade)
    def run():
        return execution.run(tmp_path/'recipe', tmp_path/'run', policy_session=session,
            metadata={}, runner_options={'max_steps': 20, 'max_input_tokens': 100000},
            authority_approval=authority, quota_guard=lambda: quota.append(True), runner=runner)
    result = run()
    assert events == ['policy-open', 'request', 'policy-close', 'state-grade', 'runtime-close']
    assert len(quota) == 2 and result['answer_extraction_requests'] == 0
    with pytest.raises(FileExistsError): run()
    assert events.count('state-grade') == 1


def test_old_execution_remains_held():
    with pytest.raises(RuntimeError, match='Source-only'):
        execution.capture_api.run()
