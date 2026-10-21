#!/usr/bin/env python3
"""Run a foreground job and its descendants in a memory-capped user scope.

CPU affinity is intentional: this WSL installation delegates memory/pids, not
the cpu/cpuset controllers. Never silently fall back to an unbounded process.
See docs/agents/local-resource-limits.md.
"""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid

SLICE = "llmjobs.slice"
GIB = 1024 ** 3
SHARED_MAX = 23 * GIB
SHARED_HIGH = 23 * GIB
ROOT = Path(__file__).resolve().parents[1]


def write_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def cpu_pool():
    # A common set across simultaneous launchers; reserve the other CPUs for
    # interactive work. On this workstation: 4-11 of the 24 logical CPUs.
    online = []
    for part in Path("/sys/devices/system/cpu/online").read_text().strip().split(","):
        bounds = [int(x) for x in part.split("-")]
        online.extend(range(bounds[0], bounds[-1] + 1))
    if len(online) < 2:
        raise RuntimeError("Need at least two online CPUs to reserve interactive capacity")
    # BOUNDED_JOB_CPUS: "all", or "a-b". Default: every CPU except the first two,
    # which stay free for the desktop/interactive sessions (owner decision 2026-10-20;
    # the old 4-11 pool left 16 of 24 cores idle during overnight runs).
    spec = os.environ.get("BOUNDED_JOB_CPUS", "")
    if spec == "all":
        chosen = online
    elif "-" in spec:
        lo, hi = (int(x) for x in spec.split("-", 1))
        chosen = [c for c in online if lo <= c <= hi]
    else:
        chosen = online[2:] if len(online) > 4 else online
    pool = set(chosen) & os.sched_getaffinity(0)
    if not pool:
        raise RuntimeError("Launcher affinity does not intersect the shared job CPU pool")
    return sorted(pool)


def cgroup_self():
    for line in Path("/proc/self/cgroup").read_text().splitlines():
        if line.startswith("0::"):
            return Path("/sys/fs/cgroup") / line[3:].lstrip("/")
    raise RuntimeError("cgroup v2 is required")


def counters(path):
    data = {}
    for name in ("memory.current", "memory.peak", "memory.events", "memory.swap.current",
                 "pids.current", "pids.peak", "cpu.stat"):
        try:
            value = (path / name).read_text().strip()
            data[name] = ({key: int(number) for key, number in
                           (line.split() for line in value.splitlines())}
                          if name.endswith(("events", "stat")) else int(value))
        except (OSError, ValueError):
            pass
    return data


def enter(args):
    """Verify effective limits inside the scope before starting user code."""
    group = cgroup_self()
    if group.parent.name != SLICE:
        raise RuntimeError("Job is outside the shared resource slice")
    expected = {"memory.max": args.memory_mib * 1024 ** 2,
                "memory.swap.max": 0, "pids.max": args.tasks or "max"}
    for name, value in expected.items():
        if (group / name).read_text().strip() != str(value):
            raise RuntimeError(f"Effective {name} differs from requested limit")
    for name, value in {"memory.max": SHARED_MAX, "memory.high": SHARED_HIGH,
                        "memory.swap.max": 0}.items():
        if (group.parent / name).read_text().strip() != str(value):
            raise RuntimeError(f"Shared {name} differs from resource policy")
    pool = cpu_pool()
    os.sched_setaffinity(0, pool)
    (group / "memory.oom.group").write_text("1")
    if (group / "memory.oom.group").read_text().strip() != "1":
        raise RuntimeError("Cannot enable whole-job OOM cleanup")
    os.nice(10)
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                 "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "RAYON_NUM_THREADS",
                 "POLARS_MAX_THREADS"):
        os.environ[name] = "2"
    write_json(args.receipt / "entry.json", {
        "pid": os.getpid(), "unit": args.unit, "cgroup": str(group),
        "cpus": sorted(os.sched_getaffinity(0)), "limits": expected,
        "memory_oom_group": 1, "nice": os.getpriority(os.PRIO_PROCESS, 0),
        "thread_environment_limit": 2,
    })
    os.execvpe(args.command[0], args.command, os.environ)


def cleanup(unit):
    # Foreground commands must not leave detached browsers/workers running.
    completed = subprocess.run(["systemctl", "--user", "kill", "--kill-who=all",
                                "--signal=SIGKILL", unit], capture_output=True, timeout=5)
    return {"kill_returncode": completed.returncode,
            "note": "Already-removed unit is normal after foreground exit"}


