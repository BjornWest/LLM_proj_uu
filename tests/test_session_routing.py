import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
import numpy as np

from intent_browser.backend import BackendResponseError, ChatCompletionsBackend
from intent_browser.openrouter import DEFAULT_PROVIDERS, provider_options, routing_record
from tests.runner_diagnostics import run_episode
from scripts.smoke_session_routing import RoutingBudgetBackend


class SessionRoutingTests(unittest.TestCase):
    def test_default_prefers_akash_with_fallbacks_and_explicit_pins_work(self):
        self.assertEqual(DEFAULT_PROVIDERS[0], 'akashml')
        self.assertNotIn('dekallm', DEFAULT_PROVIDERS)
        default=provider_options(DEFAULT_PROVIDERS)['provider']
        self.assertEqual(default['only'], list(DEFAULT_PROVIDERS))
        self.assertEqual(default['order'], ['akashml'])
        self.assertTrue(default['allow_fallbacks'])
        self.assertFalse(provider_options(['akashml'])['provider']['allow_fallbacks'])
        self.assertNotIn('order',provider_options(['akashml'])['provider'])
        self.assertTrue(provider_options(['dekallm','chutes'])['provider']['allow_fallbacks'])

    def backend(self, status=200):
        backend = ChatCompletionsBackend('https://openrouter.ai/api/v1', 'qwen/qwen3.8-27b',
            'offline-secret', session_routing=True, request_options=provider_options(DEFAULT_PROVIDERS))
        backend.client.close()
        self.requests = []
        def reply(request):
            self.requests.append(json.loads(request.content))
            return httpx.Response(status, json={'provider': 'Parasail', 'model': backend.model,
                'choices': [{'message': {'content': 'noop()'}}],
                'usage': {'prompt_tokens_details': {'cached_tokens': 512}}})
        backend.client = httpx.Client(transport=httpx.MockTransport(reply))
        self.addCleanup(backend.close)
        return backend

    def test_session_matches_trace_across_steps_and_changes_between_episodes(self):
        class Env:
            def reset(self, seed):
                return {'goal': 'Click', 'last_action_error':'',
                        'screenshot': np.zeros((2,2,3), dtype=np.uint8)}, {}
            def step(self, action):
                return self.reset(0)[0], 0, False, False, {}
            def close(self):
                pass
        backend = self.backend()
        with tempfile.TemporaryDirectory() as root, patch('intent_browser.runner.observation_text', return_value='page'):
            ids = []
            for _ in range(2):
                directory, _ = run_episode(lambda video: Env(), backend, {}, root, max_steps=2)
                ids.append(directory.name)
                metadata = json.loads((directory/'metadata.json').read_text())
                self.assertEqual(metadata['routing']['session_id'], directory.name)
                for line in (directory/'steps.jsonl').read_text().splitlines():
                    row = json.loads(line)
                    self.assertEqual(row['routing']['resolved_provider'], 'Parasail')
                    self.assertEqual(row['routing']['cached_tokens'], 512)
            self.assertNotEqual(ids[0], ids[1])
            self.assertEqual([r['session_id'] for r in self.requests], [ids[0],ids[0],ids[1],ids[1]])
        for request in self.requests:
            self.assertEqual(request['provider']['only'], list(DEFAULT_PROVIDERS))
            self.assertEqual(request['provider']['order'], ['akashml'])
            self.assertNotIn('preset', request)
            self.assertNotIn('offline-secret', json.dumps(request))

    def test_failure_keeps_session_and_does_not_retry(self):
        backend = self.backend(429)
        backend.begin_episode('trace-error')
        with self.assertRaises(BackendResponseError) as error:
            backend.complete([])
        self.assertEqual(error.exception.request_payload['session_id'], 'trace-error')
        self.assertEqual(len(self.requests), 1)

    def test_requires_trace_and_rejects_conflicting_routing(self):
        backend = self.backend()
        with self.assertRaises(ValueError): backend.complete([])
        self.assertEqual(self.requests, [])
        for kwargs in [{'model':'@preset/old'}, {'base_url':'http://localhost:8000/v1'},
                       {'request_options':{'preset':'@preset/old'}},
                       {'request_options':{'session_id':'conflicting'}}]:
            args={'model':'qwen/qwen3.8-27b','base_url':'https://openrouter.ai/api/v1','session_routing':True}
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                ChatCompletionsBackend(**(args|kwargs))
        self.assertIsNone(routing_record({}, {})['cached_tokens'])
        self.assertIsNone(routing_record({}, ['unexpected response'])['resolved_provider'])

    def test_paid_probe_reserves_before_send_and_failed_calls_block_restart(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'budget.json'
            backend=RoutingBudgetBackend('offline-secret',['parasail'],path)
            self.addCleanup(backend.close)
            backend.begin_episode('offline-probe')
            backend.client.close()
            sent=[]
            def fail(request):
                ledger=json.loads(path.read_text())
                self.assertGreater(float(ledger['reserved_cost_usd']),0)
                self.assertEqual(ledger['requests'][-1]['status'],'reserved')
                self.assertEqual(ledger['requests'][-1]['model_request'],json.loads(request.content))
                sent.append(request)
                return httpx.Response(429,json={'error':{'code':429}})
            backend.client=httpx.Client(transport=httpx.MockTransport(fail))
            with self.assertRaises(BackendResponseError): backend.complete([{'role':'user','content':'test'}])
            reserved=json.loads(path.read_text())['reserved_cost_usd']
            backend.stopped=False  # Same persisted check as a fresh backend.
            with self.assertRaises(ValueError): backend.complete([{'role':'user','content':'test'}])
            self.assertEqual(len(sent),1)
            self.assertEqual(json.loads(path.read_text())['reserved_cost_usd'],reserved)
            self.assertNotIn('offline-secret',path.read_text())


if __name__ == '__main__': unittest.main()
