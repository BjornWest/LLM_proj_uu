#!/usr/bin/env python3
"""Audit cached 27B NF4 shards and backprop through selected real projections.

CPU only, bounded layer allocations. Never loads or trains the full 27B model.
"""
import os
os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ.setdefault("OMP_NUM_THREADS", "2")

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import struct

MODEL = "greghavens/Qwen3.8-27B-bnb-4bit"
REVISION = "26157380225e427827263c34df23018a1e28dff5"


def audit(snapshot):
    config = json.loads((snapshot / "config.json").read_text())
    q = config["quantization_config"]
    assert q["quant_method"] == "bitsandbytes" and q["bnb_4bit_quant_type"] == "nf4"
    assert q["bnb_4bit_compute_dtype"] == "bfloat16" and q["bnb_4bit_use_double_quant"]
    weight_map = json.loads((snapshot / "model.safetensors.index.json").read_text())["weight_map"]
    headers, shards, byte_counts = {}, {}, Counter()
    for filename in sorted(set(weight_map.values())):
        path = snapshot / filename
        with path.open("rb") as stream:
            size = struct.unpack("<Q", stream.read(8))[0]
            assert size < 16 * 1024**2, "Unexpected safetensors header size"
            header = json.loads(stream.read(size))
        end = 0
        for name, value in header.items():
            if name == "__metadata__":
                continue
            assert name not in headers and weight_map.get(name) == filename, name
            headers[name] = value
            start, stop = value["data_offsets"]
            byte_counts[value["dtype"]] += stop - start
            end = max(end, stop)
        assert path.stat().st_size == 8 + size + end, filename
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        # Standard Hub LFS blobs are addressed by their SHA256 content hash.
        blob = path.resolve().name
        if len(blob) == 64:
            assert digest == blob, f"Corrupt cached shard: {filename}"
        shards[filename] = {"bytes": path.stat().st_size, "sha256": digest}
    assert set(headers) == set(weight_map)
    quantized = [n.removesuffix(".quant_state.bitsandbytes__nf4") for n in headers
                 if n.endswith(".quant_state.bitsandbytes__nf4")]
    assert quantized
    assert not any(any(part in n.split('.') for part in ("visual", "mtp", "lm_head")) for n in quantized)
    assert all(headers[n]["dtype"] == "U8" for n in quantized)
    return weight_map, dict(config=q, shards=shards, tensor_count=len(headers),
        tensor_bytes_by_dtype=dict(byte_counts), quantized_linears=len(quantized),
        gate_a_b_quantized=any(".in_proj_a." in n for n in quantized),
        mtp_tensor_count=sum(n.startswith("mtp.") or ".mtp." in n for n in headers))


def projection_probe(snapshot, weight_map, name):
    import torch
    import bitsandbytes as bnb
    from safetensors import safe_open
    from peft import LoraConfig, get_peft_model
    from browser_training.precision import enforce_bf16_lora, inspect_dtypes, make_optimizer, inspect_optimizer
    prefix = name + ".weight"
    keys = [k for k in weight_map if k == prefix or k.startswith(prefix + ".")]
    assert keys, name
    tensors = {}
    for shard in sorted({weight_map[k] for k in keys}):
        with safe_open(snapshot / shard, framework="pt", device="cpu") as file:
            for key in keys:
                if weight_map[key] == shard:
                    tensors[key] = file.get_tensor(key)
    weight = bnb.nn.Params4bit.from_prequantized(tensors.pop(prefix), tensors, device="cpu")
    out_features, in_features = weight.quant_state.shape

    class Projection(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.proj = bnb.nn.Linear4bit(in_features, out_features, bias=False,
                compute_dtype=torch.bfloat16, quant_type="nf4", compress_statistics=True)
            self.proj.weight = weight
            self.proj.quant_state = weight.quant_state

        def forward(self, x):
            return self.proj(x)

    torch.manual_seed(42)
    # Compare the base's backward with an explicit dequantized BF16 linear layer.
    # Finite gradients alone would not catch a missing/incorrect input gradient.
    base = Projection()
    x_quant = torch.randn(1, 4, in_features, dtype=torch.bfloat16, requires_grad=True)
    x_reference = x_quant.detach().clone().requires_grad_(True)
    reference_weight = bnb.functional.dequantize_4bit(weight, weight.quant_state).to(torch.bfloat16)
    actual = base(x_quant)
    expected = torch.nn.functional.linear(x_reference, reference_weight)
    upstream = torch.randn_like(actual)
    grad_actual = torch.autograd.grad((actual.float() * upstream.float()).sum(), x_quant)[0]
    grad_expected = torch.autograd.grad((expected.float() * upstream.float()).sum(), x_reference)[0]
    torch.testing.assert_close(actual, expected, rtol=0.01, atol=0.01)
    torch.testing.assert_close(grad_actual, grad_expected, rtol=0.01, atol=0.01)
    reference_check = dict(output_max_abs_error=(actual - expected).abs().max().item(),
        input_gradient_max_abs_error=(grad_actual - grad_expected).abs().max().item(),
        rtol=0.01, atol=0.01)
    del base, reference_weight, actual, expected, grad_actual, grad_expected, x_quant, x_reference
    model = get_peft_model(Projection(), LoraConfig(r=16, lora_alpha=32,
        lora_dropout=0, target_modules=["proj"]), autocast_adapter_dtype=False)
    enforce_bf16_lora(model)
    optimizer = make_optimizer(model, 1e-4)
    frozen = weight.detach().clone()
    x = torch.randn(1, 4, in_features, dtype=torch.bfloat16, requires_grad=True)
    losses = []
    for _ in range(2):
        optimizer.zero_grad(set_to_none=True)
        x.grad = None
        loss = model(x).float().square().mean()
        assert torch.isfinite(loss)
        loss.backward()
        inspect_dtypes(model, check_grads=True)
        assert x.grad is not None and torch.isfinite(x.grad).all() and x.grad.abs().sum() > 0
        assert all(p.grad.dtype == torch.bfloat16 for p in model.parameters() if p.requires_grad)
        optimizer.step()
        inspect_optimizer(optimizer)
        losses.append(loss.item())
    assert torch.equal(weight, frozen)
    assert all(p.grad.abs().sum() > 0 for p in model.parameters() if p.requires_grad)
    return dict(projection=name, shape=[out_features, in_features], losses=losses,
        input_gradients="finite_nonzero", adapter_gradients="BF16_finite_nonzero",
        base_unchanged=True, optimizer_moments="FP32", dequantized_reference=reference_check,
        scope="isolated projection, synthetic inputs and loss")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, default=Path("research/nf4-checkpoint-validation.json"))
    args = p.parse_args()
    from huggingface_hub import snapshot_download
    import torch
    torch.set_num_threads(2)
    snapshot = Path(snapshot_download(MODEL, revision=REVISION, local_files_only=True))
    weight_map, report = audit(snapshot)
    print("Shard audit complete", flush=True)
    report.update(model=MODEL, revision=REVISION, snapshot=str(snapshot), gpu_used=False,
        full_model_loaded=False, hybrid_attention_backward_tested=False,
        probe_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    names = ["model.language_model.layers.0.linear_attn.in_proj_qkv",
             "model.language_model.layers.0.linear_attn.in_proj_z",
             "model.language_model.layers.3.self_attn.q_proj",
             "model.language_model.layers.0.mlp.down_proj"]
    report["projections"] = []
    for name in names:
        result = projection_probe(snapshot, weight_map, name)
        report["projections"].append(result)
        print(json.dumps(result), flush=True)
    report["status"] = "PASS"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
