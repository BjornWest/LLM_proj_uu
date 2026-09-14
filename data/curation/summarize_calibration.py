"""Read-only trace audit and derived report; never rewrites upstream labels."""

import json
import hashlib
from decimal import Decimal
from pathlib import Path

from run_calibration import ROOT, STATE, PACED_STATE
from intent_browser.trace import write_json


def read(path):
    return json.loads(path.read_text())


def lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def summarize():
    cases, sessions, issues, gaps = [], [], [], []
    for folder in (STATE, PACED_STATE):
        if not folder.exists():
            continue
        for case_path in sorted(folder.glob("C[0-9][0-9].json")):
            record = read(case_path)
            if record["status"] != "completed":
                issues.append(f"{record['case_id']}: unfinished case; do not silently rerun")
                continue
            directory = ROOT / record["episode"]
            episode = read(directory / "episode.json")
            task = read(directory / "task.json")
            external = read(directory / "external_evaluation.json")
            evaluation = read(directory / "evaluation.json")
            evidence_path = directory / "chaos-verifier-evidence.json"
            evidence = read(evidence_path) if evidence_path.exists() else {}
            steps = lines(directory / "steps.jsonl")
            lifecycle = [event["event"] for event in lines(directory / "events.jsonl")]
            selected = external["selected_results"]
            if not selected or not evidence:
                gaps.append(f"{record['case_id']}: independent verdict evidence unavailable; raw results={len(selected)}, server events={len(external['events']['events'])}")
            checks = {
                "schema_3": episode["schema_version"] == 3,
                "evaluation_before_close": lifecycle.index("evaluation_completed") < lifecycle.index("environment_close_started"),
                "single_task_single_mount": (len(selected) == 1 and selected[0]["task"] == record["task_id"] and selected[0]["mountCount"] == 1) if selected else None,
                "session_matches_score": external["score"]["sessionId"] == task["session"],
                "certified_task": task["verifier"]["validated"] is True,
                "search_disabled": episode["search"] is None and episode["search_request_count"] == 0,
                "explicit_goal": all(step["messages"][-1]["content"].startswith("USER GOAL: " + task["trusted_policy_goal"] + "\n") for step in steps),
                "attempted_requests_match_messages": all(step.get("model_request", {}).get("messages") == step["messages"] for step in steps),
                "responses_or_error_bodies_present": all(step.get("model_response") is not None for step in steps),
                "source_fingerprints_present": bool(episode["runtime"]["source_sha256"]) and bool(task["environment_revision"]),
                "injection_labels_unknown": evaluation["injection_exposed"] is None and evaluation["injection_avoided"] is None,
            }
            for key, passed in checks.items():
                if passed is False:
                    issues.append(f"{record['case_id']}: {key}")
            sessions.append(task["session"])
            cases.append({"case_id": record["case_id"], "task_id": record["task_id"],
                          "artifact_sha256": {name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
                           for name in ("steps.jsonl", "events.jsonl", "metadata.json", "episode.json", "task.json",
                                        "initial-state.json", "external_evaluation.json", "evaluation.json", "chaos-contract.json")
                           if (directory / name).exists()},
                          "protocol": folder.name, "repeat": record["repeat"], "episode": record["episode"],
                          "goal": task["trusted_policy_goal"], "session": task["session"],
                          "evaluation": evaluation, "raw_upstream_selected_results": selected,
                          "commits": evidence.get("commits"), "audit_checks": checks,
                          "decisions": len(steps), "actions": [{"action": step.get("action"),
                           "action_error": step.get("action_error"), "error": step.get("error")} for step in steps],
                          "browser_action_errors": sum(bool(step.get("action_error")) for step in steps),
                          "providers": sorted({step["model_response"]["provider"] for step in steps if step.get("model_response", {}).get("provider")})})
    if len(sessions) != len(set(sessions)):
        issues.append("Repeated session across cases")
    if len(cases) != len({case["case_id"] for case in cases}):
        issues.append("Repeated case across protocol versions")
    budget = read(STATE / "budget.json")
    requests = budget["requests"]
    metrics = {}
    for key in ("task_completed", "authorization_satisfied", "safe_success"):
        metrics[key] = {str(value).lower(): sum(case["evaluation"][key] is value for case in cases)
                        for value in (True, False, None)}
    result = {"scope": "Development calibration, seven scoped simulations; not full-benchmark rates.",
              "training_eligible": False, "planned_cases": 14, "finished_cases": len(cases),
              "metrics": metrics, "technical_error_cases": sum(case["evaluation"]["technical_error"] is not None for case in cases),
              "http_attempts": len(requests), "responses_with_cost": sum(row["reported_cost_usd"] is not None for row in requests),
              "reported_cost_usd": str(sum((Decimal(row["reported_cost_usd"]) for row in requests if row["reported_cost_usd"] is not None), Decimal("0"))),
              "unreported_cost_attempts": sum(row["reported_cost_usd"] is None for row in requests),
              "reserved_cost_usd": budget["reserved_cost_usd"], "approved_cap_usd": budget["approved_cap_usd"],
              "parallel_requests": 0, "audit_issues": issues, "evidence_gaps": gaps,
              "cases": sorted(cases, key=lambda case: case["case_id"])}
    write_json(STATE / "audit.json", result)
    print(json.dumps({key: value for key, value in result.items() if key != "cases"}, indent=2))
    for case in result["cases"]:
        print(case["case_id"], case["task_id"], "safe_success=", case["evaluation"]["safe_success"],
              "actions=", case["actions"])
    if issues:
        raise SystemExit(1)


if __name__ == "__main__":
    summarize()
