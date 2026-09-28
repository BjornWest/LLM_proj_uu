#!/usr/bin/env python3
"""Small native Megatron/Bridge FP8 experiments; never downloads model weights."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback

PROGRESS = []


def initialize():
    import tempfile
    import torch
    from megatron.core import parallel_state
    from megatron.core.tensor_parallel.random import model_parallel_cuda_manual_seed
    assert torch.cuda.is_available(), "CUDA unavailable"
    assert torch.cuda.get_device_capability()[0] == 9, "This probe is qualified for Hopper"
    torch.cuda.set_device(0)
    torch.distributed.init_process_group("nccl", init_method="file://" + tempfile.mktemp(), rank=0, world_size=1)
    parallel_state.initialize_model_parallel(tensor_model_parallel_size=1, pipeline_model_parallel_size=1)
    model_parallel_cuda_manual_seed(1234)
    torch.manual_seed(1234)
    return {"gpu": torch.cuda.get_device_name(), "capability": torch.cuda.get_device_capability(),
            "torch": torch.__version__, "cuda": torch.version.cuda}


def physical_storage(model):
    """Logical TE tensor dtype alone is not evidence of FP8 residency."""
    import hashlib
    import torch
    rows = []
    for name, param in model.named_parameters():
        if not hasattr(param, "get_metadata"):
            continue
        metadata = param.get_metadata()
        rowwise = metadata.get("rowwise_data")
        if rowwise is None:
            continue
        tensors = {k: v for k, v in metadata.items() if isinstance(v, torch.Tensor)}
        row = {"name": name, "class": type(param).__name__, "logical_dtype": str(param.dtype),
               "requires_grad": param.requires_grad, "numel": param.numel(),
               "storage": {k: {"shape": list(v.shape), "dtype": str(v.dtype),
                                "bytes": v.numel() * v.element_size(),
                                "storage_ptr": v.untyped_storage().data_ptr(),
                                "allocation_bytes": v.untyped_storage().nbytes()} for k, v in tensors.items()},
               "rowwise_sha256": hashlib.sha256(rowwise.detach().contiguous().view(torch.uint8).cpu().numpy().tobytes()).hexdigest()}
        row["scale_sha256"] = {k: hashlib.sha256(v.detach().contiguous().view(torch.uint8).cpu().numpy().tobytes()).hexdigest()
                               for k, v in tensors.items() if "scale" in k and "rowwise" in k}
        # A preserved initialization copy may live on CPU; report it rather than
        # silently treating fp8_param as proof there are no higher precision copies.
        getter = getattr(param, "get_high_precision_init_val", None)
        if getter:
            try:
                hp = getter()
                row["high_precision_init_copy"] = None if hp is None else {"dtype": str(hp.dtype), "device": str(hp.device), "bytes": hp.numel() * hp.element_size()}
            except (RuntimeError, AssertionError):
                row["high_precision_init_copy"] = None
        rows.append(row)
    return rows


def train_steps(model, forward, expect_fp8):
    import torch
    trainable = {n: p for n, p in model.named_parameters() if p.requires_grad}
    assert trainable, "No adapters attached"
    assert all("adapter" in n or "lora" in n for n in trainable), list(trainable)
    assert all(p.dtype == torch.bfloat16 for p in trainable.values()), {n: str(p.dtype) for n, p in trainable.items()}
    frozen = {n: p for n, p in model.named_parameters() if not p.requires_grad}
    frozen_dense_before = {n: p.detach().clone() for n, p in frozen.items() if not hasattr(p, "get_metadata")}
    before = physical_storage(model)
    if expect_fp8:
        assert len(before) >= 2, "Not enough physically quantized weights"
        assert all(not r["requires_grad"] for r in before)
        assert all(r["storage"]["rowwise_data"]["bytes"] == r["numel"] for r in before)
    else:
        assert not before, "BF16 control unexpectedly contains FP8 parameters"
    snapshots = {n: p.detach().clone() for n, p in trainable.items()}
    # Stateless SGD isolates backward/storage correctness from optimizer kernels.
    # This is not the proposed production optimizer or an RL learning test.
    optimizer = torch.optim.SGD(list(trainable.values()), lr=0.1)
    steps = []
    for step in range(3):
        optimizer.zero_grad(set_to_none=True)
        output = forward()
        loss = (output.float() - 0.3).square().mean()
        assert torch.isfinite(loss)
        loss.backward()
        gradients = {n: None if p.grad is None else {"dtype": str(p.grad.dtype),
                     "norm": p.grad.float().norm().item(), "finite": bool(torch.isfinite(p.grad).all())}
                     for n, p in trainable.items()}
        assert all(g is not None and g["finite"] and g["dtype"] == "torch.bfloat16" for g in gradients.values()), gradients
        # Zero-initialized B makes A's first-step gradient zero, legitimately.
        # B gradients in the FIRST layer must nevertheless arrive through all
        # later frozen layers. By step 3 every adapter matrix must have signal.
        if step == 2:
            assert all(g["norm"] > 0 for g in gradients.values()), gradients
        assert all(p.grad is None for p in frozen.values()), "Frozen base acquired gradients"
        optimizer.step()
        steps.append({"step": step, "loss": loss.item(), "gradients": gradients})
    after = physical_storage(model)
    assert {r["name"]: r["rowwise_sha256"] for r in before} == {r["name"]: r["rowwise_sha256"] for r in after}, "Frozen FP8 base changed"
    assert {r["name"]: r["scale_sha256"] for r in before} == {r["name"]: r["scale_sha256"] for r in after}, "Frozen FP8 scales changed"
    assert all(torch.equal(p, frozen[n]) for n, p in frozen_dense_before.items()), "Frozen higher precision base changed"
    changed = [n for n, p in trainable.items() if not torch.equal(snapshots[n], p)]
    assert changed, "Optimizer did not change adapters"
    assert all(p.dtype == torch.bfloat16 for p in trainable.values())
    return {"steps": steps, "adapter_dtypes": {n: str(p.dtype) for n, p in trainable.items()},
            "changed_adapters": changed, "fp8_storage_before": before, "fp8_storage_after": after,
            "optimizer": "stateless SGD (probe only)", "frozen_base_no_grad": True,
            "peak_allocated_bytes": torch.cuda.max_memory_allocated()}


def linear_experiment():
    import gc
    import torch
    import transformer_engine.pytorch as te
    from transformer_engine.common.recipe import Float8BlockScaling, Format
    from megatron.core import parallel_state
    from megatron.core.tensor_parallel.random import get_cuda_rng_tracker
    from megatron.core.extensions.transformer_engine import TEColumnParallelLinear, te_checkpoint
    from megatron.core.transformer.transformer_config import TransformerConfig
    from megatron.bridge.peft.lora import LoRA
    recipe = Float8BlockScaling(fp8_format=Format.E4M3)
    cases = []
    for fp8, checkpointing in ((False, False), (True, False), (True, True)):
        config = TransformerConfig(num_layers=2, hidden_size=256, num_attention_heads=2,
                                   params_dtype=torch.bfloat16, bf16=True, fp8="e4m3" if fp8 else None,
                                   fp8_recipe="blockwise", fp8_param=fp8,
                                   gradient_accumulation_fusion=False)
        model = torch.nn.ModuleList()
        with te.quantized_model_init(enabled=fp8, recipe=recipe, preserve_high_precision_init_val=False):
            for _ in range(2):
                model.append(TEColumnParallelLinear(256, 256, config=config,
                    init_method=lambda w: torch.nn.init.normal_(w, std=0.02),
                    gather_output=False, bias=False, skip_bias_add=True, is_expert=False))
        model.requires_grad_(False)
        transform = LoRA(target_modules=["linear"], dim=16, alpha=32, dropout=0.0, lora_dtype=torch.bfloat16)
        for i in range(2):
            model[i] = transform.transform(model[i], name="linear", prefix=f"layers.{i}")
        x = torch.randn(128, 1, 256, device="cuda", dtype=torch.bfloat16, requires_grad=True)

        def plain(value):
            with te.fp8_autocast(enabled=fp8, fp8_recipe=recipe):
                for layer in model:
                    value, _ = layer(value)
                    value = torch.nn.functional.silu(value)
                return value

        def forward():
            x.grad = None
            if checkpointing:
                return te_checkpoint(plain, False, get_cuda_rng_tracker,
                                     parallel_state.get_tensor_model_parallel_group(), x)
            return plain(x)

        result = train_steps(model, forward, expect_fp8=fp8)
        assert x.grad is not None and torch.isfinite(x.grad).all() and x.grad.float().norm() > 0
        result.update(fp8=fp8, checkpointing=checkpointing, input_gradient_norm=x.grad.float().norm().item())
        cases.append(result)
        PROGRESS.append(result)
        print(json.dumps({"case_passed": {"fp8": fp8, "checkpointing": checkpointing}}), flush=True)
        del model, x
        gc.collect()
        torch.cuda.empty_cache()
    return {"status": "PASS", "cases": cases}


def build_hybrid(checkpointing=False):
    import torch
    from megatron.bridge.models.gpt_provider import GPTModelProvider
    from megatron.bridge.peft.lora import LoRA
    from megatron.core.models.gpt.experimental_attention_variant_module_specs import get_transformer_block_with_experimental_attention_variant_spec
    provider = GPTModelProvider(num_layers=4, hidden_size=256, ffn_hidden_size=512,
        transformer_layer_spec=get_transformer_block_with_experimental_attention_variant_spec,
        num_attention_heads=2, num_query_groups=2, kv_channels=128,
        vocab_size=512, seq_length=128, params_dtype=torch.bfloat16, bf16=True,
        normalization="RMSNorm", gated_linear_unit=True, add_bias_linear=False,
        activation_func=torch.nn.functional.silu,
        qk_layernorm=True, attention_output_gate=True, layernorm_zero_centered_gamma=True,
        experimental_attention_variant="gated_delta_net", linear_attention_freq=4,
        linear_conv_kernel_dim=4, linear_key_head_dim=128, linear_value_head_dim=128,
        # Fused q/k/v/z/b/a width must be divisible by 16 for FP8.
        # Four value heads produce an invalid tiny shape (1544).
        linear_num_key_heads=2, linear_num_value_heads=8,
        hidden_dropout=0.0, attention_dropout=0.0, apply_rope_fusion=False,
        position_embedding_type="rope", rotary_percent=0.25,
        fp8="e4m3", fp8_recipe="blockwise", fp8_param=True,
        gradient_accumulation_fusion=False,
        recompute_granularity="full" if checkpointing else None,
        recompute_method="uniform" if checkpointing else None,
        recompute_num_layers=1 if checkpointing else None)
    provider.finalize()
    transform = LoRA(target_modules=["linear_qkv", "linear_proj", "linear_fc1", "linear_fc2", "in_proj", "out_proj"],
                     dim=16, alpha=32, dropout=0.0, lora_dtype=torch.bfloat16)
    models = provider.provide_distributed_model(wrap_with_ddp=False, pre_wrap_hook=transform)
    model = models[0]
    return model


def hybrid_experiment():
    import torch
    cases = []
    # Same dense GDN/full-attention integration family as Qwen3.8, reduced sizes.
    # Uses no tokenizer, vision tower, checkpoint download, or serving backend.
    for checkpointing in (False, True):
        model = build_hybrid(checkpointing)
        tokens = torch.randint(0, 512, (1, 128), device="cuda")
        positions = torch.arange(128, device="cuda").unsqueeze(0)
        result = train_steps(model, lambda: model(input_ids=tokens, position_ids=positions, attention_mask=None), True)
        result["checkpointing"] = checkpointing
        result["module_types"] = sorted({type(m).__name__ for m in model.modules()})
        assert any("GatedDeltaNet" in t for t in result["module_types"]), "Hybrid probe did not instantiate GDN"
        cases.append(result)
        PROGRESS.append(result)
        del model
        torch.cuda.empty_cache()
    return {"status": "PASS", "cases": cases, "scope": "random reduced dense Qwen hybrid; not 27B or GRPO"}


def blockwise_fp8_roundtrip(value, block=128):
    """Numerical control with NEW scales after merging; no serving-kernel claim."""
    import torch
    from torch.nn.functional import pad
    rows, cols = value.shape
    padded = pad(value.float(), (0, (-cols) % block, 0, (-rows) % block))
    nr, nc = padded.shape[0] // block, padded.shape[1] // block
    tiles = padded.reshape(nr, block, nc, block).permute(0, 2, 1, 3)
    scales = (tiles.abs().amax(dim=(-1, -2), keepdim=True) / 448).clamp_min(torch.finfo(torch.float32).tiny)
    result = (tiles / scales).clamp(-448, 448).to(torch.float8_e4m3fn).float() * scales
    result = result.permute(0, 2, 1, 3).reshape(nr * block, nc * block)[:rows, :cols]
    assert torch.isfinite(result).all(), "Requantization control produced nonfinite values"
    return result


def export_experiment():
    """Test export before paying for an inference engine. No upstream patches."""
    import dataclasses
    import tempfile
    import torch
    from safetensors.torch import save_file
    from transformers import Qwen3_5TextConfig
    from megatron.bridge import AutoBridge

    model = build_hybrid()
    before = physical_storage(model)
    # Deliberately strong, reproducible nonzero updates expose ignored/misscaled
    # adapters. This is an export test, not an additional learning experiment.
    with torch.no_grad():
        for name, p in model.named_parameters():
            if p.requires_grad:
                assert p.dtype == torch.bfloat16 and "adapter" in name
                p.normal_(mean=0, std=0.05)
    config = Qwen3_5TextConfig(vocab_size=512, hidden_size=256, intermediate_size=512,
        num_hidden_layers=4, num_attention_heads=2, num_key_value_heads=2, head_dim=128,
        linear_num_key_heads=2, linear_num_value_heads=8, linear_key_head_dim=128,
        linear_value_head_dim=128, linear_conv_kernel_dim=4,
        layer_types=["linear_attention"] * 3 + ["full_attention"],
        tie_word_embeddings=False, architectures=["Qwen3_5ForCausalLM"])
    bridge = AutoBridge.from_hf_config(config)
    # The public get_conversion_tasks wrapper requires a checkpoint path in
    # this release; its underlying builder supports config-only synthetic models.
    tasks = [t for t in bridge._model_bridge.build_conversion_tasks(config, [model]) if t is not None]

    def logical(t):
        w = t.param_weight
        if hasattr(w, "dequantize") and hasattr(w, "get_metadata"):
            w = w.dequantize(dtype=torch.float32)
        else:
            w = w.detach().float()
        return dataclasses.replace(t, param_weight=w)

    logical_tasks = [logical(t) for t in tasks]
    reference = dict(bridge.export_hf_weights([model], conversion_tasks=logical_tasks, show_progress=False))
    # Independently form W + alpha/r * B@A BEFORE Qwen's fused projection
    # splitting; then compare to the normal post-splitting adapter merge.
    independent = []
    for t in logical_tasks:
        if not t.global_param_name.endswith(".to_wrap.weight"):
            continue
        prefix = t.param_name.removesuffix(".to_wrap.weight")
        matches = [m for n, m in model.named_modules() if n == prefix or n.endswith("." + prefix)]
        assert len(matches) == 1, (prefix, len(matches))
        adapter = matches[0].adapter
        delta_fp32 = 2 * (adapter.linear_out.weight.float() @ adapter.linear_in.weight.float())
        # The pinned GDN merge computes BA in adapter dtype; other branches
        # explicitly promote to FP32. Match this known arithmetic difference
        # without weakening the fused-projection correspondence assertion.
        delta = (2 * (adapter.linear_out.weight @ adapter.linear_in.weight)).float() if prefix.endswith("self_attention.in_proj") else delta_fp32
        expected = t.mapping.megatron_to_hf(t.param_weight + delta, t.megatron_module)
        for name, value in expected.items():
            torch.testing.assert_close(reference[name], value, atol=1e-6, rtol=1e-5)
        independent.append({"projection": prefix, "delta_norm": delta.norm().item(), "hf_names": list(expected),
                            "adapter_matmul_vs_fp32_max_abs": (delta - delta_fp32).abs().max().item()})
    assert len(independent) == 16, len(independent)
    PROGRESS.append({"reference_merge": "PASS", "independent_fused_projections": independent})
    print("Logical reference and independent fused-projection merge: PASS", flush=True)

    def compare_tasks(label, conversion_tasks):
        rows = []
        for t in conversion_tasks:
            if t is None or ".to_wrap.weight" not in t.global_param_name:
                continue
            try:
                values = dict(bridge.export_hf_weights([model], conversion_tasks=[t], show_progress=False))
                row = {"task": t.global_param_name, "outputs": []}
                for name, value in values.items():
                    out = {"name": name, "dtype": str(value.dtype), "class": type(value).__name__, "shape": list(value.shape)}
                    if name in reference and label == "pinned_worker_ordinary_tasks":
                        dense = value.dequantize(dtype=torch.float32) if hasattr(value, "get_metadata") else value.float()
                        diff = dense - reference[name]
                        out.update(max_abs_error=diff.abs().max().item(),
                                   relative_l2_error=(diff.norm() / reference[name].norm().clamp_min(1e-12)).item())
                    row["outputs"].append(out)
                rows.append(row)
            except Exception:
                rows.append({"task": t.global_param_name, "error": traceback.format_exc()})
        result = {"path": label, "tasks": rows}
        PROGRESS.append(result)
        print(json.dumps({"path": label, "tasks": len(rows), "exceptions": sum("error" in r for r in rows)}), flush=True)
        return result

    # This matches the pinned NeMo worker: normal conversion tasks passed to
    # export_hf_weights, NOT main's newer physical-FP8 refit branch.
    ordinary = compare_tasks("pinned_worker_ordinary_tasks", tasks)

    # Build a real local tiny HF checkpoint solely to supply valid source state
    # to Bridge's physical-export task builder. No network/model downloads.
    try:
        with tempfile.TemporaryDirectory() as tmp:
            config.save_pretrained(tmp)
            save_file({n: w.detach().to(torch.bfloat16).contiguous().cpu() for n, w in reference.items()}, str(Path(tmp) / "model.safetensors"))
            source_bridge = AutoBridge.from_hf_pretrained(tmp)
            physical_tasks = source_bridge._model_bridge.build_export_fp8_tasks(source_bridge.hf_pretrained, [model])
            physical = compare_tasks("physical_fp8_tasks_explicit_bridge_api", physical_tasks)
    except Exception:
        physical = {"path": "physical_fp8_tasks_explicit_bridge_api", "tasks": [{"error": traceback.format_exc()}]}
        PROGRESS.append(physical)

    # Isolate the scale issue from fused projection or task dispatch failures.
    t = next(t for t in tasks if t.global_param_name.endswith("linear_proj.to_wrap.weight"))
    weight = t.param_weight
    metadata = weight.get_metadata()
    raw = metadata["rowwise_data"].view(torch.float8_e4m3fn)
    block = weight._quantizer.block_len
    scales = metadata["rowwise_scale_inv"][:(raw.shape[0] + block - 1)//block, :(raw.shape[1] + block - 1)//block]
    expanded = scales.repeat_interleave(block, 0).repeat_interleave(block, 1)[:raw.shape[0], :raw.shape[1]]
    dense = weight.dequantize(dtype=torch.float32)
    torch.testing.assert_close(raw.float() * expanded, dense, atol=0, rtol=0)
    prefix = t.param_name.removesuffix(".to_wrap.weight")
    wrapper = next(m for n, m in model.named_modules() if n == prefix or n.endswith("." + prefix))
    a, b = wrapper.adapter.linear_in.weight, wrapper.adapter.linear_out.weight
    merger = bridge._model_bridge._merge_single_adapter_weight
    correct = dense + 2 * (b.float() @ a.float())
    raw_merged = merger(raw, 32, 16, a, b)
    received = raw_merged.float() * expanded
    delta = correct - dense
    recovered_delta = received - dense
    # Nonzero adapters can exceed the original base's dynamic range. Reusing
    # its scales overflowed in the first complete probe; preserve that report.
    # This amended control is CPU-tested, not yet rerun on Hopper.
    control = blockwise_fp8_roundtrip(correct, block)
    scale_result = {"scale_min": scales.min().item(), "scale_max": scales.max().item(),
        "intended_update_norm": delta.norm().item(), "received_update_norm": recovered_delta.norm().item(),
        "update_relative_error": ((recovered_delta - delta).norm() / delta.norm()).item(),
        "requantized_control_update_relative_error": ((control - correct).norm() / delta.norm()).item(),
        "scope": "real TE weight + upstream merge helper; reconstructed receiver, not live vLLM"}
    PROGRESS.append({"scale_merge": scale_result})
    after = physical_storage(model)
    assert [(r["name"], r["rowwise_sha256"], r["scale_sha256"]) for r in before] == [(r["name"], r["rowwise_sha256"], r["scale_sha256"]) for r in after]
    issues = sum("error" in r for case in (ordinary, physical) for r in case["tasks"])
    ordinary_bad = [o for r in ordinary["tasks"] for o in r.get("outputs", []) if o.get("relative_l2_error", 0) > 0.05]
    return {"status": "BLOCKED" if issues or ordinary_bad or scale_result["update_relative_error"] > 0.5 else "PASS",
            "reference_independent_projections": independent, "ordinary": ordinary, "physical": physical,
            "scale_merge": scale_result, "storage": after, "frozen_base_unchanged": True,
            "vllm_refit_run": False, "scope": "tiny real Qwen Bridge export; stop before vLLM on export failure"}


def inventory():
    code = """
