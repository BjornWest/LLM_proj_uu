"""Explicit adapter storage and optimizer checks, independent of autocast compute."""
def enforce_bf16_lora(model):
    import torch
    trainable = [(n, p) for n, p in model.named_parameters() if p.requires_grad]
    if not trainable:
        raise RuntimeError("No trainable parameters")
    unexpected = [n for n, _ in trainable if "lora_A" not in n and "lora_B" not in n]
    if unexpected:
        raise RuntimeError(f"Trainable non-LoRA weights: {unexpected[:8]}")
    for _, parameter in trainable:
        parameter.data = parameter.data.to(torch.bfloat16)
    return inspect_dtypes(model)


def inspect_dtypes(model, *, require_fp8=False, check_grads=False):
    import torch
    from collections import Counter
    base, adapters = Counter(), Counter()
    gradient_count = 0
    for name, parameter in model.named_parameters():
        if parameter.requires_grad:
            if not any(tag in name for tag in ("lora_A", "lora_B")):
                raise AssertionError(f"Non-LoRA trainable parameter: {name}")
            if parameter.dtype != torch.bfloat16:
                raise AssertionError(f"{name}: expected BF16, got {parameter.dtype}")
            adapters[str(parameter.dtype)] += parameter.numel()
            if check_grads:
                if parameter.grad is None or not torch.isfinite(parameter.grad).all():
                    raise AssertionError(f"Missing/nonfinite gradient: {name}")
                if parameter.grad.dtype != torch.bfloat16:
                    raise AssertionError(f"{name}: expected BF16 gradient, got {parameter.grad.dtype}")
                gradient_count += 1
        else:
            base[str(parameter.dtype)] += parameter.numel()
    if not adapters:
        raise AssertionError("No trainable LoRA parameters")
    if require_fp8 and not any("float8" in key for key in base):
        raise AssertionError("Expected frozen FP8 weights; load dequantized or selected the wrong base")
    return {"base_parameter_elements": dict(base), "adapter_parameter_elements": dict(adapters),
            "gradient_tensors_checked": gradient_count}


def make_optimizer(model, learning_rate, weight_decay=0.0):
    from bitsandbytes.optim import AdamW32bit
    return AdamW32bit([p for p in model.parameters() if p.requires_grad],
                     lr=learning_rate, weight_decay=weight_decay)


def inspect_optimizer(optimizer):
    import torch
    optimizer = getattr(optimizer, "optimizer", optimizer)
    checked = 0
    for state in optimizer.state.values():
        for name in ("state1", "state2"):
            value = state.get(name)
            if value is not None:
                if value.dtype != torch.float32 or not torch.isfinite(value).all():
                    raise AssertionError(f"Expected finite FP32 Adam moment {name}, got {value.dtype}")
                checked += 1
    if not checked:
        raise AssertionError("No initialized AdamW32bit moments")
    return checked


def inspect_nf4(model):
    """Check actual quantized modules, not just the requested loading flags."""
    import torch
    from bitsandbytes.nn import Linear4bit
    names = []
    for name, module in model.named_modules():
        if not isinstance(module, Linear4bit):
            continue
        weight = module.weight
        assert not weight.requires_grad, name
        assert weight.quant_state is not None, f"Unquantized Linear4bit: {name}"
        assert weight.quant_state.quant_type == "nf4", name
        assert weight.quant_state.nested, f"Double quantization missing: {name}"
        assert module.compute_dtype == torch.bfloat16, (name, module.compute_dtype)
        assert not any(part in name.split('.') for part in ('visual', 'vision', 'mtp', 'lm_head')), name
        names.append(name)
    assert names, "No NF4 modules loaded"
    return {"quantized_linears": len(names), "compute_dtype": "bfloat16", "double_quant": True,
            "vision_head_mtp_unquantized": True}
