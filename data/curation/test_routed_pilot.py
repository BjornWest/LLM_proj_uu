"""Offline actual-HTTP-boundary checks; no paid endpoints or browser launches."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from decimal import Decimal

import httpx
import numpy as np

import run_routed_pilot as pilot
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
        data = json.loads(self.path.read_text())
        self.assertEqual(len(data['requests']), len(self.sent))
        self.assertEqual(Decimal(data['reserved_cost_usd']), pilot.CARRIED + len(self.sent) * pilot.RESERVATION)
        self.waits.append(seconds)
        self.time += seconds

    def backend(self, status=200, headers=None, timeout=False):
        backend = pilot.PilotBackend('offline-secret', self.path, self.validate,
                                     clock=lambda: self.time, sleep=self.sleep)
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
                                     event_hooks={'response': [backend.capture_response]})
        self.addCleanup(backend.close)
        backend.begin_episode('offline-episode')
        return backend

    def complete(self, backend):
        return backend.complete([{'role': 'user', 'content': 'Ordinary task goal'}])

    def test_carry_forward_cumulative_cap_and_no_refunds(self):
        self.assertEqual(pilot.CARRIED, Decimal('0.15754375'))
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
        self.assertEqual([r['dispatch_epoch'] for r in rows], [1000, 1012, 1024])
        self.assertEqual([r['wait_seconds'] for r in rows], [0, 10, 10])

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
        with patch('intent_browser.runner.observation_text', return_value='page'):
            ids = []
            for _ in range(2):
                directory, summary = run_episode(lambda video: Env(), backend, {}, self.temp.name, max_steps=2)
                self.assertIsNone(summary['error'])
                ids.append(directory.name)
        self.assertNotEqual(ids[0], ids[1])
        self.assertEqual([r['session_id'] for r in self.sent], [ids[0], ids[0], ids[1], ids[1]])


if __name__ == '__main__': unittest.main()
