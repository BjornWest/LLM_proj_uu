"""Authored offline lifecycle controls; no browser, provider or authority proof."""
from contextlib import contextmanager
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from intent_browser.automatic_grading import GradingGate
from intent_browser.connected_world_task import policy_goal
from . import simulated_order_execution as consumer, simulated_order_capture as capture_api
from .simulated_order_store import OrderStore
from .catalog_cart_execution import save_new


class OrderingLifecycleControls(unittest.TestCase):
    def test_default_quota_frozen_dependencies_and_snapshot_without_rpc(self):
        from . import simulated_order_publication as publication
        from experiments.external_agent import subscription_quota
        from scripts import product_width_watch
        with patch.object(publication.shared,'source_files',return_value={}):
            sources=publication.source_files()
        for module in (subscription_quota,product_width_watch):
            path=Path(module.__file__).resolve()
            relative=str(path.relative_to(consumer.ROOT))
            self.assertEqual(sources[relative],sha256(path.read_bytes()).hexdigest())
        authored={'rateLimitsByLimitId':{'codex':{'secondary':{
            'windowDurationMins':10080,'usedPercent':20,'resetsAt':1}}}}
        with patch.object(subscription_quota,'_read',side_effect=AssertionError('No RPC authorized')):
            self.assertEqual(subscription_quota.snapshot(authored)['weekly']['remaining_percent'],80)
        with TemporaryDirectory() as temporary,patch.object(consumer,'ROOT',Path(temporary)):
            with self.assertRaises((ValueError,FileNotFoundError)):
                consumer.quota_sources()

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root/'fixture'
        self.output.mkdir()
        self.native = {'task_id': 'authored-order-task'}
        self.public = {'schema_version': 'connected-world-manual-v1', 'task_id': self.native['task_id'],
            'user_message': 'Please order the item already in my cart.', 'memories': [],
            'environment_context': {'currency': 'SEK'}, 'start_url': 'https://authored.test/#/cart'}
        for name in ('simulated-order-task.private.json', 'simulated-order-reference.private.json',
                     'simulated-order-setup.private.json'):
            save_new(self.output/name, self.native if 'task.' in name else {'authored': True})
        self.fake_viewer = ModuleType('agent_trace.adapters.browsergym')
        self.fake_viewer.__file__ = __file__
        self.fake_viewer.project = lambda directory, **kw: {'messages': [{
            'title': 'Privileged verifier — not model input',
            'text': (Path(directory)/'evaluation.json').read_text()}]}
        self.pins = {str(Path(module.__file__).resolve()): sha256(Path(module.__file__).read_bytes()).hexdigest()
                     for module in (consumer, capture_api)}
        self.policy_closed = False
        self.runtime_closed = False
        self.grade_calls = 0
        self.projection_calls = 0
        self.guard_calls = 0
        self.cleanup_error = False
        self.policy_cleanup_error = False
        self.corrupt_public = False
        self.missing_projection = False
        self.captured = None
        self.native_report = {'task_id': self.native['task_id'], 'verdict': 'inconclusive',
            'order_outcome_correct': True, 'components': {'effects': {'status': 'inconclusive'}},
            'limitations': ['Authored mock native grade; null effects remain inconclusive.']}
        owner = self

        class Episode:
            def __init__(self, output, *, additional_source_files=None):
                self.output = Path(output)
                self.native_task, self.reference = deepcopy(owner.native), {'authored': True}
                self.public = deepcopy(owner.public)
                baskets = SimpleNamespace(adapter=SimpleNamespace(world={'world_id': 'world'}, retailers={'a': {}}),
                                          plan_id='plan', domain_id='domain')
                store = OrderStore(baskets, runtime_id='runtime', record_maker=lambda b,r,s,*,order_id: {
                    'order_id': order_id, 'retailer_id': r, 'submission': deepcopy(s)})
                self.runtime = SimpleNamespace(orders=store, baskets=baskets)
                files = {**owner.pins, **additional_source_files}
                self.task = SimpleNamespace(files=files, make_env=lambda: None)
                self.profile = SimpleNamespace(name='authored-offline-profile')
                self.site_discovery = None
                self.capture = capture_api.OrderCapture(self.runtime, self.native_task, source_files=files)
                owner.captured = self.capture
            def export_private_runtime(self, output):
                output.mkdir()
                save_new(output/'binding.json', {'authored': True})
                manifest = {'files': {'binding.json': sha256((output/'binding.json').read_bytes()).hexdigest()}}
                save_new(output/'manifest.json', manifest)
                return manifest
            def __enter__(self):
                return self
            def __exit__(self, *args):
                if owner.cleanup_error:
                    raise ValueError('authored Runtime cleanup failure')
                owner.runtime_closed = True

        self.Episode = Episode

    def guard(self):
        self.guard_calls += 1
        if self.guard_calls > 2:
            raise ValueError('Quota floor exhausted after the last authorized dispatch')

    @contextmanager
    def session(self, *, before_dispatch):
        try:
            yield object()
        finally:
            if self.policy_cleanup_error:
                raise ValueError('authored policy lease cleanup failure')
            self.policy_closed = True

    def runner(self, make_env, backend, metadata, *, output, automatic_grading, **kwargs):
        self.assertEqual(automatic_grading.phase, 'external')
        self.assertEqual(kwargs['terminal_response_instruction'], consumer.TERMINAL_INSTRUCTION)
        directory = output/'episode'
        directory.mkdir(parents=True)
        trace = SimpleNamespace(directory=directory, episode_id='episode')
        save_new(directory/'metadata.json', {'episode_id': 'episode'})
        save_new(directory/'policy-task.json', self.public)
        (directory/'steps.jsonl').write_text('{"authored_fixture":true}\n')
        gate = GradingGate(trace, automatic_grading)
        gate.bind(None, {'goal': policy_goal(self.public)})
        self.captured.before(None, trace)
        self.guard()  # Stand-in for the last authorized policy dispatch.
        self.captured.store.commit('a', {'idempotency_key': 'one'})
        summary = {'stop_reason': 'agent_finished', 'terminated': False, 'truncated': False,
            'error': None, 'execution_error': None, 'cleanup_errors': [], 'trace_complete': True}
        self.captured.after(None, trace, summary)
        gate.pending_external()
        save_new(directory/'episode.json', summary)
        if self.corrupt_public:
            value = {**self.public, 'environment_context': {'currency': 'USD'}}
            (directory/'policy-task.json').write_text(json.dumps(value))
        return directory, summary

    def native_grade(self, *args, **kwargs):
        self.grade_calls += 1
        self.assertTrue(self.policy_closed and self.runtime_closed)
        self.assertIsNone(kwargs['capsule']['effect_journal'])
        self.assertEqual(len(kwargs['capsule']['after']['order_snapshot']['orders']), 1)
        return deepcopy(self.native_report)

    def viewer(self, *, trace, grade):
        self.projection_calls += 1
        self.assertEqual(grade, self.native_report)
        canonical = json.loads((trace/'episode.json').read_bytes())
        self.assertTrue(canonical['infrastructure_completed'])
        self.assertEqual(canonical['grading']['status'], 'graded')
        return {'status': 'missing' if self.missing_projection else 'verified',
                'qualification': 'Authored offline fixture; no actual HTTP viewer'}

    def execute(self):
        with patch.dict('sys.modules', {'agent_trace.adapters.browsergym': self.fake_viewer}), \
                patch.object(consumer, 'SimulatedOrderEpisode', self.Episode), \
                patch.object(consumer.grading, 'grade', self.native_grade):
            return consumer.run(self.output, self.root/'run', policy_session=self.session,
                metadata={}, runner_options={'max_steps': 2, 'max_input_tokens': 1000},
                viewer_projection=self.viewer, quota_guard=self.guard, runner=self.runner)

    def test_prospective_contract_real_gate_finalizes_once_after_both_closes_without_postpolicy_quota(self):
        result = self.execute()
        self.assertEqual(result['status'], 'graded_and_projected')
        self.assertEqual((self.grade_calls, self.projection_calls, self.guard_calls), (1, 1, 2))
        self.assertEqual(result['state_grading']['verdict'], 'inconclusive')
        self.assertEqual(result['answer_extraction_requests'], 0)
        value = json.loads((Path(result['trace'])/'evaluation.json').read_bytes())
        self.assertIsNone(value['task_completed'])
        self.assertIsNone(value['authorization_satisfied'])

    def test_runtime_cleanup_failure_cannot_grade_or_publish_success(self):
        self.cleanup_error = True
        result = self.execute()
        self.assertEqual(result['status'], 'system_failure')
        self.assertEqual((self.grade_calls, self.projection_calls), (0, 0))
        self.assertFalse(result['runtime_closed'])

    def test_policy_lease_cleanup_failure_cannot_grade_or_publish_success(self):
        self.policy_cleanup_error = True
        result = self.execute()
        self.assertEqual(result['status'], 'system_failure')
        self.assertEqual((self.grade_calls, self.projection_calls), (0, 0))
        self.assertFalse(result['policy_closed'])

    def test_context_drift_fails_before_native_grade(self):
        self.corrupt_public = True
        result = self.execute()
        self.assertEqual(result['status'], 'system_failure')
        self.assertEqual(self.grade_calls, 0)

    def test_missing_final_http_projection_is_system_failure(self):
        self.missing_projection = True
        result = self.execute()
        self.assertEqual(result['status'], 'system_failure')
        self.assertEqual((self.grade_calls, self.projection_calls), (1, 1))

    def test_caller_cannot_replace_automatic_contract_or_capture(self):
        for key in ('automatic_grading', 'allow_ungraded', 'episode_task', 'observation_pipeline'):
            with self.subTest(key=key), self.assertRaises(ValueError):
                consumer.run(self.output, self.root/key, policy_session=self.session, metadata={},
                    runner_options={'max_steps': 2, 'max_input_tokens': 1000, key: True},
                    viewer_projection=self.viewer, quota_guard=self.guard, runner=self.runner)

    def test_finite_limits_and_task_identity_are_strict(self):
        with self.assertRaises(ValueError):
            consumer.run(self.output, self.root/'invalid', policy_session=self.session, metadata={},
                runner_options={'max_steps': True, 'max_input_tokens': 1000},
                viewer_projection=self.viewer, quota_guard=self.guard, runner=self.runner)
        with self.assertRaises(ValueError):
            consumer.project_native({'task_id': 'wrong', 'native_grade': self.native_report},
                                    {'task_id': self.native['task_id']})


if __name__ == '__main__':
    unittest.main()
