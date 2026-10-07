import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from intent_browser.backend import Completion
from intent_browser.evaluation import Evaluation
from intent_browser.observation import refresh_observation
from intent_browser.runner import messages_digest
from tests.runner_diagnostics import run_episode


class Clock:
    def __init__(self): self.now = 0.0
    def advance(self, seconds): self.now += seconds


class Env:
    def __init__(self, clock, order):
        self.clock, self.order = clock, order
        self.unwrapped = self
        self.actions = []
        self.closed = False

    def obs(self, visible):
        return {'goal': 'Use the page', 'last_action_error': '', 'visible': visible,
                'screenshot': np.zeros((2, 2, 3), dtype=np.uint8)}

    def reset(self, seed): return self.obs('old transient Close'), {}

    def _get_obs(self):
        self.order.append('capture')
        self.clock.advance(.25)
        return self.obs('fresh stable Continue')

    def step(self, action):
        self.order.append('action')
        self.actions.append(action)
        self.clock.advance(.5)
        return self.obs('post action snapshot'), 0, False, False, {}

    def close(self):
        self.order.append('close')
        self.closed = True


class Task:
    def __init__(self, order): self.order = order
    def prepare(self, trace): return {'privileged': 'hidden-grader-state'}
    def capture_initial(self, *args): return {'private': 'hidden-grader-state'}
    def after_step(self, *args): return {'private': 'hidden-grader-state'}
    def evaluate(self, env, trace, outcome):
        assert not env.closed
        self.order.append('evaluate')
        return Evaluation('test', '1')


