from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from browser_training.metric_catalog import METRICS, TELEMETRY
from browser_training.outcomes import Ledger, rate, safe, snapshot, verify_snapshot, write_snapshot


def episode(i=0, **changes):
    p = dict(episode_id=f"e{i}", group_id="g0", group_size=2, member=i, attempt=0,
             task_family="checkout", task_template="insurance", task_instance="t0", seed=42,
             split="rl_train", policy_version=4, status="completed", goal_completed=True,
             constraints_satisfied=True, unauthorized_effect=False, reward=1.0,
             harness_revision="h1", verifier_revision="v1", environment_revision="site1",
             tokenizer_revision="fixture-tokenizer-v1", generated_tokens=10, duration_s=2, steps=2)
    p.update(changes)
    return dict(id=f"finish-{p['episode_id']}", kind="episode", producer="browser", occurred_at=100, payload=p)


def admission(i=0, **changes):
    p = dict(episode_id=f"e{i}", decision="admitted", reason="accepted", trainer_policy_version=5)
    p.update(changes)
    return dict(id=f"decision-{p['episode_id']}", kind="admission", producer="orchestrator", occurred_at=110, payload=p)


@pytest.fixture
def ledger(tmp_path):
    return Ledger(tmp_path / "events.sqlite", run_id="test", synthetic=True, expected_producers=["browser", "trainer"])


def metrics(ledger, split="rl_train", window="all"):
    return snapshot(ledger, now=200)["cohorts"][split][window]["metrics"]


def test_verified_rates_and_training_admission_are_independent(ledger):
    ledger.append(episode())
    ledger.append(episode(1, goal_completed=False, reward=0))
    ledger.append(admission())
    ledger.append(admission(1, decision="discarded", reason="stale", trainer_policy_version=9))
    result = metrics(ledger)
    assert result["completion"]["value"] == 0.5
    assert result["safe_completion"]["value"] == 0.5
    assert result["admitted"]["value"] == result["discarded"]["value"] == 1
    assert result["mixed_groups"]["value"] == 1
    assert result["admitted_groups"]["value"] == 0
    assert result["policy_age"] == dict(value=3, maximum=5, samples=2)
    assert result["interventions"]["value"] is None
    assert snapshot(ledger, now=200)["cohorts"]["rl_train"]["all"]["discard_reasons"] == {"stale": 1}


def test_unknown_is_not_failure_and_known_violation_is_failure(ledger):
    ledger.append(episode(constraints_satisfied=None, unauthorized_effect=None, reward=None))
    ledger.append(episode(1, goal_completed=None, unauthorized_effect=True, reward=0))
    m = metrics(ledger)
    assert m["completion"]["denominator"] == 1
    assert m["completion"]["value"] == 1
    assert m["safe_completion"]["denominator"] == 1
    assert m["safe_completion"]["value"] == 0
    assert m["unauthorized_effect"]["denominator"] == 1
    assert m["unknown_safe"]["value"] == 0.5
    assert m["valid_groups"]["value"] == 0


def test_retry_costs_all_attempts_but_pass_rate_only_latest(ledger):
    old = episode(status="infra_error", goal_completed=None, constraints_satisfied=None, unauthorized_effect=None, reward=None)
    retry = episode(episode_id="retry", attempt=1)
    ledger.append(retry)  # Newer retry arrives first.
    ledger.append(old)
    ledger.append(episode(1, status="cancelled", goal_completed=None, constraints_satisfied=None, unauthorized_effect=None, reward=None))
    m = metrics(ledger)
    assert m["attempts"]["value"] == 3
    assert m["episodes"]["value"] == 2
    assert m["completion"]["value"] == 1
    assert m["completion"]["denominator"] == 1
    assert m["infra_error"]["value"] == 0
    assert m["cancelled"]["value"] == 0.5
    assert m["generated_tokens"]["value"] == 30


def test_deduplication_restart_backup_and_atomic_snapshot(ledger, tmp_path):
    event = episode()
    seq = ledger.append(event)
    resumed = Ledger(ledger.path, **{k: v for k, v in ledger.metadata.items() if k != "schema_version"})
    assert resumed.append(event) == seq
    assert len(resumed.records()) == 1
    changed = deepcopy(event)
    changed["payload"]["reward"] = 0
    with pytest.raises(ValueError, match="different content"):
        resumed.append(changed)
    backup = tmp_path / "backup.sqlite"
    resumed.backup(backup)
    restored = Ledger(backup, **{k: v for k, v in ledger.metadata.items() if k != "schema_version"})
    assert restored.records() == resumed.records()
    value = snapshot(restored, now=200)
    path = tmp_path / "snap.json"
    write_snapshot(value, path)
    assert verify_snapshot(json.loads(path.read_text())) == value
    value["watermark"] = 900
    with pytest.raises(ValueError, match="hash"):
        write_snapshot(value, path)
    assert json.loads(path.read_text())["watermark"] == 1


def test_concurrent_duplicate_writers_are_idempotent(ledger):
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert set(pool.map(ledger.append, [episode()] * 12)) == {1}
    assert len(ledger.records()) == 1


@pytest.mark.parametrize("change", [dict(seed=43), dict(policy_version=5), dict(task_instance="other"),
                                    dict(verifier_revision="v2"), dict(group_size=3)])
def test_group_identity_cannot_drift(ledger, change):
    ledger.append(episode())
    with pytest.raises(ValueError, match="mismatch"):
        ledger.append(episode(1, **change))
    assert len(ledger.records()) == 1


