"""Acceptance checks must reject identity changes and premature eviction."""
import pytest
from browser_training.acceptance_harness import audit_policy_events


def events():
    return [dict(event="publish", version=1), dict(event="group_start", group_id=0, version=1),
        dict(event="episode_start", group_id=0, episode_id="a", version=1),
        dict(event="request_start", episode_id="a", version=1),
        dict(event="request_end", episode_id="a", version=1), dict(event="publish", version=2),
        dict(event="request_start", episode_id="a", version=1),
        dict(event="request_end", episode_id="a", version=1), dict(event="episode_end", episode_id="a"),
        dict(event="group_end", group_id=0), dict(event="eviction_claim", version=1),
        dict(event="evicted", version=1)]


def test_acceptance_policy_audit():
    assert audit_policy_events(events())["completed_multiturn_episodes"] == 1
    changed = events()
    changed[6]["version"] = 2
    with pytest.raises(AssertionError):
        audit_policy_events(changed)
    premature = events()
    premature.insert(5, dict(event="eviction_claim", version=1))
    with pytest.raises(AssertionError, match="reserved"):
        audit_policy_events(premature)
    with pytest.raises(AssertionError, match="leaked"):
        audit_policy_events(events()[:8])


def test_nested_optimizer_fingerprint(tmp_path):
    torch = pytest.importorskip("torch")
    from browser_training.acceptance_harness import optimizer_digest
    state = dict(state={0: dict(step=3, wrapped={"state1": torch.tensor([0.125]),
                    "state2": torch.tensor([0.25])})})
    path = tmp_path / "optimizer.pt"
    torch.save(state, path)
    restored = torch.load(path, weights_only=True)
    assert optimizer_digest(state) == optimizer_digest(restored)
    restored["state"][0]["wrapped"]["state1"] += 1
    assert optimizer_digest(state) != optimizer_digest(restored)
    restored = torch.load(path, weights_only=True)
    restored["state"][0]["step"] += 1
    assert optimizer_digest(state) != optimizer_digest(restored)


def test_actual_hf_peft_resume_keeps_bf16(tmp_path):
    torch = pytest.importorskip("torch")
    pytest.importorskip("peft")
    from peft import LoraConfig, get_peft_model, get_peft_model_state_dict
    from transformers import Qwen3Config, Qwen3ForCausalLM, Trainer, TrainingArguments
    from browser_training.acceptance_harness import tensor_digest
    from browser_training.precision import BF16AdapterResumeMixin, enforce_bf16_lora
    model = get_peft_model(Qwen3ForCausalLM(Qwen3Config(vocab_size=32, hidden_size=16,
        intermediate_size=32, num_hidden_layers=1, num_attention_heads=2, num_key_value_heads=2, head_dim=8)),
        LoraConfig(r=2, target_modules=["q_proj", "v_proj"], task_type="CAUSAL_LM"), autocast_adapter_dtype=False)
    enforce_bf16_lora(model)
    with torch.no_grad():
        for name, parameter in model.named_parameters():
            if "lora_B" in name:
                parameter.normal_()
    expected = tensor_digest(get_peft_model_state_dict(model))
    checkpoint = tmp_path / "checkpoint"
    model.save_pretrained(checkpoint)
    optimizer = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad])
    parameter_ids = [id(p) for group in optimizer.param_groups for p in group["params"]]
    args = TrainingArguments(output_dir=str(tmp_path / "out"), use_cpu=True, report_to="none")
    class Fixed(BF16AdapterResumeMixin, Trainer):
        pass
    trainer = Fixed(model=model, args=args, optimizers=(optimizer, None))
    # Reproduce the regression using the actual installed HF and PEFT loader.
    Trainer._load_from_checkpoint(trainer, str(checkpoint))
    assert {p.dtype for p in model.parameters() if p.requires_grad} == {torch.float32}
    trainer._load_from_checkpoint(str(checkpoint))
    assert {p.dtype for p in model.parameters() if p.requires_grad} == {torch.bfloat16}
    assert tensor_digest(get_peft_model_state_dict(model)) == expected
    assert [id(p) for p in model.parameters() if p.requires_grad] == parameter_ids
    assert [id(p) for group in optimizer.param_groups for p in group["params"]] == parameter_ids