class RunnerPacingTests(unittest.TestCase):
    def execute(self, backend, hook=None, env=None, max_steps=2, **extra):
        clock, order = self.clock, self.order
        env = env or Env(clock, order)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        with patch('intent_browser.runner.time.monotonic', side_effect=lambda: clock.now), \
             patch('intent_browser.runner.observation_text', side_effect=lambda obs: obs['visible']):
            path, summary = run_episode(lambda video: env, backend, {}, directory.name,
                                        max_steps=max_steps, before_observation=hook,
                                        episode_task=Task(order), **extra)
        rows = [json.loads(s) for s in (path/'steps.jsonl').read_text().splitlines()]
        lifecycle = [json.loads(s) for s in (path/'events.jsonl').read_text().splitlines()]
        self.assertLess(order.index('evaluate'), order.index('close'))
        return path, summary, rows, lifecycle, env

    def setUp(self): self.clock, self.order = Clock(), []

    def backend(self, fail_at=None, failure='timeout'):
        clock, order = self.clock, self.order
        class Backend:
            def __init__(self): self.calls = 0; self.last_request = None
            def complete(self, messages):
                self.calls += 1
                order.extend(['prompt', 'source_recheck'])
                if self.calls == fail_at and failure == 'preflight':
                    raise ValueError('Fingerprint changed before reservation')
                order.append('reserve')
                self.last_request = {'messages': messages, 'model': 'offline'}
                order.append('dispatch')
                clock.advance(2)
                if self.calls == fail_at:
                    raise TimeoutError('No response')
                text = "send_msg_to_user('Done')" if self.calls == 2 else 'noop()'
                return Completion(text, {'choices': [{'message': {'content': text}}]}, self.last_request)
        return Backend()

    def hook(self):
        self.order.append('wait')
        self.clock.advance(10)
        return {'diagnostic_only': 'hidden-grader-state'}

    def test_order_exact_observation_and_separate_phase_timing(self):
        path, summary, rows, events, env = self.execute(self.backend(), self.hook)
        self.assertEqual(self.order, ['wait', 'capture', 'prompt', 'source_recheck', 'reserve', 'dispatch', 'action']*2+['evaluate','close'])
        self.assertEqual(len(env.actions), 2)  # Refresh did not inject an action.
        self.assertEqual((path/'observation-000.txt').read_text(), 'old transient Close')
        self.assertEqual((path/'observation-001.txt').read_text(), 'post action snapshot')
        self.assertEqual(summary['timing_totals'], {'pacing_seconds':20, 'request_seconds':4,
            'observation_capture_seconds':.5, 'browser_step_seconds':1})
        self.assertEqual(json.loads((path/'metadata.json').read_text())['observation_lifecycle'], 'paced-fresh-v1')
        for i, row in enumerate(rows):
            text = (path/row['observation']['text']).read_text()
            self.assertEqual(row['observation']['text'], f'decision-observation-{i:03d}.txt')
            self.assertEqual(row['transition_observation']['text'], f'observation-{i:03d}.txt')
            self.assertIn(text, row['messages'][-1]['content'])
            self.assertEqual(row['observation_text_sha256'], hashlib.sha256(text.encode()).hexdigest())
            self.assertEqual(row['model_request']['messages'], row['messages'])
            self.assertEqual(row['messages_sha256'], messages_digest(row['messages']))
            self.assertEqual(row['delivered_messages_sha256'], row['messages_sha256'])
            self.assertNotIn('hidden-grader-state', json.dumps(row['messages']))
            self.assertNotIn('old transient', json.dumps(row['messages']))
            self.assertEqual(row['request_seconds'], 2)
            self.assertEqual(row['inference_seconds'], 2)
            self.assertEqual(row['pacing_seconds'], 10)
            self.assertEqual(row['observation_age_lower_bound_seconds_at_model_call'], 0)

    def test_no_hook_preserves_legacy_observations_and_messages(self):
        path, summary, rows, _, env = self.execute(self.backend())
        self.assertNotIn('capture', self.order)
        self.assertNotIn('wait', self.order)
        self.assertEqual(rows[0]['observation']['text'], 'observation-000.txt')
        self.assertEqual(rows[1]['observation']['text'], 'observation-001.txt')
        self.assertEqual(rows[0]['messages'][-1]['content'], 'USER GOAL: Use the page\nRecent actions: []\nold transient Close')
        self.assertEqual(json.loads((path/'metadata.json').read_text())['observation_lifecycle'], 'post-transition-v1')
        self.assertEqual(list(path.glob('decision-observation-*')), [])

    def test_wait_failure_keeps_previous_request_out_of_current_attempt(self):
        backend = self.backend()
        def hook():
            if backend.calls:
                self.clock.advance(3)
                raise ValueError('Readiness refused')
            return self.hook()
        _, summary, rows, _, _ = self.execute(backend, hook)
        self.assertEqual(backend.calls, 1)
        self.assertEqual(rows[1]['failure_phase'], 'before_observation')
        self.assertEqual(rows[1]['pacing_seconds'], 3)
        self.assertIsNone(rows[1]['messages'])
        self.assertIsNone(rows[1]['model_request'])
        self.assertIsNone(rows[1]['request_seconds'])
        self.assertEqual(summary['stop_reason'], 'error')

    def test_capture_failure_does_not_call_model(self):
        env=Env(self.clock,self.order)
        env._get_obs=lambda: (_ for _ in ()).throw(RuntimeError('Detached page'))
        backend=self.backend()
        _, _, rows, _, _=self.execute(backend,self.hook,env)
        self.assertEqual(backend.calls,0)
        self.assertEqual(rows[0]['failure_phase'],'observation_capture')
        self.assertIsNone(rows[0]['model_request'])

    def test_unserializable_wait_diagnostics_stop_before_model_and_remain_loggable(self):
        backend=self.backend()
        _,summary,rows,_,_=self.execute(backend,lambda: object())
        self.assertEqual(backend.calls,0)
        self.assertEqual(summary['stop_reason'],'error')
        self.assertEqual(rows[0]['failure_phase'],'before_observation')
        self.assertNotIn('observation_wait_details',rows[0])

    def test_timeout_retains_current_request_but_preflight_failure_does_not(self):
        for failure in ['timeout','preflight']:
            with self.subTest(failure=failure):
                self.setUp()
                backend=self.backend(fail_at=2,failure=failure)
                _,_,rows,_,_=self.execute(backend,self.hook)
                self.assertEqual(backend.calls,2)
                if failure=='timeout':
                    self.assertEqual(rows[1]['model_request']['messages'],rows[1]['messages'])
                    self.assertEqual(rows[1]['request_seconds'],2)
                    self.assertEqual(self.order.count('dispatch'),2)
                else:
                    self.assertIsNone(rows[1]['model_request'])
                    self.assertEqual(self.order.count('dispatch'),1)
                    self.assertEqual(self.order.count('reserve'),1)

    def test_refresh_after_search_keeps_search_context_without_browser_step(self):
        backend=self.backend()
        original=backend.complete
        def complete(messages):
            result=original(messages)
            if backend.calls==1:result.text="web_search('campus')"
            return result
        backend.complete=complete
        search=SimpleNamespace(max_calls=1,calls=0)
        def execute_search(*args):
            search.calls+=1
            return SimpleNamespace(text='Found public result',error=None), 'search.json'
        with patch('intent_browser.runner.execute_search',side_effect=execute_search):
            _,summary,rows,_,env=self.execute(backend,self.hook,search_backend=search)
        self.assertEqual(len(env.actions),1)
        self.assertEqual(self.order.count('capture'),2)
        self.assertIn('Found public result',rows[1]['messages'][-1]['content'])
        self.assertEqual(summary['search_request_count'],1)

    def test_refresh_refuses_unreviewed_browsergym_version(self):
        with patch('intent_browser.observation.version',return_value='99.0'):
            with self.assertRaisesRegex(RuntimeError,'reviewed BrowserGym'):
                refresh_observation(Env(self.clock,self.order))
        self.assertEqual(self.order,[])


if __name__=='__main__': unittest.main()
