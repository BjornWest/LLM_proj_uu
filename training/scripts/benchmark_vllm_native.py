#!/usr/bin/env python3
"""Run finite native benchmarks; raw metrics/logs preserved even on failure."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import signal
import sys
import time
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from browser_training.vllm_speed import CASES, bench_command, plan, server_command
from browser_training.vllm_speed import (residency_plan, residency_server_command,
                                         residency_cases, residency_bench_command)
from browser_training.vllm_capacity import read_capacity
from browser_training.vllm_phases import Sampler, parse_metrics, summarize_phases
from browser_training.launch import FP8, MODEL_CACHE_PATTERNS, REVISIONS


def fetch(url, method="GET"):
    with urlopen(Request(url, method=method), timeout=10) as response:
        return response.read().decode()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--vllm", default="envs/rl/.venv/bin/vllm")
    p.add_argument("--output", type=Path, default=Path("outputs/packet/benchmark"))
    p.add_argument("--preset", choices=["baseline", "mtp"], default="baseline")
    p.add_argument("--suite", choices=["smoke", "residency"], default="residency")
    p.add_argument("--seconds", type=int, default=900)
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--kv-dtype", choices=["auto", "fp8", "fp8_e4m3"])
    p.add_argument("--prefix-caching", action="store_true", help="Residency suite: test APC align instead of prior cold/no-APC recipe")
    p.add_argument("--eager", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    if args.seconds <= 0:
        p.error("seconds must be positive")
    dtype = args.kv_dtype or ("fp8_e4m3" if args.suite == "residency" else "auto")
    options = dict(preset=args.preset, port=args.port, kv_dtype=dtype, eager=args.eager)
    if args.suite == "residency":
        options["prefix_caching"] = args.prefix_caching
        config = residency_plan(args.vllm, **options)
        server = residency_server_command(args.vllm, **options)
        # Same interpreter as the server's vllm binary; probe loads in spawn children.
        server = [str(Path(args.vllm).parent / "python"),
                  str(Path(__file__).with_name("vllm_benchmark_server.py")), *server[1:]]
    else:
        config = plan(args.vllm, **options)
        server = server_command(args.vllm, **options)
    config["server"] = server
    if args.dry_run:
        print(json.dumps(config, indent=2))
        return
    # Heavy imports only on the rented worker; tokenizer pinned to the loaded revision.
    from huggingface_hub import snapshot_download
    tokenizer = snapshot_download(FP8, revision=REVISIONS[FP8], local_files_only=True,
                                  allow_patterns=MODEL_CACHE_PATTERNS)
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "plan.json").write_text(json.dumps(config, indent=2))
    started = time.monotonic()
    deadline = started + args.seconds
    base = f"http://127.0.0.1:{args.port}"
    outcomes = []
    proc = None
    complete = False
    with (args.output / "server.log").open("w") as log:
        try:
            proc = subprocess.Popen(server,
                                    stdout=log, stderr=subprocess.STDOUT,
                                    env={**os.environ, "VLLM_SERVER_DEV_MODE": "1", "VLLM_LOG_STATS_INTERVAL": "1",
                                         "PYTHONPATH": str(Path(__file__).resolve().parents[1])}, start_new_session=True)
            while True:
                if proc.poll() is not None:
                    raise RuntimeError("vLLM server exited; inspect server.log")
                if time.monotonic() >= deadline:
                    raise TimeoutError("Deadline reached while loading the server")
                try:
                    fetch(base + "/health")
                    break
                except OSError:
                    time.sleep(2)
            cases, datasets = CASES, {}
            if args.suite == "residency":
                from transformers import AutoTokenizer
                from browser_training.browser_benchmark_prompts import write_dataset
                capacities = read_capacity((args.output / "server.log").read_text())
                cases = residency_cases(capacities)
                config["capacities"] = capacities
                config["resolved_cases"] = [vars(case) for case in cases]
                tok = AutoTokenizer.from_pretrained(tokenizer, local_files_only=True)
                for isl in (30000, 5000):
                    datasets[isl] = args.output / f"browser-{isl}.jsonl"
                    metadata = write_dataset(tok, datasets[isl], isl, capacities[str(isl)]["max_concurrency"])
                    (args.output / f"browser-{isl}-manifest.json").write_text(json.dumps(metadata, indent=2))
                (args.output / "plan.json").write_text(json.dumps(config, indent=2))
            for index, case in enumerate(cases):
                if deadline - time.monotonic() < 30:
                    raise TimeoutError("No time left for another finite cohort; preserving partial coverage")
                # Isolate each case. Only the cached case has a warmup; native
                # initial checks would cache the first measured cold request.
                reset = json.loads(fetch(base + "/reset_prefix_cache", method="POST"))
                if not reset.get("success"):
                    raise RuntimeError("Prefix cache reset failed; refusing to label the next case cold")
                before_text = fetch(base + "/metrics")
                (args.output / (case.name + "-metrics-before.prom")).write_text(before_text)
                if args.suite == "residency":
                    command = residency_bench_command(args.vllm, case, output=args.output,
                                                      dataset=datasets[case.input_tokens],
                                                      tokenizer=tokenizer, port=args.port)
                else:
                    command = bench_command(args.vllm, case, output=args.output,
                                            tokenizer=tokenizer, port=args.port, seed=123 + index)
                case_start = time.monotonic()
                outcome = {"case": case.name, "input_tokens": case.input_tokens,
                           "output_tokens": case.output_tokens, "concurrency": case.concurrency,
                           "exit_code": None, "command": command}
                outcomes.append(outcome)
                try:
                    with Sampler(base + "/metrics", args.output / (case.name + "-metrics.jsonl")) as sampler, \
                         (args.output / (case.name + ".log")).open("w") as case_log:
                        run = subprocess.run(command, stdout=case_log, stderr=subprocess.STDOUT,
                                             timeout=max(0.1, deadline - time.monotonic()))
                    outcome["exit_code"] = run.returncode
                except subprocess.TimeoutExpired:
                    outcome["error"] = "case deadline exceeded"
                    raise
                finally:
                    outcome["seconds"] = time.monotonic() - case_start
                after_text = fetch(base + "/metrics")
                (args.output / (case.name + "-metrics-after.prom")).write_text(after_text)
                if run.returncode:
                    raise RuntimeError(f"Native benchmark {case.name} failed; inspect its log")
                result = json.loads((args.output / (case.name + ".json")).read_text())
                if result.get("completed") != case.requests or result.get("failed", 0):
                    raise RuntimeError(f"Incomplete native benchmark {case.name}")
                if args.suite == "residency":
                    if (result.get("input_lens") != [case.input_tokens] * case.requests
                            or result.get("output_lens") != [case.output_tokens] * case.requests):
                        raise RuntimeError("Native request geometry differs from the capacity reservation")
                    before, after = parse_metrics(before_text), parse_metrics(after_text)
                    required = ("vllm:num_preemptions_total", "computed_prompt_tokens",
                                "vllm:generation_tokens_total", "vllm:prefix_cache_hits_total")
                    if any(key not in before or key not in after for key in required):
                        raise RuntimeError("Missing server counters needed to validate the measurement")
                    preemptions = after.get("vllm:num_preemptions_total", 0) - before.get("vllm:num_preemptions_total", 0)
                    if preemptions:
                        raise RuntimeError("Preemption invalidated the near-capacity cohort")
                    if not args.prefix_caching and (after.get("vllm:prefix_cache_hits_total", 0)
                                                   != before.get("vllm:prefix_cache_hits_total", 0)):
                        raise RuntimeError("Unexpected cache hits in a cold residency case")
                phases = summarize_phases(result, sampler.rows, case.concurrency)
                (args.output / (case.name + "-phases.json")).write_text(json.dumps(phases, indent=2))
                outcomes[-1]["phases"] = phases
                outcomes[-1]["native_metrics"] = {key: result.get(key) for key in (
                    "duration", "completed", "failed", "total_input_tokens", "total_output_tokens",
                    "output_throughput", "mean_ttft_ms", "mean_tpot_ms", "p99_ttft_ms")}
                decode = {k: v for k, v in (phases.get("decode") or {}).items() if k != "segments"}
                print(case.name, json.dumps({"native": outcomes[-1]["native_metrics"], "decode": decode,
                                             "prefill": phases.get("pure_prefill"),
                                             "max_active_kv_fraction": phases.get("max_sampled_kv_fraction")}), flush=True)
            complete = True
        finally:
            if proc is not None:
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    proc.wait()
            (args.output / "execution.json").write_text(json.dumps({
                "wall_seconds": time.monotonic() - started, "cases": outcomes,
                "complete": complete,
                "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
                "note": "Residency has no warmups; only smoke's cached case wall time includes a warmup."
            }, indent=2))


if __name__ == "__main__":
    main()