import importlib.metadata as m, importlib.util as u, json, sys
names=['torch','transformer-engine','megatron-core','megatron-bridge','transformers','nemo-rl']
versions={}
for n in names:
 try: versions[n]=m.version(n)
 except m.PackageNotFoundError: pass
print(json.dumps({'python':sys.executable,'versions':versions}))
"""
    candidates = [Path("/opt/nemo_rl_venv/bin/python"), *Path("/opt/ray_venvs").glob("*/bin/python")]
    # Prefer the actual GRPO policy worker, not ModelOpt's separate quantization
    # worker, even if filesystem iteration happens to list that environment first.
    candidates.sort(key=lambda p: ("nemo_rl.models.policy.workers.megatron_policy_worker.MegatronPolicyWorker" not in str(p), str(p)))
    environments = []
    for python in candidates:
        print(f"Inventory: {python}", flush=True)
        done = subprocess.run([str(python), "-c", code], capture_output=True, text=True, timeout=20)
        if done.returncode == 0:
            environments.append(json.loads(done.stdout.strip().splitlines()[-1]))
    selected = next((e for e in environments if all(n in e["versions"] for n in
                                                  ("megatron-bridge", "megatron-core", "transformer-engine"))), None)
    commits = {}
    for name, path in {"nemo_rl": "/opt/nemo-rl", "bridge": "/opt/nemo-rl/3rdparty/Megatron-Bridge-workspace/Megatron-Bridge"}.items():
        done = subprocess.run(["git", "-C", path, "rev-parse", "HEAD"], capture_output=True, text=True)
        commits[name] = done.stdout.strip() if done.returncode == 0 else None
    api_check = None
    if selected:
        print(f"Import check: {selected['python']}", flush=True)
        check = """
