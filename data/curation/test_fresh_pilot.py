"""Offline actual-HTTP-boundary checks; no paid endpoints or browser launches."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from decimal import Decimal

import httpx
import numpy as np

import prepare_fresh_pilot as pilot
from intent_browser.runner import run_episode


class PilotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'budget.json'
        self.sent = []
        self.time = 1000.0
        self.waits = []
        self.valid = True
        self.reply = {'id': 'offline', 'model': pilot.MODEL, 'provider': 'Cloudflare',
                      'choices': [{'message': {'content': 'noop()'}}],
                      'usage': {'cost': 0.0005, 'prompt_tokens': 100, 'completion_tokens': 4}}

    def validate(self):
        if not self.valid:
            raise ValueError('Changed fingerprint')

    def sleep(self, seconds):
        data = json.loads(self.path.read_text()) if self.path.exists() else pilot.initial_ledger()
        self.assertEqual(len(data['requests']), len(self.sent))
        self.assertEqual(Decimal(data['reserved_cost_usd']), pilot.CARRIED + len(self.sent) * pilot.RESERVATION)
        self.waits.append(seconds)
        self.time += seconds

    def backend(self, status=200, headers=None, timeout=False):
        backend = pilot.PilotBackend('offline-secret', self.path, self.validate,
                                     clock=lambda: self.time, sleep=self.sleep, initial_not_before_epoch=0)
        backend.client.close()
        def respond(request):
            payload = json.loads(request.content)
            data = json.loads(self.path.read_text())
            self.assertEqual(data['requests'][-1]['model_request'], payload)
            self.assertEqual(data['requests'][-1]['status'], 'reserved')
            self.assertEqual(len(data['requests']), len(self.sent) + 1)
            self.sent.append(payload)
            self.time += 2
            if timeout:
                raise httpx.ReadTimeout('offline', request=request)
            return httpx.Response(status, json=self.reply, headers=headers)
        backend.client = httpx.Client(transport=httpx.MockTransport(respond),
                                     event_hooks={'request': [backend.capture_dispatch], 'response': [backend.capture_response]})
        self.addCleanup(backend.close)
        backend.begin_episode('offline-episode')
        return backend

    def complete(self, backend):
        backend.wait_until_ready()
        return backend.complete([{'role': 'user', 'content': 'Ordinary task goal'}])

    def test_carry_forward_cumulative_cap_and_no_refunds(self):
        self.assertEqual(pilot.CARRIED, Decimal('0.64922375'))
        self.assertEqual(pilot.RESERVATION, Decimal('0.014048'))
        with patch.object(pilot, 'CAP', pilot.CARRIED + pilot.RESERVATION):
            self.complete(self.backend())
            with self.assertRaisesRegex(ValueError, 'cap reached'):
                self.complete(self.backend())
        self.assertEqual(len(self.sent), 1)
        data = json.loads(self.path.read_text())
        self.assertEqual(Decimal(data['reserved_cost_usd']), pilot.CARRIED + pilot.RESERVATION)

    def test_actual_request_routing_prices_and_unmodified_prompt(self):
        self.complete(self.backend())
        request = self.sent[0]
        self.assertEqual(request['model'], pilot.MODEL)
        self.assertEqual(request['session_id'], 'offline-episode')
        self.assertEqual(request['provider']['only'], list(pilot.DEFAULT_PROVIDERS))
        self.assertEqual(request['provider']['max_price'], {'prompt': 0.5, 'completion': 4, 'request': 0})
        self.assertEqual(request['max_tokens'], 512)
        self.assertFalse(request['reasoning']['enabled'])
        self.assertNotIn('order', request['provider'])
        self.assertNotIn('preset', request)
        self.assertEqual(request['messages'][0]['content'], 'Ordinary task goal')
        self.assertNotIn('offline-secret', self.path.read_text())

    def test_pacing_persists_within_case_and_across_restart(self):
        backend = self.backend()
        self.complete(backend)
        self.complete(backend)
        self.complete(self.backend())
        self.assertEqual(self.waits, [10, 10])
        rows = json.loads(self.path.read_text())['requests']
        self.assertEqual([r['http_request_hook_epoch'] for r in rows], [1000, 1012, 1024])
        self.assertEqual([r['readiness']['wait_seconds'] for r in rows], [0, 10, 10])

    def test_hash_change_after_wait_blocks_reservation_send(self):
        self.complete(self.backend())
        before = self.path.read_bytes()
        backend = self.backend()
        def change(seconds):
            self.sleep(seconds)
            self.valid = False
        backend.sleep = change
        with self.assertRaisesRegex(ValueError, 'fingerprint'):
            self.complete(backend)
        self.assertEqual(self.waits, [10])
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(len(self.sent), 1)

    def test_429_retry_after_persisted_but_no_retry_or_restart(self):
        with self.assertRaisesRegex(RuntimeError, '429'):
            self.complete(self.backend(429, {'Retry-After': '120', 'X-Secret': 'never-save'}))
        before = self.path.read_bytes()
        data = json.loads(before)
        self.assertEqual(data['not_before_epoch'], 1122)
        self.assertEqual(data['requests'][0]['http']['retry_after_seconds'], 120)
        with self.assertRaisesRegex(ValueError, 'requires review'):
            self.complete(self.backend())
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertNotIn('never-save', before.decode())

    def test_timeout_retains_request_reservation_and_unknown_http(self):
        with self.assertRaises(httpx.ReadTimeout):
            self.complete(self.backend(timeout=True))
        row = json.loads(self.path.read_text())['requests'][0]
        self.assertEqual(row['model_request'], self.sent[0])
        self.assertIsNone(row['model_response'])
        self.assertIsNone(row['http'])
        self.assertIsNone(row['reported_cost_usd'])
        self.assertEqual(row['reservation_usd'], str(pilot.RESERVATION))
        with self.assertRaisesRegex(ValueError, 'requires review'):
            self.complete(self.backend())
        self.assertEqual(len(self.sent), 1)

    def test_invalid_cost_and_disallowed_provider_stop_before_action(self):
        for field, value in [('usage', {}), ('provider', 'Reka'), ('usage', {'cost': 1})]:
            with self.subTest(field=field, value=value):
                self.path.unlink(missing_ok=True)
                self.sent.clear()
                old = self.reply[field]
                self.reply[field] = value
                backend = self.backend()
                with self.assertRaises(RuntimeError):
                    self.complete(backend)
                self.assertTrue(json.loads(self.path.read_text())['requests'][0]['audit_issue'])
                with self.assertRaises(ValueError):
                    self.complete(backend)
                self.assertEqual(len(self.sent), 1)
                self.reply[field] = old

    def test_missing_session_oversize_and_interruption_never_dispatch(self):
        backend = self.backend()
        backend.session_id = None
        with self.assertRaises(ValueError): self.complete(backend)
        backend.begin_episode('offline')
        for content in ('x' * pilot.INPUT_BOUND, [{'type': 'image_url'}]):
            with self.assertRaises(ValueError):
                backend.complete([{'role': 'user', 'content': content}])
        data = pilot.initial_ledger()
        data['requests'] = [{'status': 'reserved', 'reservation_usd': str(pilot.RESERVATION)}]
        data['new_reserved_cost_usd'] = str(pilot.RESERVATION)
        data['reserved_cost_usd'] = str(pilot.CARRIED + pilot.RESERVATION)
        self.path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, 'requires review'): self.complete(backend)
        self.assertEqual(self.sent, [])

    def test_actual_runner_session_equals_trace_id_across_two_episodes(self):
        class Env:
            def reset(self, seed):
                return {'goal': 'Ordinary goal', 'last_action_error': '',
                        'screenshot': np.zeros((2,2,3), dtype=np.uint8)}, {}
            def step(self, action):
                return self.reset(0)[0], 0, False, False, {}
            def close(self): pass
        backend = self.backend()
        with patch('intent_browser.runner.observation_text', return_value='page'), patch('intent_browser.runner.refresh_observation', side_effect=lambda env: env.reset(0)[0]):
            ids = []
            for _ in range(2):
                directory, summary = run_episode(lambda video: Env(), backend, {}, self.temp.name, max_steps=2, before_observation=backend.wait_until_ready)
                self.assertIsNone(summary['error'])
                ids.append(directory.name)
        self.assertNotEqual(ids[0], ids[1])
        self.assertEqual([r['session_id'] for r in self.sent], [ids[0], ids[0], ids[1], ids[1]])
    def test_single_case_request_ceiling_survives_restart(self):
        with patch.object(pilot, 'MAX_STEPS', 2):
            self.complete(self.backend())
            self.complete(self.backend())
            with self.assertRaisesRegex(ValueError, 'Single-case'):
                self.complete(self.backend())
        self.assertEqual(len(self.sent), 2)

    def test_complete_requires_unconsumed_readiness_without_waiting(self):
        backend = self.backend()
        messages = [{'role': 'user', 'content': 'ordinary'}]
        with self.assertRaisesRegex(ValueError, 'hook missing'):
            backend.complete(messages)
        self.assertFalse(self.path.exists())
        backend.wait_until_ready()
        backend.complete(messages)
        before = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'hook missing'):
            backend.complete(messages)
        self.assertEqual(self.waits, [])
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(len(self.sent), 1)

    def test_other_sender_between_ready_and_dispatch_rejects_without_wait(self):
        backend = self.backend()
        self.complete(backend)
        backend.wait_until_ready()
        data = json.loads(self.path.read_text())
        data['not_before_epoch'] = self.time + 50
        self.path.write_text(json.dumps(data))
        before = self.path.read_bytes()
        waits = list(self.waits)
        with self.assertRaisesRegex(ValueError, 'Readiness changed'):
            backend.complete([{'role': 'user', 'content': 'Already captured'}])
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.waits, waits)
        self.assertEqual(len(self.sent), 1)

    def test_restart_and_cross_session_cannot_reuse_ready_token(self):
        backend = self.backend()
        backend.wait_until_ready()
        backend.begin_episode('different-episode')
        with self.assertRaisesRegex(ValueError, 'Readiness changed'):
            backend.complete([{'role': 'user', 'content': 'ordinary'}])
        self.assertFalse(self.path.exists())
        self.assertEqual(self.sent, [])

    def test_actual_runner_refresh_then_validation_dispatch_no_fake_actions(self):
        order = []
        outer = self
        class Env:
            @property
            def unwrapped(self): return self
            def obs(self):
                return {'goal': 'Ordinary goal', 'last_action_error': '',
                        'visible': 'expired-close' if outer.time < 1012 else 'Continue',
                        'screenshot': np.zeros((2,2,3), dtype=np.uint8)}
            def reset(self, seed): return self.obs(), {}
            def _get_obs(self):
                order.append(('capture', outer.time))
                return self.obs()
            def step(self, action):
                order.append(('action', outer.time))
                return self.obs(), 0, False, False, {}
            def close(self): pass
        backend = self.backend()
        original_sleep = backend.sleep
        def sleep(seconds):
            order.append(('wait', self.time))
            original_sleep(seconds)
        backend.sleep = sleep
        backend.validate = lambda: order.append(('validate', self.time))
        original_dispatch = backend.capture_dispatch
        def dispatch(request):
            order.append(('dispatch', self.time))
            original_dispatch(request)
        backend.client.event_hooks['request'] = [dispatch]
        with patch('intent_browser.runner.observation_text', side_effect=lambda o: o['visible']):
            directory, summary = run_episode(lambda video: Env(), backend, {}, self.temp.name,
                max_steps=2, before_observation=backend.wait_until_ready)
        self.assertIsNone(summary['error'])
        self.assertEqual([kind for kind, _ in order],
                         ['capture', 'validate', 'dispatch', 'action', 'wait', 'capture', 'validate', 'dispatch', 'action'])
        self.assertIn('Continue', self.sent[1]['messages'][-1]['content'])
        self.assertNotIn('expired-close', self.sent[1]['messages'][-1]['content'])
        self.assertNotIn('state_sha256', json.dumps(self.sent))
        self.assertEqual(summary['browser_step_count'], 2)
        rows = [json.loads(line) for line in (directory/'steps.jsonl').read_text().splitlines()]
        self.assertEqual(rows[1]['observation']['text'], 'decision-observation-001.txt')
        self.assertEqual(rows[1]['transition_observation']['text'], 'observation-001.txt')
        self.assertEqual(rows[1]['messages_sha256'], rows[1]['delivered_messages_sha256'])
        self.assertEqual((directory/'observation-001.txt').read_text(), 'expired-close')
        self.assertEqual((directory/'decision-observation-001.txt').read_text(), 'Continue')

    def test_runner_rejection_after_capture_does_not_inherit_prior_request(self):
        outer = self
        class Env:
            def obs(self):
                return {'goal': 'Ordinary goal', 'last_action_error': '',
                        'screenshot': np.zeros((2,2,3), dtype=np.uint8)}
            def reset(self, seed): return self.obs(), {}
            def step(self, action): return self.obs(), 0, False, False, {}
            def close(self): pass
        backend = self.backend()
        def capture(env):
            if len(outer.sent) == 1:
                data = json.loads(outer.path.read_text())
                data['not_before_epoch'] = outer.time + 30
                outer.path.write_text(json.dumps(data))
            return env.obs()
        with patch('intent_browser.runner.observation_text', return_value='page'), patch('intent_browser.runner.refresh_observation', side_effect=capture):
            directory, summary = run_episode(lambda video: Env(), backend, {}, self.temp.name,
                max_steps=2, before_observation=backend.wait_until_ready)
        self.assertIn('Readiness changed', summary['error'])
        rows = [json.loads(line) for line in (directory/'steps.jsonl').read_text().splitlines()]
        self.assertIsNotNone(rows[0]['model_request'])
        self.assertIsNone(rows[1]['model_request'])
        self.assertIsNone(rows[1]['model_response'])
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.waits, [10])
        self.assertEqual(len(json.loads(self.path.read_text())['requests']), 1)

    def test_negative_reservation_cannot_create_budget_credit(self):
        data = pilot.initial_ledger()
        data['requests'] = [{'status': 'completed', 'reservation_usd': '-1'}]
        data['new_reserved_cost_usd'] = '-1'
        data['reserved_cost_usd'] = str(pilot.CARRIED - 1)
        self.path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, 'credits'):
            self.backend().wait_until_ready()
        self.assertEqual(self.sent, [])

    def test_inherited_deadline_precedes_first_capture_without_reservation(self):
        backend = self.backend()
        backend.initial_not_before_epoch = self.time + 20
        backend.wait_until_ready()
        self.assertEqual(self.waits, [20])
        self.assertFalse(self.path.exists())
        self.assertEqual(self.sent, [])
        backend.complete([{'role': 'user', 'content': 'captured after inherited wait'}])
        self.assertEqual(self.sent[0]['session_id'], 'offline-episode')

    def test_dispatch_lock_contention_rejects_without_wait_or_reservation(self):
        import fcntl
        backend = self.backend()
        backend.wait_until_ready()
        with self.path.with_suffix('.lock').open('a') as other:
            fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError):
                backend.complete([{'role': 'user', 'content': 'captured'}])
        self.assertEqual(self.sent, [])
        self.assertEqual(self.waits, [])
        self.assertFalse(self.path.exists())



if __name__ == '__main__': unittest.main()
