"""Offline checks for actual send boundaries and persistent reservation behavior."""

import json
import tempfile
import unittest
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
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
        backend.client = httpx.Client(transport=httpx.MockTransport(handle),
                                     event_hooks={"response": [backend.capture_response_metadata]})
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

    def test_timeout_retains_full_reservation_and_request(self):
        backend = self.backend()
        backend.client.close()

        def timeout(request):
            self.sent.append(json.loads(request.content))
            raise httpx.ReadTimeout("offline timeout", request=request)

        backend.client = httpx.Client(transport=httpx.MockTransport(timeout))
        with self.assertRaises(httpx.ReadTimeout):
            backend.complete([{"role": "user", "content": "Click Finish"}])
        data = json.loads(self.path.read_text())
        self.assertEqual(data["reserved_cost_usd"], str(RESERVATION))
        self.assertIsNone(data["requests"][0]["reported_cost_usd"])
        self.assertEqual(data["requests"][0]["error_type"], "ReadTimeout")
        self.assertEqual(backend.last_request, self.sent[0])
        self.assertEqual(len(self.sent), 1)

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

    def test_pacing_uses_persisted_previous_attempt_without_retry(self):
        self.backend().complete([{"role": "user", "content": "Click Finish"}])
        backend = self.backend()
        backend.pace_seconds = 10
        with patch("run_calibration.time.sleep") as sleep:
            backend.complete([{"role": "user", "content": "Click Finish"}])
        self.assertEqual(len(self.sent), 2)
        self.assertEqual(sleep.call_count, 1)
        self.assertGreater(sleep.call_args.args[0], 8)
        self.assertLessEqual(sleep.call_args.args[0], 10)
        data = json.loads(self.path.read_text())
        self.assertEqual(data["requests"][1]["pacing_wait_seconds"], sleep.call_args.args[0])
        self.assertEqual(Decimal(data["reserved_cost_usd"]), 2 * RESERVATION)

    def test_failed_attempt_gets_60_second_cooldown_without_retry(self):
        with self.assertRaises(RuntimeError):
            self.backend(status=429).complete([{"role": "user", "content": "Click Finish"}])
        backend = self.backend()
        backend.pace_seconds = 10
        with patch("run_calibration.time.sleep") as sleep:
            backend.complete([{"role": "user", "content": "Click Finish"}])
        self.assertGreater(sleep.call_args.args[0], 58)
        self.assertLessEqual(sleep.call_args.args[0], 60)
        self.assertEqual(len(self.sent), 2)
        self.assertEqual(json.loads(self.path.read_text())["requests"][0]["http"]["http_status"], 429)

    def test_longer_retry_after_is_honored_without_extra_send(self):
        self.backend().complete([{"role": "user", "content": "Click Finish"}])
        data = json.loads(self.path.read_text())
        data["requests"][0].update(status="error", http={"http_status": 429, "retry_after_seconds": 120})
        self.path.write_text(json.dumps(data))
        backend = self.backend()
        backend.pace_seconds = 10
        with patch("run_calibration.time.sleep") as sleep:
            backend.complete([{"role": "user", "content": "Click Finish"}])
        self.assertGreater(sleep.call_args.args[0], 118)
        self.assertLessEqual(sleep.call_args.args[0], 120)
        self.assertEqual(len(self.sent), 2)

    def test_fake_clock_wait_has_no_send_or_reservation_within_case_and_restart(self):
        class Clock(datetime):
            current = datetime(2026, 9, 14, tzinfo=timezone.utc)

            @classmethod
            def now(cls, tz=None):
                return cls.current

        waits = []

        def advance(seconds):
            ledger = json.loads(self.path.read_text())
            prior = len(self.sent)
            self.assertEqual(len(ledger["requests"]), prior)
            self.assertEqual(Decimal(ledger["reserved_cost_usd"]), prior * RESERVATION)
            waits.append(seconds)
            Clock.current += timedelta(seconds=seconds)

        with patch("run_calibration.datetime", Clock), patch("run_calibration.time.sleep", advance):
            backend = self.backend()
            backend.pace_seconds = 10
            message = [{"role": "user", "content": "Click Finish"}]
            backend.complete(message)
            backend.complete(message)
            restarted = self.backend()
            restarted.case_id = "next-case"
            restarted.pace_seconds = 10
            restarted.complete(message)
        self.assertEqual(waits, [10, 10])
        rows = json.loads(self.path.read_text())["requests"]
        starts = [datetime.fromisoformat(row["started_at"]) for row in rows]
        self.assertEqual([(start - starts[0]).total_seconds() for start in starts], [0, 10, 20])
        self.assertEqual([row["case_id"] for row in rows], ["test", "test", "next-case"])
        self.assertEqual(len(self.sent), 3)

    def test_post_wait_fingerprint_change_stops_before_reservation_and_send(self):
        backend = self.backend()
        backend.complete([{"role": "user", "content": "Click Finish"}])
        before = self.path.read_bytes()
        backend.pace_seconds = 10
        backend.pinned = {"source": "original"}
        ordering = []

        def changed():
            ordering.append("fingerprint")
            return {"source": "changed"}

        with patch("run_calibration.time.sleep", lambda seconds: ordering.append("wait")), patch("run_calibration.fingerprints", changed):
            with self.assertRaisesRegex(ValueError, "changed; no request sent"):
                backend.complete([{"role": "user", "content": "Click Finish"}])
        self.assertEqual(ordering, ["wait", "fingerprint"])
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(len(self.sent), 1)


if __name__ == "__main__":
    unittest.main()
