#!/usr/bin/env python3
"""Prepared, NOT GPU-qualified: one-rank Megatron GRPO-loss/adapter-export probe.

Run only in the pinned NeMo policy-worker environment on authorized Hopper.
Uses random reduced Qwen3.5-family hybrid modules, not pretrained Qwen3.8-27B.
No inference server, training controller, cloud allocation or model downloads.
"""
import argparse
import json
from pathlib import Path

from nemo_fp8_probe import build_hybrid, initialize, physical_storage
from probe_grpo_loss_boundary import load_loss, loss_context, selected_logprobs


def run(source, output):
    import torch
    from megatron.bridge import AutoBridge
    from megatron.bridge.peft.lora import LoRA
    from safetensors.torch import load_file, save_file
    from transformers import Qwen3_5TextConfig

    hardware = initialize()
    loss_fn = load_loss(source)
    model = build_hybrid()
    model.train()
    frozen_before = physical_storage(model)
    assert frozen_before and all(not row["requires_grad"] for row in frozen_before)
    dense_before = {n: p.detach().clone() for n, p in model.named_parameters()
                    if not p.requires_grad and not hasattr(p, "get_metadata")}
    adapters = {n: p for n, p in model.named_parameters() if p.requires_grad}
    assert adapters and all("adapter" in n and p.dtype == torch.bfloat16 for n, p in adapters.items())
    adapter_before = {n: p.detach().clone() for n, p in adapters.items()}

    def forward(input_ids, position_ids, labels, completion_mask, use_cache):
        assert input_ids.shape[0] == 1
        assert torch.equal(position_ids, torch.arange(input_ids.shape[1], device=input_ids.device)[None])
        logits = model(input_ids=input_ids, position_ids=position_ids, attention_mask=None)
        return selected_logprobs(logits, input_ids, temperature=1.0)

    tokens = torch.randint(0, 512, (1, 128), device="cuda")
    mask = torch.zeros_like(tokens)
    mask[:, 32:64] = 1
    mask[:, 96:] = 1
    batch = dict(input_ids=tokens, position_ids=torch.arange(128, device="cuda")[None],
                 attention_mask=torch.ones_like(tokens), completion_mask=mask,
                 old_log_probs=torch.zeros_like(tokens, dtype=torch.float),
                 advantages=torch.ones_like(tokens, dtype=torch.float),
                 global_n_tokens=mask.sum().float()[None],
                 global_n_forward_tokens=torch.tensor([128.], device="cuda"),
                 mean_seq_len=torch.tensor([128.], device="cuda"))
    with torch.no_grad():
        batch["old_log_probs"][:, 1:] = forward(tokens, batch["position_ids"], tokens, mask, False)["log_probs"]
    # Synthetic advantage; this tests the unchanged loss/backward boundary, not GRPO reward grouping.
    optimizer = torch.optim.SGD(adapters.values(), lr=0.1)
    loss = loss_fn(loss_context(), forward, batch)
    assert torch.isfinite(loss)
    loss.backward()
    assert all(p.grad is not None and p.grad.dtype == torch.bfloat16 and torch.isfinite(p.grad).all()
               for p in adapters.values())
    assert any(p.grad.float().norm() > 0 for p in adapters.values())
    assert all(p.grad is None for p in model.parameters() if not p.requires_grad)
    optimizer.step()
    changed = [n for n, p in adapters.items() if not torch.equal(p, adapter_before[n])]
    assert changed

    config = Qwen3_5TextConfig(vocab_size=512, hidden_size=256, intermediate_size=512,
        num_hidden_layers=4, num_attention_heads=2, num_key_value_heads=2, head_dim=128,
        linear_num_key_heads=2, linear_num_value_heads=8, linear_key_head_dim=128,
        linear_value_head_dim=128, linear_conv_kernel_dim=4,
        layer_types=["linear_attention"] * 3 + ["full_attention"],
        tie_word_embeddings=False, architectures=["Qwen3_5ForCausalLM"])
    bridge = AutoBridge.from_hf_config(config)
    exported = list(bridge.export_adapter_weights([model], cpu=True, show_progress=False))
    assert exported and all(w.weight.dtype == torch.bfloat16 for w in exported)
    assert all(w.param_name.endswith((".lora_A.weight", ".lora_B.weight")) for w in exported)
    assert any("in_proj_qkv" in w.param_name for w in exported)
    assert any("q_proj" in w.param_name for w in exported)
    assert any(w.weight.float().norm() > 0 for w in exported if ".lora_B." in w.param_name)
    peft_config = LoRA(target_modules=["linear_qkv", "linear_proj", "linear_fc1", "linear_fc2", "in_proj", "out_proj"],
                       dim=16, alpha=32, dropout=0.0, lora_dtype=torch.bfloat16)
    adapter_dir = output.parent / "adapter-v000001"
    if adapter_dir.exists():
        raise FileExistsError(f"Refusing to overwrite {adapter_dir}")
    bridge.save_hf_adapter([model], adapter_dir, peft_config=peft_config,
                          base_model_name_or_path="synthetic-qwen-hybrid-NOT-A-27B-ADAPTER", show_progress=False)
    path = adapter_dir / "adapter_model.safetensors"
    saved = load_file(str(path))
    original_saved_dtypes = sorted({str(t.dtype) for t in saved.values()})
    # The tested older Bridge saver promotes BF16 to FP32. Restore only adapter
    # serialization dtype, after verifying the source adapters themselves are BF16.
    saved = {n: t.bfloat16().contiguous() for n, t in saved.items()}
    save_file(saved, str(path))
    restored = load_file(str(path))
    assert all(t.dtype == torch.bfloat16 for t in restored.values())
    for w in exported:
        assert torch.equal(restored["base_model.model." + w.param_name], w.weight)
    assert all(torch.equal(p, dict(model.named_parameters())[n]) for n, p in dense_before.items())
    frozen_after = physical_storage(model)
    signature = lambda rows: [(r["name"], r["rowwise_sha256"], r["scale_sha256"]) for r in rows]
    assert signature(frozen_before) == signature(frozen_after)
    return {"status": "PASS", "hardware": hardware, "loss": loss.item(), "changed_adapters": changed,
            "exported_tensors": len(exported), "serialized_bytes": path.stat().st_size,
            "original_saved_dtypes": original_saved_dtypes, "saved_dtype": "torch.bfloat16",
            "adapter_dir": str(adapter_dir), "base_weights_exported": False,
            "scope": "One synthetic GRPO-loss update, physical FP8 tiny hybrid, BF16 adapter export",
            "limitations": ["Not pretrained Qwen3.8-27B", "Not a full TRL/NeMo training loop",
                            "No vLLM load, logprob comparison, distributed execution or resume",
                            "Fused GDN adapters include a/b; different from existing HF target set",
                            "Export layout and equality checked; inference numerical equivalence not checked"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="Hash-checked pinned TRL trainer source")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Refusing to overwrite probe evidence")
    # Validate provenance before CUDA initialization.
    source = args.source.read_bytes()
    load_loss(source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        report = run(source, args.output)
    except Exception:
        import traceback
        report = {"status": "FAIL", "error": traceback.format_exc()}
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2), flush=True)
    import torch
    if torch.distributed.is_initialized():
        torch.distributed.destroy_process_group()
    raise SystemExit(0 if report["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
