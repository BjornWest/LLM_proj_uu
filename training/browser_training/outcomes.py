"""CPU-only immutable episode ledger and deterministic metric reduction.

SQLite is local to ONE orchestrator host, not a network filesystem/shared-node DB.
Producers send records to that host; durable snapshots/SQLite backups are portable.
This module does not change rewards, schedule tasks or call a training framework.
"""
from collections import defaultdict
from contextlib import closing
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import tempfile
import time

from .metric_catalog import METRICS, TELEMETRY, SCHEMA_VERSION

SPLITS = {"harness_dev", "model_dev", "sft_train", "sft_validation", "rl_train", "generic_eval", "final_test"}
PRODUCERS = {"trainer", "rollout", "browser", "orchestrator", "evaluator"}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def number(value, name, *, integer=False, nullable=False):
    if value is None and nullable:
        return
    require(type(value) in ((int,) if integer else (int, float)) and math.isfinite(value)
            and value >= 0, f"{name} must be a finite nonnegative {'integer' if integer else 'number'}")


def fields(value, required, optional=()):
    require(isinstance(value, dict), "Expected an object")
    require(set(required) <= value.keys(), f"Missing fields: {set(required) - value.keys()}")
    require(value.keys() <= set(required) | set(optional), f"Unknown fields: {value.keys() - set(required) - set(optional)}")


def validate(event):
    fields(event, {"id", "kind", "occurred_at", "producer", "payload"})
    require(isinstance(event["id"], str) and event["id"], "Event id required")
    number(event["occurred_at"], "occurred_at")
    require(event["producer"] in PRODUCERS, "Unknown producer")
    p = event["payload"]
    if event["kind"] == "episode":
        fields(p, {"episode_id", "group_id", "group_size", "member", "attempt", "task_family",
                   "task_template", "task_instance", "seed", "split", "policy_version", "status",
                   "goal_completed", "constraints_satisfied", "unauthorized_effect", "reward",
                   "harness_revision", "verifier_revision", "environment_revision", "tokenizer_revision"},
               {"generated_tokens", "duration_s", "steps", "interventions", "trace_ref"})
        for key in ("episode_id", "group_id", "task_family", "task_template", "task_instance",
                    "harness_revision", "verifier_revision", "environment_revision", "tokenizer_revision"):
            require(isinstance(p[key], str) and p[key], f"{key} required")
        for key in ("group_size", "member", "attempt", "seed", "policy_version"):
            number(p[key], key, integer=True)
        require(0 <= p["member"] < p["group_size"], "Invalid group member")
        require(p["split"] in SPLITS, "Unknown split")
        require(p["split"] != "rl_train" or p["group_size"] >= 2, "GRPO needs at least two group members")
        require(p["status"] in {"completed", "infra_error", "cancelled"}, "Unknown terminal status")
        for key in ("goal_completed", "constraints_satisfied", "unauthorized_effect"):
            require(p[key] is None or type(p[key]) is bool, f"{key} must be boolean or null")
        reward = p["reward"]
        require(reward is None or (type(reward) in (int, float) and math.isfinite(reward)), "Invalid reward")
        if p["status"] != "completed":
            require(all(p[k] is None for k in ("goal_completed", "constraints_satisfied", "unauthorized_effect", "reward")),
                    "Infrastructure/cancelled outcomes must not masquerade as verified policy outcomes")
        for key in ("generated_tokens", "steps", "interventions"):
            number(p.get(key), key, integer=True, nullable=True)
        number(p.get("duration_s"), "duration_s", nullable=True)
        require(p.get("trace_ref") is None or isinstance(p["trace_ref"], str), "trace_ref must be string/null")
    elif event["kind"] == "admission":
        fields(p, {"episode_id", "decision", "reason", "trainer_policy_version"})
        require(isinstance(p["episode_id"], str) and p["episode_id"], "Episode id required")
        require(p["decision"] in {"admitted", "discarded"}, "Unknown admission decision")
        require(isinstance(p["reason"], str) and p["reason"], "Decision reason required")
        number(p["trainer_policy_version"], "trainer_policy_version", integer=True)
    elif event["kind"] == "telemetry":
        fields(p, {"step", "axis", "policy_version", "checkpoint_id", "context", "values"}, {"unavailable"})
        number(p["step"], "step", integer=True)
        number(p["policy_version"], "policy_version", integer=True, nullable=True)
        require(p["axis"] in {"optimizer_step", "measurement", "evaluation"}, "Unknown telemetry axis")
        require(p["checkpoint_id"] is None or (isinstance(p["checkpoint_id"], str) and p["checkpoint_id"]), "Invalid checkpoint identity")
        require(isinstance(p["context"], str) and p["context"], "Describe measurement scope/source")
        require(isinstance(p["values"], dict), "Invalid telemetry")
        missing = p.get("unavailable", {})
        require(isinstance(missing, dict) and (p["values"] or missing), "Empty telemetry")
        require(not (p["values"].keys() & missing.keys()), "Available and unavailable overlap")
        for key, reason in missing.items():
            require(key in TELEMETRY and TELEMETRY[key]["producer"] == event["producer"], "Wrong unavailable metric")
            require(isinstance(reason, str) and reason, "Unavailable reason required")
        for key, value in p["values"].items():
            require(key in TELEMETRY, f"Metric not catalogued: {key}")
            definition = TELEMETRY[key]
            require(definition["producer"] == event["producer"], f"Wrong producer for {key}")
            require(type(value) in (int, float) and math.isfinite(value), f"Nonfinite telemetry: {key}")
            require(definition["minimum"] is None or value >= definition["minimum"], f"Below minimum: {key}")
            require(definition["maximum"] is None or value <= definition["maximum"], f"Above maximum: {key}")
    elif event["kind"] == "evaluation":
        from .evaluation import validate_report
        require(event["producer"] == "evaluator", "Only evaluator reports fixed suites")
        validate_report(p)
    elif event["kind"] == "task_draw":
        from .curriculum import validate_draw
        require(event["producer"] == "orchestrator", "Only orchestrator draws tasks")
        validate_draw(p)
    elif event["kind"] in {"row_manifest", "row_decision", "row_use"}:
        from .row_accounting import validate_event
        validate_event(event)
    else:
        raise ValueError(f"Unknown event kind: {event['kind']}")
    canonical(event)  # Reject non-JSON data before persistence.


