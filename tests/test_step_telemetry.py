"""Native BrowserGym step and Playwright protocol doubles; no browser or model."""
import asyncio
from contextlib import nullcontext
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from browsergym.core.env import BrowserEnv

from intent_browser.step_telemetry import ARTIFACT, EnvStepTelemetry, resolve_step_telemetry


class Connection:
    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.sent = []

    def _send_message_to_server(self, obj, method, params, no_reply=False):
        future = self.loop.create_future()
        self.sent.append((method, params, future))
        return SimpleNamespace(future=future)


def fixture():
    connection = Connection()
    page = SimpleNamespace(_impl_obj=SimpleNamespace(_connection=connection), frames=[],
                           url='http://fixture/', is_closed=lambda: False,
                           wait_for_load_state=lambda *a, **k: None)
    calls = []
    context = SimpleNamespace(pages=[page], browser=None, cookies=lambda: calls.append('cookies'))
    page.context = context
    def operation():
        calls.append('action')
        cb = connection._send_message_to_server(SimpleNamespace(_type='Frame'), 'click', {'private': 'SECRET'})
        cb.future.set_result({'private': 'REPLY'})
        connection.loop.run_until_complete(asyncio.sleep(0))
    page.operation = operation
    observation = {'goal': 'Inspect', 'url': page.url, 'last_action_error': '',
                   'axtree_object': {'nodes': []}, 'screenshot': None}
    def capture():
        calls.append('capture')
        cb = connection._send_message_to_server(SimpleNamespace(_type='CDPSession'), 'send',
            {'method': 'Accessibility.getFullAXTree', 'params': {'private': 'SECRET'}})
        cb.future.set_result({'nodes': []})
        connection.loop.run_until_complete(asyncio.sleep(0))
        return {**observation, 'last_action_error': env.last_action_error}
    env = object.__new__(BrowserEnv)
    env.page, env.context = page, context
    env.chat = SimpleNamespace(messages=[{'role': 'user', 'message': 'Inspect'}])
    env.pre_observation_delay = 0
    env.wait_for_user_message = False
    env.terminate_on_infeasible = False
    env.infeasible_message_received = False
    env._active_page_check = lambda: None
    env._task_validate = lambda: (0, False, None, {})
    env._get_obs = capture
    env.action_mapping = lambda _: 'page.operation()'
    env.reset = lambda seed: (observation, {})
    env.close = lambda: None
    return env, connection, calls


def rows(directory):
    return [json.loads(line) for line in (directory / ARTIFACT).read_text().splitlines()]


def test_explicit_option_environment_and_validation(monkeypatch):
    monkeypatch.delenv('HARNESS_ENV_STEP_TELEMETRY', raising=False)
    assert resolve_step_telemetry() is False
    monkeypatch.setenv('HARNESS_ENV_STEP_TELEMETRY', '1')
    assert resolve_step_telemetry() is True
    assert resolve_step_telemetry(False) is False
    monkeypatch.setenv('HARNESS_ENV_STEP_TELEMETRY', 'true')
    with pytest.raises(ValueError): resolve_step_telemetry()
    with pytest.raises(ValueError): resolve_step_telemetry(1)


def test_native_step_results_calls_order_and_instance_hooks_preserved(tmp_path):
    env, conn, calls = fixture()
    before_env, before_connection = dict(vars(env)), dict(vars(conn))
    original_code = BrowserEnv.step.__code__
    original_globals = BrowserEnv.step.__globals__['execute_python_code']
    recorder = EnvStepTelemetry(tmp_path)
    try:
        with recorder.observe(env, step=3, tool='click'):
            actual = env.step("click(bid='3957')")
        assert calls == ['action', 'cookies', 'capture']
        assert actual[0]['last_action_error'] == '' and actual[1:4] == (0, False, False)
        assert [x[0] for x in conn.sent] == ['click', 'send']
        assert vars(env).keys() == before_env.keys() | {'last_action', 'last_action_error'}
        for key, value in before_env.items(): assert vars(env)[key] is value
        assert vars(conn).keys() == before_connection.keys()
        assert BrowserEnv.step.__code__ is original_code
        assert BrowserEnv.step.__globals__['execute_python_code'] is original_globals
        result = rows(tmp_path)
        started = [r['phase'] for r in result if r['event'] == 'phase_started']
        assert started == ['env_step', 'pre_step', 'action_execution', 'post_step',
                           '_wait_dom_loaded', '_active_page_check', '_wait_for_user_message',
                           '_task_validate', '_get_obs']
        assert {r['rpc_id'] for r in result if r['event'] == 'rpc_started'} == {
               r['rpc_id'] for r in result if r['event'] == 'rpc_finished'}
        assert 'SECRET' not in json.dumps(result) and 'REPLY' not in json.dumps(result)
        assert result[-1]['pending_rpc_count'] == 0
    finally:
        recorder.close(); conn.loop.close()


