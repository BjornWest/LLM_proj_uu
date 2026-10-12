"""Source-only protocol doubles for the optional routing diagnostic caller."""
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase, mock
from tempfile import TemporaryDirectory
import json

from .runtime import ScenarioRuntime


class OriginDiagnosticCaller(TestCase):
    def runtime(self, path=None):
        runtime = object.__new__(ScenarioRuntime)
        runtime.origin_diagnostics_path = path
        runtime.origin_map = object()
        runtime._browser_bridges = []
        return runtime

    def test_disabled_delegates_exact_context_to_native(self):
        context = object()
        runtime = self.runtime()
        with mock.patch('environments.website_world.runtime.Runtime.attach_browser', return_value='native') as call:
            self.assertEqual(runtime.attach_browser(context), 'native')
            call.assert_called_once_with(context)

    def test_enabled_preserves_attach_and_owned_cleanup(self):
        context = object()
        runtime = self.runtime(Path('/tmp/prospective-origin-phases.jsonl'))
        bridge = SimpleNamespace(attach=mock.Mock(), close=mock.Mock())
        with mock.patch('environments.website_world.local_origins.LocalOriginBridge', return_value=bridge) as factory:
            self.assertIs(runtime.attach_browser(context), bridge)
            factory.assert_called_once_with(runtime.origin_map, diagnostics_path=runtime.origin_diagnostics_path)
        bridge.attach.assert_called_once_with(context)
        bridge.close.assert_not_called()
        self.assertEqual(runtime._browser_bridges, [(context, bridge)])

    def test_duplicate_rejected_before_constructing_bridge(self):
        context = object()
        runtime = self.runtime(Path('/tmp/phases'))
        runtime._browser_bridges.append((context, object()))
        with mock.patch('environments.website_world.local_origins.LocalOriginBridge') as factory:
            with self.assertRaisesRegex(ValueError, 'already attached'):
                runtime.attach_browser(context)
            factory.assert_not_called()

    def test_missing_map_rejected_before_constructing_bridge(self):
        runtime = self.runtime(Path('/tmp/phases'))
        runtime.origin_map = None
        with mock.patch('environments.website_world.local_origins.LocalOriginBridge') as factory:
            with self.assertRaisesRegex(ValueError, 'readable logical origins'):
                runtime.attach_browser(object())
            factory.assert_not_called()

    def test_failed_attach_closes_unregistered_bridge(self):
        runtime = self.runtime(Path('/tmp/phases'))
        bridge = SimpleNamespace(attach=mock.Mock(side_effect=RuntimeError('original')), close=mock.Mock())
        with mock.patch('environments.website_world.local_origins.LocalOriginBridge', return_value=bridge):
            with self.assertRaisesRegex(RuntimeError, 'original'):
                runtime.attach_browser(object())
        bridge.close.assert_called_once_with()
        self.assertEqual(runtime._browser_bridges, [])

    def test_invalid_paths_fail_before_native_construction(self):
        for path in [False, 3, '', '   ', {}]:
            with self.subTest(path=path), mock.patch('environments.website_world.runtime.Runtime.__init__') as constructor:
                with self.assertRaisesRegex(ValueError, 'nonempty filesystem path'):
                    ScenarioRuntime(origin_diagnostics_path=path)
                constructor.assert_not_called()

    def test_path_is_normalized_before_native_construction(self):
        with mock.patch('environments.website_world.runtime.Runtime.__init__'):
            runtime = ScenarioRuntime(origin_diagnostics_path='phase.jsonl')
        self.assertEqual(runtime.origin_diagnostics_path, Path('phase.jsonl').resolve())

    def test_episode_without_readable_origins_rejected_before_runtime(self):
        from .episode import ScenarioEpisode
        constructor = mock.Mock()
        with mock.patch.dict(ScenarioEpisode.__init__.__globals__, {
                'runtime_arguments': mock.Mock(return_value=(Path('/tmp/world'), {}, {'readable_origins': False})),
                'ScenarioRuntime': constructor}):
            with self.assertRaisesRegex(ValueError, 'readable logical origins'):
                ScenarioEpisode('/tmp/world', {}, origin_diagnostics_path='/tmp/phases',
                    task={'task_id': 'test', 'user_message': 'Inspect', 'memories': [], 'start': 'retailer'},
                    bind_episode=lambda _: {})
            constructor.assert_not_called()