GROUP_IDENTITY = ("group_size", "task_family", "task_template", "task_instance", "seed", "split",
                  "policy_version", "harness_revision", "verifier_revision", "environment_revision", "tokenizer_revision")


def validate_relations(events):
    from .row_accounting import validate_relations as validate_rows
    validate_rows(events)
    episodes, groups, slots, decisions = {}, {}, set(), {}
    attempts_by_slot = defaultdict(list)
    draws = {}
    for event in events:
        p = event["payload"]
        if event["kind"] == "episode":
            require(p["episode_id"] not in episodes, "Duplicate episode identity; retry the original event id")
            episodes[p["episode_id"]] = p
            identity = tuple(p[k] for k in GROUP_IDENTITY)
            require(groups.setdefault(p["group_id"], identity) == identity, "Group task/seed/policy/provenance mismatch")
            slot = (p["group_id"], p["member"], p["attempt"])
            require(slot not in slots, "Duplicate group member attempt")
            slots.add(slot)
            attempts_by_slot[slot[:2]].append(p)
        elif event["kind"] == "admission":
            require(p["episode_id"] not in decisions, "Admission is final; duplicate or conflicting decision")
            decisions[p["episode_id"]] = p
        elif event["kind"] == "task_draw":
            require(p["group_id"] not in draws, "Duplicate group draw")
            draws[p["group_id"]] = p
    for p in episodes.values():
        if p["group_id"] in draws:
            require(all(p[k] == draws[p["group_id"]][k] for k in GROUP_IDENTITY),
                    "Episode differs from committed task/policy draw")
    for attempts in attempts_by_slot.values():
        ordered = sorted(attempts, key=lambda p: p["attempt"])
        require(all(p["status"] != "completed" for p in ordered[:-1]),
                "Cannot retry a completed policy sample; use a new group for another trial")
    for episode_id, decision in decisions.items():
        # Arrival order may differ across producers. Join only when terminal evidence arrives.
        if episode_id not in episodes:
            continue
        p = episodes[episode_id]
        require(p["split"] == "rl_train", "Training admission only applies to RL train")
        require(decision["trainer_policy_version"] >= p["policy_version"], "Negative policy age")
        if decision["decision"] == "admitted":
            require(p["status"] == "completed" and p["reward"] is not None and safe(p) is not None,
                    "Cannot admit an unverified or incomplete trajectory")