@pytest.mark.parametrize('enabled', [False, True])
def test_actual_native_timeout_preserves_error_and_still_captures(tmp_path, enabled):
    env, conn, calls = fixture()
    def timeout():
        calls.append('action')
        raise TimeoutError('Timeout 5000ms exceeded. SECRET')
    env.page.operation = timeout
    recorder = EnvStepTelemetry(tmp_path) if enabled else None
    try:
        with recorder.observe(env, step=0, tool='click') if enabled else nullcontext():
            result = env.step('click')
        assert calls == ['action', 'cookies', 'capture']
        assert result[0]['last_action_error'] == 'TimeoutError: Timeout 5000ms exceeded. SECRET'
        assert result[4]['action_exec_timeout'] == 5.0
        if enabled:
            out = rows(tmp_path)
            assert any(r.get('phase') == 'action_execution' and r.get('error_type') == 'TimeoutError' for r in out)
            assert 'SECRET' not in json.dumps(out)
        else:
            assert not (tmp_path / ARTIFACT).exists()
    finally:
        if recorder: recorder.close()
        conn.loop.close()


def test_capture_failure_is_distinct_and_hooks_restore(tmp_path):
    env, conn, calls = fixture()
    failure = RuntimeError('private capture failure')
    def broken(): raise failure
    env._get_obs = broken
    recorder = EnvStepTelemetry(tmp_path)
    try:
        with pytest.raises(RuntimeError) as caught:
            with recorder.observe(env, step=1, tool='click'):
                env.step('click')
        assert caught.value is failure and env._get_obs is broken
        assert 'step' not in vars(env) and '_send_message_to_server' not in vars(conn)
        out = rows(tmp_path)
        assert any(r.get('phase') == 'action_execution' and r['event'] == 'phase_finished'
                   and r['error_type'] is None for r in out)
        assert any(r.get('phase') == '_get_obs' and r.get('error_type') == 'RuntimeError' for r in out)
    finally:
        recorder.close(); conn.loop.close()


def test_rpc_starts_flushed_before_send_and_future_error_redacted(tmp_path):
    env, conn, calls = fixture()
    original = conn._send_message_to_server
    failure = RuntimeError('PRIVATE RPC URL')
    def send(*args, **kwargs):
        assert rows(tmp_path)[-1]['event'] == 'rpc_started'
        return original(*args, **kwargs)
    conn._send_message_to_server = send
    recorder = EnvStepTelemetry(tmp_path)
    try:
        with recorder.observe(env, step=2, tool='click'):
            cb = conn._send_message_to_server(SimpleNamespace(_type='CDPSession'), 'send',
                {'method': 'Fetch.fulfillRequest', 'body': 'SECRET'})
            cb.future.set_exception(failure)
            conn.loop.run_until_complete(asyncio.sleep(0))
            assert cb.future.exception() is failure
        out = rows(tmp_path)
        rpc = [r for r in out if r['event'] == 'rpc_finished'][0]
        assert rpc['cdp_method'] == 'Fetch.fulfillRequest' and rpc['error_type'] == 'RuntimeError'
        assert 'PRIVATE' not in json.dumps(out) and 'SECRET' not in json.dumps(out)
        assert conn._send_message_to_server is send
    finally:
        recorder.close(); conn.loop.close()


