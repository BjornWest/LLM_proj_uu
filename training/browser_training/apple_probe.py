"""Deterministic SFT behavior probe; no model or browser dependencies."""
import random

SYSTEM = "Follow the user's request."


def example(words):
    return {
        "words": words,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": "Repeat: " + " ".join(words)},
            {"role": "assistant", "content": " ".join(w + " apple" for w in words)},
        ],
    }


def splits(seed=42):
    colors = "red blue green yellow black white pink orange".split()
    nouns = "boat chair house book train cup tree door lamp shoe bird hat".split()
    pairs = [(a, b) for a in colors for b in nouns]
    random.Random(seed).shuffle(pairs)
    rows = [example(list(pair)) for pair in pairs]
    return {"train": rows[:64], "heldout": rows[64:80], "train_eval": rows[:8]}


def score(words, response):
    tokens = response.strip().split()
    return {
        "exact_match": response.strip() == " ".join(w + " apple" for w in words),
        "apple_placement": len(tokens) == 2 * len(words) and tokens[1::2] == ["apple"] * len(words),
        "word_preservation": tokens[::2] == words and len(tokens) == 2 * len(words),
    }


def summarize(rows):
    if not rows:
        raise ValueError("Evaluation must not be empty")
    return {"n": len(rows), **{key: sum(r[key] for r in rows) / len(rows)
            for key in ("exact_match", "apple_placement", "word_preservation")}}


def validate_tokenized(dataset, tokenizer, rows):
    """Require the exact assistant payload + EOS and matching inference prefix."""
    expected = {}
    for row in rows:
        ids = tokenizer.apply_chat_template(row["messages"][:-1], tokenize=True,
            add_generation_prompt=True, enable_thinking=False, return_dict=False)
        expected[tuple(ids)] = row["messages"][-1]["content"]
    assert len(dataset) == len(expected)
    seen = set()
    for row in dataset:
        ids, labels = row["input_ids"], row["labels"]
        first = next(i for i, label in enumerate(labels) if label != -100)
        prefix = tuple(ids[:first])
        assert prefix in expected, "Training prefix differs from generation prompt"
        assert all(label == -100 for label in labels[:first])
        supervised = [label for label in labels[first:] if label != -100]
        assert tokenizer.decode(supervised, skip_special_tokens=True).strip() == expected[prefix]
        assert tokenizer.eos_token_id in supervised, "Assistant EOS is not supervised"
        seen.add(prefix)
    assert seen == set(expected)


def evaluate(model, tokenizer, examples, path):
    import json
    import time
    import torch
    started = time.monotonic()
    was_training = model.training
    model.eval()
    results = []
    try:
        with torch.inference_mode(), torch.autocast("cuda", dtype=torch.bfloat16):
            for row in examples:
                ids = tokenizer.apply_chat_template(row["messages"][:-1], tokenize=True,
                    add_generation_prompt=True, enable_thinking=False, return_dict=False)
                inputs = torch.tensor([ids], device=model.get_input_embeddings().weight.device)
                generated = model.generate(input_ids=inputs, attention_mask=torch.ones_like(inputs),
                    do_sample=False, max_new_tokens=20, use_cache=True,
                    pad_token_id=tokenizer.pad_token_id, eos_token_id=tokenizer.eos_token_id)
                completion = generated[0, len(ids):].tolist()
                response = tokenizer.decode(completion, skip_special_tokens=True)
                results.append({"words": row["words"], "response": response,
                    "completion_ids": completion, **score(row["words"], response)})
                print(f"Apple eval {len(results)}/{len(examples)}: {response!r}", flush=True)
    finally:
        model.train(was_training)
    report = {"summary": summarize(results), "rows": results,
              "elapsed_seconds": time.monotonic() - started}
    path.write_text(json.dumps(report, indent=2) + "\n")
    return report
