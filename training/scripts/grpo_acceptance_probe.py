#!/usr/bin/env python3
"""Portable real NF4/FP8 GRPO + monitoring acceptance; run once, then --resume.

Needs a private running vLLM server and a distinct trainer GPU. No browser task,
learning-effect claim, algorithm replacement, model download, or W&B network call.
"""
import argparse
from collections import Counter
import json
import multiprocessing
import os
from pathlib import Path
import subprocess
import sys
import time


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--snapshot", required=True)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--run-id", required=True)
    p.add_argument("--resume", type=Path)
    p.add_argument("--steps", type=int, default=3)
    p.add_argument("--server", default="http://127.0.0.1:8000")
    p.add_argument("--trainer-gpu", help="Physical nvidia-smi index or UUID for resource collection")
    p.add_argument("--rollout-gpu", help="Physical nvidia-smi index or UUID for resource collection")
    p.add_argument("--browser-frozen", type=Path, help="Opt into qualified P11/core-tools-v3 browser episodes")
    p.add_argument("--browser-python", default="/opt/browser/.venv/bin/python")
    a = p.parse_args()
    a.output = a.output.resolve()
    a.output.mkdir(parents=True, exist_ok=False)
    if a.resume:
        a.resume = a.resume.resolve()
    import torch
    import yaml
    from datasets import Dataset
    from peft import LoraConfig, get_peft_model_state_dict
    from safetensors.torch import load_file
    from transformers import AutoTokenizer, TrainerCallback
    from browser_training.acceptance_harness import (ChoiceFactory, TwoTurnAdapter, choice_outcome,
        task_pool, tensor_digest, optimizer_digest, audit_policy_events)
    from browser_training.choice_probe import PROMPT
    from browser_training.qlora_compat import candidate_module
    from browser_training.precision import (enforce_bf16_lora, inspect_nf4,
        inspect_optimizer, make_optimizer, inspect_dtypes)
    from browser_training.runtime_metrics import start_metrics
    from browser_training.monitored_harness import MonitoredSessionFactory, MonitoredHarnessAdapter
    from browser_training.trl_monitoring import MonitoredHarnessWorker, check_sources
    from browser_training.row_hooks import RowTrainingMixin
    from browser_training.monitoring_callback import MonitoringCallback
    from browser_training.outcomes import Ledger
    from browser_training.provenance import capture
    from modal_grpo_probe import reject_packed_inputs

    torch.manual_seed(42)
    started = time.monotonic()
    _, candidate, source_audit = candidate_module()
    check_sources()
    tasks = task_pool()
    if a.browser_frozen:
        from browser_training.project_harness import ProjectFactory, ProjectAdapter, project_outcome, project_tasks
        tasks = project_tasks(json.loads((a.browser_frozen.parent / "frozen-sources.json").read_text())["sha256"])
    manager, monitor = start_metrics(multiprocessing.get_context("spawn"), a.output / "metrics",
        run_id=a.run_id, synthetic=True, tasks=tasks, resume=a.resume)
    before_snapshot = monitor.emit_snapshot()
    evidence = {}
    sidecars = []
    for role, device in (("trainer", a.trainer_gpu), ("rollout", a.rollout_gpu)):
        if device is not None:
            command = [sys.executable, "scripts/monitor_resources.py", "--monitoring-dir", str(a.output / "metrics"),
                       "--role", role, "--gpu", device, "--interval-s", "2"]
            if role == "trainer":
                command += ["--pid", str(os.getpid())]
            sidecars.append(subprocess.Popen(command))

    class Trainer(RowTrainingMixin, candidate.AsyncGRPOTrainer):
        def _load_optimizer_and_scheduler(self, checkpoint):
            super()._load_optimizer_and_scheduler(checkpoint)
            if checkpoint:
                saved = torch.load(Path(checkpoint) / "optimizer.pt", map_location="cpu", weights_only=True)
                actual = optimizer_digest(self.optimizer.state_dict())
                assert actual == optimizer_digest(saved), "Optimizer moments/counters did not restore exactly"
                evidence["restored_optimizer_sha256"] = actual

    class Witness(TrainerCallback):
        def on_train_begin(self, args, state, control, **kwargs):
            evidence["begin_global_step"] = state.global_step
            evidence["begin_adapter_sha256"] = tensor_digest(get_peft_model_state_dict(trainer.model))
            inspect_dtypes(trainer.model)
            if a.resume:
                saved = load_file(str(a.resume / "adapter_model.safetensors"))
                assert evidence["begin_adapter_sha256"] == tensor_digest(saved), "Adapter restore mismatch"
                assert state.global_step == json.loads((a.resume / "trainer_state.json").read_text())["global_step"]
                evidence["restored_scheduler"] = trainer.lr_scheduler.state_dict()
                expected = torch.load(a.resume / "scheduler.pt", map_location="cpu", weights_only=True)
                assert evidence["restored_scheduler"] == expected

    trainer = None
    try:
        tokenizer = AutoTokenizer.from_pretrained(a.snapshot, local_files_only=True)
        data = Dataset.from_list([{"prompt": PROMPT} for _ in range(128)])
        factory, adapter, extractor = ChoiceFactory(), TwoTurnAdapter(), choice_outcome
        max_tokens, max_turns = 8, 2
        if a.browser_frozen:
            factory = ProjectFactory(a.browser_frozen, a.browser_python, a.output / "browser",
                                     Path(__file__).resolve().parent / "project_browser_worker.py")
            adapter, extractor = ProjectAdapter(a.snapshot), project_outcome
            max_tokens, max_turns = 512, 4
        worker = MonitoredHarnessWorker(
            harness_session_factory=MonitoredSessionFactory(factory, monitor, group_size=4, extractor=extractor),
            harness_adapter=MonitoredHarnessAdapter(adapter),
            model_name="Qwen/Qwen3.8-27B-FP8", lora_name="trl-policy", dataset=data,
            reward_funcs=[], processing_class=tokenizer, num_generations=4,
            max_inflight_tasks=4, queue_maxsize=4, child_ready_timeout=60, max_tokens=max_tokens,
            request_timeout=60, max_tool_calling_iterations=max_turns, vllm_server_url=a.server,
            temperature=1.0, top_p=1.0, top_k=0,
            chat_template_kwargs={"enable_thinking": False, "preserve_thinking": True})
        if a.browser_frozen:
            worker.enable_shutdown_drain(monitor)
        config = candidate.AsyncGRPOConfig(output_dir=str(a.output), max_steps=a.steps,
            bf16=True, dtype="bfloat16", report_to="none", seed=42,
            per_device_train_batch_size=1, gradient_accumulation_steps=4, token_budget=0,
            num_generations=4, max_inflight_tasks=4, queue_maxsize=4, max_staleness=2,
            weight_sync_steps=1, learning_rate=1e-4, lr_scheduler_type="constant",
            gradient_checkpointing=True, gradient_checkpointing_kwargs={"use_reentrant": False},
            model_init_kwargs={"attn_implementation": "sdpa", "local_files_only": True},
            vllm_server_base_url=a.server, max_completion_length=max_tokens, max_tool_calling_iterations=max_turns,
            temperature=1.0, top_p=1.0, top_k=0, chat_template_kwargs={"enable_thinking": False},
            logging_steps=1, save_steps=a.steps, save_total_limit=None, log_completions=False)
        targets = yaml.safe_load(Path("configs/sft_qwen38_27b_nf4_qlora.yml").read_text())["lora_target_modules"]
        trainer = Trainer(model=a.snapshot, args=config, processing_class=tokenizer,
            peft_config=LoraConfig(r=16, lora_alpha=32, lora_dropout=0, target_modules=targets, task_type="CAUSAL_LM"),
            train_dataset=data, reward_funcs=[], rollout_worker=worker)
        assert trainer._lora_sync and trainer._lora_name == "trl-policy"
        evidence["dtypes"] = enforce_bf16_lora(trainer.model)
        evidence["nf4"] = inspect_nf4(trainer.model)
        trainer.model.register_forward_pre_hook(reject_packed_inputs, with_kwargs=True)
        trainer.optimizer = make_optimizer(trainer.model, config.learning_rate)
        trainer.enable_row_monitoring(monitor)
        callback = MonitoringCallback(monitor)
        callback.trainer = trainer
        trainer.add_callback(callback)
        trainer.add_callback(Witness())
        capture(a.output, dict(args=config.to_dict(), snapshot=a.snapshot, resume=str(a.resume), candidate=source_audit,
            scope="P11 browser integration; infrastructure only" if a.browser_frozen else
                  "synthetic two-turn native GRPO, real NF4/BF16 update and checkpoint restore; no browser benchmark"))
        trained = trainer.train(resume_from_checkpoint=str(a.resume) if a.resume else None)
        registry = worker.policy_registry.snapshot()
        if a.browser_frozen:
            evidence['shutdown_discarded_rows'] = worker.shutdown_discarded_rows
            (a.output / 'shutdown-native-metrics.json').write_text(json.dumps(worker.shutdown_metrics, default=str))
        worker.policy_registry.assert_healthy()
        assert not registry["groups"] and not registry["episodes"]
        checkpoint = a.output / f"checkpoint-{a.steps}"
        for file in ("adapter_model.safetensors", "optimizer.pt", "scheduler.pt", "trainer_state.json",
                     "rng_state.pth", "rollout_state.json", "monitoring/state.json", "monitoring/events.sqlite"):
            assert (checkpoint / file).is_file(), file
        evidence["optimizer_moment_tensors"] = inspect_optimizer(trainer.optimizer)
        final_digest = tensor_digest(get_peft_model_state_dict(trainer.model))
        evidence["adapter_changed"] = final_digest != evidence["begin_adapter_sha256"]
        if not a.browser_frozen:
            assert evidence["adapter_changed"], "No adapter update observed"
        assert final_digest == tensor_digest(load_file(str(checkpoint / "adapter_model.safetensors")))
        value = monitor.emit_snapshot()
        ledger = Ledger(a.output / "metrics/events.sqlite", run_id=a.run_id, synthetic=True,
                        expected_producers=("browser", "orchestrator", "trainer"),
                        publication=value.get("publication"))
        events = [r["event"] for r in ledger.records()]
        inherited = before_snapshot["watermark"]
        new_events = [r["event"] for r in ledger.records() if r["seq"] > inherited]
        applied = Counter(e["payload"]["optimizer_step"] for e in new_events
                          if e["kind"] == "row_use" and e["payload"]["stage"] == "applied")
        expected_steps = range(evidence["begin_global_step"] + 1, a.steps + 1)
        assert applied == Counter({step: 4 for step in expected_steps}), applied
        totals = value["training_rows"]["totals"]
        assert totals["applied"] == a.steps * 4 and totals["backward"] >= totals["applied"]
        assert any(e["kind"] == "episode" and e["payload"]["reward"] == 1 for e in events)
        if not a.browser_frozen:
            assert any(e["kind"] == "episode" and e["payload"]["reward"] == 0 for e in events)
        evidence["episode_reward_counts"] = dict(Counter(str(e["payload"]["reward"]) for e in events if e["kind"] == "episode"))
        policy = audit_policy_events([json.loads(line) for line in (a.output / "policy-events.jsonl").read_text().splitlines()])
        if a.resume:
            old_version = json.loads((a.resume / "rollout_state.json").read_text())["model_version"]
            assert min(policy["published"]) > old_version
            assert value["publication"]["parent_run_id"] == a.run_id
        report = dict(status="PASS", global_step=trainer.state.global_step, policy=policy,
            checkpoint=str(checkpoint), applied_rows_by_step=dict(applied), row_totals=totals,
            evidence=evidence, final_adapter_sha256=final_digest, snapshot_id=value["snapshot_id"],
            train_metrics=trained.metrics, elapsed_seconds=time.monotonic()-started,
            peak_allocated_gib=torch.cuda.max_memory_allocated()/2**30,
            limitations=("P11 harness-dev only; no learning-effect/generalization claim. Uniform-reward groups may have zero gradient."
                         if a.browser_frozen else "Synthetic task; no learning-effect/generalization claim, no browser, no crash mid-optimizer"))
        (a.output / "acceptance-report.json").write_text(json.dumps(report, indent=2, default=str))
        print(json.dumps(report, indent=2, default=str), flush=True)
        # No episodes remain and the worker has stopped. Clean this invocation's
        # resident policies before the next process restores against the same server.
        for version in registry["versions"]:
            trainer.vllm_client.unload_lora_adapter(f"{trainer._lora_name}-v{version}")
    finally:
        if trainer is not None:
            trainer.rollout_worker.stop()
        for process in sidecars:
            process.terminate()
            process.wait(timeout=10)
        manager.shutdown()


if __name__ == "__main__":
    main()