def test_real_installed_dispatch_no_reply_is_send_not_pending_wait(tmp_path):
    from playwright._impl._connection import Connection as NativeConnection
    loop = asyncio.new_event_loop()
    messages = []
    transport = SimpleNamespace(send=messages.append)
    connection = NativeConnection(None, lambda *args: None, transport, loop)
    env = SimpleNamespace(page=SimpleNamespace(_impl_obj=SimpleNamespace(_connection=connection)),
                          step=lambda: None)
    channel = SimpleNamespace(_was_collected=False, _guid='fixture', _type='Frame')
    recorder = EnvStepTelemetry(tmp_path)
    connection._api_zone.set({'apiName': 'fixture', 'frames': []})
    try:
        with recorder.observe(env, step=0, tool='click'):
            async def exercise():
                ignored = connection._send_message_to_server(channel, 'waitForEventInfo', {}, no_reply=True)
                ignored_id = messages[-1]['id']
                connection.dispatch({'id': ignored_id, 'result': {}})
                assert ignored_id not in connection._callbacks and not ignored.future.done()
                assert ignored.future._callbacks is None  # No diagnostic completion observer.
                ordinary = connection._send_message_to_server(channel, 'click', {})
                connection.dispatch({'id': messages[-1]['id'], 'result': {}})
                await asyncio.sleep(0)
                assert ordinary.future.done()
            loop.run_until_complete(exercise())
        out = rows(tmp_path)
        assert out[-1]['pending_rpc_count'] == 0
        assert [r['event'] for r in out if r.get('method') == 'waitForEventInfo'] == [
            'rpc_send_started', 'rpc_send_finished']
        assert next(r for r in out if r['event'] == 'rpc_send_finished')['scope'] == 'transport_send_only'
        assert any(r['event'] == 'rpc_finished' and r['method'] == 'click' for r in out)
        assert '_send_message_to_server' not in vars(connection)
    finally:
        recorder.close(); loop.close()


@pytest.mark.parametrize('cancel', [False, True])
def test_pending_rpc_and_late_reply_cannot_cross_next_step(tmp_path, cancel):
    env, conn, calls = fixture(); recorder = EnvStepTelemetry(tmp_path)
    try:
        with recorder.observe(env, step=1, tool='click'):
            cb = conn._send_message_to_server(SimpleNamespace(_type='Frame'), 'click', {})
        assert rows(tmp_path)[-1]['pending_rpc_count'] == 1
        with recorder.observe(env, step=2, tool='noop'):
            if cancel: cb.future.cancel()
            else: cb.future.set_result(None)
            conn.loop.run_until_complete(asyncio.sleep(0))
        assert not any(r['event'] == 'rpc_finished' for r in rows(tmp_path))
        assert rows(tmp_path)[-1]['step'] == 2
    finally:
        recorder.close(); conn.loop.close()


def test_record_and_byte_caps_stop_diagnostics_not_actions(tmp_path):
    for label, limits in [('records', {'max_records': 2}), ('bytes', {'max_bytes': 1024})]:
        directory = tmp_path / label; directory.mkdir()
        env, conn, calls = fixture(); recorder = EnvStepTelemetry(directory, **limits)
        try:
            with recorder.observe(env, step=0, tool='click'): env.step('click')
            assert calls == ['action', 'cookies', 'capture']
            out = rows(directory)
            assert out[-1]['event'] == 'telemetry_limit'
            assert (directory / ARTIFACT).stat().st_size <= recorder.max_bytes
            assert len(out) <= recorder.max_records
        finally:
            recorder.close(); conn.loop.close()


def test_write_failure_does_not_interrupt_effects_or_restore(tmp_path):
    env, conn, calls = fixture(); recorder = EnvStepTelemetry(tmp_path)
    real_stream = recorder.stream
    recorder.stream = SimpleNamespace(write=lambda _: (_ for _ in ()).throw(OSError('SECRET')),
                                       close=lambda: None)
    try:
        with recorder.observe(env, step=0, tool='click'): env.step('click')
        assert calls == ['action', 'cookies', 'capture']
        assert recorder.describe()['write_error_type'] == 'OSError'
        assert 'step' not in vars(env) and '_intent_step_telemetry_owner' not in vars(conn)
    finally:
        recorder.close(); real_stream.close(); conn.loop.close()