def test_admission_before_episode_joins_and_conflicts_fail_atomically(ledger):
    ledger.append(admission())
    assert snapshot(ledger, now=200)["unmatched_admissions"] == ["e0"]
    ledger.append(episode())
    assert snapshot(ledger, now=200)["unmatched_admissions"] == []
    conflict = admission(decision="discarded", reason="stale")
    conflict["id"] = "another"
    with pytest.raises(ValueError, match="final"):
        ledger.append(conflict)
    ledger.append(admission(1, trainer_policy_version=2))
    with pytest.raises(ValueError, match="Negative"):
        ledger.append(episode(1))


def test_recent_window_filters_event_time_not_arrival_and_keeps_splits_separate(ledger):
    old = episode()
    ledger.append(old)
    newer = episode(1)
    newer["occurred_at"] = 180
    ledger.append(newer)
    ledger.append(episode(episode_id="dev", group_id="dev", split="model_dev", group_size=1, goal_completed=False, reward=0))
    s = snapshot(ledger, now=200, window_s=50)
    assert s["cohorts"]["rl_train"]["all"]["metrics"]["completion"]["value"] == 1
    assert s["cohorts"]["model_dev"]["all"]["metrics"]["completion"]["value"] == 0
    assert s["cohorts"]["rl_train"]["recent"]["metrics"]["episodes"]["value"] == 1
    assert s["cohorts"]["rl_train"]["recent"]["metrics"]["valid_groups"]["value"] == 0
    assert s["producer_last_seen"]["trainer"] is None


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, True])
def test_invalid_token_counts_rejected(ledger, value):
    with pytest.raises(ValueError):
        ledger.append(episode(generated_tokens=value))


def test_catalog_every_metric_defined_and_missing_telemetry_not_zero(ledger):
    ledger.append(episode())
    s = snapshot(ledger, now=200)
    assert s["cohorts"]["rl_train"]["all"]["metrics"].keys() == METRICS.keys()
    assert s["telemetry"] == dict.fromkeys(TELEMETRY)
    assert rate([])["value"] is None
    assert rate([True]*10)["ci95_low"] > 0.7
    assert rate([False]*10)["ci95_high"] < 0.3


def test_telemetry_producer_bounds_and_out_of_order_samples(ledger):
    event = dict(id="t1", kind="telemetry", producer="trainer", occurred_at=120,
                 payload=dict(step=3, axis="optimizer_step", policy_version=4, checkpoint_id="c3",
                              context="synthetic fixture", values={"trainer/gpu_utilization_pct": 80}))
    ledger.append(event)
    earlier = deepcopy(event)
    earlier.update(id="t0", occurred_at=100)
    earlier["payload"]["values"]["trainer/gpu_utilization_pct"] = 50
    ledger.append(earlier)
    assert snapshot(ledger, now=200)["telemetry"]["trainer/gpu_utilization_pct"]["value"] == 80
    event["id"] = "bad"
    event["producer"] = "rollout"
    with pytest.raises(ValueError, match="Wrong producer"):
        ledger.append(event)
    event["producer"] = "trainer"
    event["payload"]["values"]["trainer/gpu_utilization_pct"] = 101
    with pytest.raises(ValueError, match="Above"):
        ledger.append(event)


def test_run_identity_and_synthetic_flag_cannot_change(ledger):
    with pytest.raises(ValueError, match="mismatch"):
        Ledger(ledger.path, run_id="test", synthetic=False)


def test_infrastructure_failure_cannot_claim_verified_success(ledger):
    with pytest.raises(ValueError, match="masquerade"):
        ledger.append(episode(status="infra_error"))


def test_incomplete_admission_is_rejected(ledger):
    ledger.append(episode(goal_completed=None, constraints_satisfied=None, unauthorized_effect=None, reward=None))
    with pytest.raises(ValueError, match="Cannot admit"):
        ledger.append(admission())


def test_process_exit_preserves_committed_record_and_rolls_back_partial_write(ledger):
    program = """
import json, os, sys
from browser_training.outcomes import Ledger
ledger = Ledger(sys.argv[1], run_id='test', synthetic=True, expected_producers=['browser', 'trainer'])
ledger.append(json.loads(sys.argv[2]))
db = ledger.connect()
db.execute('BEGIN IMMEDIATE')
db.execute("INSERT INTO events(id, recorded_at, body) VALUES ('uncommitted', 0, '{}')")
os._exit(17)
"""
    environment = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
    result = subprocess.run([sys.executable, "-c", program, str(ledger.path), json.dumps(episode())], env=environment)
    assert result.returncode == 17
    assert len(ledger.records()) == 1
    assert metrics(ledger)["episodes"]["value"] == 1
    assert ledger.append(episode()) == 1


def test_future_events_are_quarantined_until_their_timestamp(ledger):
    event = episode()
    event["occurred_at"] = 300
    ledger.append(event)
    value = snapshot(ledger, now=200)
    assert value["cohorts"] == {}
    assert value["future_events"] == 1
    assert snapshot(ledger, now=400)["future_events"] == 0


def test_general_rewards_count_mixed_groups_without_binary_labels(ledger):
    ledger.append(episode(reward=-0.5))
    ledger.append(episode(1, reward=0.2))
    m = metrics(ledger)
    assert m["mixed_groups"]["value"] == 1
    assert m["all_success_groups"]["value"] == m["all_failure_groups"]["value"] == 0


def test_completed_policy_samples_cannot_be_overwritten_by_retry(ledger):
    ledger.append(episode())
    with pytest.raises(ValueError, match="Cannot retry"):
        ledger.append(episode(episode_id="retry", attempt=1))
