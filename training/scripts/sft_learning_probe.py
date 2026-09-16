#!/usr/bin/env python3
"""Real Axolotl SFT learning + saved-adapter evaluation, or CPU dataset preflight."""
import argparse
import json
from pathlib import Path
import time


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--snapshot", required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--steps", type=int, choices=range(1, 33), default=32)
    p.add_argument("--prepare-only", action="store_true")
    a = p.parse_args()
    import yaml
    from transformers import AutoTokenizer
    from axolotl.cli.config import load_cfg
    from axolotl.common.datasets import load_datasets
    from browser_training.apple_probe import splits, validate_tokenized, evaluate
    from browser_training.provenance import capture

    output = a.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    data = splits()
    (output / "splits.json").write_text(json.dumps(data, indent=2))
    source = output / "train.jsonl"
    source.write_text("".join(json.dumps({"messages": r["messages"]}) + "\n" for r in data["train"]))
    cfg = yaml.safe_load(Path("configs/sft_qwen38_27b_nf4_qlora.yml").read_text())
    cfg.update(base_model=a.snapshot, revision_of_model=None, output_dir=str(output),
        plugins=["browser_training.apple_plugin.ApplePlugin"],
        dataset_prepared_path=str(output / "prepared"), sequence_len=128,
        max_steps=a.steps, save_steps=a.steps, gradient_accumulation_steps=2,
        lr_scheduler="constant", warmup_ratio=0.0,
        dataset_num_proc=1, dataset_processes=1, dataloader_num_workers=0,
        use_wandb=False, use_mlflow=False, use_tensorboard=False)
    if a.prepare_only:
        cfg.update(use_cpu=True, tf32=False, device_map={"": "cpu"})
    cfg["datasets"][0]["path"] = str(source)
    resolved = output / "resolved.yml"
    resolved.write_text(yaml.safe_dump(cfg, sort_keys=False))
    normalized = load_cfg(str(resolved))
    dataset = load_datasets(cfg=normalized)
    tokenizer = AutoTokenizer.from_pretrained(a.snapshot, local_files_only=True)
    validate_tokenized(dataset.train_dataset, tokenizer, data["train"])
    manifest = capture(output, {"resolved_config": cfg, "scope": "SFT apple learning probe"})
    preflight = {"status": "PASS", "examples": len(dataset.train_dataset),
        "lengths": sorted(set(len(row["input_ids"]) for row in dataset.train_dataset)),
        "assistant_payload_eos_and_generation_prefix_checked": True,
        "manifest": str(manifest)}
    (output / "dataset-report.json").write_text(json.dumps(preflight, indent=2))
    if a.prepare_only:
        print(json.dumps(preflight), flush=True)
        return

    import torch
    from axolotl.train import train
    from peft import get_peft_model_state_dict, set_peft_model_state_dict
    from peft.utils.save_and_load import load_peft_weights
    from browser_training.precision import inspect_dtypes, inspect_nf4, inspect_optimizer
    from check_adapter_dtypes import check
    torch.cuda.reset_peak_memory_stats()
    model, tokenizer, trainer = train(normalized, dataset)
    assert trainer.state.global_step == a.steps
    checkpoint = output / f"checkpoint-{a.steps}"
    audit = {"dtypes": inspect_dtypes(model), "nf4": inspect_nf4(model),
        "optimizer_moment_tensors": inspect_optimizer(trainer.optimizer), "checkpoint": check(checkpoint)}
    assert all(not p.requires_grad for n, p in model.named_parameters() if ".visual." in n)
    for name in ("trainer_state.json", "optimizer.pt", "scheduler.pt", "rng_state.pth"):
        assert (checkpoint / name).is_file(), name
    saved = load_peft_weights(str(checkpoint), device="cpu")
    assert max(v.float().abs().max().item() for k, v in saved.items() if "lora_B" in k) > 0
    # Erase in-memory adapters before reloading: post-training evaluation must
    # actually depend on the saved artifact. Frozen NF4 base stays in memory.
    with torch.no_grad():
        for n, parameter in model.named_parameters():
            if "lora_A" in n or "lora_B" in n:
                parameter.zero_()
    loaded = set_peft_model_state_dict(model, saved)
    assert not loaded.unexpected_keys, loaded.unexpected_keys
    actual = get_peft_model_state_dict(model)
    assert set(actual) == set(saved)
    assert all(torch.equal(actual[k].detach().cpu(), v) for k, v in saved.items())
    audit["reloaded_adapter_tensors_exact"] = len(saved)
    audit["after_reload_dtypes"] = inspect_dtypes(model)
    del saved, actual
    evaluations = {}
    for split in ("heldout", "train_eval"):
        before = json.loads((output / f"before-{split}.json").read_text())
        after = evaluate(model, tokenizer, data[split], output / f"after-{split}.json")
        evaluations[split] = {"before": before["summary"], "after": after["summary"]}
    before, after = (evaluations["heldout"][key]["exact_match"] for key in ("before", "after"))
    learned = after >= 0.75 and after - before >= 0.5
    report = {"status": "PASS" if learned else "PIPELINE_PASS_LEARNING_INCONCLUSIVE",
        "steps": a.steps, "evaluations": evaluations, "audit": audit,
        "clear_improvement": learned, "history": trainer.state.log_history,
        "elapsed_seconds": time.monotonic() - started,
        "max_logged_allocated_gib": max(r.get("memory/max_allocated (GiB)", 0) for r in trainer.state.log_history),
        "limitations": "One formatting rule; heldout combinations of familiar words; NF4 Transformers generation, no FP8 vLLM, browser, or cold base reload"}
    (output / "learning-report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
