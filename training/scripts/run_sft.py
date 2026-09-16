#!/usr/bin/env python3
import argparse
import os
from pathlib import Path
import shlex
import sys
import yaml
from browser_training.provenance import capture


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--config", default="configs/sft_qwen38_27b_bf16_lora.yml")
    p.add_argument("--steps", type=int)
    p.add_argument("--save-steps", type=int)
    p.add_argument("--sequence-len", type=int)
    p.add_argument("--grad-accum", type=int)
    p.add_argument("--rank", type=int, choices=[16, 32])
    p.add_argument("--output")
    p.add_argument("--dataset")
    p.add_argument("--resume")
    p.add_argument("--packing", action="store_true")
    p.add_argument("--enable-thinking", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    cfg = yaml.safe_load(Path(args.config).read_text())
    for key, value in {"max_steps": args.steps, "save_steps": args.save_steps, "sequence_len": args.sequence_len,
                       "gradient_accumulation_steps": args.grad_accum,
                       "lora_r": args.rank, "output_dir": args.output,
                       "resume_from_checkpoint": args.resume}.items():
        if value is not None:
            cfg[key] = value
    if args.rank:
        cfg["lora_alpha"] = 2 * args.rank
    if args.dataset:
        cfg["datasets"][0]["path"] = str(Path(args.dataset).resolve())
    if args.steps:
        cfg["save_steps"] = min(cfg["save_steps"], args.steps)
    if args.packing:
        cfg.update(sample_packing=True, attn_implementation="flash_attention_2")
    if args.enable_thinking:
        cfg.setdefault("chat_template_kwargs", {})["enable_thinking"] = True
    cfg["output_dir"] = str(Path(cfg["output_dir"]).resolve())
    resolved = Path(cfg["output_dir"]) / "resolved.yml"
    if args.dry_run:
        print(yaml.safe_dump(cfg, sort_keys=False))
        return
    if not Path(cfg["datasets"][0]["path"]).is_file():
        p.error("Dataset missing; run prepare_sft_dataset.py or make_smoke_data.py")
    if args.resume and not (Path(args.resume) / "trainer_state.json").is_file():
        p.error("Resume requires a Trainer checkpoint, not just an adapter export")
    if resolved.exists() and not args.resume:
        p.error("Output already contains a run. Use a new --output or --resume.")
    capture(cfg["output_dir"], cfg)
    resolved.write_text(yaml.safe_dump(cfg, sort_keys=False))
    cmd = [str(Path(sys.executable).parent / "axolotl"), "train", str(resolved)]
    print(shlex.join(cmd), flush=True)
    os.execv(cmd[0], cmd)


if __name__ == "__main__":
    main()