class DiagnosticLifecycle(TestCase):
    def prepared(self, root):
        native_step = mock.Mock(return_value='ordinary-effect')
        env = SimpleNamespace(step=native_step, unwrapped=object())
        trace = SimpleNamespace(directory=root/'trace', metadata={})
        trace.directory.mkdir()
        task = SimpleNamespace(make_env=mock.Mock(return_value=env), trace=trace)
        prepared = SimpleNamespace(episode=SimpleNamespace(task=task,
            runtime=SimpleNamespace(origin_diagnostics_path=root/'origin.jsonl', _browser_bridges=[])),
            policy=mock.Mock(return_value=('click', {'bid': 'live'})),
            config={'metadata': {'tags': ['scripted', 'wrong']}}, source_files={},
            instance_sha256='prepared-immutable-instance-pin', close=mock.Mock())
        return prepared, env, native_step

    def test_actual_step_delegated_once_with_limits_cleanup_and_native_grade_unchanged(self):
        from contextlib import nullcontext
        from . import phase_diagnostic as diagnostic
        with TemporaryDirectory() as temp:
            root = Path(temp)
            instance = root/'instance.json'
            instance.write_text(json.dumps({'family': 'pricing_promotions', 'mechanism': 'quantity_condition'}))
            prepared, env, ordinary_step = self.prepared(root)
            original_policy, original_factory = prepared.policy, prepared.episode.task.make_env
            recorder = SimpleNamespace(observe=mock.Mock(return_value=nullcontext()), close=mock.Mock(),
                                       describe=mock.Mock(return_value={'enabled': True}))

            def run_saved(candidate, output, **kwargs):
                self.assertEqual(kwargs, {'max_steps': 40, 'max_input_tokens': 500000})
                actual = candidate.episode.task.make_env()
                self.assertEqual(candidate.policy(actual), ('click', {'bid': 'live'}))
                self.assertEqual(actual.step('unchanged native code'), 'ordinary-effect')
                return {'publication': {'status': 'fail', 'control_matches_expectation': True},
                        'trace': str(root/'trace')}

            with mock.patch.object(diagnostic.publication, 'prepare_episode', return_value=prepared), \
                    mock.patch.object(diagnostic.publication, 'checked_files'), \
                    mock.patch.object(diagnostic.publication, 'run_saved', side_effect=run_saved), \
                    mock.patch.object(diagnostic.matrix, '_control_completed', return_value=True), \
                    mock.patch('intent_browser.step_telemetry.EnvStepTelemetry', return_value=recorder):
                result = diagnostic.run(root/'world', instance, root/'output')
            self.assertEqual(result['native_status'], 'fail')
            self.assertEqual(result['status'], 'completed')
            ordinary_step.assert_called_once_with('unchanged native code')
            recorder.observe.assert_called_once_with(env.unwrapped, step=0, tool='click')
            recorder.close.assert_called_once_with()
            self.assertIs(env.step, ordinary_step)
            self.assertIs(prepared.policy, original_policy)
            self.assertIs(prepared.episode.task.make_env, original_factory)
            prepared.close.assert_called_once_with()
            self.assertIn('phase-diagnostic', prepared.config['metadata']['tags'])
            binding = json.loads((root/'output/diagnostic-binding.private.json').read_text())
            self.assertEqual(binding['tags'], prepared.config['metadata']['tags'])
            self.assertEqual(binding['instance_sha256'], prepared.instance_sha256)

    def test_wrong_family_and_existing_output_rejected_before_runtime(self):
        from . import phase_diagnostic as diagnostic
        with TemporaryDirectory() as temp, mock.patch.object(diagnostic.publication, 'prepare_episode') as prepare:
            root = Path(temp)
            instance = root/'instance.json'
            instance.write_text(json.dumps({'family': 'steering_recurrence', 'mechanism': 'quantity_condition'}))
            with self.assertRaisesRegex(ValueError, 'only quantity'):
                diagnostic.run(root, instance, root/'output')
            self.assertFalse((root/'output').exists())
            instance.write_text(json.dumps({'family': 'pricing_promotions', 'mechanism': 'quantity_condition'}))
            (root/'output').mkdir()
            with self.assertRaises(FileExistsError):
                diagnostic.run(root, instance, root/'output')
            prepare.assert_not_called()

    def test_pre_dispatch_source_failure_closes_runtime_without_action_or_retry(self):
        from . import phase_diagnostic as diagnostic
        with TemporaryDirectory() as temp:
            root = Path(temp)
            instance = root/'instance.json'
            instance.write_text(json.dumps({'family': 'pricing_promotions', 'mechanism': 'quantity_condition'}))
            prepared, _, ordinary_step = self.prepared(root)
            with mock.patch.object(diagnostic.publication, 'prepare_episode', return_value=prepared), \
                    mock.patch.object(diagnostic.publication, 'checked_files', side_effect=ValueError('source changed')), \
                    mock.patch.object(diagnostic.publication, 'run_saved') as runner:
                with self.assertRaisesRegex(ValueError, 'source changed'):
                    diagnostic.run(root, instance, root/'output')
            prepared.close.assert_called_once_with()
            ordinary_step.assert_not_called()
            runner.assert_not_called()
            self.assertEqual(json.loads((root/'output/diagnostic-terminal.json').read_text()),
                             {'status': 'infrastructure_incomplete', 'effects': 'unknown'})

    def test_real_native_step_records_action_phase_and_restores_bare_environment(self):
        # The actual task returns a bare BrowserEnv: unwrapped is the same object.
        # Use real BrowserEnv.step and EnvStepTelemetry with protocol doubles,
        # retaining actual action/capture RPC attribution without a browser.
        import asyncio
        from browsergym.core.env import BrowserEnv
        from . import phase_diagnostic as diagnostic
        loop, calls = asyncio.new_event_loop(), []

        class Connection:
            def _send_message_to_server(self, obj, method, params, no_reply=False):
                future = loop.create_future()
                future.set_result({})
                return SimpleNamespace(future=future)

        connection = Connection()
        page = SimpleNamespace(_impl_obj=SimpleNamespace(_connection=connection), frames=[],
            url='http://fixture/', is_closed=lambda: False, wait_for_load_state=lambda *a, **k: None)
        context = SimpleNamespace(pages=[page], browser=None, cookies=lambda: calls.append('cookies'))
        page.context = context

        def operation():
            calls.append('action')
            connection._send_message_to_server(SimpleNamespace(_type='Frame'), 'click', {})
            loop.run_until_complete(asyncio.sleep(0))

        env = object.__new__(BrowserEnv)
        page.operation = operation
        env.page, env.context = page, context
        env.chat = SimpleNamespace(messages=[{'role': 'user', 'message': 'Inspect'}])
        env.pre_observation_delay = 0
        env.wait_for_user_message = env.terminate_on_infeasible = env.infeasible_message_received = False
        env._active_page_check = lambda: None
        env._task_validate = lambda: (0, False, None, {})
        env._get_obs = lambda: {'last_action_error': env.last_action_error}
        env.action_mapping = lambda _: 'page.operation()'
        before_env, before_connection = dict(vars(env)), dict(vars(connection))
        original_code = BrowserEnv.step.__code__
        self.assertIs(env.unwrapped, env)
        try:
            with TemporaryDirectory() as temp:
                root = Path(temp)
                instance = root/'instance.json'
                instance.write_text(json.dumps({'family': 'pricing_promotions', 'mechanism': 'quantity_condition'}))
                prepared, _, _ = self.prepared(root)
                prepared.episode.task.make_env = mock.Mock(return_value=env)

                def run_saved(candidate, output, **kwargs):
                    current = candidate.episode.task.make_env()
                    initial = json.loads((root/'output/diagnostic-terminal.json').read_text())
                    self.assertEqual(initial['status'], 'infrastructure_incomplete')
                    for _ in range(2):
                        candidate.policy(current)
                        result = current.step('unchanged native action')
                        self.assertEqual(result[0]['last_action_error'], '')
                    return {'publication': {'status': 'fail', 'control_matches_expectation': True},
                            'trace': str(root/'trace')}

                with mock.patch.object(diagnostic.publication, 'prepare_episode', return_value=prepared), \
                        mock.patch.object(diagnostic.publication, 'checked_files'), \
                        mock.patch.object(diagnostic.publication, 'run_saved', side_effect=run_saved), \
                        mock.patch.object(diagnostic.matrix, '_control_completed', return_value=True):
                    result = diagnostic.run(root/'world', instance, root/'output')
                rows = [json.loads(line) for line in (root/'trace/env-step-telemetry.jsonl').read_text().splitlines()]
                actions = [row for row in rows if row['event'] == 'phase_started' and row['phase'] == 'action_execution']
                self.assertEqual([row['step'] for row in actions], [0, 1])
                self.assertFalse(any(row['event'] == 'execution_boundary_unavailable' for row in rows))
                self.assertEqual(sum(row['event'] == 'rpc_started' for row in rows), 2)
                self.assertEqual(sum(row['event'] == 'rpc_finished' for row in rows), 2)
                self.assertEqual(result['status'], 'completed')
                self.assertEqual(calls, ['action', 'cookies', 'action', 'cookies'])
                self.assertEqual(vars(env).keys(), before_env.keys() | {'last_action', 'last_action_error'})
                for key, value in before_env.items():
                    self.assertIs(vars(env)[key], value)
                self.assertEqual(vars(connection), before_connection)
                self.assertIs(BrowserEnv.step.__code__, original_code)
                self.assertNotIn('step', vars(env))
        finally:
            loop.close()
