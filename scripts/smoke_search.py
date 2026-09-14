"""Real BrowserGym + deterministic search fixture. No API key or paid requests."""

import argparse
import os
from pathlib import Path

import gymnasium as gym
import httpx

from intent_browser.actions import make_action_set
from intent_browser.backend import Completion
from intent_browser.cli import SMOKE_URL, SmokeBackend
from intent_browser.runner import run_episode
from intent_browser.search import ParallelSearch


class FixtureAgent:
    def __init__(self):
        self.searched = False
        self.browser_smoke = SmokeBackend()

    def complete(self, messages):
        if not self.searched:
            self.searched = True
            return Completion("web_search('BrowserGym documentation')", {"source": "fixture"})
        assert "Example search fixture" in messages[-1]["content"]
        return self.browser_smoke.complete(messages)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    display = parser.add_mutually_exclusive_group()
    display.add_argument("--headless", dest="headless", action="store_true")
    display.add_argument("--headful", dest="headless", action="store_false")
    parser.set_defaults(headless=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    libraries = root / ".local/system-libs/usr/lib/x86_64-linux-gnu"
    if libraries.is_dir():
        os.environ["LD_LIBRARY_PATH"] = str(libraries) + ":" + os.getenv("LD_LIBRARY_PATH", "")
    action_set = make_action_set()

    def environment(video):
        return gym.make("browsergym/openended", task_kwargs={"start_url": SMOKE_URL, "goal": "Click the Finish button."},
                        action_mapping=action_set.to_python_code, headless=args.headless, slow_mo=250,
                        wait_for_user_message=False, record_video_dir=video)

    def handle(request):
        return httpx.Response(200, json={"search_id": "fixture", "session_id": "fixture", "results": [
            {"title": "Example search fixture", "url": "https://example.test/browsergym",
             "excerpts": ["This is a synthetic search response for integration testing."]}
        ]})

    search = ParallelSearch("offline-fixture-key", max_calls=1, transport=httpx.MockTransport(handle))
    try:
        _, summary = run_episode(environment, FixtureAgent(), {
            "task": "openended", "model": "scripted", "driver": "offline-search-integration-fixture",
            "headless": args.headless, "search_response_source": "httpx.MockTransport; no network request",
            "verifier": None,
        }, max_steps=4, record_video=True, search_backend=search)
    finally:
        search.close()
    if summary["error"] or summary["search_request_count"] != 1 or summary["browser_step_count"] != 3:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
