#!/usr/bin/env python3
"""Bounded serving-only throughput probe; run separately for each vLLM preset."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import time
import urllib.request
from check_vllm import request


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--server", default="http://127.0.0.1:8000")
    p.add_argument("--model", help="Adapter name from /v1/models, or the base model")
    p.add_argument("--concurrency", type=int, default=4)
    p.add_argument("--requests", type=int, default=16)
    p.add_argument("--tokens", type=int, default=128)
    p.add_argument("--output", required=True)
    args = p.parse_args()
    if not 1 <= args.concurrency <= 64 or not 1 <= args.requests <= 256:
        p.error("Bounded benchmark: concurrency 1–64, requests 1–256")
    model = args.model or request(args.server, "/v1/models")["data"][0]["id"]
    def metrics():
        with urllib.request.urlopen(args.server + "/metrics", timeout=30) as response:
            return response.read().decode()
    def generate(i):
        start = time.monotonic()
        response = request(args.server, "/v1/completions", {"model": model,
            "prompt": f"Browser task {i}: describe a careful sequence of actions to fill a form.",
            "max_tokens": args.tokens, "temperature": 1.0, "top_p": 1.0, "top_k": -1, "seed": 42 + i})
        return {"seconds": time.monotonic() - start, "tokens": response["usage"]["completion_tokens"]}
    generate(-1)
    before = metrics()
    start = time.monotonic()
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        rows = list(pool.map(generate, range(args.requests)))
    elapsed = time.monotonic() - start
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"config": vars(args), "model": model, "wall_seconds": elapsed,
        "tokens_per_second": sum(row["tokens"] for row in rows) / elapsed,
        "requests_per_second": len(rows) / elapsed, "requests": rows}, indent=2))
    output.with_suffix(".before.prom").write_text(before)
    output.with_suffix(".after.prom").write_text(metrics())
    print(output.read_text())


if __name__ == "__main__":
    main()