def run(args):
    if not 32 <= args.memory_mib <= SHARED_MAX // (1024 ** 2):
        raise ValueError(f"Per-job memory must be 32-{SHARED_MAX // (1024 ** 2)} MiB")
    # --tasks 0 removes the per-job task cap (deployments, many-browser cohorts);
    # memory stays the only bound then.
    if args.tasks != 0 and not 16 <= args.tasks <= 512:
        raise ValueError("Per-job tasks must be 16-512, or 0 for no task cap")
    pool = cpu_pool()
    subprocess.run(["systemctl", "--user", "set-property", "--runtime", SLICE,
                    "MemoryAccounting=yes", f"MemoryHigh={SHARED_HIGH}",
                    f"MemoryMax={SHARED_MAX}", "MemorySwapMax=0", "TasksMax=infinity"],
                   check=True, timeout=10)
    args.unit = "llmjob-" + uuid.uuid4().hex[:16] + ".scope"
    args.receipt = (args.receipt or ROOT / ".local" / "bounded-jobs" / args.unit[:-6]).resolve()
    args.receipt.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    write_json(args.receipt / "launch.json", {
        "started_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "unit": args.unit, "cwd": str(Path.cwd()), "launcher_pid": os.getpid(),
        # Avoid recording credentials that could be present in command arguments.
        "executable": Path(args.command[0]).name, "argument_count": len(args.command) - 1,
        "cpu_pool": pool, "memory_mib": args.memory_mib, "shared_memory_max": SHARED_MAX,
        "tasks": args.tasks, "automatic_retries": 0,
    })
    print(f"Bounded job: {args.unit}; receipt: {args.receipt}", file=sys.stderr, flush=True)
    invocation = ["systemd-run", "--user", "--scope", "--quiet", "--slice=" + SLICE,
                  "--unit=" + args.unit, "-p", f"MemoryMax={args.memory_mib}M",
                  # Do not stall a single oversize allocation in reclaim well
                  # below its hard cap. Shared MemoryHigh still limits pressure.
                  "-p", f"MemoryHigh={args.memory_mib}M",
                  "-p", "MemorySwapMax=0", "-p", f"TasksMax={args.tasks or 'infinity'}",
                  sys.executable, str(Path(__file__).resolve()), "--enter",
                  "--unit", args.unit, "--receipt", str(args.receipt),
                  "--memory-mib", str(args.memory_mib), "--tasks", str(args.tasks),
                  "--", *args.command]
    child = subprocess.Popen(invocation, start_new_session=True)
    previous_handlers = {}
    interrupted = []

    def stop(signum, _frame):
        interrupted.append(signum)
        cleanup(args.unit)
        try:
            os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass

    for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        previous_handlers[signum] = signal.signal(signum, stop)
    last = {}
    try:
        with (args.receipt / "resources.jsonl").open("w") as stream:
            while True:
                entry_path = args.receipt / "entry.json"
                if entry_path.exists():
                    entry = json.loads(entry_path.read_text())
                    group = Path(entry["cgroup"])
                    sample = {"elapsed_s": round(time.monotonic() - started, 3),
                              "job": counters(group), "shared_slice": counters(group.parent)}
                    if sample["job"]:
                        last = sample
                        stream.write(json.dumps(sample) + "\n")
                        stream.flush()
                if child.poll() is not None:
                    break
                time.sleep(0.25)
    finally:
        cleaned = cleanup(args.unit)
        if child.poll() is None:
            try:
                child.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait(timeout=3)
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)
    result = {"returncode": child.returncode, "elapsed_s": round(time.monotonic() - started, 3),
              "entry_verified": (args.receipt / "entry.json").exists(),
              "last_observed": last, "cleanup": cleaned, "interrupt_signals": interrupted,
              "telemetry": "Sampled at 250ms; short jobs may exit before a resource sample"}
    write_json(args.receipt / "result.json", result)
    return child.returncode if child.returncode >= 0 else 128 - child.returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--memory-mib", type=int, default=6144)
    parser.add_argument("--tasks", type=int, default=256)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--enter", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--unit", help=argparse.SUPPRESS)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.command[:1] == ["--"]:
        args.command = args.command[1:]
    if not args.command:
        parser.error("Specify a foreground command after --")
    try:
        return enter(args) if args.enter else run(args)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"Bounded job refused or failed: {error}", file=sys.stderr)
        return 125


if __name__ == "__main__":
    sys.exit(main())
