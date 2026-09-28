"""Optional W&B publication/readback of the SAME locally persisted snapshot.

No dashboard layout or training framework imports. W&B imports are lazy so CPU
accounting, local readers and curriculum do not require the service or its SDK.
"""
import json
import hashlib
import os
from pathlib import Path
import tempfile
import time

from .publication import publication_run_id, publication_config
from .metric_catalog import METRICS, TELEMETRY, CURRICULUM, ROW_METRICS, EVALUATION, SCHEMA_VERSION
from .outcomes import canonical, require, verify_snapshot, write_snapshot


def scalar_metrics(snapshot):
    """Bounded scalar cardinality; task-family/template detail lives in the snapshot/table."""
    verify_snapshot(snapshot)
    values = {"monitoring/watermark": snapshot["watermark"],
              "monitoring/snapshot_at": snapshot["snapshot_at"],
              "monitoring/unmatched_admissions": len(snapshot["unmatched_admissions"]),
              "monitoring/future_events": snapshot["future_events"]}
    for split, windows in snapshot["cohorts"].items():
        for window, cohort in windows.items():
            for key, measurement in cohort["metrics"].items():
                for statistic, value in measurement.items():
                    if value is not None:
                        values[f"outcomes/{split}/{window}/{key}/{statistic}"] = value
    for key, measurement in snapshot["telemetry"].items():
        values[f"telemetry_available/{key}"] = int(measurement is not None and not measurement.get("inherited", False))
        if measurement is not None and not measurement.get("inherited", False):
            values[f"telemetry/{key}"] = measurement["value"]
            values[f"telemetry_time/{key}"] = measurement["occurred_at"]
            values[f"telemetry_step/{key}"] = measurement["step"]
    if snapshot.get("curriculum") is not None:
        for window, data in snapshot["curriculum"].items():
            values[f"curriculum/{window}/draws"] = data["draws"]
    if snapshot.get("training_rows") is not None:
        for section in ("totals", "episode_states"):
            for key, value in snapshot["training_rows"][section].items():
                values[f"training_rows/{section}/{key}"] = value
    # Only the latest complete report per fixed suite gets dashboard scalars;
    # full per-checkpoint records remain in the immutable snapshot.
    latest = {}
    for report in snapshot.get("evaluations", []):
        latest[report["suite_name"]] = report
    for name, report in latest.items():
        prefix = f"evaluation/{name}"
        values[f"{prefix}/valid_for_comparison"] = int(report["valid_for_comparison"])
        values[f"{prefix}/inherited"] = int(report["publication_run_id"] != publication_run_id(snapshot))
        values[f"{prefix}/policy_version"] = report["policy_version"]
        values[f"{prefix}/occurred_at"] = report["occurred_at"]
        for key in ("completion", "safe_completion", "unauthorized_effect", "infra_error", "unknown_safe"):
            for stat, value in report["metrics"][key].items():
                if value is not None:
                    values[f"{prefix}/{key}/{stat}"] = value
    return values


def family_rows(snapshot):
    columns = ["split", "window", "family", "episodes", "completion", "completion_n", "safe_completion",
               "safe_n", "unauthorized_effect", "effect_n", "unknown_safe", "infra_error", "mixed_groups"]
    rows = []
    for split, windows in snapshot["cohorts"].items():
        for window, cohort in windows.items():
            for family, family_data in cohort["families"].items():
                m = family_data["metrics"]
                rows.append([split, window, family, m["episodes"]["value"], m["completion"]["value"],
                             m["completion"]["denominator"], m["safe_completion"]["value"],
                             m["safe_completion"]["denominator"], m["unauthorized_effect"]["value"],
                             m["unauthorized_effect"]["denominator"], m["unknown_safe"]["value"],
                             m["infra_error"]["value"], m["mixed_groups"]["value"]])
    return columns, rows


