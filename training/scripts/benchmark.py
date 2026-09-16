#!/usr/bin/env python3
"""Bounded benchmark wrapper. GPU work occurs only when explicitly launched remotely."""
import argparse
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time


def summarize(output, elapsed, returncode):
    path = Path(output)
    records = [json.loads(line) for line in (path / "metrics.jsonl").read_text().splitlines()] if (path / "metrics.jsonl").exists() else []
    # Ignore the first five steps as warmup; retain all raw records in metrics.jsonl.
    warmed = [row for row in records if row.get("step", 0) > 5]
    steady = warmed or records
    counters = [row["tokens/trainable"] for row in records if "tokens/trainable" in row]
    counter_reset = any(b < a for a, b in zip(counters, counters[1:]))
    numeric = {}
    for row in steady:
        for name, value in row.items():
            if isinstance(value, (int, float)) and name not in {"step", "wall_time"}:
                if "per_sec" in name and (value < 0 or counter_reset):
                    continue  # Axolotl counters can reset on same-process resume.
                numeric.setdefault(name, []).append(value)
    means = {key: statistics.mean(values) for key, values in numeric.items()}
    # Axolotl counts both input+output slots and supervised tokens separately.
    tokens = max((r.get("tokens/trainable", 0) for r in records), default=0)
    rate = tokens / elapsed if tokens and elapsed > 0 and not counter_reset else None
    report = {"wall_seconds": elapsed, "returncode": returncode, "metric_means": means,
              "supervised_tokens_per_wall_second": rate,
              "seconds_per_million_supervised_tokens": 1e6 / rate if rate else None,
              "peak_vram_gib": max((r[k] for r in records for k in
                  ("peak_vram_gib", "memory/max_allocated (GiB)") if k in r), default=None),
              "token_counter_reset_detected": counter_reset, "warmup_excluded": bool(warmed)}
    phases = {key: means.get(key) for key in ("perf/step_s", "perf/fwd_bwd_s", "perf/weight_sync_s", "perf/rollout_wait_s")}
    report["trainer_phase_seconds"] = phases
    step = phases["perf/step_s"]
    report["trainer_phase_fractions"] = {k: v / step for k, v in phases.items() if v is not None} if step else {}
    report["note"] = "Generation overlaps training; do not sum rollout duration, trainer compute and synchronization as disjoint wall time. Missing metrics remain null."
    if counter_reset:
        report["note"] += " Token counters reset; aggregate token rates are suppressed."
    if not warmed:
        report["note"] += " No post-warmup samples; means include startup effects."
    (path / "benchmark-summary.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return report


def main():
    p = argparse.ArgumentParser()
    p.add_argument("kind", choices=["sft", "rl"])
    p.add_argument("--config")
    p.add_argument("--steps", type=int, default=20)
    p.add_argument("--output", required=True)
    args, rest = p.parse_known_args()
    if not 1 <= args.steps <= 100:
        p.error("Benchmark must be bounded to 1–100 optimizer steps")
    output = Path(args.output).resolve()
    if output.exists():
        p.error("Use a fresh benchmark output directory")
    # Store telemetry next to the trainer output so it doesn't trip the new-run guard.
    logs = output.with_name(output.name + "-telemetry")
    logs.mkdir(parents=True)
    script = "scripts/run_sft.sh" if args.kind == "sft" else "scripts/run_async_grpo.sh"
    command = [script, "--steps", str(args.steps), "--output", str(output)]
    if args.config:
        command += ["--config", args.config]
    command += rest
    with (logs / "gpu.csv").open("w") as gpu_log, (logs / "console.log").open("w") as console:
        gpu = subprocess.Popen(["nvidia-smi", "--query-gpu=timestamp,index,utilization.gpu,memory.used,power.draw",
                                "--format=csv", "--loop=1"], stdout=gpu_log, stderr=subprocess.STDOUT)
        start = time.monotonic()
        try:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            try:
                for line in process.stdout:
                    console.write(line)
                    print(line, end="", flush=True)
                code = process.wait()
            except BaseException:
                process.terminate()
                process.wait(timeout=20)
                raise
        finally:
            gpu.terminate()
            gpu.wait(timeout=10)
    output.mkdir(parents=True, exist_ok=True)
    summarize(output, time.monotonic() - start, code)
    sys.exit(code)


if __name__ == "__main__":
    main()
