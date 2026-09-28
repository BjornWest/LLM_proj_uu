#!/usr/bin/env python3
"""Installed native TRL queue/collator + tiny CPU backward/optimizer boundary.

No model download or GRPO optimizer run. Synthetic rows exercise native staleness
and packing; a scalar torch parameter tests the accounting around actual backward
and SGD calls. A stub training_step delegates only this scalar backward.
"""
import argparse
import ast
from collections import defaultdict
import hashlib
import inspect
import json
import os
from pathlib import Path
import pickle
import queue
from types import SimpleNamespace

os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ["HF_HUB_OFFLINE"] = "1"


def main():
    import torch
    from transformers.trainer_callback import CallbackHandler, TrainerState, TrainerControl, DefaultFlowCallback
    from trl.experimental.async_grpo.async_grpo_trainer import RolloutQueueDataset, DataCollatorForRollout
    from trl.experimental.async_grpo.async_rollout_worker import RolloutSample
    from browser_training.runtime_metrics import RuntimeMetrics
    from browser_training.row_hooks import RowMetrics, ObservedQueue, ObservedCollator, RowTrainingMixin
    from browser_training.monitoring_callback import MonitoringCallback
    from browser_training.trl_monitoring import check_sources
    check_sources()
    from accelerate import Accelerator, DataLoaderConfiguration
    accelerator = Accelerator(cpu=True, dataloader_config=DataLoaderConfiguration(dispatch_batches=True))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    task = dict(task_id="mock", task_family="fixture", task_template="synthetic-rows", split="rl_train",
                harness_revision="synthetic", verifier_revision="synthetic", environment_revision="synthetic",
                tokenizer_revision="synthetic-token-ids:no-natural-text-tokenization")
    monitor = RuntimeMetrics(args.output / "metrics", run_id=args.output.name, synthetic=True, tasks=[task])
    good = dict(status="completed", goal_completed=True, constraints_satisfied=True, unauthorized_effect=False, reward=1.0)
    for group, version in ((0, 1), (1, 3)):
        for episode in (f"g{group}a", f"g{group}b"):
            monitor.begin(native_group_id=group, episode_id=episode, policy_version=version, group_size=2)
            monitor.finish(episode, good)
        monitor.register_group_rows(group, version, {f"g{group}a": [
            dict(row_id=f"g{group}a:{i}", content_sha256="0"*64, loss_tokens=2) for i in range(2)]})
    def sample(episode, index, version, group):
        s = RolloutSample(prompt=[], completion=[], input_ids=[1, 2, 3], completion_mask=[0, 1, 1],
            old_log_probs=[0, -0.2, -0.3], advantage=1.0, model_version=version, group_id=group,
            metrics=RowMetrics({"reward": 1.0}, dict(episode_id=episode, row_id=f"{episode}:{index}")))
        return pickle.loads(pickle.dumps(s))
    fifo = queue.Queue()
    for s in (sample("g0a", 0, 1, 0), sample("g0a", 1, 1, 0),
              sample("g1a", 0, 3, 1), sample("g1a", 1, 3, 1)):
        fifo.put(s)
    current = [3]
    observed = ObservedQueue(fifo, monitor, lambda: current[0], max_staleness=2)
    metrics = defaultdict(list)
    dataset = RolloutQueueDataset(observed, observed.version_for_decision, lambda _: None, 10,
                                  metrics, max_staleness=2, poll_interval_s=0.1)
    iterator = iter(dataset)
    first = next(iterator)
    current[0] = 4  # Second row of g0a is now stale; g1a remains fresh.
    prefetched = next(iterator)
    third = next(iterator)
    native_collator = DataCollatorForRollout(0, metrics=defaultdict(list))
    collator = ObservedCollator(native_collator)
    loader = accelerator.prepare(torch.utils.data.DataLoader(
        [[[row]] for row in (first, prefetched, third)], batch_size=1, collate_fn=collator))
    first_batch, prefetched_batch, third_batch = list(loader)
    assert [int(b["_monitoring_batch"].item()) for b in (first_batch, prefetched_batch, third_batch)] == [0, 1, 2]
    reference = native_collator([[[first]]])
    assert all(torch.equal(reference[k], first_batch[k]) for k in reference)
    assert metrics["sample/dropped_stale_total"] == [1.0]
    assert native_collator.groups_trained == {0, 1}  # Already includes unused prefetch.
    assert monitor.emit_snapshot()["training_rows"]["totals"]["applied"] == 0

    class BackwardStub:
        def training_step(self, model, inputs, num_items_in_batch=None):
            assert "_monitoring_batch" not in inputs
            loss = model.square().sum()
            loss.backward()
            return loss.detach()
    class Probe(RowTrainingMixin, BackwardStub):
        pass
    probe = Probe()
    probe.accelerator = SimpleNamespace(num_processes=1, optimizer_step_was_skipped=False)
    probe.state = SimpleNamespace(global_step=0)
    probe.enable_row_monitoring(monitor)
    probe._row_collator = collator
    weight = torch.nn.Parameter(torch.ones(1))
    optimizer = torch.optim.SGD([weight], lr=0.1)
    probe.training_step(weight, first_batch)
    before = weight.detach().clone()
    optimizer.step()
    optimizer.zero_grad()
    assert not torch.equal(weight, before)
    callback = MonitoringCallback(monitor)
    callback.trainer = probe
    handler = CallbackHandler([DefaultFlowCallback(), callback], None, None, None, None)
    callback_state = TrainerState(global_step=1, is_world_process_zero=True)
    # Callbacks that schedule work need the real TrainingArguments defaults.
    from transformers import TrainingArguments
    train_args = TrainingArguments(output_dir=str(args.output), use_cpu=True, report_to="none")
    handler.on_step_end(train_args, callback_state, TrainerControl())
    # A later backward whose optimizer is skipped must not count as applied.
    probe.state.global_step = 1
    probe.training_step(weight, third_batch)
    probe.accelerator.optimizer_step_was_skipped = True
    callback_state.global_step = 2
    handler.on_step_end(train_args, callback_state, TrainerControl())
    value = monitor.emit_snapshot()
    totals = value["training_rows"]["totals"]
    assert (totals["rows"], totals["admitted"], totals["discarded"], totals["backward"], totals["applied"], totals["skipped"]) == (4, 3, 1, 2, 1, 1)
    assert value["training_rows"]["episodes"]["g0a"]["admission"] == "mixed"
    assert len(collator.batches) == 1  # Prefetch never reached training_step.
    # Execute the audited native checkpoint-cursor method. Only its superclass
    # model/optimizer saver is stubbed: this does not create a model checkpoint.
    import itertools
    from trl.experimental.async_grpo.async_grpo_trainer import AsyncGRPOTrainer
    from trl.experimental.async_grpo.async_rollout_worker import AsyncRolloutWorker
    source = Path(inspect.getfile(AsyncGRPOTrainer)).read_text()
    cls = next(n for n in ast.parse(source).body if isinstance(n, ast.ClassDef) and n.name == "AsyncGRPOTrainer")
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "_save_checkpoint")
    class SaverStub:
        def _save_checkpoint(self, model, trial): pass
    node = ast.ClassDef(name="NativeCheckpoint", bases=[ast.Name(id="SaverStub", ctx=ast.Load())],
                       keywords=[], body=[method], decorator_list=[])
    namespace = dict(SaverStub=SaverStub, os=os, json=json, itertools=itertools,
                     PREFIX_CHECKPOINT_DIR="checkpoint", AsyncRolloutWorker=AsyncRolloutWorker)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), "<audited-native-cursor>", "exec"), namespace)
    checkpoint_probe = type("CheckpointProbe", (RowTrainingMixin, namespace["NativeCheckpoint"]), {})()
    checkpoint_probe.row_monitor = monitor
    checkpoint_probe._trained_groups = {0, 1}
    checkpoint_probe.accelerator = SimpleNamespace(is_main_process=True)
    checkpoint_probe.state = SimpleNamespace(global_step=2)
    checkpoint_probe.model_version = 4
    checkpoint_probe.rollout_worker = AsyncRolloutWorker.__new__(AsyncRolloutWorker)
    checkpoint_probe.rollout_worker._loop_kwargs = {"dataset_start_index": 10}
    checkpoint_probe._get_output_dir = lambda trial: str(args.output)
    checkpoint_probe._save_checkpoint(None, None)
    cursor = json.loads((args.output / "checkpoint-2/rollout_state.json").read_text())
    assert cursor["prompt_index"] == 10  # Unused prefetch cannot skip these prompts.
    assert checkpoint_probe._trained_groups == {0, 1}
    report = dict(status="PASS", totals=totals, native_queue_stale_rows=1,
        native_collator_counts_prefetched_group_as_trained=True, monitoring_applied_rows=1,
        native_collated_tensors_unchanged=True, pickle_identity_preserved=True,
        accelerate_dispatch_preserves_batch_identity=True,
        native_checkpoint_cursor_method_executed=True, model_checkpoint_saver="stubbed",
        checkpoint_cursor_excludes_unapplied_groups=True,
        unused_prefetch_counted_as_applied=False, scalar_cpu_sgd_changed_parameter=True,
        gpu_used=False, model_loaded=False, grpo_optimizer_executed=False,
        backward_boundary="scalar torch backward stub; native TRL queue/collator and installed callback dispatch",
        native_source_sha256=hashlib.sha256(Path(inspect.getfile(RolloutQueueDataset)).read_bytes()).hexdigest(),
        snapshot_id=value["snapshot_id"])
    (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
