import gzip
import hashlib
import json
import tempfile
import unittest
from unittest.mock import Mock, patch

import numpy as np

from intent_browser.backend import Completion
from intent_browser.runner import observation_text
from tests.runner_diagnostics import run_episode


class ObservationLimitTests(unittest.TestCase):
    def test_default_is_exact_legacy_text_at_character_boundaries(self):
        for length in (0, 15999, 16000, 16001, 48001):
            with self.subTest(length=length):
                tree = "å" * length
                obs = {"url": "http://local/", "last_action_error": "prior error", "axtree_object": {"nodes":[{"fixture_text":tree}]}}
                expected_tree = tree if length <= 16000 else tree[:16000] + "\n[Accessibility tree truncated]"
                expected = f"URL: http://local/\nLast action error: prior error\nAccessibility tree:\n{expected_tree}"
                with patch("intent_browser.runner.flatten_axtree_to_str", side_effect=lambda x: x["nodes"][0]["fixture_text"]):
                    self.assertEqual(observation_text(obs).encode(), expected.encode())
                    self.assertEqual(observation_text(obs, limit=16000), expected)
                    enlarged = observation_text(obs, limit=48000)
                    self.assertEqual(enlarged.endswith("[Accessibility tree truncated]"), length > 48000)

    def test_selected_limit_reaches_every_observation_and_exact_prompt(self):
        for paced in (False, True):
            for limit in (16000, 48000):
                with self.subTest(paced=paced, limit=limit):
                    self.check_episode(paced, limit)

    def check_episode(self, paced, limit):
        class Env:
            steps = 0
            captures = 0
            closed = False

            def obs(self, stage):
                return {"url": "http://local/", "goal": "Inspect the assigned user",
                        "last_action_error": "", "screenshot": np.zeros((2, 2, 3), dtype=np.uint8),
                        "axtree_object": {"nodes":[{"fixture_text": "x" * 38528 + f"[a1109] combobox 'Choose option' {stage}\n[a1446] option 'Assigned to'"}]}}

            def reset(self, seed):
                return self.obs("initial"), {}

            def fresh(self):
                self.captures += 1
                return self.obs(f"fresh-{self.captures}" )

            def step(self, action):
                self.steps += 1
                return self.obs(f"transition-{self.steps}"), 0, False, False, {}

            def close(self):
                self.closed = True

        class Backend:
            calls = 0

            def complete(self, messages):
                self.calls += 1
                output = "noop()" if self.calls == 1 else "send_msg_to_user('Done')"
                return Completion(output, {"source": "offline-test"}, {"messages": messages})

        env = Env()
        with tempfile.TemporaryDirectory() as root, \
             patch("intent_browser.runner.flatten_axtree_to_str", side_effect=lambda x: x["nodes"][0]["fixture_text"]), \
             patch("intent_browser.runner.refresh_observation", side_effect=lambda _: env.fresh()):
            directory, summary = run_episode(
                lambda video: env, Backend(), {"observation_text_limit": 999}, root,
                max_steps=2, observation_text_limit=limit,
                before_observation=(lambda: None) if paced else None)
            self.assertTrue(env.closed)
            self.assertEqual(env.steps, 2)
            self.assertEqual(env.captures, 2 if paced else 0)
            self.assertEqual(summary["stop_reason"], "agent_finished")
            self.assertIsNone(summary["evaluation"]["safe_success"])
            metadata = json.loads((directory / "metadata.json").read_text())
            self.assertEqual(metadata["observation_text_limit"], limit)
            self.assertEqual(metadata["observation_text_limit_scope"], "flattened_axtree_characters_before_truncation_marker")
            self.assertEqual(json.loads((directory / "episode.json").read_text())["observation_text_limit"], limit)
            rows = [json.loads(line) for line in (directory / "steps.jsonl").read_text().splitlines()]
            paths = list(directory.glob("*observation-*.txt"))
            self.assertEqual(len(paths), 5 if paced else 3)
            for path in paths:
                with gzip.open(path.with_suffix(".json.gz"), "rt") as handle:
                    raw = json.load(handle)
                text = path.read_text()
                self.assertIn("Choose option", raw["axtree_object"]["nodes"][0]["fixture_text"])
                self.assertEqual(text, observation_text(raw, limit=limit))
                self.assertEqual("Choose option" in text, limit == 48000)
            for index, row in enumerate(rows):
                selected = (directory / row["observation"]["text"]).read_text()
                self.assertEqual(row["observation_text_sha256"], hashlib.sha256(selected.encode()).hexdigest())
                self.assertTrue(row["messages"][1]["content"].endswith(selected))
                self.assertEqual(row["model_request"]["messages"], row["messages"])
                self.assertEqual("Choose option" in row["messages"][1]["content"], limit == 48000)
                if paced and limit == 48000:
                    self.assertIn(f"fresh-{index+1}", selected)
                    self.assertNotIn("transition-", selected)

    def test_invalid_limits_fail_before_trace_browser_and_model(self):
        for limit in (None, True, False, 0, -1, 16000.0, "48000"):
            with self.subTest(limit=limit), patch("intent_browser.runner.Trace") as trace:
                factory, backend = Mock(), Mock()
                with self.assertRaisesRegex(ValueError, "positive integer"):
                    run_episode(factory, backend, {}, observation_text_limit=limit)
                factory.assert_not_called()
                trace.assert_not_called()
                self.assertEqual(backend.mock_calls, [])


if __name__ == "__main__":
    unittest.main()
