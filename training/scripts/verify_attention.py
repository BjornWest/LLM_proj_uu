#!/usr/bin/env python3
"""Seconds-long GPU check, no model download: BF16 GQA varlen forward/backward."""
import argparse
import importlib.metadata
import json
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--backend", choices=["flash_attention_2", "kernels-community/flash-attn3"],
                   default="flash_attention_2")
    p.add_argument("--output", default="reports/attention.json")
    args = p.parse_args()
    import torch
    from torch.nn import functional as F
    if not torch.cuda.is_available():
        p.error("CUDA GPU required; this test does not use the local GTX 1070")
    capability = torch.cuda.get_device_capability()
    if capability[0] < 8:
        p.error("BF16 attention requires Ampere or newer")
    if args.backend == "flash_attention_2":
        from flash_attn import flash_attn_varlen_func
    else:
        if capability[0] >= 10:
            p.error("Audited FA3 artifact dispatches Blackwell into Hopper kernels; select FA2")
        from kernels import get_kernel
        flash_attn_varlen_func = get_kernel("kernels-community/flash-attn3").flash_attn_varlen_func
    torch.manual_seed(42)
    # Exact dense-attention head dimensions of the target: 24 Q, 4 KV, head dim 256.
    # Two packed sequences prove boundaries as well as finite gradients.
    lengths = [17, 23]
    q, k, v = [torch.randn(sum(lengths), heads, 256, device="cuda", dtype=torch.bfloat16,
                           requires_grad=True) for heads in (24, 4, 4)]
    cu = torch.tensor([0, 17, 40], device="cuda", dtype=torch.int32)
    out = flash_attn_varlen_func(q, k, v, cu, cu, max(lengths), max(lengths), causal=True)
    grad = torch.randn_like(out)
    actual_grads = torch.autograd.grad(out, (q, k, v), grad)
    refs = [x.detach().float().requires_grad_() for x in (q, k, v)]
    chunks = []
    offset = 0
    for length in lengths:
        a, b, c = [x[offset:offset + length].transpose(0, 1).unsqueeze(0) for x in refs]
        # FP32 math reference, explicitly separate sequences; no attention-kernel reuse.
        from torch.nn.attention import SDPBackend, sdpa_kernel
        with sdpa_kernel(SDPBackend.MATH):
            chunks.append(F.scaled_dot_product_attention(a, b, c, is_causal=True,
                                                         enable_gqa=True).squeeze(0).transpose(0, 1))
        offset += length
    ref = torch.cat(chunks)
    ref_grads = torch.autograd.grad(ref, refs, grad.float())
    comparisons = [(out, ref), *zip(actual_grads, ref_grads)]
    errors = []
    for actual, expected in comparisons:
        assert torch.isfinite(actual).all()
        torch.testing.assert_close(actual.float(), expected, atol=0.06, rtol=0.06)
        errors.append(float((actual.float() - expected).abs().max()))
    changed_v = v.detach().clone()
    changed_v[lengths[0]:] += 10
    altered = flash_attn_varlen_func(q.detach(), k.detach(), changed_v, cu, cu, 23, 23, causal=True)
    torch.testing.assert_close(out[:17], altered[:17], atol=0, rtol=0)
    torch.cuda.synchronize()
    report = {"status": "PASS", "gpu": torch.cuda.get_device_name(), "capability": capability,
        "backend": args.backend, "torch": torch.__version__, "cuda": torch.version.cuda,
        "flash_attn": importlib.metadata.version("flash-attn") if args.backend == "flash_attention_2" else None,
        "dtype": "bfloat16", "q_heads": 24, "kv_heads": 4, "head_dim": 256,
        "lengths": lengths, "max_abs_errors_output_dq_dk_dv": errors,
        "packed_sequences_isolated": True, "model_backward_tested": False}
    dest = Path(args.output)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
