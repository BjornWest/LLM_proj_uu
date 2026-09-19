import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from .bindings import ROOT, build, contract_for, load_registry, revision
from .context import RuntimeContext
from .tasks import make_task
from intent_browser.task_finalization import finalize_task_run
from intent_browser.evaluation import Evaluation


class BridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = build()

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.registry_path = self.directory / 'registry.json'
        self.registry_path.write_text(json.dumps(self.registry))
        self.identity = {'instance_id': 'dedicated-test-instance', 'reset_id': 'reset-1'}
        self.context = RuntimeContext(self.registry_path, fixture_root=ROOT / '.local/tricky-full-v1',
            origins={'shopping': 'http://isolated-shop:80', 'reddit': 'http://isolated-forum:80'},
            attest=lambda: self.identity.copy(), native_grade=lambda *args: {'score': 1})

    def task(self, task_id):
        row = next(r for r in self.registry['tasks'] if r['id'] == task_id)
        return make_task(task_id, runtime_context=self.context, revision=row['revision'])

    def prepare_native(self):
        task = self.task('webarena:117')
        task.prepare(SimpleNamespace(directory=self.directory))
        task.har_path.write_text('{"log":{"entries":[]}}')
        (self.directory / 'evaluation.json').write_text(json.dumps(Evaluation('pending', '1').to_dict()))
        (self.directory / 'events.jsonl').write_text(json.dumps({'event': 'environment_close_completed'}) + '\n')
        task.final_response = {'task_type': 'retrieve', 'status': 'SUCCESS', 'retrieved_data': []}
        return task

    def test_all_203_exact_contracts_and_goals_construct(self):
        self.assertEqual(len(self.registry['tasks']), 203)
        for row in self.registry['tasks']:
            task = self.task(row['id'])
            self.assertEqual(task.policy_goal, row['policy_input']['goal'])
            self.assertEqual(task.contract, contract_for(ROOT, row))
            self.assertEqual(set(row['policy_input']), {'goal', 'terminal_response_instruction'})

    def test_scripted_representatives_are_in_reviewed_registry(self):
        from .verify_webarena import SUPPORTED
        self.assertTrue(set(SUPPORTED) <= {r['id'] for r in self.registry['tasks']})

    def test_private_contract_not_in_policy_projection(self):
        task = self.task('tricky:AU01')
        self.assertIn('grader_input', task.contract)
        self.assertNotIn('grader_input', task.row['policy_input'])
        self.assertNotIn('setup', task.row['policy_input'])

    def test_wrong_revision_and_unknown_id_rejected(self):
        for task_id in ('tricky:AU01', 'made-up'):
            with self.assertRaises(ValueError):
                make_task(task_id, runtime_context=self.context, revision='wrong')

    def test_registry_tamper_and_duplicate_rejected(self):
        for kind in ('tamper', 'duplicate'):
            changed = copy.deepcopy(self.registry)
            if kind == 'tamper':
                changed['tasks'][0]['policy_input']['goal'] = 'Leaked or replaced objective'
            else:
                changed['tasks'].append(changed['tasks'][0])
            self.registry_path.write_text(json.dumps(changed))
            with self.assertRaises(ValueError):
                load_registry(self.registry_path)

    def test_missing_isolation_fails_before_browser(self):
        self.context.attest = None
        with self.assertRaises(ValueError):
            self.task('webarena:117').prepare(SimpleNamespace(directory=self.directory))

    def test_stale_instance_rejected_before_native_grader(self):
        task = self.prepare_native()
        task.context_closed = True
        self.identity['reset_id'] = 'another-reset'
        calls = []
        self.context.native_grade = lambda *args: calls.append(args)
        with self.assertRaises(ValueError):
            task.finalize_after_close(self.directory, {})
        self.assertEqual(calls, [])

    def test_native_requires_context_close_and_preserves_runtime_unknown(self):
        task = self.prepare_native()
        with self.assertRaises(ValueError):
            task.finalize_after_close(self.directory, {})
        task.context_closed = True
        original = {'evaluation': {'task_completed': None}, 'error': None}
        result = finalize_task_run(task, self.directory, original)
        self.assertIsNone(original['evaluation']['task_completed'])
        self.assertTrue(result['evaluation']['task_completed'])
        self.assertIsNone(result['evaluation']['safe_success'])
        self.assertEqual(result['grading_phase'], 'after_browser_close')
        self.assertIsNone(json.loads((self.directory / 'evaluation.json').read_text())['task_completed'])
        with self.assertRaises(FileExistsError):
            finalize_task_run(task, self.directory, original)

    def test_native_error_and_bad_response_stay_unknown(self):
        task = self.prepare_native()
        task.context_closed = True
        task.final_response = None
        calls = []
        self.context.native_grade = lambda *args: calls.append(args)
        result = task.finalize_after_close(self.directory, {}).to_dict()
        self.assertIsNone(result['task_completed'])
        self.assertTrue(result['technical_error'])
        self.assertEqual(calls, [])

    def test_native_failure_does_not_erase_runner_error(self):
        task = self.prepare_native()
        task.context_closed = True
        result = task.finalize_after_close(self.directory, {'error': 'parser failure'}).to_dict()
        self.assertTrue(result['task_completed'])
        self.assertEqual(result['technical_error'], 'parser failure')
        self.assertIsNone(result['safe_success'])

    def test_native_evaluator_error_is_not_task_failure(self):
        task = self.prepare_native()
        task.context_closed = True
        self.context.native_grade = lambda *args: {'score': 0, 'status': 'error'}
        result = task.finalize_after_close(self.directory, {}).to_dict()
        self.assertIsNone(result['task_completed'])
        self.assertTrue(result['technical_error'])

    def test_proxy_credentials_excluded_from_context_repr(self):
        self.context.browser_proxy = {'server': 'http://proxy.invalid', 'username': 'job', 'password': 'secret-lease'}
        self.assertNotIn('secret-lease', repr(self.context))

    def test_readonly_blocks_writes_and_foreign_scheme(self):
        task = self.task('webarena:117')
        for url, method, allowed in [('http://isolated-shop:80/a', 'GET', True),
                                      ('http://isolated-shop:80/a', 'POST', False),
                                      ('https://isolated-shop:80/a', 'GET', False),
                                      ('http://other/a', 'GET', False)]:
            calls = []
            route = SimpleNamespace(request=SimpleNamespace(url=url, method=method),
                                    continue_=lambda: calls.append(True), abort=lambda: calls.append(False))
            task.route(route)
            self.assertEqual(calls, [allowed])

    def test_wishlist_retains_original_product_start(self):
        task = self.task('webarena:516')
        self.assertNotEqual(task.start_url, task.origin)
        self.assertTrue(task.start_url.startswith(task.origin + '/'))

    def test_state_read_fails_closed_on_midread_reset(self):
        task = self.task('webarena:630')
        task.identity = self.identity.copy()
        def callback(operation, arguments):
            self.identity['reset_id'] = 'changed'
            return []
        self.context.state_read = callback
        with self.assertRaises(ValueError):
            task.read_state('forum.submission_ids')

    def test_tricky_fixture_mismatch_fails_before_server(self):
        self.context.fixture_root = self.directory
        (self.directory / 'build.json').write_text('{}')
        task = self.task('tricky:AU01')
        with self.assertRaises(ValueError):
            task.prepare(SimpleNamespace(directory=self.directory))
        self.assertIsNone(task.adapter.server)


if __name__ == '__main__':
    unittest.main()
