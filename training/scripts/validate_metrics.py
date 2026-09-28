#!/usr/bin/env python3
"""CPU-only synthetic accounting/restart check; --online also verifies W&B readback.

No training, model downloads, browser runs, GPU allocation or dashboard edits.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from browser_training.metric_catalog import TELEMETRY
from browser_training.monitoring_io import (agent_summary, credentials_from_project_env, family_rows,
                                          load_wandb_snapshot, publish_snapshot, scalar_metrics)
from browser_training.outcomes import Ledger, canonical, snapshot, write_snapshot


def build_fixture(directory, run_id):
    metadata = dict(run_id=run_id, synthetic=True,
                    expected_producers=["browser", "trainer", "rollout", "orchestrator"])
    ledger = Ledger(directory / "events.sqlite", **metadata)
    origin = time.time() - 300

    def episode(group, member, *, attempt=0, status="completed", reward=1, split="rl_train", **updates):
        identity = f"{split}-{group}-{member}-{attempt}"
        p = dict(episode_id=identity, group_id=f"{split}-{group}", group_size=2, member=member, attempt=attempt,
                 task_family="checkout" if group % 2 == 0 else "preferences", task_template=f"template-{group}",
                 task_instance=f"instance-{group}", seed=group, split=split, policy_version=3,
                 status=status, goal_completed=bool(reward), constraints_satisfied=True,
                 unauthorized_effect=False, reward=reward, harness_revision="SYNTHETIC-h1",
                 verifier_revision="SYNTHETIC-v1", environment_revision="SYNTHETIC-site1",
                 tokenizer_revision="synthetic-counts-no-tokenizer-executed", generated_tokens=10,
                 duration_s=2, steps=2, interventions=0)
        if status != "completed":
            p.update(goal_completed=None, constraints_satisfied=None, unauthorized_effect=None, reward=None)
        p.update(updates)
        event = dict(id=f"finish-{identity}", kind="episode", occurred_at=origin+20+group*5+attempt,
                     producer="browser", payload=p)
        ledger.append(event)
        assert ledger.append(event)  # Same transport delivery; no double counting.
        return identity

    def decision(identity, *, discarded=False, reason="accepted"):
        ledger.append(dict(id=f"admit-{identity}", kind="admission", occurred_at=origin+100,
                           producer="orchestrator", payload=dict(episode_id=identity,
                           decision="discarded" if discarded else "admitted", reason=reason,
                           trainer_policy_version=8 if discarded else 4)))

    for group, rewards in enumerate(((1, 0), (1, 1), (0, 0))):
        for member, reward in enumerate(rewards):
            decision(episode(group, member, reward=reward))
    first = snapshot(ledger, now=origin+110)
    # Reopen and repeat a known admission to demonstrate persisted deduplication.
    ledger = Ledger(directory / "events.sqlite", **metadata)
    decision("rl_train-0-0-0")
    failed = episode(3, 0, status="infra_error")
    retry = episode(3, 0, attempt=1)
    decision(failed, discarded=True, reason="infrastructure")
    decision(retry, discarded=True, reason="stale")
    episode(3, 1, reward=None, goal_completed=None, constraints_satisfied=None, unauthorized_effect=None)
    episode(4, 0, status="cancelled")
    episode(5, 0, goal_completed=True, unauthorized_effect=True, reward=0)
    for split in ("model_dev", "generic_eval"):
        episode(0, 0, split=split)
        episode(0, 1, split=split, reward=0)
    for producer in ("trainer", "rollout", "browser", "orchestrator"):
        values = {key: 0.5 if definition["maximum"] is None else definition["maximum"] / 2
                  for key, definition in TELEMETRY.items() if definition["producer"] == producer}
        ledger.append(dict(id=f"telemetry-{producer}", kind="telemetry", producer=producer, occurred_at=origin+120,
                           payload=dict(step=1, axis="measurement", policy_version=8, checkpoint_id="SYNTHETIC-checkpoint-1",
                           context="Synthetic values only; no hardware/trainer/tokenizer measurement was performed.", values=values)))
    final = snapshot(ledger, now=origin+130)
    m = final["cohorts"]["rl_train"]["all"]["metrics"]
    assert m["attempts"]["value"] == 11
    assert m["episodes"]["value"] == 10
    assert m["completion"]["value"] == 5/8
    assert m["safe_completion"]["value"] == 4/8
    assert m["mixed_groups"]["value"] == 1/3
    assert m["valid_groups"]["value"] == 3
    assert m["admitted"]["value"] == 6
    assert m["discarded"]["value"] == 2
    assert m["infra_error_attempts"]["value"] == 1
    assert all(v is not None for v in final["telemetry"].values())
    write_snapshot(first, directory / "first.json")
    write_snapshot(final, directory / "snapshot.json")
    ledger.backup(directory / "backup.sqlite")
    restored = Ledger(directory / "backup.sqlite", **metadata)
    assert snapshot(restored, now=origin+130) == final
    return first, final


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--online", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/metrics-check")
    args = parser.parse_args()
    run_id = "metrics-" + uuid.uuid4().hex[:12]
    directory = args.output.resolve() / run_id
    directory.mkdir(parents=True, exist_ok=False)
    first, final = build_fixture(directory, run_id)
    summary = agent_summary(final)
    (directory / "agent-summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    report = dict(status="LOCAL_PASS", synthetic=True, training_performed=False, run_id=run_id,
                  snapshot_id=final["snapshot_id"], watermark=final["watermark"], scalar_keys=len(scalar_metrics(final)),
                  telemetry_keys=len(TELEMETRY), snapshot=str(directory / "snapshot.json"),
                  backup_restore_verified=True, remote_readback_verified=False, dashboard_created=False)
    report_path = directory / "report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    if args.online:
        credentials_from_project_env(ROOT.parent)
        if not os.environ.get("WANDB_API_KEY") or not os.environ.get("WANDB_ENTITY"):
            parser.error("Configure WANDB_API_KEY and WANDB_ENTITY in ignored .env; local checks passed")
        import wandb
        settings = wandb.Settings(base_url="https://api.wandb.ai", init_timeout=30, x_service_wait=30,
                                  x_disable_stats=True, disable_git=True, disable_code=True, console="off", silent=True)
        # No retries creating new runs; failures leave the local evidence intact.
        report["status"] = "REMOTE_PENDING"
        report_path.write_text(json.dumps(report, indent=2) + "\n")
        with wandb.init(entity=os.environ["WANDB_ENTITY"], project=os.environ.get("WANDB_PROJECT", "browser-training"),
                        id=run_id, name="Metric accounting — SYNTHETIC, NO TRAINING", job_type="metrics-validation",
                        tags=["synthetic", "exclude-from-model-results"], mode="online", dir=str(directory),
                        save_code=False, settings=settings,
                        config=dict(synthetic=True, training_performed=False, metric_schema=1)) as run:
            report["url"] = run.url
            report_path.write_text(json.dumps(report, indent=2) + "\n")
            publish_snapshot(run, first, directory)
            publish_snapshot(run, final, directory)
            run_path = f"{run.entity}/{run.project}/{run.id}"
        remote_snapshot, remote = load_wandb_snapshot(run_path)
        assert remote_snapshot == final
        for key, value in scalar_metrics(final).items():
            actual = remote.summary[key]
            assert abs(actual-value) <= 1e-9 * max(1, abs(value)), (key, actual, value)
        assert remote.summary["monitoring/available_scalar_count"] == len(scalar_metrics(final))
        assert remote.summary["monitoring/available_scalar_sha256"] == hashlib.sha256(canonical(sorted(scalar_metrics(final))).encode()).hexdigest()
        key = "outcomes/rl_train/all/completion/value"
        values = [r[key] for r in remote.scan_history(keys=[key], use_cache=False)]
        assert values == [0.5, 0.625], values
        table_path = remote.summary["monitoring/families"]["path"]
        with remote.file(table_path).download(root=str(directory / "readback")) as stream:
            table = json.load(stream)
        columns, rows = family_rows(final)
        assert table["columns"] == columns and table["data"] == rows
        report.update(status="PASS", remote_readback_verified=True, history_verified=True,
                      table_verified=True, history_points=len(values), wandb_version=wandb.__version__)
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
