import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
import numpy as np

from intent_browser.backend import Completion
from intent_browser.chaos import ChaosClient
from intent_browser.evaluation import Evaluation
from intent_browser.runner import run_episode


class EvaluationTests(unittest.TestCase):
    def test_unknown_authorization_is_not_safe_success(self):
        self.assertIsNone(Evaluation('fixture', '1', task_completed=True).to_dict()['safe_success'])
        self.assertTrue(Evaluation('fixture', '1', task_completed=True,
                                   authorization_satisfied=True).to_dict()['safe_success'])
        self.assertFalse(Evaluation('fixture', '1', task_completed=True,
                                    authorization_satisfied=False).to_dict()['safe_success'])
        self.assertIsNone(Evaluation('fixture', '1', task_completed=True,
                                     authorization_satisfied=True, technical_error='timeout').to_dict()['safe_success'])

    def test_avoidance_requires_exposure_and_boolean_labels(self):
        for exposed in (None, False):
            with self.subTest(exposed=exposed), self.assertRaises(ValueError):
                Evaluation('fixture', '1', injection_exposed=exposed, injection_avoided=True).to_dict()
        with self.assertRaises(ValueError):
            Evaluation('fixture', '1', task_completed='true').to_dict()
        with self.assertRaises(ValueError):
            Evaluation('fixture', '1', unauthorized_effects=['marketing'], authorization_satisfied=True).to_dict()

    def test_terminal_hook_runs_before_close_without_policy_leakage(self):
        class Env:
            closed = False
            def reset(self, seed):
                return {'goal': 'Click', 'screenshot': np.zeros((2, 2, 3), dtype=np.uint8),
                        'last_action_error': ''}, {'private': 'reset-secret'}
            def step(self, action):
                return self.reset(0)[0], 0, False, False, {}
            def close(self):
                self.closed = True

        class Model:
            def complete(self, messages):
                self.messages = messages
                return Completion("send_msg_to_user('Done')", {'source': 'fixture'})

        class Task:
            def prepare(self, trace):
                return {'source_task_id': 'stable-source-id', 'original_goal': 'original source prompt'}
            def capture_initial(self, env, obs, info):
                return {'private': 'initial-secret'}
            def evaluate(self, env, trace, outcome):
                assert not env.closed
                return Evaluation('fixture-ledger', '1', task_completed=True,
                                  authorization_satisfied=False, unauthorized_effects=['marketing'])

        env, model = Env(), Model()
        with tempfile.TemporaryDirectory() as root, patch('intent_browser.runner.observation_text', return_value='page'):
            directory, summary = run_episode(lambda video: env, model, {}, root, episode_task=Task())
            self.assertTrue(env.closed)
            self.assertIsNone(summary['success'])
            self.assertFalse(summary['evaluation']['safe_success'])
            self.assertNotIn('secret', json.dumps(model.messages))
            self.assertNotIn('original source prompt', json.dumps(model.messages))
            events = [json.loads(row)['event'] for row in (directory / 'events.jsonl').read_text().splitlines()]
            self.assertLess(events.index('evaluation_completed'), events.index('environment_close_started'))
            self.assertTrue((directory / 'initial-state.json').is_file())
            self.assertEqual(json.loads((directory / 'task.json').read_text())['source_task_id'], 'stable-source-id')
            self.assertIn('runner.py', json.loads((directory / 'metadata.json').read_text())['runtime']['source_sha256'])

    def test_reset_failure_closes_environment_and_logs_unknown_evaluation(self):
        class Env:
            closed = False
            def reset(self, seed):
                raise RuntimeError('reset failed')
            def close(self):
                self.closed = True
        env = Env()
        with tempfile.TemporaryDirectory() as root:
            directory, summary = run_episode(lambda video: env, None, {}, root)
            self.assertTrue(env.closed)
            self.assertEqual(summary['step_count'], 0)
            self.assertIsNone(summary['evaluation']['safe_success'])
            self.assertIn('reset failed', summary['error'])
            self.assertTrue((directory / 'evaluation.json').is_file())

    def test_explicit_chaos_selection_uses_fresh_sessions_without_mounting(self):
        requests = []
        sessions = []
        def handle(request):
            path = request.url.path
            requests.append(path)
            if path == '/api/challenges':
                return httpx.Response(200, json={'challenges': [{'id': 'confirmshaming', 'template': 'dark-pattern-form'}]})
            if path == '/new-session':
                self.assertEqual(request.url.params['pack'], 'long')
                session = 'session-' + str(len(sessions))
                sessions.append(session)
                return httpx.Response(200, json={'session': session, 'challenges': [
                    {'id': session, 'taskUrl': '/task/' + session}], 'scoreUrl': '/api/score/' + session})
            if path.startswith('/api/resolve/'):
                return httpx.Response(200, json={'sessionId': path.rsplit('/', 1)[1],
                    'challengeId': 'confirmshaming', 'template': 'dark-pattern-form'})
            self.fail('Unexpected request: ' + path)
        client = ChaosClient('http://localhost:1234', transport=httpx.MockTransport(handle))
        self.addCleanup(client.close)
        first, second = client.prepare('confirmshaming'), client.prepare('confirmshaming')
        self.assertNotEqual(first['session'], second['session'])
        self.assertEqual(first['source_task_id'], 'confirmshaming')
        self.assertFalse(any('/mount' in path or '/act' in path for path in requests))
        with self.assertRaises(ValueError):
            client.prepare('unknown')
        self.assertEqual(len(sessions), 2)

    def test_wrong_session_score_is_rejected(self):
        client = ChaosClient('http://localhost:1234', transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={'sessionId': 'wrong'})))
        self.addCleanup(client.close)
        with self.assertRaises(ValueError):
            client.score({'session': 'expected'})


if __name__ == '__main__':
    unittest.main()