def curriculum_rows(snapshot):
    columns = ["window", "family", "requested_probability", "draws", "realized_fraction",
               "evidence_groups", "evidence_episodes", "smoothed_pass_rate", "evidence_at", "policy_version"]
    rows = []
    for window, data in (snapshot.get("curriculum") or {}).items():
        latest = data["latest"]
        if latest is None:
            continue
        for family, probability in latest["probabilities"].items():
            stats = latest["evidence"][family]
            rows.append([window, family, probability, data["family_draws"].get(family, 0),
                         data["realized_fractions"].get(family, 0), stats["groups"], stats["episodes"],
                         stats["smoothed_pass_rate"], latest["evidence_at"], latest["policy_version"]])
    return columns, rows


def publish_snapshot(run, snapshot, directory):
    """Persist first, then upload. Caller decides retry/backoff outside training steps.

    A repeated upload can add a W&B history row, but snapshot IDs/watermarks are
    idempotent accounting identities. Never sum snapshot counters across rows.
    """
    require(run.id == publication_run_id(snapshot), "W&B run id must match publication run")
    if snapshot.get("publication"):
        require(all(run.config.get(k) == v for k, v in publication_config(snapshot).items()),
                "W&B publication lineage mismatch")
    require(run.config.get("synthetic") is snapshot["synthetic"], "W&B synthetic classification mismatch")
    directory = Path(directory).resolve()
    path = directory / f"snapshot-{snapshot['snapshot_id']}.json"
    write_snapshot(snapshot, path)
    import wandb
    columns, rows = family_rows(snapshot)
    values = scalar_metrics(snapshot)
    run.save(str(path), base_path=str(directory), policy="now")
    extras = {}
    if snapshot.get("curriculum") is not None:
        cc, cr = curriculum_rows(snapshot)
        extras["monitoring/curriculum"] = wandb.Table(columns=cc, data=cr)
    run.log({**values, **extras, "monitoring/families": wandb.Table(columns=columns, data=rows),
             "monitoring/snapshot_id": snapshot["snapshot_id"]})
    # Explicit missing list prevents stale summary scalars from being interpreted as current.
    run.summary.update({"monitoring/snapshot_id": snapshot["snapshot_id"],
                        "monitoring/snapshot_path": path.name,
                        "monitoring/schema_version": SCHEMA_VERSION,
                        "monitoring/curriculum_available": snapshot.get("curriculum") is not None,
                        "monitoring/available_scalar_count": len(values),
                        "monitoring/available_scalar_sha256": hashlib.sha256(canonical(sorted(values)).encode()).hexdigest(),
                        "monitoring/missing_telemetry": [k for k, v in snapshot["telemetry"].items() if v is None],
                        "monitoring/inherited_telemetry": [k for k, v in snapshot["telemetry"].items() if v is not None and v.get("inherited")],
                        "monitoring/missing_producers": [k for k, v in snapshot["producer_last_seen"].items() if v is None]})
    return path


def load_snapshot(path):
    return verify_snapshot(json.loads(Path(path).read_text()))


def load_wandb_snapshot(run_path, *, api=None):
    """Read-only calls; API credentials themselves may have broader permissions."""
    require(len(run_path.split("/")) == 3 and all(run_path.split("/")), "Use entity/project/run_id")
    if api is None:
        import wandb
        api = wandb.Api(overrides={"base_url": "https://api.wandb.ai"}, timeout=30)
    api.flush()
    run = api.run(run_path)
    identity = run.summary.get("monitoring/snapshot_id")
    require(isinstance(identity, str) and len(identity) == 64 and all(c in "0123456789abcdef" for c in identity),
            "Run has no valid monitoring snapshot identity")
    filename = f"snapshot-{identity}.json"
    require(run.summary.get("monitoring/snapshot_path") == filename, "Snapshot file/identity mismatch")
    # Do not return old scalar summaries if the current immutable file is not uploaded yet.
    with tempfile.TemporaryDirectory(prefix="training-metrics-") as temp:
        with run.file(filename).download(root=temp, replace=True) as stream:
            snapshot = verify_snapshot(json.load(stream))
    require(snapshot["snapshot_id"] == identity and publication_run_id(snapshot) == run.id, "Remote snapshot identity mismatch")
    require(run.config.get("synthetic") is snapshot["synthetic"], "Remote synthetic classification mismatch")
    if snapshot.get("publication"):
        require(all(run.config.get(k) == v for k, v in publication_config(snapshot).items()),
                "Remote publication lineage mismatch")
    return snapshot, run


