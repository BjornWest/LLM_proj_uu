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
from browser_training.launch import FP8, REVISIONS


def fetch(url, method="GET"):
    with urlopen(Request(url, method=method), timeout=10) as response:
        return response.read().decode()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--vllm", default="envs/rl/.venv/bin/vllm")
    p.add_argument("--output", type=Path, default=Path("outputs/packet/benchmark"))
    p.add_argument("--preset", choices=["baseline", "mtp"], default="baseline")
    p.add_argument("--seconds", type=int, default=900)
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--kv-dtype", choices=["auto", "fp8"], default="auto")
    p.add_argument("--eager", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    if args.seconds <= 0:
        p.error("seconds must be positive")
    config = plan(args.vllm, preset=args.preset, port=args.port, kv_dtype=args.kv_dtype, eager=args.eager)
    if args.dry_run:
        print(json.dumps(config, indent=2))
        return
    # Heavy imports only on the rented worker; tokenizer pinned to the loaded revision.
    from huggingface_hub import snapshot_download
    tokenizer = snapshot_download(FP8, revision=REVISIONS[FP8], local_files_only=True)
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "plan.json").write_text(json.dumps(config, indent=2))
    started = time.monotonic()
    deadline = started + args.seconds
    base = f"http://127.0.0.1:{args.port}"
    outcomes = []
    proc = None
    with (args.output / "server.log").open("w") as log:
        try:
            proc = subprocess.Popen(server_command(args.vllm, preset=args.preset, port=args.port,
                                                    kv_dtype=args.kv_dtype, eager=args.eager),
                                    stdout=log, stderr=subprocess.STDOUT,
                                    env={**os.environ, "VLLM_SERVER_DEV_MODE": "1"}, start_new_session=True)
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
            for index, case in enumerate(CASES):
                # Isolate each case. Only the cached case has a warmup; native
                # initial checks would cache the first measured cold request.
                reset = json.loads(fetch(base + "/reset_prefix_cache", method="POST"))
                if not reset.get("success"):
                    raise RuntimeError("Prefix cache reset failed; refusing to label the next case cold")
                (args.output / (case.name + "-metrics-before.prom")).write_text(fetch(base + "/metrics"))
                command = bench_command(args.vllm, case, output=args.output,
                                        tokenizer=tokenizer, port=args.port, seed=123 + index)
                case_start = time.monotonic()
                with (args.output / (case.name + ".log")).open("w") as case_log:
                    run = subprocess.run(command, stdout=case_log, stderr=subprocess.STDOUT,
                                         timeout=max(0.1, deadline - time.monotonic()))
                outcomes.append({"case": case.name, "seconds": time.monotonic() - case_start,
                                 "exit_code": run.returncode, "command": command})
                (args.output / (case.name + "-metrics-after.prom")).write_text(fetch(base + "/metrics"))
                if run.returncode:
                    raise RuntimeError(f"Native benchmark {case.name} failed; inspect its log")
                result = json.loads((args.output / (case.name + ".json")).read_text())
                if result.get("completed") != case.requests or result.get("failed", 0):
                    raise RuntimeError(f"Incomplete native benchmark {case.name}")
                outcomes[-1]["native_metrics"] = {key: result.get(key) for key in (
                    "duration", "completed", "failed", "total_input_tokens", "total_output_tokens",
                    "output_throughput", "mean_ttft_ms", "mean_tpot_ms", "p99_ttft_ms")}
                print(case.name, json.dumps(outcomes[-1]["native_metrics"]), flush=True)
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
                "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
                "note": "cached case wall time includes its warmup; native duration excludes it"
            }, indent=2))


if __name__ == "__main__":
    main()
