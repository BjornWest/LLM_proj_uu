"""Budgeted Chaos calibration through the existing harness; no grader changes.

Run from the repository root with .venv/bin/python. --live requires the user's
existing $3 authorization AND a recorded readiness reply from the harness owner.
One case per invocation makes inspection/resumption explicit. Never reuses a
case that has already started. Private contracts remain inside ChaosTask.
"""

import argparse
import fcntl
import hashlib
import json
import math
import os
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal
from email.utils import parsedate_to_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from intent_browser.backend import ChatCompletionsBackend
from intent_browser.trace import write_json

MODEL = "qwen/qwen3.8-27b"
TASKS = ("confirmshaming", "drip-pricing", "archive-vs-delete",
         "revoke-current-only", "drop-database", "transfer-by-not-clicking-save", "force-push")
CASES = [{"case_id": f"C{repeat * 7 + i + 1:02}", "task_id": task,
          "repeat": repeat + 1, "browsergym_seed": repeat}
         for repeat in range(2) for i, task in enumerate(TASKS)]
STATE = ROOT / "data/curation/calibration-chaos-v1"
PACED_STATE = ROOT / "data/curation/calibration-chaos-paced-v2"
CAP = Decimal("3")
TOKEN_BOUND = 24000
MAX_TOKENS = 512
RESERVATION = Decimal(TOKEN_BOUND) * Decimal("0.0000005") + Decimal(MAX_TOKENS) * Decimal("0.000003")
PINNED_FILES = ["intent_browser/runner.py", "intent_browser/backend.py", "intent_browser/actions.py",
                "intent_browser/trace.py", "intent_browser/evaluation.py", "intent_browser/chaos.py",
                "intent_browser/chaos_verifier.py", "config/chaos_verifier.json",
                "scripts/inspect_chaos.mjs", "data/curation/run_calibration.py"]


def now():
    return datetime.now(timezone.utc).isoformat()


def fingerprints():
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in PINNED_FILES}


