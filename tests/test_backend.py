import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from intent_browser.backend import BackendResponseError, ChatCompletionsBackend
from scripts.smoke_openrouter import SmokeBudgetBackend


class BackendTests(unittest.TestCase):
    def backend(self, response):
        backend = ChatCompletionsBackend('https://example.test/v1', 'fixture', 'fixture-secret',
                                          request_options={'preset': '@preset/fixture'})
        backend.client.close()
        backend.client = httpx.Client(transport=httpx.MockTransport(lambda request: response))
        self.addCleanup(backend.close)
        return backend

    def test_http_failure_preserves_response_and_request_without_headers(self):
        backend = self.backend(httpx.Response(401, json={'error': {'message': 'Invalid credential'}}))
        with self.assertRaises(BackendResponseError) as caught:
            backend.complete([{'role': 'user', 'content': 'Click'}])
        self.assertEqual(caught.exception.request_payload['preset'], '@preset/fixture')
        self.assertEqual(caught.exception.response_payload['error']['message'], 'Invalid credential')
        self.assertNotIn('fixture-secret', json.dumps(caught.exception.request_payload))

    def test_empty_text_preserves_usage_for_parser_failure(self):
        raw = {'choices': [{'message': {'content': None, 'reasoning': 'unfinished'}}], 'usage': {'cost': 0.001}}
        completion = self.backend(httpx.Response(200, json=raw)).complete([])
        self.assertEqual(completion.text, '')
        self.assertEqual(completion.raw, raw)

    def test_smoke_reservation_survives_backend_restart(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'budget.json'
            for _ in range(6):
                backend = SmokeBudgetBackend('qwen/qwen3.8-27b', 'fixture-secret', path)
                backend.reserve()
                backend.close()
            backend = SmokeBudgetBackend('qwen/qwen3.8-27b', 'fixture-secret', path)
            self.addCleanup(backend.close)
            with self.assertRaises(ValueError):
                backend.reserve()
            ledger = json.loads(path.read_text())
            self.assertEqual(ledger['requests'], 6)
            self.assertLess(float(ledger['reserved_cost_usd']), 0.05)


if __name__ == '__main__':
    unittest.main()