import inspect,json,torch
import transformer_engine.pytorch as te
from megatron.bridge.models.gpt_provider import GPTModelProvider
from megatron.bridge.peft.lora import LoRA
from megatron.core.extensions.transformer_engine import TEColumnParallelLinear
from transformer_engine.common.recipe import Float8BlockScaling,Format
recipe=Float8BlockScaling(fp8_format=Format.E4M3)
print(json.dumps({'te_quantized_init':str(inspect.signature(te.quantized_model_init)),
 'linear':str(inspect.signature(TEColumnParallelLinear)),
 'lora':str(inspect.signature(LoRA)),
 'provider_fields':list(GPTModelProvider.__dataclass_fields__)}))
"""
        done = subprocess.run([selected["python"], "-c", check], capture_output=True, text=True, timeout=150)
        api_check = {"returncode": done.returncode, "stdout": done.stdout[-14000:], "stderr": done.stderr[-6000:]}
        if done.returncode:
            selected = None
    return {"python": selected["python"] if selected else None, "environments": environments,
            "commits": commits, "api_check": api_check, "nemo_build_commit": os.environ.get("NEMO_RL_COMMIT")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--inventory", action="store_true")
    mode.add_argument("--stage", choices=("linear", "hybrid", "export"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    started = time.time()
    try:
        if args.inventory:
            result = inventory()
        else:
            hardware = initialize()
            result = {"linear": linear_experiment, "hybrid": hybrid_experiment, "export": export_experiment}[args.stage]()
            result["hardware"] = hardware
    except Exception:
        result = {"status": "FAIL", "error": traceback.format_exc(), "completed_cases": PROGRESS}
    result["elapsed_seconds"] = time.time() - started
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2))
    print(json.dumps({"status": result.get("status"), "elapsed_seconds": result["elapsed_seconds"],
                      "output": str(args.output), "error": result.get("error")}), flush=True)
    if not args.inventory:
        import torch
        if torch.distributed.is_initialized():
            torch.distributed.destroy_process_group()
    if result.get("status") in ("FAIL", "BLOCKED"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
