"""Trusted per-step instrumentation; offline runner/native doubles, no providers."""
from contextlib import contextmanager, nullcontext
from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from intent_browser.backend import Completion
from intent_browser.harness import native_tools_profile, SemanticFeedback
from intent_browser.runner import _browser_step, run_episode as actual_run_episode
from tests.runner_diagnostics import run_episode
from tests.test_step_telemetry import fixture


def test_no_hook_preserves_exact_result_and_environment_method():
    result = object()
    calls = []
    env = SimpleNamespace(step=lambda action: (calls.append(action), result)[1])
    original = env.step
    assert _browser_step(env, 'once', step=4, tool='click', context=None) is result
    assert calls == ['once'] and env.step is original


@pytest.mark.parametrize('failure', [RuntimeError('step failed'), KeyboardInterrupt('interrupted')])
@pytest.mark.parametrize('suppress', [False, True])
def test_step_failure_unwinds_and_cannot_be_suppressed(failure, suppress):
    calls = []
    def step(action):
        calls.append(('action', action))
        raise failure
    @contextmanager
    def context(index, tool):
        calls.append(('begin', index, tool))
        try:
            yield
        except BaseException as exc:
            assert exc is failure
            if not suppress:
                raise
        finally:
            calls.append(('end', index, tool))
    with pytest.raises(type(failure)) as caught:
        _browser_step(SimpleNamespace(step=step), 'once', step=7, tool='fill', context=context)
    assert caught.value is failure
    assert calls == [('begin', 7, 'fill'), ('action', 'once'), ('end', 7, 'fill')]


@pytest.mark.parametrize('stage', ['enter', 'exit'])
def test_context_failures_never_replay_the_action(stage):
    calls = []
    failure = RuntimeError(stage)
    @contextmanager
    def context(index, tool):
        if stage == 'enter':
            raise failure
        try:
            yield
        finally:
            raise failure
    with pytest.raises(RuntimeError) as caught:
        _browser_step(SimpleNamespace(step=lambda action: calls.append(action)),
                      'once', step=0, tool='click', context=context)
    assert caught.value is failure
    assert calls == ([] if stage == 'enter' else ['once'])


def test_invalid_factory_rejected_before_environment_setup(tmp_path):
    calls = []
    with pytest.raises(ValueError, match='browser_step_context'):
        actual_run_episode(lambda _: calls.append('setup'), object(), {},
                           output=tmp_path, browser_step_context=object())
    assert calls == []


def response(calls):
    return Completion('', {'choices': [{'finish_reason': 'tool_calls', 'message': {
        'role': 'assistant', 'content': None, 'tool_calls': [
            {'id': f'call-{i}', 'type': 'function', 'function': {
                'name': name, 'arguments': json.dumps(arguments)}}
            for i, (name, arguments) in enumerate(calls)]}}]})


@pytest.mark.parametrize('telemetry', [False, True])
@pytest.mark.parametrize('capture_fails', [False, True])
def test_actual_runner_context_surrounds_step_with_optional_native_telemetry(
        tmp_path, monkeypatch, telemetry, capture_fails):
    # This fixture's in-memory RPC connection has no real driver/close transport.
    monkeypatch.setattr('intent_browser.browser_shutdown.cleanup_rpc_budget',
                        lambda *args, **kwargs: nullcontext(0))
    env, connection, calls = fixture()
    contexts = []
    failure = RuntimeError('post-action capture failed')
    @contextmanager
    def context(index, tool):
        contexts.append(('begin', index, tool, tuple(calls)))
        if capture_fails:
            def broken():
                raise failure
            env._get_obs = broken
        try:
            yield
        except BaseException as exc:
            contexts.append(('error', exc))
            raise
        finally:
            contexts.append(('end', index, tool, tuple(calls)))
    class Backend:
        def configure_tools(self, options): pass
        def complete(self, messages):
            return response([('send_msg_to_user', {'text': 'Done'})])
    profile = replace(native_tools_profile(), feedback_factory=SemanticFeedback,
                      observation=lambda obs, **kwargs: 'Inspect')
    try:
        path, summary = run_episode(lambda _: env, Backend(), {'tags': ['scripted']},
            str(tmp_path), max_steps=1, harness_profile=profile,
            observation_pipeline=None, env_step_telemetry=telemetry,
            browser_step_context=context)
        assert contexts[0] == ('begin', 0, 'send_msg_to_user', ())
        assert contexts[-1][:3] == ('end', 0, 'send_msg_to_user')
        assert calls.count('action') == 1
        assert 'step' not in vars(env)
        if capture_fails:
            assert contexts[1] == ('error', failure)
            assert summary['error'] == 'RuntimeError: post-action capture failed'
        else:
            assert summary['error'] is None and summary['stop_reason'] == 'agent_finished'
        assert len((path/'steps.jsonl').read_text().splitlines()) == 1
    finally:
        connection.loop.close()


def test_batch_uses_fresh_contexts_with_execution_indices(tmp_path, monkeypatch):
    monkeypatch.setattr('intent_browser.browser_shutdown.cleanup_rpc_budget',
                        lambda *args, **kwargs: nullcontext(0))
    env, connection, calls = fixture()
    env.last_action_error = ''
    frame = SimpleNamespace(evaluate=lambda _: ['http://fixture/', 1],
                            wait_for_load_state=lambda *args, **kwargs: None)
    env.page.main_frame = frame
    env.page.frames = [frame]
    entries = []
    @contextmanager
    def context(index, tool):
        entries.append(('begin', index, tool))
        try:
            yield
        finally:
            entries.append(('end', index, tool))
    class Backend:
        def configure_tools(self, options): pass
        def complete(self, messages):
            return response([('noop', {'wait_ms': 0}), ('send_msg_to_user', {'text': 'Done'})])
    profile = replace(native_tools_profile(), feedback_factory=SemanticFeedback,
                      observation=lambda obs, **kwargs: 'Inspect')
    profile = replace(profile, tools=replace(profile.tools, batch_size=2))
    try:
        _, summary = run_episode(lambda _: env, Backend(), {'tags': ['scripted']},
            str(tmp_path), max_steps=1, harness_profile=profile,
            observation_pipeline=None, browser_step_context=context)
        assert summary['error'] is None
        assert entries == [('begin', 0, 'noop'), ('end', 0, 'noop'),
                           ('begin', 1, 'send_msg_to_user'), ('end', 1, 'send_msg_to_user')]
        assert calls.count('action') == 2 and 'step' not in vars(env)
    finally:
        connection.loop.close()