def agent_summary(snapshot, *, now=None, stale_after_s=120, split=None, window="recent", families=False):
    verify_snapshot(snapshot)
    now = time.time() if now is None else now
    require(stale_after_s > 0, "Freshness threshold must be positive")
    require(window in {"all", "recent"}, "Unknown window")
    require(split is None or split in snapshot["cohorts"], "Split not present in snapshot")
    def age(timestamp):
        return None if timestamp is None else max(0, now-timestamp)
    def freshness(timestamp):
        elapsed = age(timestamp)
        return {"age_s": elapsed, "status": "missing" if elapsed is None else
                "clock_ahead" if timestamp > now else "stale" if elapsed > stale_after_s else "recent"}
    headlines = {"episodes", "attempts", "completion", "safe_completion", "unauthorized_effect",
                 "infra_error", "infra_error_attempts", "unknown_safe", "mixed_groups", "policy_age",
                 "admitted", "discarded", "pending_admission", "mixed_admission"}
    cohorts = {}
    for name, windows in snapshot["cohorts"].items():
        if split is not None and name != split:
            continue
        selected = windows[window]
        cohorts[name] = {"window": window, "metrics": {k: v for k, v in selected["metrics"].items() if k in headlines},
                         "discard_reasons": selected["discard_reasons"]}
        if families:
            cohorts[name]["families"] = selected["families"]
    return {"schema_version": snapshot["schema_version"], "run_id": snapshot["run_id"],
            "synthetic": snapshot["synthetic"], "snapshot_id": snapshot["snapshot_id"],
            "publication_run_id": publication_run_id(snapshot), "publication": snapshot.get("publication"),
            "watermark": snapshot["watermark"], "snapshot_at": snapshot["snapshot_at"],
            "freshness": freshness(snapshot["last_occurred_at"]),
            "snapshot_age_s": age(snapshot["snapshot_at"]), "window_s": snapshot["window_s"],
            "producers": {p: freshness(t) for p, t in snapshot["producer_last_seen"].items()},
            "cohorts": cohorts,
            "curriculum": snapshot.get("curriculum"),
            "evaluations": [{k: v for k, v in r.items() if k != "cases"} for r in snapshot.get("evaluations", [])],
            "training_rows": None if snapshot.get("training_rows") is None else
                {k: v for k, v in snapshot["training_rows"].items() if k != "episodes"},
            "telemetry": {k: None if v is None else {**v, "freshness": freshness(v["occurred_at"])}
                          for k, v in snapshot["telemetry"].items()},
            "telemetry_unavailable": {k: {**v, "freshness": freshness(v["occurred_at"])}
                                      for k, v in snapshot.get("telemetry_unavailable", {}).items()},
            "unmatched_admissions": snapshot["unmatched_admissions"], "future_events": snapshot["future_events"],
            "tokenizer_revisions": snapshot["tokenizer_revisions"], "policy_versions": snapshot["policy_versions"],
            "provenance": snapshot["provenance"], "uncertainty_note": snapshot["uncertainty_note"]}


def credentials_from_project_env(project_root):
    """Read only known keys; never emit credentials or arbitrary dotenv variables."""
    from dotenv import dotenv_values
    values = dotenv_values(Path(project_root) / ".env", interpolate=False)
    for key in ("WANDB_API_KEY", "WANDB_ENTITY", "WANDB_PROJECT"):
        if values.get(key):
            os.environ.setdefault(key, values[key])


def catalog():
    return {"schema_version": SCHEMA_VERSION, "outcomes": METRICS, "telemetry": TELEMETRY,
            "curriculum": CURRICULUM, "training_rows": ROW_METRICS, "evaluations": EVALUATION}
