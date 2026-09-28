from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from browser_training.monitoring_io import (agent_summary, family_rows, load_snapshot,
                                          load_wandb_snapshot, publish_snapshot, scalar_metrics)
from browser_training.outcomes import snapshot
from test_outcome_metrics import episode, ledger


class FakeRun:
    def __init__(self, value):
        self.id = value["run_id"]
        self.config = {"synthetic": value["synthetic"]}
        self.summary = {}
        self.paths = {}
        self.logged = []

    def save(self, path, **kwargs):
        self.paths[Path(path).name] = path

    def log(self, values):
        self.logged.append(values)
        self.summary.update(values)

    def file(self, path):
        return SimpleNamespace(download=lambda **kwargs: open(self.paths[path]))


@pytest.fixture
def fake_wandb(monkeypatch):
    monkeypatch.setitem(sys.modules, "wandb", SimpleNamespace(Table=lambda **kwargs: kwargs))


def test_publish_and_readback_identical_snapshot_and_values(ledger, tmp_path, fake_wandb):
    ledger.append(episode())
    value = snapshot(ledger, now=200)
    run = FakeRun(value)
    path = publish_snapshot(run, value, tmp_path)
    assert load_snapshot(path) == value
    assert run.summary["monitoring/missing_telemetry"]
    assert run.summary["monitoring/missing_producers"] == ["trainer"]
    for key, scalar in scalar_metrics(value).items():
        assert run.logged[0][key] == scalar
    api = SimpleNamespace(flush=lambda: None, run=lambda path: run)
    read, _ = load_wandb_snapshot("team/project/test", api=api)
    assert read == value
    # Exact denominators and nulls survive JSON and the W&B boundary.
    columns, rows = family_rows(value)
    assert "safe_n" in columns and len(rows) == 2


def test_failed_upload_leaves_complete_local_evidence(ledger, tmp_path, fake_wandb):
    ledger.append(episode())
    value = snapshot(ledger, now=200)
    run = FakeRun(value)
    def fail(*args, **kwargs):
        raise ConnectionError("simulated offline")
    run.save = fail
    with pytest.raises(ConnectionError):
        publish_snapshot(run, value, tmp_path)
    assert load_snapshot(tmp_path / f"snapshot-{value['snapshot_id']}.json") == value
    assert len(ledger.records()) == 1


def test_remote_reader_refuses_missing_or_mismatched_snapshot(ledger, tmp_path, fake_wandb):
    ledger.append(episode())
    value = snapshot(ledger, now=200)
    run = FakeRun(value)
    api = SimpleNamespace(flush=lambda: None, run=lambda path: run)
    with pytest.raises(ValueError, match="identity"):
        load_wandb_snapshot("team/project/test", api=api)
    publish_snapshot(run, value, tmp_path)
    run.summary["monitoring/snapshot_path"] = "../../secret"
    with pytest.raises(ValueError, match="mismatch"):
        load_wandb_snapshot("team/project/test", api=api)
    run.summary["monitoring/snapshot_path"] = f"snapshot-{value['snapshot_id']}.json"
    run.paths.clear()  # Summary has arrived, file has not. No fallback to older values.
    with pytest.raises(KeyError):
        load_wandb_snapshot("team/project/test", api=api)


def test_freshness_is_measured_at_read_time_and_missing_is_distinct(ledger):
    ledger.append(episode())
    value = snapshot(ledger, now=200)
    fresh = agent_summary(value, now=110)
    old = agent_summary(value, now=500)
    assert fresh["freshness"]["status"] == "recent"
    assert old["freshness"]["status"] == "stale"
    assert old["producers"]["trainer"]["status"] == "missing"
    assert "families" not in old["cohorts"]["rl_train"]
    assert "families" in agent_summary(value, now=500, families=True)["cohorts"]["rl_train"]
    with pytest.raises(ValueError, match="Split"):
        agent_summary(value, split="final_test")


def test_missing_scalars_are_absent_not_zeros(ledger):
    ledger.append(episode(goal_completed=None, constraints_satisfied=None, unauthorized_effect=None, reward=None))
    values = scalar_metrics(snapshot(ledger, now=200))
    assert "outcomes/rl_train/all/completion/value" not in values
    assert values["outcomes/rl_train/all/completion/denominator"] == 0
    assert not any(key.startswith("telemetry/") for key in values)


def test_synthetic_data_cannot_be_published_as_real(ledger, tmp_path, fake_wandb):
    ledger.append(episode())
    value = snapshot(ledger, now=200)
    run = FakeRun(value)
    run.config["synthetic"] = False
    with pytest.raises(ValueError, match="classification"):
        publish_snapshot(run, value, tmp_path)


def test_availability_flags_do_not_present_retained_summary_values_as_current(ledger):
    ledger.append(dict(id='resource-ok', kind='telemetry', producer='trainer', occurred_at=100,
                       payload=dict(step=0, axis='measurement', policy_version=None, checkpoint_id=None,
                                    context='physical GPU fixture', values={'trainer/vram_gib': 30})))
    assert scalar_metrics(snapshot(ledger, now=101))['telemetry_available/trainer/vram_gib'] == 1
    ledger.append(dict(id='resource-missing', kind='telemetry', producer='trainer', occurred_at=102,
                       payload=dict(step=1, axis='measurement', policy_version=None, checkpoint_id=None,
                                    context='physical GPU fixture', values={},
                                    unavailable={'trainer/vram_gib': 'device_query_failed'})))
    values = scalar_metrics(snapshot(ledger, now=103))
    assert values['telemetry_available/trainer/vram_gib'] == 0
    assert 'telemetry/trainer/vram_gib' not in values