class Ledger:
    """Immutable events; atomic deduplication and validation survive process restarts."""
    def __init__(self, path, *, run_id, synthetic, expected_producers=(), publication=None):
        require(isinstance(run_id, str) and run_id, "run_id required")
        require(type(synthetic) is bool, "Explicit synthetic flag required")
        require(set(expected_producers) <= PRODUCERS, "Unknown expected producer")
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.metadata = {"schema_version": SCHEMA_VERSION, "run_id": run_id, "synthetic": synthetic,
                         "expected_producers": sorted(set(expected_producers))}
        if publication is not None:
            from .publication import validate_publication
            self.metadata["publication"] = validate_publication(publication, run_id)
        with closing(self.connect()) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS metadata (id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL, recorded_at REAL NOT NULL, body TEXT NOT NULL)")
            db.execute("CREATE INDEX IF NOT EXISTS event_episode ON events(json_extract(body, '$.payload.episode_id'))")
            db.execute("CREATE INDEX IF NOT EXISTS event_group ON events(json_extract(body, '$.payload.group_id'))")
            db.execute("INSERT OR IGNORE INTO metadata VALUES (1, ?)", (canonical(self.metadata),))
            require(json.loads(db.execute("SELECT body FROM metadata").fetchone()[0]) == self.metadata,
                    "Ledger run/schema/synthetic/producers mismatch")

    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        return db

    def append(self, event):
        validate(event)
        body = canonical(event)
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT seq, body FROM events WHERE id=?", (event["id"],)).fetchone()
            if previous:
                require(previous[1] == body, "Event id reused with different content")
                return previous[0]
            p = event["payload"]
            # Validate related identities only; appending telemetry never scans episode history.
            related = db.execute("SELECT body FROM events WHERE json_extract(body, '$.payload.episode_id')=? "
                                 "OR json_extract(body, '$.payload.group_id')=? ORDER BY seq",
                                 (p.get("episode_id"), p.get("group_id")))
            existing = [json.loads(row[0]) for row in related]
            if event["kind"] == "evaluation":
                from .evaluation import validate_report
                ids = p["episode_ids"]
                rows = db.execute("SELECT body FROM events WHERE id IN (" + ",".join("?" for _ in ids) + ")", ids)
                validate_report(p, [json.loads(row[0]) for row in rows])
            validate_relations([*existing, event])
            cursor = db.execute("INSERT INTO events(id, recorded_at, body) VALUES (?, ?, ?)", (event["id"], time.time(), body))
            return cursor.lastrowid

    def records(self):
        with closing(self.connect()) as db:
            return [dict(seq=row[0], recorded_at=row[1], event=json.loads(row[2]))
                    for row in db.execute("SELECT seq, recorded_at, body FROM events ORDER BY seq")]

    def event(self, identity):
        with closing(self.connect()) as db:
            row = db.execute("SELECT body FROM events WHERE id=?", (identity,)).fetchone()
            return None if row is None else json.loads(row[0])

    def watermark(self):
        with closing(self.connect()) as db:
            return db.execute("SELECT COALESCE(MAX(seq), 0) FROM events").fetchone()[0]

    def backup(self, destination, *, publication=None):
        """Use SQLite's consistent backup, not a live copy omitting the WAL."""
        destination = Path(destination)
        require(destination.resolve() != self.path.resolve(), "Backup must use a different path")
        require(not destination.exists(), "Backup destination already exists")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as source, closing(sqlite3.connect(destination)) as target:
            source.backup(target)
            if publication is not None:
                from .publication import validate_publication
                metadata = {**self.metadata, "publication": validate_publication(publication, self.metadata["run_id"])}
                with target:
                    target.execute("UPDATE metadata SET body=? WHERE id=1", (canonical(metadata),))


def safe(p):
    if p["status"] != "completed":
        return None
    if p["goal_completed"] is False or p["constraints_satisfied"] is False or p["unauthorized_effect"] is True:
        return False
    if p["goal_completed"] is True and p["constraints_satisfied"] is True and p["unauthorized_effect"] is False:
        return True
    return None


def rate(values):
    values = [x for x in values if x is not None]
    n, successes = len(values), sum(values)
    if not n:
        return {"value": None, "numerator": 0, "denominator": 0, "ci95_low": None, "ci95_high": None}
    p, z = successes / n, 1.959963984540054
    center = (p + z*z/(2*n)) / (1 + z*z/n)
    margin = z * math.sqrt(p*(1-p)/n + z*z/(4*n*n)) / (1 + z*z/n)
    return dict(value=p, numerator=successes, denominator=n, ci95_low=max(0, center-margin), ci95_high=min(1, center+margin))


