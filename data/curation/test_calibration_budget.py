"""Offline checks for actual send boundaries and persistent reservation behavior."""

import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

import httpx

from run_calibration import BudgetBackend, CAP, RESERVATION


class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "budget.json"
        self.sent = []
        self.reply = {"id": "offline", "model": "qwen/qwen3.8-27b", "provider": "DekaLLM",
                      "choices": [{"message": {"content": "noop()"}}],
                      "usage": {"cost": 0.0001, "prompt_tokens": 100, "completion_tokens": 4}}

    def tearDown(self):
        self.temp.cleanup()

    def backend(self, status=200):
        def handle(request):
            self.sent.append(json.loads(request.content))
            return httpx.Response(status, json=self.reply)
        backend = BudgetBackend("offline-key", self.path, "test")
        backend.client.close()
        backend.client = httpx.Client(transport=httpx.MockTransport(handle))
        self.addCleanup(backend.close)
        return backend

    def test_limit_persists_across_instances_and_blocks_send(self):
        self.path.write_text(json.dumps({"approved_cap_usd": str(CAP),
                             "reserved_cost_usd": str(CAP - RESERVATION), "requests": []}))
        self.backend().complete([{"role": "user", "content": "Click Finish"}])
        with self.assertRaisesRegex(ValueError, "cap reached"):
            self.backend().complete([{"role": "user", "content": "Click Finish"}])
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(Decimal(json.loads(self.path.read_text())["reserved_cost_usd"]), CAP)

    def test_http_error_is_reserved_without_retry(self):
        with self.assertRaises(RuntimeError):
            self.backend(status=503).complete([{"role": "user", "content": "Click Finish"}])
        data = json.loads(self.path.read_text())
        self.assertEqual(data["reserved_cost_usd"], str(RESERVATION))
        self.assertEqual(data["requests"][0]["status"], "error")
        self.assertEqual(len(self.sent), 1)

    def test_oversized_or_multimodal_input_never_sends(self):
        backend = self.backend()
        for content in ("x" * 24000, [{"type": "image_url", "image_url": "offline"}]):
            with self.assertRaises(ValueError):
                backend.complete([{"role": "user", "content": content}])
        self.assertEqual(self.sent, [])
        self.assertFalse(self.path.exists())

    def test_missing_cost_blocks_next_request_even_after_restart(self):
        self.reply["usage"].pop("cost")
        completion = self.backend().complete([{"role": "user", "content": "Click Finish"}])
        self.assertEqual(completion.text, "noop()")  # Preserve raw evidence first.
        with self.assertRaisesRegex(ValueError, "Prior response needs review"):
            self.backend().complete([{"role": "user", "content": "Click Finish"}])
        self.assertEqual(len(self.sent), 1)

    def test_price_and_generation_limits_are_in_real_payload(self):
        self.backend().complete([{"role": "user", "content": "Click Finish"}])
        payload = self.sent[0]
        self.assertEqual(payload["provider"]["max_price"], {"prompt": 0.5, "completion": 3, "request": 0})
        self.assertFalse(payload["provider"]["allow_fallbacks"])
        self.assertEqual(payload["provider"]["only"], ["dekallm"])
        self.assertEqual(payload["max_tokens"], 512)
        self.assertEqual(payload["reasoning"], {"enabled": False})


if __name__ == "__main__":
    unittest.main()
