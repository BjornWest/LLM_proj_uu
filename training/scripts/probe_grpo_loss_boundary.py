#!/usr/bin/env python3
"""CPU interface probe: unchanged pinned TRL loss, synthetic BF16 adapters.

This does not instantiate AsyncGRPOTrainer, Megatron, TE, FP8, or vLLM.
It tests only whether a logits-producing backend can satisfy the loss contract.
No model weights or packages are downloaded; an optional source fetch is 102 KB.
"""
import argparse
import ast
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import time
from types import SimpleNamespace
from urllib.request import urlopen

REVISION = "a04ffd337108285002df29d9ae73ef7e855e03f1"
SOURCE_URL = f"https://raw.githubusercontent.com/huggingface/trl/{REVISION}/trl/experimental/async_grpo/async_grpo_trainer.py"
SOURCE_SHA256 = "15951bb122c4477ba82aeeb24ad85b35dd46fd8489f244364837dc958919af99"


def load_loss(source):
    import torch
    if hashlib.sha256(source).hexdigest() != SOURCE_SHA256:
        raise ValueError("TRL source changed; review the loss contract before using it")
    tree = ast.parse(source)
    trainer = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "AsyncGRPOTrainer")
    method = next(n for n in trainer.body if isinstance(n, ast.FunctionDef) and n.name == "compute_loss")
    # Single-rank, nonempty-completion fixtures: nan helpers affect metrics only.
    namespace = {"torch": torch, "time": time,
                 "nanmin": lambda x: x[~x.isnan()].min(),
                 "nanmax": lambda x: x[~x.isnan()].max()}
    exec(compile(ast.Module(body=[method], type_ignores=[]), SOURCE_URL, "exec"), namespace)
    return namespace["compute_loss"]


def loss_context(accumulation=1):
    return SimpleNamespace(
        epsilon_low=0.2, epsilon_high=0.2, aux_loss_enabled=False,
        current_gradient_accumulation_steps=accumulation,
        accelerator=SimpleNamespace(num_processes=1, reduce=lambda x, **kw: x, gather=lambda x: x),
        _metrics={"train": defaultdict(list)}, _step_forward_tokens=0,
        _step_trained_tokens=0, _step_seq_len_weighted=0, _step_samples=0, _step_forward_s=0)


def selected_logprobs(logits, tokens, temperature):
    """Single sequence, full vocabulary, next-token alignment; no packing/TP."""
    import torch
    if logits.shape[:2] != tokens.shape or tokens.shape[0] != 1 or temperature <= 0:
        raise ValueError("Expected one sequence, full-vocabulary [1,T,V] logits, positive temperature")
    distribution = torch.log_softmax(logits[:, :-1].float() / temperature, dim=-1)
    return {"log_probs": distribution.gather(-1, tokens[:, 1:, None]).squeeze(-1),
            "entropy": -(distribution.exp() * distribution).sum(-1)}


def run(source):
    import torch
    torch.set_num_threads(1)
    torch.manual_seed(41)
    loss_fn = load_loss(source)

    class SyntheticPolicy(torch.nn.Module):
        """Frozen BF16 weights and small BF16 factors; deliberately no FP8 claim."""
        def __init__(self):
            super().__init__()
            self.base = torch.nn.Parameter(torch.randn(16, 16).bfloat16(), requires_grad=False)
            self.a = torch.nn.Parameter((torch.randn(2, 16) * 0.1).bfloat16())
            self.b = torch.nn.Parameter((torch.randn(16, 2) * 0.1).bfloat16())

        def forward(self, input_ids, position_ids, labels, completion_mask, use_cache):
            assert torch.equal(position_ids, torch.arange(input_ids.shape[1])[None])
            # Cumulative context means masked observation tokens still affect later actions.
            hidden = torch.nn.functional.one_hot(input_ids, 16).float().cumsum(1)
            weights = self.base.float() + 2 * (self.b.float() @ self.a.float())
            return selected_logprobs(hidden @ weights.T, input_ids, temperature=0.8)

    model = SyntheticPolicy()
    tokens = torch.tensor([[1, 2, 3, 4, 5, 6]])
    mask = torch.tensor([[0, 0, 1, 0, 1, 1]])  # Includes a later environment observation.
    batch = dict(input_ids=tokens, position_ids=torch.arange(6)[None],
                 attention_mask=torch.ones_like(tokens), completion_mask=mask,
                 old_log_probs=torch.zeros_like(tokens, dtype=torch.float),
                 advantages=torch.ones_like(tokens, dtype=torch.float),
                 global_n_tokens=torch.tensor([3.]), global_n_forward_tokens=torch.tensor([6.]),
                 mean_seq_len=torch.tensor([6.]))
    with torch.no_grad():
        batch["old_log_probs"][:, 1:] = model(tokens, batch["position_ids"], tokens, mask, False)["log_probs"]
    loss = loss_fn(loss_context(), model, batch)
    assert torch.allclose(loss, torch.tensor(-1.))
    altered = dict(batch, old_log_probs=batch["old_log_probs"] + (1 - mask) * 2)
    assert torch.equal(loss_fn(loss_context(), model, altered), loss), "Masked behavior logprobs leaked into loss"
    assert torch.equal(loss_fn(loss_context(2), model, batch), loss / 2), "Accumulation scaled incorrectly"
    zero = dict(batch, advantages=torch.zeros_like(batch["advantages"]))
    assert loss_fn(loss_context(), model, zero).item() == 0
    negative = dict(batch, advantages=-batch["advantages"])
    positive_grads = torch.autograd.grad(loss, (model.a, model.b))
    negative_grads = torch.autograd.grad(loss_fn(loss_context(), model, negative), (model.a, model.b))
    assert all(torch.equal(p, -n) for p, n in zip(positive_grads, negative_grads))
    clipped = dict(batch, old_log_probs=batch["old_log_probs"] - 1)
    clip_grads = torch.autograd.grad(loss_fn(loss_context(), model, clipped), (model.a, model.b))
    assert all(torch.count_nonzero(g) == 0 for g in clip_grads), "Positive clipped branch still updates"
    assert all(g.dtype == torch.bfloat16 and torch.isfinite(g).all() and g.norm() > 0 for g in positive_grads)
    before = {n: p.detach().clone() for n, p in model.named_parameters()}
    optimizer = torch.optim.SGD([model.a, model.b], lr=0.1)
    loss_fn(loss_context(), model, batch).backward()
    optimizer.step()
    assert model.base.grad is None and torch.equal(model.base, before["base"])
    assert all(not torch.equal(p, before[n]) for n, p in [("a", model.a), ("b", model.b)])
    assert all(p.dtype == torch.bfloat16 for p in (model.a, model.b))
    return {"status": "PASS", "scope": "CPU loss interface only; synthetic BF16 base and adapters",
            "source": SOURCE_URL, "source_sha256": SOURCE_SHA256, "torch": torch.__version__,
            "checks": ["next-token alignment", "environment token loss masking", "accumulation scaling",
                       "zero advantages", "positive/negative advantage gradients", "clipped gradient",
                       "BF16 adapter gradients and updates", "frozen base unchanged"],
            "limitations": ["No actual AsyncGRPOTrainer or rollout worker instantiated",
                            "No Megatron, TE, FP8, Bridge export, optimizer resume, or vLLM tested",
                            "Single sequence/rank, full vocabulary; not a production chunked logprob kernel",
                            "Synthetic advantages supplied; no reward grouping or browser episode tested"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, help="Use cached official source instead of fetching 102 KB")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = args.source.read_bytes() if args.source else urlopen(SOURCE_URL, timeout=30).read()
    report = run(source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