def reduce_cohort(attempts, latest, decisions):
    finished = [p for p in latest if p["status"] == "completed"]
    admitted = [decisions[p["episode_id"]] for p in attempts if p["episode_id"] in decisions]
    ages = [decisions[p["episode_id"]]["trainer_policy_version"] - p["policy_version"]
            for p in attempts if p["episode_id"] in decisions]
    metrics = {
        "attempts": {"value": len(attempts)}, "episodes": {"value": len(latest)},
        "completion": rate([p["goal_completed"] for p in finished]),
        "safe_completion": rate([safe(p) for p in finished]),
        "unauthorized_effect": rate([p["unauthorized_effect"] for p in finished]),
        "infra_error": rate([p["status"] == "infra_error" for p in latest]),
        "infra_error_attempts": {"value": sum(p["status"] == "infra_error" for p in attempts)},
        "cancelled_attempts": {"value": sum(p["status"] == "cancelled" for p in attempts)},
        "cancelled": rate([p["status"] == "cancelled" for p in latest]),
        "unknown_goal": rate([p["goal_completed"] is None for p in finished]),
        "unknown_safe": rate([safe(p) is None for p in finished]),
        "admitted": {"value": sum(p["decision"] == "admitted" for p in admitted)},
        "discarded": {"value": sum(p["decision"] == "discarded" for p in admitted)},
        "mixed_admission": {"value": sum(p["decision"] == "mixed" for p in admitted)},
        "pending_admission": {"value": sum(p["split"] == "rl_train" and p["episode_id"] not in decisions for p in attempts)},
        "policy_age": {"value": sum(ages)/len(ages) if ages else None, "maximum": max(ages, default=None), "samples": len(ages)},
    }
    reasons = defaultdict(int)
    for decision in admitted:
        if decision["decision"] == "discarded":
            reasons[decision["reason"]] += 1
    for key in ("generated_tokens", "duration_s", "steps", "interventions"):
        measured = [p[key] for p in attempts if p.get(key) is not None]
        metrics[key] = {"value": sum(measured) if measured else None, "measured_attempts": len(measured),
                        "missing_attempts": len(attempts) - len(measured)}
    groups = defaultdict(list)
    for p in latest:
        if p["split"] == "rl_train":
            groups[p["group_id"]].append(p)
    valid = [g for g in groups.values() if len(g) == g[0]["group_size"] and
             all(p["status"] == "completed" and safe(p) is not None and p["reward"] is not None for p in g)]
    metrics.update(groups={"value": len(groups)}, valid_groups={"value": len(valid)},
                   mixed_groups=rate([len({p["reward"] for p in g}) > 1 for g in valid]),
                   all_success_groups={"value": sum(all(p["reward"] == 1 for p in g) for g in valid)},
                   all_failure_groups={"value": sum(all(p["reward"] == 0 for p in g) for g in valid)},
                   admitted_groups={"value": sum(all(decisions.get(p["episode_id"], {}).get("decision") == "admitted" for p in g) for g in valid)})
    require(metrics.keys() == METRICS.keys(), "Metric catalog and reducer differ")
    return {"metrics": metrics, "discard_reasons": dict(sorted(reasons.items()))}


