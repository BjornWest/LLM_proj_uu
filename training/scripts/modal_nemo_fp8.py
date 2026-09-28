#!/usr/bin/env python3
"""Isolated NeMo FP8 qualification; CPU preparation precedes one bounded H100 call."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import uuid

import modal

ROOT = Path(__file__).resolve().parents[1]
# NVIDIA NeMo-RL v0.7.0, linux/amd64 manifest (not a moving release tag).
CONTAINER = "nvcr.io/nvidia/nemo-rl@sha256:9392cc2cc07140f6a4cbd30f31ebffd0a54de3ded25c5a3b49505407a779e4f9"
SOURCES = [ROOT / "scripts/modal_nemo_fp8.py", ROOT / "scripts/nemo_fp8_probe.py", ROOT / "browser_training/processes.py"]
image = modal.Image.from_registry(CONTAINER, add_python="3.13").env({
    "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "WANDB_MODE": "disabled",
    "PYTHONUNBUFFERED": "1", "NVTE_FP8_BLOCK_SCALING_FP32_SCALES": "1",
    "TOKENIZERS_PARALLELISM": "false", "PYTHONPATH": "/opt/probe:/opt/probe/scripts",
})
for source in SOURCES:
    image = image.add_local_file(source, "/opt/probe/" + str(source.relative_to(ROOT)))
results = modal.Volume.from_name("browser-training-results", create_if_missing=True)
app = modal.App("browser-training-nemo-fp8-probe", image=image, include_source=False)


@app.function(cpu=2, memory=8192, timeout=240, startup_timeout=60, retries=0, max_containers=1, scaledown_window=2)
def prepare():
    from browser_training.processes import run_logged
    log = Path("/tmp/nemo-inventory.log")
    status = run_logged(["/opt/nemo_rl_venv/bin/python", "/opt/probe/scripts/nemo_fp8_probe.py",
                         "--inventory", "--output", "/tmp/nemo-inventory.json"], log,
                        cwd="/opt/nemo-rl", env=os.environ.copy(), timeout=200)
    if status:
        raise RuntimeError(f"CPU inventory failed (exit {status}); see streamed preparation log")
    report = json.loads(Path("/tmp/nemo-inventory.json").read_text())
    if not report.get("python"):
        raise RuntimeError("No preinstalled Megatron/TE environment; GPU will not start")
    return report


@app.function(gpu="H100", cpu=4, memory=16384, timeout=510, startup_timeout=60,
              retries=0, max_containers=1, scaledown_window=2, volumes={"/results": results})
def gpu_probe(run_id, prepared, outer_deadline, stages_to_run=("linear", "hybrid"), execution_seconds=510):
    import traceback
    from browser_training.processes import run_logged
    started = time.time()
    if not 120 <= execution_seconds <= 510 or any(s not in ("linear", "hybrid", "export") for s in stages_to_run):
        raise ValueError("Invalid probe scope or execution budget")
    deadline = min(outer_deadline - 30, started + execution_seconds - 30)
    if deadline - started < 60:
        raise TimeoutError("GPU authorization window expired")
    results.reload()
    run = Path("/results") / run_id
    if run.exists():
        raise RuntimeError("Refusing replay of an existing run")
    run.mkdir()
    (run / "started.json").write_text(json.dumps({"started": started, "deadline": deadline}))
    results.commit()
    stages = []
    for stage in stages_to_run:
        stage_started = time.time()
        try:
            status = run_logged([prepared["python"], "/opt/probe/scripts/nemo_fp8_probe.py",
                                 "--stage", stage, "--output", str(run / f"{stage}.json")],
                                run / f"{stage}.log", cwd="/opt/nemo-rl", env=os.environ.copy(),
                                timeout=min(240 if len(stages_to_run) == 1 else 210, deadline - time.time()))
            item = {"stage": stage, "exit_code": status}
        except Exception:
            item = {"stage": stage, "exit_code": -1, "error": traceback.format_exc()}
        # A probe may write a complete result and then time out during final
        # output/cleanup. Preserve its evidence while keeping the launch failed.
        if (run / f"{stage}.json").exists():
            try:
                item["result"] = json.loads((run / f"{stage}.json").read_text())
            except (OSError, json.JSONDecodeError) as error:
                item["artifact_error"] = str(error)
        item["elapsed_seconds"] = time.time() - stage_started
        stages.append(item)
        results.commit()
        # The hybrid experiment depends on the elementary backward test.
        if item["exit_code"]:
            break
    report = {"status": "PASS" if len(stages) == len(stages_to_run) and all(s["exit_code"] == 0 for s in stages) else "FAIL",
              "stages": stages, "elapsed_seconds": time.time() - started, "run_id": run_id}
    (run / "report.json").write_text(json.dumps(report, indent=2))
    results.commit()
    return report


def main():
    from dotenv import dotenv_values
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--stage", choices=("both", "linear", "hybrid", "export"), default="both")
    parser.add_argument("--gpu-seconds", type=int, choices=range(240, 601), default=600)
    parser.add_argument("--prepared-inventory", type=Path, help="Reuse a successful inventory for this exact container digest")
    args = parser.parse_args()
    cached_inventory = None
    if args.prepared_inventory:
        donor_plan = json.loads(args.prepared_inventory.with_name("plan.json").read_text())
        cached_inventory = json.loads(args.prepared_inventory.read_text())
        if (donor_plan.get("container") != CONTAINER or not cached_inventory.get("python")
                or cached_inventory.get("api_check", {}).get("returncode") != 0
                or "nemo_rl.models.policy.workers.megatron_policy_worker.MegatronPolicyWorker" not in cached_inventory["python"]):
            raise SystemExit("Inventory is not a successful policy-worker check for this exact container")
    plan = {"container": CONTAINER, "gpu": "H100", "gpu_count": 1,
            "gpu_window_seconds": args.gpu_seconds, "function_timeout_seconds": args.gpu_seconds - 90,
            "startup_timeout_seconds": 60, "retries": 0, "model_downloads": False,
            "scope": "random small TE/Megatron modules; no GRPO or pretrained-model qualification", "stage": args.stage,
            "source_sha256": {str(s.relative_to(ROOT)): hashlib.sha256(s.read_bytes()).hexdigest() for s in SOURCES}}
    if cached_inventory:
        plan["reused_inventory_sha256"] = hashlib.sha256(args.prepared_inventory.read_bytes()).hexdigest()
    if args.dry_run:
        print(json.dumps(plan, indent=2))
        return
    for key, value in dotenv_values(ROOT.parent / ".env").items():
        if key in ("MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET") and value:
            os.environ.setdefault(key, value)
    if not all(os.environ.get(k) for k in ("MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET")):
        raise SystemExit("Modal token pair missing")
    run_id = time.strftime("nemo-fp8-%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8]
    local = ROOT / "outputs/modal" / run_id
    local.mkdir(parents=True)
    plan["git_commit"] = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    (local / "plan.json").write_text(json.dumps(plan, indent=2))
    for source in SOURCES:
        dest = local / "sources" / source.relative_to(ROOT)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(source.read_bytes())
    with modal.enable_output(), app.run():
        (local / "app.json").write_text(json.dumps({"app_id": app.app_id, "url": app.get_dashboard_url()}))
        if cached_inventory:
            prepared = cached_inventory
        else:
            preparation = prepare.spawn()
            try:
                prepared = preparation.get(timeout=300)
            finally:
                preparation.cancel(terminate_containers=True)
        (local / "inventory.json").write_text(json.dumps(prepared, indent=2))
        if args.prepare_only:
            print(json.dumps(prepared, indent=2))
            return
        deadline = time.time() + args.gpu_seconds
        stages = ("linear", "hybrid") if args.stage == "both" else (args.stage,)
        execution_seconds = args.gpu_seconds - 90
        call = gpu_probe.with_options(timeout=execution_seconds).spawn(run_id, prepared, deadline, stages, execution_seconds)
        (local / "call.json").write_text(json.dumps({"call_id": call.object_id, "deadline": deadline}))
        try:
            report = call.get(timeout=max(1, deadline - time.time()))
        finally:
            call.cancel(terminate_containers=True)
        (local / "report.json").write_text(json.dumps(report, indent=2))
        print(json.dumps(report, indent=2))
        print(f"Artifacts: {local}; browser-training-results/{run_id}")
        if report["status"] != "PASS":
            raise SystemExit(1)


if __name__ == "__main__":
    main()
