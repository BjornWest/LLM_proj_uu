#!/usr/bin/env python3
"""REMOTE probe: load through Axolotl itself, exercise two backward/optimizer steps."""
import argparse
import json
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--config", default="configs/sft_smoke.yml")
    args = p.parse_args()
    import torch
    from transformers import AutoTokenizer
    from axolotl.cli.config import load_cfg
    from axolotl.loaders.model import ModelLoader
    from browser_training.precision import inspect_dtypes, make_optimizer, inspect_optimizer
    if not torch.cuda.is_available():
        raise RuntimeError("This is a remote GPU probe; use pytest for local smoke tests")
    cfg = load_cfg(args.config)
    tokenizer = AutoTokenizer.from_pretrained(cfg.base_model, revision=cfg.revision_of_model)
    model, _ = ModelLoader(cfg, tokenizer).load()
    model.train()
    if cfg.gradient_checkpointing:
        model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
        model.enable_input_require_grads()
    optimizer = make_optimizer(model, 1e-4)
    encoded = tokenizer("Task: click button 1.\nAction: click('1')", return_tensors="pt").to("cuda")
    losses = []
    for _ in range(2):
        optimizer.zero_grad(set_to_none=True)
        loss = model(**encoded, labels=encoded["input_ids"]).loss
        if not torch.isfinite(loss):
            raise AssertionError("Nonfinite loss")
        loss.backward()
        report = inspect_dtypes(model, require_fp8="FP8" in cfg.base_model, check_grads=True)
        # Zero-initialized B makes A gradients zero on step one; step two tests propagation.
        optimizer.step()
        inspect_optimizer(optimizer)
        losses.append(loss.item())
    report.update(losses=losses, peak_vram_gib=torch.cuda.max_memory_allocated() / 2**30)
    print(json.dumps(report, indent=2))
    output = Path(cfg.output_dir) / "dtype-probe"
    model.save_pretrained(output)
    from check_adapter_dtypes import check
    print(check(output))


if __name__ == "__main__":
    main()