def test_reentrant_scope_rejected_and_preexisting_instrumentation_restored(tmp_path):
    env, conn, _ = fixture(); original = conn._send_message_to_server
    conn._send_message_to_server = lambda *a, **k: original(*a, **k)
    prior = conn._send_message_to_server
    recorder = EnvStepTelemetry(tmp_path)
    try:
        with recorder.observe(env, step=0, tool='noop'):
            with pytest.raises(ValueError):
                with recorder.observe(env, step=1, tool='noop'): pass
        assert conn._send_message_to_server is prior
    finally:
        recorder.close(); conn.loop.close()


def test_unsupported_version_rejected_before_artifact(tmp_path):
    with patch('intent_browser.step_telemetry.version', return_value='wrong'), pytest.raises(ValueError):
        EnvStepTelemetry(tmp_path)
    assert not (tmp_path / ARTIFACT).exists()


def test_abrupt_child_exit_preserves_pending_rpc_without_completion(tmp_path):
    code = '''
import os,sys
from types import SimpleNamespace
from intent_browser.step_telemetry import EnvStepTelemetry
connection=SimpleNamespace(_send_message_to_server=lambda *a,**k:os._exit(0))
env=SimpleNamespace(page=SimpleNamespace(_impl_obj=SimpleNamespace(_connection=connection)),step=lambda:None)
telemetry=EnvStepTelemetry(sys.argv[1])
with telemetry.observe(env,step=15,tool='click'):
    connection._send_message_to_server(SimpleNamespace(_type='Frame'),'click',{'bid':'PRIVATE'})
'''
    environment = {**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1])}
    completed = subprocess.run([sys.executable, '-B', '-c', code, str(tmp_path)],
                               env=environment, cwd=tmp_path, capture_output=True, timeout=10)
    assert completed.returncode == 0, completed.stderr.decode()
    out = rows(tmp_path)
    assert out[-1]['event'] == 'rpc_started' and out[-1]['method'] == 'click'
    assert not any(r['event'] in ('rpc_finished', 'phase_finished') for r in out)
    assert 'PRIVATE' not in json.dumps(out)


@pytest.mark.parametrize('enabled', [False, True])
def test_actual_runner_attaches_only_when_opted_in_and_preserves_policy(tmp_path, enabled):
    from dataclasses import replace
    from intent_browser.backend import Completion
    from intent_browser.harness import native_tools_profile, SemanticFeedback
    from tests.runner_diagnostics import run_episode
    env, conn, calls = fixture()
    class Backend:
        def configure_tools(self, options): self.options = options
        def complete(self, messages):
            self.messages = messages
            return Completion('', {'choices': [{'finish_reason': 'tool_calls', 'message': {
                'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'one',
                'type': 'function', 'function': {'name': 'send_msg_to_user',
                'arguments': '{"text":"Done"}'}}]}}]})
    backend = Backend()
    profile = replace(native_tools_profile(), feedback_factory=SemanticFeedback,
                      observation=lambda obs, **kwargs: 'Inspect')
    try:
        path, summary = run_episode(lambda _: env, backend, {'tags': ['scripted']}, str(tmp_path),
            max_steps=2, harness_profile=profile, observation_pipeline=None,
            env_step_telemetry=enabled)
        assert summary['stop_reason'] == 'agent_finished' and summary['error'] is None
        assert calls == ['action', 'cookies', 'capture']
        assert (path / ARTIFACT).exists() is enabled
        assert ARTIFACT not in json.dumps(backend.messages)
        metadata = json.loads((path / 'metadata.json').read_text())
        assert ('env_step_telemetry' in metadata) is enabled
        assert 'step' not in vars(env) and '_send_message_to_server' not in vars(conn)
    finally:
        conn.loop.close()
