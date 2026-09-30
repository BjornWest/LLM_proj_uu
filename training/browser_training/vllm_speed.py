"""Native vLLM benchmark commands, kept importable without CUDA dependencies."""
from dataclasses import asdict, dataclass
import json
from .launch import FP8, REVISIONS


@dataclass(frozen=True)
class Case:
    name: str
    input_tokens: int
    output_tokens: int
    concurrency: int
    requests: int
    prefix_tokens: int = 0


CASES = (
    Case("decode-c1", 512, 512, 1, 16),
    Case("decode-c4", 512, 512, 4, 32),
    Case("decode-c16", 512, 512, 16, 64),
    Case("prefill-8k", 8192, 16, 4, 32),
    Case("cached-8k", 256, 256, 4, 32, 8192),
    Case("context-32k", 32768, 128, 4, 8),
)


def server_command(vllm, *, port=8000, preset="baseline", context=65536,
                   memory_fraction=0.85, kv_dtype="auto", eager=False):
    if preset not in ("baseline", "mtp") or kv_dtype not in ("auto", "fp8"):
        raise ValueError("Unsupported benchmark preset/cache dtype")
    if context < 32768 + 128 or not 0 < memory_fraction < 1:
        raise ValueError("Context must fit all cases; memory fraction must be between 0 and 1")
    cmd = [str(vllm), "serve", FP8, "--revision", REVISIONS[FP8],
           "--host", "127.0.0.1", "--port", str(port), "--dtype", "bfloat16",
           "--language-model-only", "--generation-config", "vllm",
           "--enable-prefix-caching", "--mamba-cache-mode", "align",
           "--max-model-len", str(context), "--max-num-seqs", "16",
           "--max-num-batched-tokens", "8192", "--gpu-memory-utilization", str(memory_fraction),
           "--kv-cache-dtype", kv_dtype]
    if preset == "mtp":
        cmd += ["--speculative-config", json.dumps({"method": "mtp", "num_speculative_tokens": 3})]
    if eager:
        cmd += ["--enforce-eager"]
    return cmd


def bench_command(vllm, case, *, output, tokenizer=FP8, port=8000, seed=123):
    return [str(vllm), "bench", "serve", "--backend", "vllm",
            "--base-url", f"http://127.0.0.1:{port}", "--endpoint", "/v1/completions",
            "--model", FP8, "--tokenizer", str(tokenizer),
            "--dataset-name", "random", "--random-input-len", str(case.input_tokens),
            "--random-prefix-len", str(case.prefix_tokens),
            "--random-output-len", str(case.output_tokens), "--random-range-ratio", "0.0",
            "--num-prompts", str(case.requests), "--max-concurrency", str(case.concurrency),
            "--request-rate", "inf", "--num-warmups", "1" if case.prefix_tokens else "0",
            "--ready-check-timeout-sec", "0", "--seed", str(seed),
            "--ignore-eos", "--disable-tqdm", "--save-result", "--save-detailed",
            "--result-dir", str(output), "--result-filename", case.name + ".json"]


def plan(vllm, **kwargs):
    return {"model": FP8, "revision": REVISIONS[FP8],
            "server": server_command(vllm, **kwargs),
            "cases": [asdict(case) for case in CASES],
            "extra_requests": "one warmup for the cached case only; native initial request disabled",
            "caveat": "Synthetic tokens; cached input throughput is logical, not fresh prefill compute."}
