#!/usr/bin/env python3
"""Real AsyncGRPO train/rollout/sync on a trivial response-reward task.

Requires an already running, private FP8 vLLM server and a separate trainer GPU.
This is deliberately not a BrowserGym or generalization benchmark.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import time


def evaluate(server, model, prompt_ids, count, seed):
    import requests
    def sample(i):
        response = requests.post(server + "/v1/completions", timeout=60, json={
            "model": model, "prompt": prompt_ids, "max_tokens": 8, "temperature": 1.0,
            "top_p": 1.0, "top_k": 0, "n": 1, "seed": seed+i,
            "return_token_ids": True, "logprobs": 0})
        response.raise_for_status()
        return response.json()["choices"][0]
    with ThreadPoolExecutor(max_workers=4) as pool:
        return list(pool.map(sample, range(count)))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--snapshot", required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--server", default="http://127.0.0.1:8000")
    p.add_argument("--steps", type=int, default=16, choices=range(2, 33))
    a = p.parse_args()
    if a.output.exists():
        p.error("Choose a fresh output directory")
    a.output.mkdir(parents=True)
    import torch
    import yaml
    from datasets import Dataset
    from peft import LoraConfig
    from transformers import AutoTokenizer
    from browser_training.choice_probe import PROMPT, choice_reward, choose_target, summarize, compare, render_prompt_ids
    from browser_training.qlora_compat import candidate_module
    from browser_training.precision import enforce_bf16_lora, inspect_nf4, inspect_optimizer, make_optimizer
    from browser_training.callbacks import AuditCallback
    from browser_training.provenance import capture
    from modal_grpo_probe import reject_packed_inputs
    from check_adapter_dtypes import check
    torch.manual_seed(42)
    started = time.monotonic()
    _, candidate, audit = candidate_module()
    tokenizer = AutoTokenizer.from_pretrained(a.snapshot, local_files_only=True)
    prompt_ids = render_prompt_ids(tokenizer)
    targets = yaml.safe_load(Path("configs/sft_qwen38_27b_nf4_qlora.yml").read_text())["lora_target_modules"]
    args = candidate.AsyncGRPOConfig(output_dir=str(a.output), max_steps=a.steps,
        bf16=True, dtype="bfloat16", report_to="none", seed=42,
        per_device_train_batch_size=1, gradient_accumulation_steps=4, token_budget=0,
        num_generations=4, max_inflight_tasks=4, queue_maxsize=4, max_staleness=2,
        weight_sync_steps=1, learning_rate=1e-4, lr_scheduler_type="constant",
        gradient_checkpointing=True, gradient_checkpointing_kwargs={"use_reentrant": False},
        model_init_kwargs={"attn_implementation": "sdpa", "local_files_only": True},
        vllm_server_base_url=a.server, max_completion_length=8, max_tool_calling_iterations=0,
        temperature=1.0, top_p=1.0, top_k=0, chat_template_kwargs={"enable_thinking": False},
        logging_steps=1, save_steps=a.steps, save_total_limit=1, log_completions=False)
    # Initial target is replaced BEFORE worker.start() from a separate calibration sample.
    trainer = candidate.AsyncGRPOTrainer(model=a.snapshot, args=args, processing_class=tokenizer,
        peft_config=LoraConfig(r=16, lora_alpha=32, lora_dropout=0, target_modules=targets, task_type="CAUSAL_LM"),
        train_dataset=Dataset.from_list([{"prompt": PROMPT, "target": "A"} for _ in range(64)]),
        reward_funcs=choice_reward, callbacks=[AuditCallback()])
    if not trainer._lora_sync:
        raise RuntimeError("Refuse full-weight sync: server must enable runtime LoRA")
    audit["dtypes"] = enforce_bf16_lora(trainer.model)
    audit["nf4"] = inspect_nf4(trainer.model)
    trainer.model.register_forward_pre_hook(reject_packed_inputs, with_kwargs=True)
    name, parameter = next((n, v) for n, v in trainer.model.named_parameters() if v.requires_grad and "lora_B" in n)
    initial_tensor = parameter.detach().clone()
    trainer.optimizer = make_optimizer(trainer.model, args.learning_rate)
    initial = a.output / "adapter-initial"
    trainer.save_model(str(initial))
    # Evaluation uses native serving endpoints, never a replacement synchronization path.
    trainer.vllm_client.load_lora_adapter("probe-initial", str(initial.resolve()))
    try:
        calibration = evaluate(a.server, "probe-initial", prompt_ids, 32, 10000)
        (a.output / "calibration.json").write_text(json.dumps(calibration, indent=2))
        target = choose_target([c["text"] for c in calibration])
        baseline = evaluate(a.server, "probe-initial", prompt_ids, 64, 20000)
    finally:
        trainer.vllm_client.unload_lora_adapter("probe-initial")
    (a.output / "baseline.json").write_text(json.dumps(baseline, indent=2))
    dataset = Dataset.from_list([{"prompt": PROMPT, "target": target} for _ in range(64)])
    # Pinned worker takes a picklable Dataset at spawn; no generation/algorithm replacement.
    trainer.train_dataset = dataset
    trainer.rollout_worker._loop_kwargs["dataset"] = dataset
    capture(a.output, {"args": args.to_dict(), "snapshot": a.snapshot, "target": target,
                       "scope": "choice bandit: real AsyncGRPO train + FP8 vLLM + NF4/BF16 adapters",
                       "candidate": audit, "evaluation_seeds": [10000, 20000, 30000]})
    trained = trainer.train()
    trainer.rollout_worker.policy_registry.assert_healthy()
    final = a.output / "adapter-final"
    trainer.save_model(str(final))
    checkpoint = a.output / f"checkpoint-{a.steps}"
    assert (checkpoint / "optimizer.pt").is_file()
    assert (checkpoint / "rollout_state.json").is_file()
    audit["checkpoint"] = check(checkpoint)
    audit["optimizer_moment_tensors"] = inspect_optimizer(trainer.optimizer)
    delta = (parameter.detach().float() - initial_tensor.float()).abs().max().item()
    assert delta > 0, "No observed adapter update"
    assert trainer.model_version == a.steps + 1, "Missing initial or per-step native LoRA synchronization"
    # Use the FINAL NATIVE-SYNCED policy, not a manually reloaded trained adapter.
    final_model = f"{trainer._lora_name}-v{trainer.model_version}"
    after = evaluate(a.server, final_model, prompt_ids, 64, 30000)
    (a.output / "after.json").write_text(json.dumps(after, indent=2))
    before_stats = summarize([c["text"] for c in baseline], target)
    after_stats = summarize([c["text"] for c in after], target)
    effect = compare(before_stats, after_stats)
    events = [json.loads(line) for line in (a.output / "policy-events.jsonl").read_text().splitlines()]
    observed = sorted({event["version"] for event in events if event["event"] == "episode_start"})
    assert len(observed) >= 2, "Rollouts never used an updated native policy"
    report = {"status": "PASS" if effect["clear_improvement"] else "PIPELINE_PASS_LEARNING_INCONCLUSIVE",
              "target": target, "baseline": before_stats, "after": after_stats, **effect,
              "steps": trainer.state.global_step, "final_served_policy": final_model,
              "rollout_policy_versions": observed, "adapter_max_change": delta, "checked_tensor": name,
              "native_train_metrics": trained.metrics, "audit": audit,
              "elapsed_seconds": time.monotonic()-started,
              "peak_allocated_gib": torch.cuda.max_memory_allocated()/2**30,
              "limitations": "One-prompt learning smoke; no browser, tools, generalization, or numerical parity qualification"}
    (a.output / "learning-report.json").write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps(report, indent=2, default=str), flush=True)


if __name__ == "__main__":
    main()
