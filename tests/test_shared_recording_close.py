"""Original pooled close under exact fact-recording instrumentation; no models."""
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from browsergym.core.env import BrowserEnv
from intent_browser.browser_shutdown import close_resources, supported
from intent_browser.chromium_pool import PoolError, PoolSupervisor
from intent_browser.shared_browsergym import PoolEpisode, SharedBrowserEnv, supported_shared
from training.browser_training.native_suite_recording import (
    NativeSuiteProvider, package_pins, recording_env_factory, recording_runner,
)


@pytest.mark.parametrize('failed', [None, 'task', 'chat', 'context', 'browser'])
def test_saved_original_close_runs_independent_resources_once(failed):
    calls = []
    def operation(name):
        def execute():
            calls.append(name)
            if name == failed:
                raise RuntimeError('injected ' + name)
        return execute
    env = SharedBrowserEnv.__new__(SharedBrowserEnv)
    env.pool_episode = PoolEpisode(object(), 'unit-recorded')
    env.task_entrypoint = type('Task', (), {})
    env.task = SimpleNamespace(teardown=operation('task'))
    env.chat = SimpleNamespace(close=operation('chat'))
    env.context = SimpleNamespace(close=operation('context'))
    env.browser = SimpleNamespace(close=operation('browser'))
    env.page = None
    provider = SimpleNamespace(close=operation('provider'))
    wrapped = recording_env_factory(SimpleNamespace(make_env=lambda _: env), provider)()
    assert wrapped is env
    # Generic shutdown must still call instrumentation, never skip it.
    assert not supported(env)
    assert not supported_shared(env)
    with pytest.raises(ValueError):
        close_resources(env, lambda *a, **k: pytest.fail('guard bypassed'))
    if failed:
        with pytest.raises(PoolError, match='injected ' + failed):
            env.close()
    else:
        env.close()
    assert calls == ['provider', 'task', 'chat', 'context', 'browser']
    assert env.context is None
    assert (env.browser is None) == (failed != 'browser')


def test_explicit_close_proof_rejects_wrong_receiver_native_custom_and_subclass():
    first = SharedBrowserEnv(task_entrypoint=type('Task', (), {}),
                             pool_episode=PoolEpisode(object(), 'first'))
    second = SharedBrowserEnv(task_entrypoint=type('Task', (), {}),
                              pool_episode=PoolEpisode(object(), 'second'))
    class Custom(SharedBrowserEnv):
        pass
    custom = Custom(task_entrypoint=type('Task', (), {}),
                    pool_episode=PoolEpisode(object(), 'subclass'))
    native = BrowserEnv.__new__(BrowserEnv)
    for env, close in ((first, second.close), (first, lambda: None),
                       (native, first.close), (custom, custom.close)):
        with pytest.raises(ValueError):
            close_resources(env, lambda *a, **k: pytest.fail('guard bypassed'), shared_close=close)
    first.close = second.close
    assert not supported_shared(first)
    with patch.object(BrowserEnv, 'close', lambda self: None), pytest.raises(PoolError):
        close_resources(second, None, shared_close=second.close)


