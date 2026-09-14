import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
import numpy as np

from intent_browser.actions import parse_decision
from intent_browser.backend import Completion
from intent_browser.runner import run_episode
from intent_browser.search import ParallelSearch, format_results, run_search


FIXTURE = {"search_id": "fixture-search", "session_id": "fixture-session", "results": [
    {"title": "BrowserGym", "url": "https://example.test/docs", "publish_date": None,
     "excerpts": ["BrowserGym exposes browser observations."]}
], "usage": [{"name": "search", "count": 1}]}


class SearchTests(unittest.TestCase):
    def test_request_schema_fast_mode_and_preserved_response(self):
        requests = []

        def handle(request):
            requests.append(request)
            return httpx.Response(200, json=FIXTURE)

        backend = ParallelSearch("fixture-secret", transport=httpx.MockTransport(handle))
        self.addCleanup(backend.close)
        result = backend.search("BrowserGym documentation")
        self.assertEqual(str(requests[0].url), "https://api.parallel.ai/v1/search")
        self.assertEqual(requests[0].headers["x-api-key"], "fixture-secret")
        payload = json.loads(requests[0].content)
        self.assertEqual(payload, {"mode": "fast", "objective": "BrowserGym documentation",
                                  "search_queries": ["BrowserGym documentation"], "max_chars_total": 4000})
        self.assertEqual(result.raw, FIXTURE)
        self.assertIn("https://example.test/docs", result.text)
        self.assertIsNone(result.error)

    def test_failed_requests_consume_budget_without_retry(self):
        requests = []

        def handle(request):
            requests.append(request)
            return httpx.Response(429, json={"error": {"message": "Rate limit"}})

        backend = ParallelSearch("fixture-secret", max_calls=1, transport=httpx.MockTransport(handle))
        self.addCleanup(backend.close)
        first = backend.search("first query")
        second = backend.search("second query")
        self.assertIn("429", first.error)
        self.assertEqual(first.raw["error"]["message"], "Rate limit")
        self.assertFalse(second.request_attempted)
        self.assertEqual(len(requests), 1)

    def test_timeout_is_reported(self):
        def handle(request):
            raise httpx.ReadTimeout("timeout", request=request)

        backend = ParallelSearch("fixture-secret", transport=httpx.MockTransport(handle))
        self.addCleanup(backend.close)
        self.assertIn("ReadTimeout", backend.search("query").error)
        self.assertEqual(backend.calls, 1)

    def test_parser_requires_enabled_search_and_literal_query(self):
        decision = parse_decision("web_search(query='BrowserGym docs')", allow_search=True)
        self.assertEqual(decision.arguments, {"query": "BrowserGym docs"})
        for action in ["web_search('x')", "web_search('')", "web_search(3)", "web_search(str(3))"]:
            with self.subTest(action=action), self.assertRaises(ValueError):
                parse_decision(action, allow_search=action != "web_search('x')")

    def test_view_is_bounded_without_truncating_raw_response(self):
        raw = {"results": [{"title": "x" * 1000, "url": "https://example.test/" + "x" * 1000,
                            "excerpts": ["y" * 20000]}] * 20}
        self.assertLess(len(format_results(raw)), 6100)
        self.assertEqual(len(raw["results"]), 20)

    def test_standalone_search_records_request_before_dispatch(self):
        with tempfile.TemporaryDirectory() as root:
            def handle(request):
                event_file = next(Path(root).glob("*/events.jsonl"))
                self.assertEqual(json.loads(event_file.read_text().splitlines()[-1])["event"], "tool_started")
                return httpx.Response(200, json=FIXTURE)

            backend = ParallelSearch("fixture-secret", transport=httpx.MockTransport(handle))
            self.addCleanup(backend.close)
            summary = run_search("query", backend, root)
            self.assertTrue(summary["search_ok"])
            directory = next(Path(root).iterdir())
            self.assertEqual(json.loads((directory / "search-000.json").read_text())["raw"], FIXTURE)
            for file in directory.iterdir():
                self.assertNotIn("fixture-secret", file.read_text())

    def test_search_result_enters_context_without_browser_step_or_reward(self):
        class Environment:
            def __init__(self):
                self.actions = []
                self.closed = False

            def reset(self, seed):
                return {"goal": "Read docs then click", "screenshot": np.zeros((2, 2, 3), dtype=np.uint8),
                        "last_action_error": ""}, {"verifier_secret": "not-for-model"}

            def step(self, action):
                self.actions.append(action)
                return self.reset(0)[0], 1.0, True, False, {}

            def close(self):
                self.closed = True

        class Model:
            def __init__(self):
                self.messages = []

            def complete(self, messages):
                self.messages.append(messages)
                action = "web_search('BrowserGym docs')" if len(self.messages) == 1 else "click('6')"
                return Completion(action, {"source": "fixture"})

        env, model = Environment(), Model()
        search = ParallelSearch("fixture-secret", transport=httpx.MockTransport(lambda r: httpx.Response(200, json=FIXTURE)))
        self.addCleanup(search.close)
        with tempfile.TemporaryDirectory() as root, patch("intent_browser.runner.observation_text", return_value="page"):
            directory, summary = run_episode(lambda video: env, model, {"driver": "fixture", "verifier": "fixture"},
                                             output=root, max_steps=3, search_backend=search)
            steps = [json.loads(line) for line in (directory / "steps.jsonl").read_text().splitlines()]
            self.assertEqual(env.actions, ["click('6')"])
            self.assertIsNone(steps[0]["reward"])
            self.assertEqual(steps[0]["observation"], steps[0]["next_observation"])
            self.assertEqual(summary["browser_step_count"], 1)
            self.assertEqual(summary["search_request_count"], 1)
            self.assertTrue(summary["success"])
            self.assertTrue(env.closed)
            self.assertIn("browser observations", model.messages[1][1]["content"])
            self.assertNotIn("not-for-model", json.dumps(model.messages))


if __name__ == "__main__":
    unittest.main()
