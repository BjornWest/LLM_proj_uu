#!/usr/bin/env python3
"""Verify completions/logprobs and immutable adapter registration on a running server."""
import argparse
import json
import math
from pathlib import Path
import urllib.request


def request(base, path, payload=None):
    req = urllib.request.Request(base.rstrip("/") + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as response:
        return json.load(response)


def completion(base, model):
    result = request(base, "/v1/completions", {"model": model, "prompt": "The next number after one is",
        "max_tokens": 8, "temperature": 0, "logprobs": 0, "return_token_ids": True})
    choice = result["choices"][0]
    ids, probabilities = choice["token_ids"], choice["logprobs"]["token_logprobs"]
    assert ids and len(ids) == len(probabilities)
    assert all(x is not None and math.isfinite(x) for x in probabilities)
    return choice


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--server", default="http://127.0.0.1:8000")
    p.add_argument("--adapter")
    p.add_argument("--next-adapter")
    p.add_argument("--output", default="reports/vllm-check.json")
    args = p.parse_args()
    import uuid
    models = request(args.server, "/v1/models")["data"]
    result = {"base": completion(args.server, models[0]["id"])}
    names = []
    try:
        for i, path in enumerate([args.adapter, args.next_adapter]):
            if not path:
                continue
            from check_adapter_dtypes import check
            check(path)
            name = f"preflight-{uuid.uuid4().hex}-v{i}"
            request(args.server, "/v1/load_lora_adapter", {"lora_name": name,
                    "lora_path": str(Path(path).resolve()), "load_inplace": False})
            names.append(name)
            result[name] = completion(args.server, name)
        if len(names) == 2:
            old_again = completion(args.server, names[0])
            assert old_again["token_ids"] == result[names[0]]["token_ids"], "Old policy changed after publishing next version"
            old_probs = result[names[0]]["logprobs"]["token_logprobs"]
            new_probs = old_again["logprobs"]["token_logprobs"]
            assert all(abs(a - b) < 0.02 for a, b in zip(old_probs, new_probs, strict=True)), "Old adapter logprobs drifted"
            result["old_policy_still_available"] = True
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2))
        print(f"PASS: {output}")
    finally:
        for name in names:
            request(args.server, "/v1/unload_lora_adapter", {"lora_name": name})


if __name__ == "__main__":
    main()