def snapshot(ledger, *, now=None, window_s=3600):
    from .curriculum import summarize_draws
    now = time.time() if now is None else now
    number(now, "now")
    number(window_s, "window_s")
    require(window_s > 0, "Window must be positive")
    records = ledger.records()
    events = [r["event"] for r in records if r["event"]["occurred_at"] <= now]
    episodes = [e for e in events if e["kind"] == "episode"]
    decisions = {e["payload"]["episode_id"]: e["payload"] for e in events if e["kind"] == "admission"}
    from .row_accounting import summarize
    row_flow, row_decisions = summarize(events)
    require(not (decisions.keys() & row_decisions.keys()), "Legacy and row-derived admission overlap")
    decisions.update(row_decisions)
    latest = {}
    for e in episodes:
        p = e["payload"]
        slot = p["group_id"], p["member"]
        if slot not in latest or p["attempt"] > latest[slot]["payload"]["attempt"]:
            latest[slot] = e
    # Select latest attempt BEFORE time filtering, so a late old attempt cannot resurrect a slot.
    cohorts = {}
    for split in sorted({e["payload"]["split"] for e in episodes}):
        cohorts[split] = {}
        for window, lower in (("all", 0), ("recent", now-window_s)):
            attempts = [e["payload"] for e in episodes if e["payload"]["split"] == split and e["occurred_at"] >= lower]
            selected = [e["payload"] for e in latest.values() if e["payload"]["split"] == split and e["occurred_at"] >= lower]
            summary = reduce_cohort(attempts, selected, decisions)
            summary["families"] = {family: reduce_cohort([p for p in attempts if p["task_family"] == family],
                                                        [p for p in selected if p["task_family"] == family], decisions)
                                   for family in sorted({p["task_family"] for p in attempts})}
            # JSON keys are namespaced by family to avoid template-name collisions.
            summary["templates"] = {canonical([family, template]): reduce_cohort(
                [p for p in attempts if (p["task_family"], p["task_template"]) == (family, template)],
                [p for p in selected if (p["task_family"], p["task_template"]) == (family, template)], decisions)
                for family, template in sorted({(p["task_family"], p["task_template"]) for p in attempts})}
            cohorts[split][window] = summary
    telemetry = {key: None for key in TELEMETRY}
    unavailable = {}
    for e in sorted(events, key=lambda e: (e["occurred_at"], e["id"])):
        if e["kind"] == "telemetry":
            for key, value in e["payload"]["values"].items():
                telemetry[key] = {**{k: v for k, v in e["payload"].items() if k not in {"values", "unavailable"}},
                                  "value": value, "occurred_at": e["occurred_at"], "producer": e["producer"]}
                unavailable.pop(key, None)
            for key, reason in e["payload"].get("unavailable", {}).items():
                telemetry[key] = None
                unavailable[key] = dict(reason=reason, occurred_at=e["occurred_at"],
                                        context=e["payload"]["context"], producer=e["producer"])
    inherited_ids = set()
    if ledger.metadata.get("publication"):
        boundary = ledger.metadata["publication"]["inherited_watermark"]
        inherited_ids = {r["event"]["id"] for r in records if r["seq"] <= boundary}
        latest_sources = {}
        for e in sorted(events, key=lambda e: (e["occurred_at"], e["id"])):
            if e["kind"] == "telemetry":
                for key in e["payload"]["values"].keys() | e["payload"].get("unavailable", {}).keys():
                    latest_sources[key] = e["id"]
        for key, measurement in telemetry.items():
            if measurement is not None:
                measurement["inherited"] = latest_sources[key] in inherited_ids
        for key, measurement in unavailable.items():
            measurement["inherited"] = latest_sources[key] in inherited_ids
    producers = {p: max((e["occurred_at"] for e in events if e["producer"] == p and e["id"] not in inherited_ids), default=None)
                 for p in ledger.metadata["expected_producers"]}
    result = {**ledger.metadata, "snapshot_at": now, "window_s": window_s,
              "watermark": records[-1]["seq"] if records else 0,
              "last_recorded_at": records[-1]["recorded_at"] if records else None,
              "last_occurred_at": max((e["occurred_at"] for e in events), default=None),
              "future_events": sum(r["event"]["occurred_at"] > now for r in records),
              "producer_last_seen": producers, "cohorts": cohorts, "telemetry": telemetry,
              "curriculum": summarize_draws(events, now=now, window_s=window_s),
              "unmatched_admissions": sorted(set(decisions) - {e["payload"]["episode_id"] for e in episodes}),
              "tokenizer_revisions": sorted({e["payload"]["tokenizer_revision"] for e in episodes}),
              "provenance": {key: sorted({e["payload"][key] for e in episodes}) for key in
                             ("harness_revision", "verifier_revision", "environment_revision")},
              "policy_versions": sorted({e["payload"]["policy_version"] for e in episodes}),
              "uncertainty_note": "Wilson 95% intervals are descriptive episode-level intervals; related GRPO samples/tasks are not independent trials."}
    # Never sum incompatible tokenizers into an apparently common token unit.
    from .evaluation import summarize_evaluations
    evaluations = summarize_evaluations(events)
    if evaluations:
        result["evaluations"] = evaluations
    if unavailable:
        result["telemetry_unavailable"] = unavailable
    if row_flow is not None:
        result["training_rows"] = row_flow
    require(len(result["tokenizer_revisions"]) <= 1, "Separate runs are required for different token-counting tokenizers")
    result["snapshot_id"] = hashlib.sha256(canonical(result).encode()).hexdigest()
    return result


def verify_snapshot(value):
    body = {k: v for k, v in value.items() if k != "snapshot_id"}
    require(value.get("schema_version") == SCHEMA_VERSION, "Unsupported snapshot schema")
    require(value.get("snapshot_id") == hashlib.sha256(canonical(body).encode()).hexdigest(), "Snapshot content hash mismatch")
    if value.get("publication") is not None:
        from .publication import validate_publication
        validate_publication(value["publication"], value["run_id"])
    return value


def write_snapshot(value, destination):
    verify_snapshot(value)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".snapshot-", dir=destination.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, destination)
        parent_fd = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    finally:
        if os.path.exists(name):
            os.unlink(name)
