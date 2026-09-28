#!/usr/bin/env python3
"""CPU-only checks of pinned upstream merge/quantization math, not live refit.

Downloads three small official source files; requires only an existing PyTorch
environment. AST extraction avoids importing the distributed/GPU frameworks.
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.request import urlopen


def main():
    import torch
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    bridge = "https://raw.githubusercontent.com/NVIDIA-NeMo/Megatron-Bridge/151168f36372132c8fb8f926501f573019feb967/src/megatron/bridge/"
    nemo = "https://raw.githubusercontent.com/NVIDIA-NeMo/RL/19244a0949fb363326f71675223da75e09d14866/"
    sources = [(bridge + "peft/lora.py", "LoRAMerge"),
               (bridge + "models/conversion/peft_bridge.py", "_merge_single_adapter_weight"),
               (nemo + "nemo_rl/models/generation/vllm/quantization/fp8.py", "cast_tensor_to_fp8_blockwise")]
    namespace = {"torch": torch, "global_fp8_config": SimpleNamespace(use_weight_pow2_scale=False)}
    provenance = []
    for url, name in sources:
        source = urlopen(url, timeout=30).read()
        node = next(n for n in ast.walk(ast.parse(source))
                    if isinstance(n, (ast.ClassDef, ast.FunctionDef)) and n.name == name)
        exec(compile(ast.Module(body=[node], type_ignores=[]), url, "exec"), namespace)
        provenance.append({"url": url, "sha256": hashlib.sha256(source).hexdigest(), "extracted": name})
    raw = torch.full((128, 128), 128.0).to(torch.float8_e4m3fn)
    scale = 1 / 4096
    a = torch.full((16, 128), 0.05, dtype=torch.bfloat16)
    b = torch.full((128, 16), 0.05, dtype=torch.bfloat16)
    base = raw.float() * scale
    expected = base + 2 * (b.float() @ a.float())
    received = namespace["_merge_single_adapter_weight"](None, raw, 32, 16, a, b).float() * scale
    # The pinned worker's ordinary export sends BF16. Test the actual NeMo
    # receiver quantizer with that wire dtype, including its fresh scales.
    quantized, new_scale = namespace["cast_tensor_to_fp8_blockwise"](expected.bfloat16().float(), [128, 128])
    recovered = quantized.float() * new_scale.reshape(1, 1)
    update = expected - base
    wrong_error = ((received - expected).norm() / update.norm()).item()
    proper_error = ((recovered - expected).norm() / update.norm()).item()
    assert wrong_error > 0.99, "Expected raw-number merge regression was not reproduced"
    assert torch.isfinite(recovered).all() and proper_error < 0.01
    report = {"status": "PASS", "scope": "source-extracted CPU arithmetic; no TE, transport, vLLM worker, or logprobs",
              "torch": torch.__version__, "sources": provenance,
              "expected_update": update[0, 0].item(), "raw_merge_received_update": (received - base)[0, 0].item(),
              "native_requantization_received_update": (recovered - base)[0, 0].item(),
              "raw_merge_update_relative_error": wrong_error,
              "native_requantization_update_relative_error": proper_error}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
