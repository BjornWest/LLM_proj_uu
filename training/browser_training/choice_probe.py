"""Deliberately trivial bandit for an RL learning smoke test, not a benchmark.

Uses TRL's public completion-reward API. No labels are supplied to the policy.
Calibration chooses a reachable reward; independent evaluation estimates change.
"""
import math
import json

PROMPT = [{"role": "user", "content":
    "Pick one of A and B at random, with equal probability. Reply with just the single letter."}]


def render_prompt_ids(tokenizer):
    # Transformers 5.16 defaults to BatchEncoding, which requests cannot serialize.
    ids = tokenizer.apply_chat_template(PROMPT, tokenize=True, return_dict=False,
        add_generation_prompt=True, enable_thinking=False)
    if not isinstance(ids, list) or not ids or not all(type(token) is int for token in ids):
        raise TypeError("Evaluation requires a nonempty flat list of integer token IDs")
    json.dumps({"prompt": ids})
    return ids


def answer(completion):
    if isinstance(completion, str):
        return completion.strip()
    return "".join(m.get("content") or "" for m in completion if m.get("role") == "assistant").strip()


def choice_reward(completions, target, **kwargs):
    """Exact single-letter reward; malformed/verbose completions receive zero."""
    if len(completions) != len(target) or any(t not in ("A", "B") for t in target):
        raise ValueError("Every completion needs an A/B target")
    return [float(answer(c) == t) for c, t in zip(completions, target, strict=True)]


def choose_target(completions):
    """Require both choices to be reachable; never silently train on zero variance."""
    counts = {letter: sum(answer(c) == letter for c in completions) for letter in ("A", "B")}
    if not completions or min(counts.values()) / len(completions) < 0.125:
        raise ValueError(f"Insufficient choice diversity for a short learning test: {counts}")
    return min(counts, key=counts.get)


def summarize(completions, target):
    rewards = choice_reward(completions, [target] * len(completions))
    n = len(rewards)
    if not n:
        raise ValueError("Empty evaluation")
    p = sum(rewards) / n
    z = 1.96
    center = (p + z*z/(2*n)) / (1 + z*z/n)
    radius = z * math.sqrt(p*(1-p)/n + z*z/(4*n*n)) / (1 + z*z/n)
    return {"n": n, "successes": int(sum(rewards)), "reward_mean": p,
            "wilson95": [center-radius, center+radius],
            "invalid": sum(answer(c) not in ("A", "B") for c in completions)}


def compare(before, after):
    # Conservative descriptive gate; one prompt/seed is not evidence of generalization.
    return {"reward_change": after["reward_mean"] - before["reward_mean"],
            "clear_improvement": after["wilson95"][0] > before["wilson95"][1]}
