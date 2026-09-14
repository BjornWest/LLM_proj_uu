"""Explicit paid MiniWoB smoke: up to six requests, reservation below US$0.05.

Requires --live. This script pins routing for reproducibility; the main harness
remains model/provider independent. No retries, paid tools, or fallback models.
"""

import argparse
import json
import os
import fcntl
from decimal import Decimal
from pathlib import Path

import browsergym.miniwob  # noqa: F401
import gymnasium as gym
from dotenv import load_dotenv

from intent_browser.actions import make_action_set
from intent_browser.backend import ChatCompletionsBackend
from intent_browser.runner import run_episode
from intent_browser.trace import write_json


class SmokeBudgetBackend(ChatCompletionsBackend):
    max_calls = 6
    prompt_token_bound = 12000
    per_request_reservation = Decimal("12000") * Decimal("0.0000005") + Decimal("512") * Decimal("0.000003")

    def __init__(self, model, api_key, budget_path):
        super().__init__("https://openrouter.ai/api/v1", model, api_key, max_tokens=512,
                         request_options={"preset": "@preset/deka-llm-qwen38-27-b",
                                          "reasoning": {"enabled": False},
                                          "provider": {"only": ["dekallm"], "allow_fallbacks": False,
                                                       "require_parameters": True,
                                                       "max_price": {"prompt": 0.5, "completion": 3, "request": 0}}})
        self.calls = 0
        self.reported_cost = Decimal("0")
        self.unreported_cost_calls = 0
        self.budget_path = Path(budget_path)

    def reserve(self):
        self.budget_path.parent.mkdir(parents=True, exist_ok=True)
        with self.budget_path.with_suffix('.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            ledger = json.loads(self.budget_path.read_text()) if self.budget_path.exists() else {
                'approved_cap_usd': '0.05', 'reserved_cost_usd': '0', 'requests': 0}
            reserved = Decimal(ledger['reserved_cost_usd']) + self.per_request_reservation
            if reserved > Decimal('0.05'):
                raise ValueError('Shared smoke budget exhausted; no request sent')
            ledger.update(reserved_cost_usd=str(reserved), requests=ledger['requests'] + 1)
            write_json(self.budget_path, ledger)

    def complete(self, messages):
        # Qwen's byte-level text tokenizer cannot exceed UTF-8 bytes for plain
        # text; reserve a further 1024 tokens for chat framing. No multimodal
        # content/tools are sent by this smoke script.
        size = len(json.dumps(messages, ensure_ascii=False).encode("utf-8")) + 1024
        if size > self.prompt_token_bound:
            raise ValueError("Smoke prompt exceeds the reserved input-token bound")
        if self.calls >= self.max_calls or (self.calls + 1) * self.per_request_reservation > Decimal("0.05"):
            raise ValueError("Smoke cost reservation exhausted; no request sent")
        self.reserve()
        self.calls += 1  # Reserve even if the request times out or fails.
        self.unreported_cost_calls += 1
        completion = super().complete(messages)
        cost = completion.raw.get("usage", {}).get("cost")
        if cost is not None:
            self.reported_cost += Decimal(str(cost))
            self.unreported_cost_calls -= 1
        if self.reported_cost > Decimal("0.05"):
            self.max_calls = self.calls
        return completion


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Authorize this paid smoke run")
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    display = parser.add_mutually_exclusive_group()
    display.add_argument("--headless", dest="headless", action="store_true")
    display.add_argument("--headful", dest="headless", action="store_false")
    parser.set_defaults(headless=True)
    args = parser.parse_args()
    if not args.live:
        parser.error("Pass --live only with an authorized US$0.05 OpenRouter budget")
    load_dotenv(args.env_file, override=False)
    model, key = os.getenv("MODEL_NAME"), os.getenv("OPENROUTER_API_KEY")
    if not model or not key:
        parser.error("Configure MODEL_NAME and OPENROUTER_API_KEY")
    if model != "qwen/qwen3.8-27b":
        parser.error("This price/routing/token-bound smoke configuration is for qwen/qwen3.8-27b")
    root = Path(__file__).resolve().parents[1]
    libraries = root / ".local/system-libs/usr/lib/x86_64-linux-gnu"
    if libraries.is_dir():
        os.environ["LD_LIBRARY_PATH"] = str(libraries) + ":" + os.getenv("LD_LIBRARY_PATH", "")
    os.environ.setdefault("MINIWOB_URL", (root / ".local/miniwob-plusplus/miniwob/html/miniwob").as_uri() + "/")
    backend = SmokeBudgetBackend(model, key, root / 'runs/openrouter-smoke-budget.json')
    episodes = []
    try:
        for task, steps in (("click-test", 1), ("enter-text", 3), ("choose-list", 2)):
            action_set = make_action_set()

            def environment(video):
                return gym.make("browsergym/miniwob." + task, headless=args.headless,
                                action_mapping=action_set.to_python_code, slow_mo=250,
                                record_video_dir=video)

            directory, summary = run_episode(environment, backend, {
                "task": "miniwob." + task, "model": model, "backend": backend.base_url,
                "driver": "llm", "verifier": "miniwob", "headless": args.headless,
                "generation": {"temperature": 0, "max_tokens": 512, **backend.request_options},
                "budget": {"suite_cap_usd": "0.05", "max_calls": 6,
                           "per_request_reservation_usd": str(backend.per_request_reservation),
                           "input_token_bound": backend.prompt_token_bound},
                "environment": {"miniwob_revision": "7fd85d71a4b60325c6585396ec4f48377d049838",
                                "slow_mo_ms": 250, "record_video": True},
            }, output=root / "runs", max_steps=steps, seed=0, record_video=True)
            rows = [json.loads(line) for line in (directory / "steps.jsonl").read_text().splitlines()]
            episodes.append({"task": task, "episode": str(directory.relative_to(root)),
                             "success": summary["success"], "error": summary["error"],
                             "decisions": len(rows), "parsed_actions": sum(row.get("action") is not None for row in rows),
                             "browser_action_errors": sum(bool(row.get("action_error")) for row in rows)})
            if summary["error"]:
                break  # Inspect a failure before spending on further episodes.
    finally:
        backend.close()
        result = {"model": model, "episodes": episodes, "requests": backend.calls,
                  "reported_cost_usd": str(backend.reported_cost),
                  "unreported_cost_calls": backend.unreported_cost_calls,
                  "reserved_cost_usd": str(backend.per_request_reservation * backend.calls),
                  "approved_cap_usd": "0.05"}
        if episodes:
            path = root / episodes[0]["episode"] / "smoke-suite.json"
            write_json(path, result)
        print(json.dumps(result, indent=2))
    if any(row['error'] for row in episodes):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
