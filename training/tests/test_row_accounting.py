import json

import pytest

from browser_training.runtime_metrics import RuntimeMetrics
from browser_training.monitoring_io import scalar_metrics, agent_summary
from test_runtime_metrics import make, begin, GOOD, checkpoint


def prepared(tmp_path):
    monitor = make(tmp_path)
    begin(monitor, "a", version=1)
    begin(monitor, "b", version=1)
    monitor.finish("a", GOOD)
    monitor.finish("b", GOOD)
    rows = {e: [dict(row_id=f"{e}:{i}", content_sha256="0"*64, loss_tokens=2)
                for i in range(n)] for e, n in (("a", 2), ("b", 1))}
    monitor.register_group_rows(0, 1, rows)
    return monitor


def identity(episode="a", row=0):
    return dict(episode_id=episode, row_id=f"{episode}:{row}")


def test_partial_episode_and_optimizer_use_are_distinct(tmp_path):
    monitor = prepared(tmp_path)
    monitor.decide_row(identity(), "admitted", "native_queue_gate", 2)
    monitor.decide_row(identity(row=1), "discarded", "staleness", 4)
    monitor.decide_row(identity("b"), "admitted", "native_queue_gate", 2)
    monitor.use_rows([identity("b")], "backward", 1)
    monitor.use_rows([identity("b")], "applied", 1)
    value = monitor.emit_snapshot()
    m = value["cohorts"]["rl_train"]["all"]["metrics"]
    assert (m["admitted"]["value"], m["mixed_admission"]["value"], m["pending_admission"]["value"]) == (1, 1, 0)
    assert value["training_rows"]["totals"] == dict(rows=3, admitted=2, discarded=1, pending=0,
                                                   backward=1, applied=1, skipped=0, abandoned=0)
    assert scalar_metrics(value)["training_rows/totals/applied"] == 1
    assert agent_summary(value)["training_rows"]["episode_states"] == {"mixed": 1, "admitted": 1}
    # Re-delivering the same fact is harmless; changing the decision is not.
    before = monitor.ledger.watermark()
    monitor.decide_row(identity(), "admitted", "native_queue_gate", 2)
    assert before == monitor.ledger.watermark()
    with pytest.raises(ValueError, match="different content"):
        monitor.decide_row(identity(), "discarded", "staleness", 4)


def test_backward_without_optimizer_does_not_count_as_applied(tmp_path):
    monitor = prepared(tmp_path)
    monitor.decide_row(identity(), "admitted", "native_queue_gate", 1)
    monitor.use_rows([identity()], "backward", 1)
    assert monitor.emit_snapshot()["training_rows"]["totals"]["applied"] == 0
    monitor.use_rows([identity()], "skipped", 1)
    assert monitor.emit_snapshot()["training_rows"]["totals"]["skipped"] == 1
    with pytest.raises(ValueError, match="Conflicting"):
        monitor.use_rows([identity()], "applied", 1)


def test_abandoned_prefetch_cannot_later_claim_backward(tmp_path):
    monitor = prepared(tmp_path)
    monitor.decide_row(identity(), "admitted", "gate", 1)
    monitor.use_rows([identity()], "abandoned", 0)
    with pytest.raises(ValueError, match="cannot follow"):
        monitor.use_rows([identity()], "backward", 1)


def test_incomplete_episode_stays_pending_and_zero_rows_is_explicit(tmp_path):
    monitor = prepared(tmp_path)
    monitor.decide_row(identity(), "admitted", "native_queue_gate", 2)
    assert monitor.emit_snapshot()["training_rows"]["episodes"]["a"]["admission"] == "pending"
    begin(monitor, "empty1", group=1)
    begin(monitor, "empty2", group=1)
    monitor.finish("empty1", GOOD)
    monitor.finish("empty2", GOOD)
    monitor.register_group_rows(1, 3, {})
    value = monitor.emit_snapshot()
    assert value["training_rows"]["episode_states"]["no_rows"] == 2


def test_resume_keeps_applied_rows_but_abandons_unsaved_gradients_and_queue(tmp_path):
    monitor = prepared(tmp_path)
    for i in range(2): monitor.decide_row(identity(row=i), "admitted", "native_queue_gate", 1)
    monitor.use_rows([identity()], "backward", 1)
    monitor.use_rows([identity()], "applied", 1)
    monitor.use_rows([identity(row=1)], "backward", 2)
    folder = checkpoint(tmp_path, monitor)
    monitor.use_rows([identity(row=1)], "applied", 2)  # Beyond saved state.
    restored = make(tmp_path, "restored", resume=folder)
    value = restored.emit_snapshot()["training_rows"]
    assert value["totals"]["applied"] == 1
    assert value["totals"]["abandoned"] == 1
    assert value["episodes"]["b"]["admission"] == "discarded"


def test_checkpoint_cursor_requires_every_row_of_every_group_member(tmp_path):
    from browser_training.row_hooks import RowTrainingMixin
    monitor = prepared(tmp_path)
    for row in (identity(), identity(row=1), identity("b")):
        monitor.decide_row(row, "admitted", "gate", 1)
        monitor.use_rows([row], "backward", 1)
    monitor.use_rows([identity()], "applied", 1)
    assert monitor.applied_native_groups() == []
    class NativeSaveStub:
        def _save_checkpoint(self, model, trial):
            return set(self._trained_groups)
    class Probe(RowTrainingMixin, NativeSaveStub): pass
    probe = Probe()
    probe.row_monitor = monitor
    collated = probe._trained_groups = {0, 1, 2}
    assert probe._save_checkpoint(None, None) == set()
    assert probe._trained_groups is collated
    monitor.use_rows([identity(row=1), identity("b")], "applied", 1)
    assert probe._save_checkpoint(None, None) == {0}
    assert probe._trained_groups is collated


@pytest.mark.parametrize("fault", ["unknown", "no_backward", "wrong_step", "legacy"])
def test_contradictory_lifecycle_rejected(tmp_path, fault):
    monitor = prepared(tmp_path)
    monitor.decide_row(identity(), "admitted", "native_queue_gate", 1)
    if fault == "unknown":
        with pytest.raises(ValueError, match="Unknown"):
            monitor.decide_row(identity(row=99), "admitted", "gate", 1)
    elif fault == "no_backward":
        with pytest.raises(ValueError, match="matching completed backward"):
            monitor.use_rows([identity()], "applied", 1)
    elif fault == "wrong_step":
        monitor.use_rows([identity()], "backward", 1)
        with pytest.raises(ValueError, match="matching completed backward"):
            monitor.use_rows([identity()], "applied", 2)
    else:
        with pytest.raises(ValueError, match="mix legacy"):
            monitor.ledger.append(dict(id="legacy", kind="admission", occurred_at=10, producer="trainer",
                payload=dict(episode_id="a", decision="admitted", reason="legacy", trainer_policy_version=1)))