class BudgetBackend(ChatCompletionsBackend):
    def __init__(self, key, ledger_path, case_id, pinned=None, pace_seconds=0):
        super().__init__("https://openrouter.ai/api/v1", MODEL, key, max_tokens=MAX_TOKENS,
                         request_options={"preset": "@preset/deka-llm-qwen38-27-b",
                                          "reasoning": {"enabled": False},
                                          "provider": {"only": ["dekallm"], "allow_fallbacks": False,
                                                       "require_parameters": True,
                                                       "max_price": {"prompt": 0.5, "completion": 3, "request": 0}}})
        self.ledger_path, self.case_id, self.pinned = Path(ledger_path), case_id, pinned
        self.stop_issue = None
        self.pace_seconds = pace_seconds
        self.response_metadata = None
        self.client.event_hooks["response"].append(self.capture_response_metadata)

    def capture_response_metadata(self, response):
        # Response-only whitelist; never serialize authentication/request headers.
        retry_after = response.headers.get("retry-after")
        delay = None
        if retry_after is not None:
            try:
                delay = max(0.0, float(retry_after))
            except ValueError:
                try:
                    delay = max(0.0, (parsedate_to_datetime(retry_after) - datetime.now(timezone.utc)).total_seconds())
                except (ValueError, TypeError, OverflowError):
                    pass
        if delay is not None and not math.isfinite(delay):
            delay = None
        self.response_metadata = {"http_status": response.status_code, "retry_after": retry_after,
                                  "retry_after_seconds": delay}

    def change_ledger(self, change):
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with self.ledger_path.with_suffix(".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            data = json.loads(self.ledger_path.read_text()) if self.ledger_path.exists() else {
                "approved_cap_usd": str(CAP), "reserved_cost_usd": "0", "requests": []}
            if Decimal(data["approved_cap_usd"]) != CAP:
                raise ValueError("Unexpected budget ledger cap")
            result = change(data)
            write_json(self.ledger_path, data)
            return result

    def complete(self, messages):
        # Plain-text only. Serialized UTF-8 bytes plus 2048 framing tokens is a
        # conservative bound for this byte-level text tokenizer; reject oversize.
        if any(set(m) != {"role", "content"} or not isinstance(m["content"], str) for m in messages):
            raise ValueError("Calibration accepts plain-text role/content messages only")
        if len(json.dumps(messages, ensure_ascii=False).encode("utf-8")) + 2048 > TOKEN_BOUND:
            raise ValueError("Input exceeds the reserved token bound; no request sent")
        if self.stop_issue:
            raise ValueError(self.stop_issue)
        waited = 0.0
        if self.pace_seconds and self.ledger_path.exists():
            previous = json.loads(self.ledger_path.read_text())["requests"]
            if previous:
                timestamp = previous[-1].get("finished_at", previous[-1]["started_at"])
                since = (datetime.now(timezone.utc) - datetime.fromisoformat(timestamp)).total_seconds()
                # Old v1 error rows lack HTTP metadata: conservatively apply the
                # same cooldown to every failed attempt, including unknown errors.
                cooldown = max(self.pace_seconds, 60 if previous[-1]["status"] != "completed" else 0,
                               (previous[-1].get("http") or {}).get("retry_after_seconds") or 0)
                waited = max(0.0, cooldown - since)
                time.sleep(waited)
        if self.pinned is not None and fingerprints() != self.pinned:
            raise ValueError("Relevant harness/configuration changed; no request sent")

        def reserve(data):
            if any(row.get("audit_issue") for row in data["requests"]):
                raise ValueError("Prior response needs review; no request sent")
            total = Decimal(data["reserved_cost_usd"]) + RESERVATION
            if total > CAP:
                raise ValueError("$3 reservation cap reached; no request sent")
            index = len(data["requests"])
            data["reserved_cost_usd"] = str(total)
            data["requests"].append({"index": index, "case_id": self.case_id, "started_at": now(),
                                     "reservation_usd": str(RESERVATION), "status": "reserved",
                                     "pacing_seconds": self.pace_seconds, "pacing_wait_seconds": waited,
                                     "reported_cost_usd": None})
            return index

        index = self.change_ledger(reserve)  # Never release reservations, even on errors/restart.
        self.response_metadata = None
        try:
            completion = super().complete(messages)
        except BaseException as exc:
            self.change_ledger(lambda data: data["requests"][index].update(
                status="error", error_type=type(exc).__name__, finished_at=now(), http=self.response_metadata))
            raise
        raw = completion.raw
        usage = raw.get("usage") or {}
        cost = usage.get("cost")
        issues = []
        if raw.get("provider") != "DekaLLM" or raw.get("model") != MODEL:
            issues.append("Unexpected model/provider")
        if cost is None:
            issues.append("Missing reported cost")
        elif not Decimal(str(cost)).is_finite() or not Decimal("0") <= Decimal(str(cost)) <= RESERVATION:
            issues.append("Reported cost exceeds reservation or is invalid")
        for name, maximum in (("prompt_tokens", TOKEN_BOUND), ("completion_tokens", MAX_TOKENS)):
            value = usage.get(name)
            if not isinstance(value, int) or not 0 <= value <= maximum:
                issues.append(f"Invalid {name} or token bound exceeded")
        self.stop_issue = "; ".join(issues) or None
        self.change_ledger(lambda data: data["requests"][index].update(
            status="completed", finished_at=now(), response_id=raw.get("id"), model=raw.get("model"),
            http=self.response_metadata,
            provider=raw.get("provider"), usage=usage, reported_cost_usd=str(cost) if cost is not None else None,
            audit_issue=self.stop_issue))
        return completion  # Preserve the exact response in harness traces before stopping.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--case", choices=[row["case_id"] for row in CASES])
    parser.add_argument("--chaos-base-url", default="http://localhost:45379")
    parser.add_argument("--readiness-reference", help="Reference to the harness owner's readiness reply")
    parser.add_argument("--pace-seconds", type=int, choices=[0, 10, 30, 60], default=0,
                        help="Explicit v2 amendment: minimum gap after previous HTTP attempt; no retries")
    args = parser.parse_args()
    if not args.live:
        print(json.dumps({"cases": CASES, "cap_usd": str(CAP), "max_steps": 12,
                          "per_request_reservation_usd": str(RESERVATION),
                          "maximum_14_case_reservation_usd": str(RESERVATION * 14 * 12),
                          "search": "disabled", "pacing_seconds": args.pace_seconds,
                          "status": "plan_only"}, indent=2))
        return
    if not args.case or not args.readiness_reference:
        parser.error("Live runs need --case and --readiness-reference")

    from dotenv import load_dotenv
    import browsergym.core  # noqa: F401
    import gymnasium as gym
    from intent_browser.actions import make_action_set
    from intent_browser.chaos import ChaosClient, ChaosTask
    from intent_browser.runner import run_episode

    load_dotenv(ROOT / ".env", override=False)
    key = os.getenv("OPENROUTER_API_KEY")
    if not key:
        parser.error("OPENROUTER_API_KEY is missing")
    libraries = ROOT / ".local/system-libs/usr/lib/x86_64-linux-gnu"
    if libraries.is_dir():
        os.environ["LD_LIBRARY_PATH"] = str(libraries) + ":" + os.getenv("LD_LIBRARY_PATH", "")
    state = PACED_STATE if args.pace_seconds else STATE
    state.mkdir(parents=True, exist_ok=True)
    STATE.mkdir(parents=True, exist_ok=True)  # Shared lock and $3 budget across amendments.
    with (STATE / "suite.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        plan_path = state / "plan.json"
        current = fingerprints()
        if plan_path.exists():
            plan = json.loads(plan_path.read_text())
            if (plan["source_sha256"] != current or plan["chaos_base_url"] != args.chaos_base_url
                    or plan.get("pacing_seconds", 0) != args.pace_seconds):
                raise ValueError("Protocol changed; inspect and explicitly version the suite")
        else:
            plan = {"suite_id": state.name, "created_at": now(), "cases": CASES,
                    "pacing_seconds": args.pace_seconds,
                    "error_cooldown_seconds": 60 if args.pace_seconds else 0,
                    "retry_after": "Honor longer response Retry-After when available; no retry of the failed case.",
                    "amends": "data/curation/calibration-chaos-v1/plan.json" if args.pace_seconds else None,
                    "amendment_reason": "Repeated upstream shared-pool HTTP 429; pacing only, no retries or policy changes." if args.pace_seconds else None,
                    "timing_note": "Harness inference_seconds includes pacing; ledger records HTTP-attempt timing and pacing wait.",
                    "source_sha256": current, "readiness_reference": args.readiness_reference,
                    "chaos_base_url": args.chaos_base_url, "model": MODEL, "headless": True,
                    "max_steps": 12, "max_tokens": MAX_TOKENS, "temperature": 0,
                    "search": "disabled", "approved_cap_usd": str(CAP),
                    "per_request_reservation_usd": str(RESERVATION), "prompt_token_bound": TOKEN_BOUND,
                    "training_eligible": False, "split": "development",
                    "scope": "Seven scoped simulated contracts, two fresh sessions each; not benchmark-wide rates."}
            write_json(plan_path, plan)
        case = next(row for row in CASES if row["case_id"] == args.case)
        case_path = state / f"{args.case}.json"
        if any((folder / f"{args.case}.json").exists() for folder in (STATE, PACED_STATE)):
            raise ValueError("Case already started under this protocol or an earlier version; no paid rerun")
        # Exclusive creation prevents accidental paid reruns, including interrupted cases.
        with case_path.open("x") as handle:
            json.dump({**case, "status": "started", "started_at": now()}, handle, indent=2)

        class CertifiedTask(ChaosTask):
            def prepare(self, trace):
                self.trace_directory = trace.directory
                result = super().prepare(trace)
                if not self.verifier_ready or not self.policy_goal or self.preflight:
                    raise ValueError("Certified task contract unavailable; no model request permitted")
                return result

        task = CertifiedTask(ChaosClient(args.chaos_base_url), case["task_id"])
        backend = BudgetBackend(key, STATE / "budget.json", args.case, current, args.pace_seconds)
        action_set = make_action_set()

        def environment(video):
            return gym.make("browsergym/openended", task_kwargs={"start_url": task.start_url,
                            "goal": task.policy_goal}, headless=True, slow_mo=250,
                            wait_for_user_message=False, record_video_dir=video,
                            action_mapping=action_set.to_python_code)

        try:
            directory, summary = run_episode(environment, backend, {
                "task": "openended", "source": "browser-agent-chaos", "source_task_id": case["task_id"],
                "driver": "llm", "model": MODEL, "backend": backend.base_url, "headless": True,
                "verifier": None, "calibration_case": case,
                "generation": {"temperature": 0, "max_tokens": MAX_TOKENS, **backend.request_options},
                "pacing_seconds": args.pace_seconds,
                "budget": {"ledger": str((STATE / 'budget.json').relative_to(ROOT)),
                           "approved_cap_usd": str(CAP), "per_request_reservation_usd": str(RESERVATION)},
                "environment": {"slow_mo_ms": 250, "record_video": True},
                "calibration_plan": str(plan_path.relative_to(ROOT)),
            }, output=ROOT / "runs", max_steps=12, seed=case["browsergym_seed"],
                record_video=True, search_backend=None, episode_task=task)
            write_json(case_path, {**case, "status": "completed", "episode": str(directory.relative_to(ROOT)),
                                  "finished_at": now(), "summary": summary, "budget_audit_issue": backend.stop_issue})
        finally:
            backend.close()
            task.client.close()
        if summary["error"] or backend.stop_issue:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
