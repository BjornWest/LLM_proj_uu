#!/usr/bin/env python3
"""Focused integration tests for the standalone Codex usage CLI."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("codex_usage.py")


def event(timestamp: str, kind: str, payload: dict) -> dict:
    return {"timestamp": timestamp, "type": kind, "payload": payload}


def meta(thread_id: str, parent: str | None = None, path: str | None = None) -> dict:
    payload = {"id": thread_id, "cwd": "/work"}
    if parent:
        payload["parent_thread_id"] = parent
    if path:
        payload["agent_path"] = path
    return event("2026-09-20T00:00:00Z", "session_meta", payload)


def context(timestamp: str, turn: str, model: str) -> dict:
    return event(timestamp, "turn_context", {"turn_id": turn, "model": model})


def usage(timestamp: str, thread: str, turn: str, response: str | None, **values: int) -> dict:
    payload = {"thread_id": thread, "turn_id": turn, "usage": values}
    if response is not None:
        payload["response_id"] = response
    return event(timestamp, "token_usage_record", payload)


def counters(input_tokens: int, cached: int = 0, write: int = 0, output: int = 0, reasoning: int = 0) -> dict[str, int]:
    return {
        "input_tokens": input_tokens,
        "cached_input_tokens": cached,
        "cache_write_input_tokens": write,
        "output_tokens": output,
        "reasoning_output_tokens": reasoning,
    }


class CliFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.sessions = self.root / "sessions"
        self.sessions.mkdir()
        self.prices = self.root / "prices.json"
        self.prices.write_text(json.dumps({
            "schema": "codex-token-prices-v1",
            "as_of": "2026-09-21",
            "currency": "USD",
            "source_url": "https://example.invalid/prices",
            "tier_multipliers": {"standard": "1", "fast": "2", "batch": "0.5", "flex": "0.5"},
            "models": {
                "model-a": {"input": "10", "cached_input": "1", "cache_write_input": "12.5", "output": "50",
                            "long_context": {"threshold_input_tokens": 272000, "input_multiplier": "2", "output_multiplier": "1.5"}},
                "model-b": {"input": "20", "cached_input": "2", "cache_write_input": "25", "output": "100",
                            "long_context": {"threshold_input_tokens": 272000, "input_multiplier": "2", "output_multiplier": "1.5"}},
            },
        }), encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write_session(self, name: str, events: list[dict]) -> None:
        (self.sessions / f"{name}.jsonl").write_text("".join(json.dumps(item) + "\n" for item in events), encoding="utf-8")

    def run_cli(self, *arguments: str, success: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run([sys.executable, str(SCRIPT), *arguments], text=True, capture_output=True, check=False)
        if success and result.returncode:
            self.fail(f"CLI failed ({result.returncode}): {result.stderr}")
        return result

    def estimate(self, *extra: str, output: Path | None = None) -> tuple[dict, subprocess.CompletedProcess[str]]:
        arguments = ["estimate", "--thread", "root", "--start", "2026-09-20T02:00:00+02:00",
                     "--end", "2026-09-20T03:00:00+02:00", "--sessions", str(self.sessions),
                     "--prices", str(self.prices), *extra]
        if output:
            arguments += ["--output", str(output)]
        result = self.run_cli(*arguments)
        return (json.loads(output.read_text()) if output else json.loads(result.stdout), result)


class CodexUsageTests(CliFixture):
    def test_threads_window_and_model_context_are_temporal(self) -> None:
        self.write_session("root", [
            meta("root"),
            context("2026-09-20T00:00:01Z", "turn", "model-a"),
            usage("2026-09-20T00:10:00Z", "root", "turn", "one", **counters(10)),
            context("2026-09-20T00:20:00Z", "turn", "model-b"),
            usage("2026-09-20T00:30:00Z", "root", "turn", "two", **counters(10)),
            usage("2026-09-20T01:00:00Z", "root", "turn", "at-end", **counters(10)),
        ])
        result = self.run_cli("threads", "--sessions", str(self.sessions), "--start", "2026-09-20T02:00:00+02:00",
                              "--end", "2026-09-20T03:00:00+02:00")
        rows = json.loads(result.stdout)
        self.assertEqual(rows[0]["models"], ["model-a", "model-b"])
        self.assertEqual(rows[0]["counts"]["token_usage_records"], 2)
        self.assertEqual(rows[0]["first_usage"], "2026-09-20T00:10:00.000Z")
        report, _ = self.estimate()
        self.assertEqual({row["model"]: row["responses"] for row in report["per_model"]}, {"model-a": 1, "model-b": 1})

    def test_descendants_exact_attribution_dedup_and_conflict(self) -> None:
        shared = usage("2026-09-20T00:10:00Z", "root", "t", "same", **counters(100, 20, 10, 5, 2))
        self.write_session("root-a", [meta("root"), context("2026-09-20T00:00:01Z", "t", "model-a"), shared,
                                      usage("2026-09-20T00:12:00Z", "root", "t", "conflict", **counters(50))])
        self.write_session("root-b", [meta("root"), context("2026-09-20T00:00:01Z", "t", "model-a"), shared,
                                      usage("2026-09-20T00:12:00Z", "root", "t", "conflict", **counters(51))])
        self.write_session("child", [meta("child", "root", "/root/child"), context("2026-09-20T00:00:01Z", "c", "model-b"),
                                     # Inherited root telemetry in a fork file must not be attributed again.
                                     usage("2026-09-20T00:10:00Z", "root", "t", "inherited", **counters(999)),
                                     usage("2026-09-20T00:20:00Z", "child", "c", "child-response", **counters(200))])
        report, _ = self.estimate("--include-descendants")
        self.assertEqual(report["scope"]["resolved_threads"], ["child", "root"])
        self.assertEqual(report["scope"]["active_threads"], ["child", "root"])
        self.assertEqual(report["scope"]["active_descendants"], ["child"])
        self.assertEqual(report["total"]["responses"], 2)
        self.assertEqual(report["total"]["input_tokens"], 300)
        self.assertEqual(report["coverage"]["duplicate_records_deduplicated"], 2)
        self.assertEqual(report["coverage"]["conflicting_response_ids_excluded"], ["conflict"])
        self.assertFalse(report["coverage"]["complete"])
        root_row = next(row for row in report["per_thread"] if row["thread_id"] == "root")
        self.assertFalse(root_row["complete"])
        self.assertIsNone(root_row["estimated_cost_usd"])

    def test_unknown_model_and_missing_cache_split_make_total_null(self) -> None:
        incomplete = {"input_tokens": 10, "cached_input_tokens": 0, "output_tokens": 1, "reasoning_output_tokens": 0}
        self.write_session("root", [meta("root"), context("2026-09-20T00:00:01Z", "known", "model-a"),
                                    context("2026-09-20T00:00:01Z", "mystery", "unlisted"),
                                    usage("2026-09-20T00:05:00Z", "root", "known", "good", **counters(100)),
                                    usage("2026-09-20T00:06:00Z", "root", "mystery", "unknown", **counters(100)),
                                    usage("2026-09-20T00:07:00Z", "root", "known", "missing-write", **incomplete)])
        report, _ = self.estimate()
        self.assertIsNone(report["total"]["estimated_cost_usd"])
        self.assertEqual(report["total"]["known_cost_usd"], "0.001000000000")
        self.assertEqual(report["total"]["unpriceable_reasons"], {"missing_counter:cache_write_input_tokens": 1, "unknown_model": 1})
        self.assertFalse(report["coverage"]["complete"])

    def test_long_context_cache_write_tier_and_reasoning_subset(self) -> None:
        self.write_session("root", [meta("root"), context("2026-09-20T00:00:01Z", "t", "model-a"),
                                    usage("2026-09-20T00:05:00Z", "root", "t", "long",
                                          **counters(300000, cached=100000, write=50000, output=10000, reasoning=9000))])
        report, _ = self.estimate("--tier", "fast")
        # Full long request: ((150k*10 + 100k*1 + 50k*12.5)*2 + 10k*50*1.5) / 1m, then fast*2.
        self.assertEqual(report["total"]["estimated_cost_usd"], "10.400000000000")
        self.assertEqual(report["total"]["reasoning_output_tokens"], 9000)
        self.assertEqual(report["total"]["long_context_responses"], 1)

    def test_cumulative_only_is_unsupported_but_empty_supported_window_is_zero(self) -> None:
        self.write_session("root", [meta("root"), event("2026-09-20T00:10:00Z", "event_msg", {"type": "token_count", "info": {}})])
        report, _ = self.estimate()
        self.assertEqual(report["coverage"]["legacy_cumulative_only_threads"], ["root"])
        self.assertFalse(report["coverage"]["complete"])
        self.assertEqual(report["total"]["responses"], 0)
        self.assertIsNone(report["total"]["estimated_cost_usd"])

        # A thread with supported telemetry outside the selected interval has a valid zero in the interval.
        self.sessions.joinpath("root.jsonl").unlink()
        self.write_session("root-supported", [meta("root"), context("2026-09-19T00:00:00Z", "t", "model-a"),
                                              usage("2026-09-19T00:10:00Z", "root", "t", "old", **counters(1))])
        report, _ = self.estimate()
        self.assertTrue(report["coverage"]["complete"])
        self.assertEqual(report["total"]["estimated_cost_usd"], "0.000000000000")

        self.sessions.joinpath("root-supported.jsonl").unlink()
        self.write_session("root-missing", [meta("root")])
        report, _ = self.estimate()
        self.assertEqual(report["coverage"]["missing_per_request_telemetry_threads"], ["root"])
        self.assertFalse(report["coverage"]["complete"])
        self.assertIsNone(report["total"]["estimated_cost_usd"])

    def test_output_is_exclusive_new(self) -> None:
        self.write_session("root", [meta("root"), context("2026-09-20T00:00:01Z", "t", "model-a"),
                                    usage("2026-09-20T00:05:00Z", "root", "t", "one", **counters(1))])
        output = self.root / "result.json"
        report, result = self.estimate(output=output)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["output"], str(output))
        self.assertEqual(summary["active_thread_count"], 1)
        self.assertEqual(report["schema"], "codex-usage-estimate-v1")
        second = self.run_cli("estimate", "--thread", "root", "--start", "2026-09-20T00:00:00Z",
                              "--end", "2026-09-20T01:00:00Z", "--sessions", str(self.sessions),
                              "--prices", str(self.prices), "--output", str(output), success=False)
        self.assertNotEqual(second.returncode, 0)
        self.assertIn("output already exists", second.stderr)

    def test_validation_and_missing_thread_errors(self) -> None:
        self.write_session("root", [meta("root"), context("2026-09-20T00:00:01Z", "t", "model-a"),
                                    usage("2026-09-20T00:05:00Z", "root", "t", "bad", **counters(10, cached=9, write=2))])
        report, _ = self.estimate()
        self.assertEqual(report["total"]["unpriceable_reasons"], {"cached_plus_write_exceeds_input": 1})
        result = self.run_cli("estimate", "--thread", "absent", "--start", "2026-09-20T00:00:00Z",
                              "--end", "2026-09-20T01:00:00Z", "--sessions", str(self.sessions),
                              "--prices", str(self.prices), success=False)
        self.assertIn("thread ID not found", result.stderr)

    def test_catalog_rejects_bad_currency_rates_multipliers_and_thresholds(self) -> None:
        self.write_session("root", [meta("root"), context("2026-09-20T00:00:01Z", "t", "model-a"),
                                    usage("2026-09-20T00:05:00Z", "root", "t", "one", **counters(1))])
        original = json.loads(self.prices.read_text())
        mutations = {
            "currency": lambda catalog: catalog.update(currency="EUR"),
            "negative rate": lambda catalog: catalog["models"]["model-b"].update(input="-1"),
            "NaN rate": lambda catalog: catalog["models"]["model-b"].update(output="NaN"),
            "infinite multiplier": lambda catalog: catalog["tier_multipliers"].update(fast="Infinity"),
            "numeric rather than string": lambda catalog: catalog["models"]["model-b"].update(input=2),
            "bad threshold": lambda catalog: catalog["models"]["model-b"]["long_context"].update(threshold_input_tokens=-1),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                catalog = json.loads(json.dumps(original))
                mutate(catalog)
                self.prices.write_text(json.dumps(catalog), encoding="utf-8")
                result = self.run_cli("estimate", "--thread", "root", "--start", "2026-09-20T00:00:00Z",
                                      "--end", "2026-09-20T01:00:00Z", "--sessions", str(self.sessions),
                                      "--prices", str(self.prices), success=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("price catalog", result.stderr)

    def test_missing_response_and_invalid_timestamp_null_affected_thread(self) -> None:
        self.write_session("root", [
            meta("root"), context("2026-09-20T00:00:01Z", "t", "model-a"),
            usage("2026-09-20T00:05:00Z", "root", "t", "good", **counters(10)),
            usage("2026-09-20T00:06:00Z", "root", "t", None, **counters(20)),
            usage("not-a-timestamp", "root", "t", "unplaceable", **counters(30)),
        ])
        report, _ = self.estimate()
        self.assertEqual(report["coverage"]["records_without_response_id_threads"], ["root"])
        self.assertEqual(report["coverage"]["invalid_timestamp_token_records"], 1)
        self.assertEqual(report["coverage"]["invalid_timestamp_threads"], ["root"])
        self.assertFalse(report["coverage"]["complete"])
        self.assertIsNone(report["total"]["estimated_cost_usd"])
        self.assertFalse(report["per_thread"][0]["complete"])
        self.assertIsNone(report["per_thread"][0]["estimated_cost_usd"])


if __name__ == "__main__":
    unittest.main()
