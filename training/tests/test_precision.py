"""Runs with an existing CPU torch; skipped by the minimal uv environment."""
import pytest
torch = pytest.importorskip("torch")
from browser_training.precision import enforce_bf16_lora, inspect_dtypes


def test_explicit_cast_and_frozen_base():
    model = torch.nn.Module()
    model.register_parameter("base", torch.nn.Parameter(torch.ones(2, 2), requires_grad=False))
    model.lora_A = torch.nn.Linear(2, 1, bias=False)
    model.lora_B = torch.nn.Linear(1, 2, bias=False)
    assert model.lora_A.weight.dtype == torch.float32
    enforce_bf16_lora(model)
    assert model.lora_A.weight.dtype == torch.bfloat16
    assert model.base.dtype == torch.float32 and not model.base.requires_grad
    model.lora_B(model.lora_A(torch.ones(1, 2, dtype=torch.bfloat16))).sum().backward()
    assert inspect_dtypes(model, check_grads=True)["gradient_tensors_checked"] == 2
    model.lora_B.float()
    with pytest.raises(AssertionError, match="expected BF16"):
        inspect_dtypes(model)


def test_refuse_full_model_training():
    with pytest.raises(RuntimeError, match="non-LoRA"):
        enforce_bf16_lora(torch.nn.Linear(2, 2))
