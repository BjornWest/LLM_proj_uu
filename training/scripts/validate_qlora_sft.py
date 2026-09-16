#!/usr/bin/env python3
"""Four bounded CPU SFT steps, including resume, through installed Axolotl.

Uses cached pretrained Qwen3-0.6B ONLY. No GPU, downloads, or hybrid qualification.
"""
import os
os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["AXOLOTL_DO_NOT_TRACK"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"
os.environ.setdefault("OMP_NUM_THREADS", "2")

import argparse
import gc
import hashlib
import importlib.metadata as metadata
import json
from pathlib import Path
import tempfile
import time


def hybrid_loader_probe(run):
    """Actual Axolotl prequantized hybrid loading; no attention execution."""
    import torch
    import yaml
    from transformers import AutoConfig, AutoTokenizer, BitsAndBytesConfig, Qwen3_5Config, Qwen3_5ForConditionalGeneration
    from axolotl.cli.config import load_cfg
    from axolotl.loaders.model import ModelLoader
    from browser_training.precision import inspect_dtypes, inspect_nf4
    from check_adapter_dtypes import check
    raw = AutoConfig.from_pretrained(".cache/qwen38-tokenizer", local_files_only=True).to_dict()
    raw["text_config"].update(vocab_size=64, hidden_size=64, intermediate_size=128,
        num_hidden_layers=2, num_attention_heads=4, num_key_value_heads=2, head_dim=16,
        layer_types=["linear_attention", "full_attention"], linear_key_head_dim=16,
        linear_value_head_dim=16, linear_num_key_heads=2, linear_num_value_heads=4,
        max_position_embeddings=128, bos_token_id=1, eos_token_id=2)
    raw["vision_config"].update(depth=1, hidden_size=32, intermediate_size=64, num_heads=4,
        out_hidden_size=64, num_position_embeddings=16)
    config = Qwen3_5Config.from_dict(raw)
    config._attn_implementation = "sdpa"
    base, quantized = run / "hybrid-bf16", run / "hybrid-nf4"
    Qwen3_5ForConditionalGeneration(config).to(torch.bfloat16).save_pretrained(base)
    q = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=True,
        llm_int8_skip_modules=["model.visual", "lm_head", "mtp"])
    model = Qwen3_5ForConditionalGeneration.from_pretrained(base, dtype=torch.bfloat16,
        quantization_config=q, device_map={"": "cpu"}, attn_implementation="sdpa")
    model.save_pretrained(quantized)
    del model
    tokenizer = AutoTokenizer.from_pretrained(".cache/qwen38-tokenizer", local_files_only=True)
    tokenizer.save_pretrained(quantized)
    cfg = yaml.safe_load(Path("configs/sft_qwen38_27b_nf4_qlora.yml").read_text())
    cfg.update(base_model=str(quantized), output_dir=str(run / "hybrid-loader"),
        use_cpu=True, tf32=False, device_map={"": "cpu"}, sequence_len=64)
    resolved = run / "hybrid-loader.yml"
    resolved.write_text(yaml.safe_dump(cfg, sort_keys=False))
    cfg = load_cfg(str(resolved))
    model, _ = ModelLoader(cfg, tokenizer).load()
    assert all(not p.requires_grad for n, p in model.named_parameters() if ".visual." in n)
    result = dict(status="PASS", nf4=inspect_nf4(model), dtypes=inspect_dtypes(model),
        scope="random tiny hybrid checkpoint through Axolotl ModelLoader; no forward/backward")
    adapter = run / "hybrid-loader/adapter"
    model.save_pretrained(adapter)
    result["adapter"] = check(adapter)
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, default=Path("research/qlora-sft-validation.json"))
    args = p.parse_args()
    import torch
    import yaml
    from huggingface_hub import snapshot_download
    from axolotl.cli.config import load_cfg
    from axolotl.common.datasets import load_datasets
    from axolotl.train import train
    from browser_training.dataset import convert_trajectory
    from browser_training.precision import inspect_dtypes, inspect_nf4, inspect_optimizer
    from check_adapter_dtypes import check

    torch.set_num_threads(2)
    started = time.monotonic()
    revision = "c1899de289a04d12100db370d81485cdf75e47ca"
    base = snapshot_download("Qwen/Qwen3-0.6B", revision=revision, local_files_only=True)
    root = Path("outputs")
    root.mkdir(exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix="qlora-cpu-", dir=root)).resolve()
    data = run / "data.jsonl"
    rows = []
    for i in range(4):
        rows.extend(convert_trajectory({"task": f"Click button {i}.", "success": True,
            "steps": [{"observation": f"Button [{i}]", "action": f"click('{i}')"}]}))
    data.write_text("".join(json.dumps(row) + "\n" for row in rows))
    cfg = yaml.safe_load(Path("configs/sft_smoke.yml").read_text())
    cfg.update(base_model=base, adapter="qlora", load_in_4bit=True,
        bnb_config_kwargs={"bnb_4bit_quant_storage": "uint8"},
        tf32=False, use_cpu=True, device_map={"": "cpu"}, sequence_len=128,
        max_steps=2, save_steps=1, output_dir=str(run),
        dataset_prepared_path=str(run / "prepared"), dataset_processes=1,
        lora_mlp_kernel=False, lora_qkv_kernel=False, lora_o_kernel=False,
        dataloader_num_workers=0, dataloader_pin_memory=False,
        chat_template_kwargs={"enable_thinking": False},
        use_wandb=False, use_mlflow=False, use_tensorboard=False)
    cfg["datasets"][0]["path"] = str(data)
    resolved = run / "resolved.yml"
    resolved.write_text(yaml.safe_dump(cfg, sort_keys=False))
    normalized = load_cfg(str(resolved))
    dataset = load_datasets(cfg=normalized)
    assert len(dataset.train_dataset) == len(rows)
    for example in dataset.train_dataset:
        assert any(label != -100 for label in example["labels"])
        assert any(label == -100 for label in example["labels"])
    model, tokenizer, trainer = train(normalized, dataset)
    assert trainer.state.global_step == 2
    report = dict(status="PASS", gpu_used=False, model="Qwen/Qwen3-0.6B", revision=revision,
        hybrid_27b_qualified=False, run_dir=str(run), scope="actual Axolotl dataset/model/trainer/save/resume; CPU NF4",
        packages={n: metadata.version(n) for n in ("axolotl", "torch", "transformers", "peft", "bitsandbytes")},
        probe_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        dtypes=inspect_dtypes(model), nf4=inspect_nf4(model),
        fp32_moment_tensors=inspect_optimizer(trainer.optimizer), initial_history=trainer.state.log_history,
        supervised_examples=len(rows), initial_checkpoint=check(run / "checkpoint-2"))
    for filename in ("trainer_state.json", "optimizer.pt", "scheduler.pt", "rng_state.pth"):
        assert (run / "checkpoint-2" / filename).is_file(), filename
    del trainer, model, tokenizer
    gc.collect()
    cfg.update(max_steps=3, resume_from_checkpoint=str(run / "checkpoint-2"))
    resolved = run / "resume.yml"
    resolved.write_text(yaml.safe_dump(cfg, sort_keys=False))
    normalized = load_cfg(str(resolved))
    model, tokenizer, trainer = train(normalized, dataset)
    assert trainer.state.global_step == 3
    inspect_dtypes(model)
    inspect_nf4(model)
    inspect_optimizer(trainer.optimizer)
    report.update(resume_step=trainer.state.global_step, final_checkpoint=check(run / "checkpoint-3"),
        final_history=trainer.state.log_history)
    # Strip adapters WITHOUT merging. Persist the original NF4 base to exercise
    # Axolotl's distinct prequantized-checkpoint branch, used by the 27B candidate.
    prequantized = run / "base-nf4"
    model.unload().save_pretrained(prequantized)
    tokenizer.save_pretrained(prequantized)
    del trainer, model, tokenizer
    gc.collect()
    cfg.update(base_model=str(prequantized), output_dir=str(run / "prequantized-run"),
        max_steps=1, resume_from_checkpoint=None)
    resolved = run / "prequantized.yml"
    resolved.write_text(yaml.safe_dump(cfg, sort_keys=False))
    normalized = load_cfg(str(resolved))
    model, tokenizer, trainer = train(normalized, dataset)
    assert trainer.state.global_step == 1
    report["prequantized_reload"] = dict(nf4=inspect_nf4(model), dtypes=inspect_dtypes(model),
        checkpoint=check(run / "prequantized-run/checkpoint-1"),
        history=trainer.state.log_history, fp32_moment_tensors=inspect_optimizer(trainer.optimizer))
    del trainer, model, tokenizer
    gc.collect()
    report["hybrid_axolotl_loader"] = hybrid_loader_probe(run)
    report["elapsed_seconds"] = time.monotonic() - started
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
