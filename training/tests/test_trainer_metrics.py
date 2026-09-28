import pytest

from browser_training.metric_catalog import TELEMETRY
from browser_training.trainer_metrics import COMMON, RL, SFT, trainer_event


def event(row, kind="rl"):
    return trainer_event({"step": 2, "wall_time": 100, **row}, kind=kind, source_id="sha256-fixture",
                         row_number=0, context="Synthetic test")


def test_kl_is_behavior_diagnostic_and_loss_kind_is_explicit():
    values = event(dict(loss=-0.05, kl=0.12, entropy=0.8))["payload"]["values"]
    assert values == {"rl/loss": -0.05, "rl/behavior_kl": 0.12, "rl/entropy": 0.8}
    assert event(dict(loss=0.5, eval_loss=0.6), kind="sft")["payload"]["values"] == {
        "sft/train_loss": 0.5, "sft/validation_loss": 0.6}


def test_timing_and_memory_not_conflated():
    e = event({"perf/step_s": 10, "perf/optimizer_s": 0.2, "perf/weight_sync_s": 2, "peak_vram_gib": 30})
    assert e["payload"]["values"] == {"trainer/step_s": 10, "trainer/update_s": 0.2,
                                      "trainer/adapter_sync_s": 2, "trainer/peak_allocated_gib": 30}
    assert e["payload"]["policy_version"] is None
    assert e["payload"]["checkpoint_id"] is None


def test_mapping_catalogued_and_null_missing_not_zero():
    assert set(COMMON.values()) | set(RL.values()) | set(SFT.values()) <= TELEMETRY.keys()
    assert event({"loss": None, "some_new_upstream_metric": 10}) is None
    with pytest.raises(ValueError, match="Nonfinite"):
        event({"loss": float("nan")})


def test_redelivery_same_identity():
    assert event({"loss": 0.5}) == event({"loss": 0.5})
