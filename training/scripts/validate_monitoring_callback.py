#!/usr/bin/env python3
"""Installed Transformers callback dispatch + monitoring checkpoint/restore on CPU.

No model, optimizer or trainer.train(): native rollout_state.json is a fixture.
The spawned browser-worker probe exercises the real TRL worker independently.
"""
import argparse
import json
import os
from pathlib import Path
from types import SimpleNamespace

os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ["HF_HUB_OFFLINE"] = "1"


def main():
    from transformers.trainer_callback import CallbackHandler, TrainerState, TrainerControl, DefaultFlowCallback
    from browser_training.monitoring_callback import MonitoringCallback
    from browser_training.runtime_metrics import RuntimeMetrics

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    monitor = RuntimeMetrics(args.output / "metrics", run_id=args.output.name, synthetic=True,
                             expected_producers=["trainer"])
    callback = MonitoringCallback(monitor)
    # Exercise the installed callback boundary without starting training.
    blocked = MonitoringCallback(SimpleNamespace(evaluation_enabled=lambda: True))
    try:
        blocked.on_train_begin(SimpleNamespace(save_total_limit=3), None, None)
    except ValueError as exc:
        assert "pruning" in str(exc)
    else:
        raise AssertionError("Pending evaluation checkpoint could be pruned")
    callback.trainer = SimpleNamespace(model_version=3)
    handler = CallbackHandler([DefaultFlowCallback(), callback], model=None, processing_class=None, optimizer=None, lr_scheduler=None)
    state = TrainerState(global_step=8, is_world_process_zero=True)
    control = TrainerControl()
    training_args = SimpleNamespace(output_dir=str(args.output))
    handler.on_log(training_args, state, control, logs={"loss": 0.2, "kl": 0.01, "perf/optimizer_s": 0.05})
    checkpoint = args.output / "checkpoint-8"
    checkpoint.mkdir()
    (checkpoint / "rollout_state.json").write_text(json.dumps(dict(prompt_index=2, model_version=3)))
    handler.on_save(training_args, state, control)
    restored = RuntimeMetrics(args.output / "restored", run_id=args.output.name, synthetic=True,
                              expected_producers=["trainer"], resume=checkpoint)
    value = restored.emit_snapshot()
    assert value["telemetry"]["rl/loss"]["value"] == 0.2
    assert value["telemetry"]["rl/behavior_kl"]["value"] == 0.01
    assert value["telemetry"]["trainer/update_s"]["value"] == 0.05
    assert value["telemetry"]["rl/loss"]["policy_version"] == 3
    assert value["telemetry"]["rl/loss"]["step"] == 8
    assert value["publication"]["parent_run_id"] == args.output.name
    assert value["telemetry"]["rl/loss"]["inherited"] is True
    assert value["producer_last_seen"]["trainer"] is None
    resumed_callback = MonitoringCallback(restored)
    resumed_callback.trainer = SimpleNamespace(model_version=4)
    resumed_handler = CallbackHandler([DefaultFlowCallback(), resumed_callback], model=None,
                                     processing_class=None, optimizer=None, lr_scheduler=None)
    resumed_handler.on_log(training_args, TrainerState(global_step=9, is_world_process_zero=True),
                           control, logs={"loss": 0.1})
    assert restored.emit_snapshot()["telemetry"]["rl/loss"]["inherited"] is False
    handler.on_train_end(training_args, state, control)
    report = dict(status="PASS", callback_dispatch="installed transformers CallbackHandler",
                  model_loaded=False, trainer_executed=False, gpu_used=False,
                  native_rollout_state="fixture; not a real trainer checkpoint",
                  checkpoint_sidecar_written=True, restored_values_match=True,
                  publication_lineage_verified=True, inherited_health_masked_until_new_callback=True,
                  evaluation_retention_guard_verified=True,
                  logged_optimizer_step=8, logged_actual_policy_version=3)
    (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
