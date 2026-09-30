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
    if preset not in ("baseline", "mtp") or kv_dtype not in ("auto", "fp8", "fp8_e4m3"):
        raise ValueError("Unsupported benchmark preset/cache dtype")
    if context <= 0 or not 0 < memory_fraction < 1:
        raise ValueError("Context must be positive; memory fraction must be between 0 and 1")
    cmd = [str(vllm), "serve", FP8, "--revision", REVISIONS[FP8], "--tokenizer-revision", REVISIONS[FP8],
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
    if kwargs.get("context", 65536) < max(c.input_tokens + c.prefix_tokens + c.output_tokens for c in CASES):
        raise ValueError("Context must fit every smoke case")
    return {"model": FP8, "revision": REVISIONS[FP8],
            "server": server_command(vllm, **kwargs),
            "cases": [asdict(case) for case in CASES],
            "extra_requests": "one warmup for the cached case only; native initial request disabled",
            "caveat": "Synthetic tokens; cached input throughput is logical, not fresh prefill compute."}


def residency_server_command(vllm, *, port=8000, preset="baseline", kv_dtype="fp8_e4m3",
                             eager=False, prefix_caching=False):
    if kv_dtype not in ("auto", "fp8", "fp8_e4m3"):
        raise ValueError("Unsupported cache dtype")
    # Match the prior exact-model RTX suite, keeping our pinned vLLM version.
    cmd = server_command(vllm, port=port, preset=preset, context=31008,
                         memory_fraction=0.95, kv_dtype="auto", eager=eager)
    for flag, value in (("--max-num-seqs", "256"), ("--kv-cache-dtype", kv_dtype),
                        ("--mamba-cache-mode", "align" if prefix_caching else "none")):
        cmd[cmd.index(flag) + 1] = value
    if not prefix_caching:
        cmd[cmd.index("--enable-prefix-caching")] = "--no-enable-prefix-caching"
    cmd += ["--mamba-cache-dtype", "bfloat16", "--mamba-ssm-cache-dtype", "float32",
            "--gdn-prefill-backend", "triton", "--enable-prompt-tokens-details"]
    return cmd


def residency_cases(capacities):
    long = capacities["30000"]["max_concurrency"]
    short = capacities["5000"]["max_concurrency"]
    # Maximum-residency points first. Half-capacity short decode tests whether
    # the throughput optimum is below the memory ceiling.
    return [Case("decode-30k", 30000, 1000, long, long),
            Case("decode-5k", 5000, 1000, short, short),
            Case("prefill-30k", 30000, 1, long, long),
            Case("prefill-5k", 5000, 1, short, short),
            Case("decode-5k-half", 5000, 1000, max(1, short // 2), max(1, short // 2))]


def residency_bench_command(vllm, case, *, output, dataset, tokenizer, port=8000):
    return [str(vllm), "bench", "serve", "--backend", "vllm", "--base-url", f"http://127.0.0.1:{port}",
            "--endpoint", "/v1/completions", "--model", FP8, "--tokenizer", str(tokenizer),
            "--dataset-name", "custom", "--dataset-path", str(dataset), "--skip-chat-template",
            "--disable-shuffle", "--no-oversample", "--custom-output-len", str(case.output_tokens),
            "--num-prompts", str(case.requests), "--max-concurrency", str(case.concurrency),
            "--request-rate", "inf", "--num-warmups", "0", "--ready-check-timeout-sec", "0",
            "--temperature", "0", "--ignore-eos", "--disable-tqdm", "--save-result", "--save-detailed",
            "--result-dir", str(output), "--result-filename", case.name + ".json"]


def residency_plan(vllm, **kwargs):
    return {"model": FP8, "revision": REVISIONS[FP8], "suite": "residency",
            "server": residency_server_command(vllm, **kwargs),
            "input_tokens": [30000, 5000], "output_tokens": {"decode": 1000, "prefill": 1},
            "concurrency": "resolved from final hybrid-aware startup capacity, scheduler ceiling 256",
            "arms": ["decode-30k", "decode-5k", "prefill-30k", "prefill-5k", "decode-5k-half"],
            "maximum_requests": 1152, "repeats": 1, "extra_model_requests": 0,
            "caveat": "Cold finite cohorts; only guarded full-concurrency intervals qualify as decode-only."}