@pytest.mark.parametrize('case', ['correct', 'wrong', 'missing'])
def test_recorded_actual_runner_after_close_native_grade(tmp_path, case):
    from intent_browser.ax_explorer import AXConfig
    from intent_browser.automatic_grading import AutomaticGrading, file_hash
    from intent_browser.backend import Completion
    from intent_browser.evaluation import Evaluation
    from intent_browser.harness import native_tools_profile
    from intent_browser.runner import run_episode
    from intent_browser.trace import write_json
    from tests.shared_chromium_controls import IsolatedPageTask, factory

    tokenizer = Path(os.environ.get('HARNESS_TEST_TOKENIZER',
        str(Path(__file__).resolve().parents[1] / 'training/.cache/qwen38-tokenizer/tokenizer.json')))
    if not tokenizer.is_file():
        pytest.skip('Requires existing local Qwen tokenizer asset')
    reference = tmp_path / 'reference.json'
    reference.write_text('{"color":"red"}')
    with PoolSupervisor(tmp_path / 'pool') as client:
        episode = client.episode('recorded-' + case)
        holder = []
        def make_env(video):
            env = episode.wrap(factory('red'))(video)
            holder.append(env)
            return env
        class Policy:
            calls = 0
            def configure_tools(self, options):
                self.options = options
            def complete(self, messages):
                self.calls += 1
                if self.calls == 1 and case != 'wrong':
                    name = 'click'
                    args = {'bid': holder[0].page.locator('#buy').get_attribute('bid')}
                else:
                    name, args = 'send_msg_to_user', {'text': 'Done'}
                raw = {'choices': [{'message': {'role': 'assistant', 'tool_calls': [
                    {'id': str(self.calls), 'type': 'function', 'function': {
                        'name': name, 'arguments': json.dumps(args)}}]}, 'finish_reason': 'tool_calls'}]}
                return Completion('', raw, {'messages': messages, **self.options})
        class Task:
            supported_harness_profiles = ('core-tools-v7-context',)
            def prepare(self, trace):
                return {'synthetic': True}
            def capture_initial(self, env, observation, info):
                return {}
            def evaluate(self, env, trace, outcome):
                write_json(trace.directory / 'native-state.json', {
                    'basket': env.page.evaluate("localStorage.getItem('basket')"),
                    'answered': any(x['role'] == 'assistant' and x['message'] == 'Done'
                                    for x in env.chat.messages)})
                return Evaluation('synthetic-browser-phase', '1', trust='manual')
        def bind(env, trace, obs):
            import intent_browser.automatic_grading as automatic
            import agent_trace.adapters.browsergym as viewer
            return {'task_id': 'recorded-' + case,
                    'goal_sha256': hashlib.sha256(obs['goal'].encode()).hexdigest(),
                    'reference_files': {str(reference): file_hash(reference)},
                    'source_files': {str(Path(p).resolve()): file_hash(p)
                                     for p in (__file__, automatic.__file__, viewer.__file__)}}
        def grade(env, trace, outcome):
            assert env.task is None and env.context is None and env.browser is None and env.chat is None
            assert client.status()['leases'] == []
            return {'state': json.loads((trace.directory / 'native-state.json').read_text()),
                    'closed': True, 'technical_error': outcome.get('error')}
        def project(raw, binding):
            state = raw['state']
            return Evaluation('recorded-native', '1', trust='native_state',
                task_completed=None if not state['answered'] else state['basket'] == 'red',
                authorization_satisfied=True, technical_error=raw['technical_error'],
                limitations=['Synthetic state only; no generated-world acceptance'])
        runner = recording_runner(run_episode, enabled=True, expected_sources=package_pins())
        try:
            with patch.object(NativeSuiteProvider, 'close', autospec=True,
                              side_effect=NativeSuiteProvider.close) as provider_close, \
                    patch.object(IsolatedPageTask, 'teardown', autospec=True,
                                 side_effect=IsolatedPageTask.teardown) as task_teardown:
                trace, summary = runner(make_env, Policy(), {'model': 'scripted', 'tags': ['scripted']},
                    output=tmp_path / 'runs', max_steps=1 if case == 'missing' else 2,
                    trace_screenshots=False, observation_pipeline='native', episode_task=Task(),
                    harness_profile=native_tools_profile(ax_config=AXConfig(str(tokenizer), incremental=True)),
                    automatic_grading=AutomaticGrading('recorded-v1', bind, grade, project))
                assert provider_close.call_count == 1
                assert task_teardown.call_count == 1
            assert runner.recording_status['enabled']
            assert runner.recording_status['capture_count'] >= 1
            assert summary['error'] is None
            metadata = json.loads((trace / 'metadata.json').read_text())
            assert metadata['fact_recording']['capture_boundary'] == 'native-full-v1'
            assert list(trace.glob('fact-*.json*'))
            projection = json.loads((trace / 'automatic-grade-projection.json').read_text())
            assert projection['verified']
            raw = json.loads((trace / 'automatic-grade.json').read_text())['raw_grade']
            assert raw['closed']
            assert raw['state']['answered'] == (case != 'missing')
            assert raw['state']['basket'] == (None if case == 'wrong' else 'red')
            assert all(row['released'] for row in episode.metadata()['contexts'])
            events = [json.loads(line) for line in (tmp_path / 'pool/events.jsonl').read_text().splitlines()]
            for lease in episode.leases:
                releases = [row for row in events if row['kind'] == 'lease_release_acknowledged'
                            and row['lease_id'] == lease.record['lease_id']]
                assert len(releases) == 1
            evaluation = json.loads((trace / 'evaluation.json').read_text())
            assert evaluation['task_completed'] == {'correct': True, 'wrong': False, 'missing': None}[case]
        finally:
            episode.close()
