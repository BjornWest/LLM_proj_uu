#!/usr/bin/env python3
"""One bounded L40S apple SFT test using cached weights; no automatic retries."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import uuid
import modal
from modal_training import ROOT, MODEL, REVISION, PYTHON, SOURCES as BASE_SOURCES, image as base_image, cache, results

EXTRA = [ROOT / "scripts" / n for n in ("modal_sft_learning.py", "sft_learning_probe.py")]
SOURCES = BASE_SOURCES + EXTRA
image = base_image
for source in EXTRA:
    image = image.add_local_file(source, "/opt/training/" + str(source.relative_to(ROOT)))
app = modal.App("browser-training-sft-learning", image=image, include_source=False)


@app.function(cpu=4, memory=16384, timeout=240, retries=0, max_containers=1,
              scaledown_window=2, volumes={"/model-cache": cache})
def prepare():
    from browser_training.processes import run_logged
    code = f"""
import json, subprocess, sys
from pathlib import Path
from huggingface_hub import snapshot_download
snapshot = snapshot_download({MODEL!r}, revision={REVISION!r}, local_files_only=True)
subprocess.run([sys.executable, 'scripts/sft_learning_probe.py', '--snapshot', snapshot,
               '--output', '/tmp/apple-preflight', '--prepare-only'], check=True)
report = json.loads(Path('/tmp/apple-preflight/dataset-report.json').read_text())
manifest = json.loads(Path(report['manifest']).read_text())
for name in ('pyproject.toml', 'uv.lock'):
    assert '/opt/sft/'+name in manifest['environment_file_sha256']
print(json.dumps({{'snapshot': snapshot, 'dataset': report}}))
"""
    log = Path("/tmp/apple-prepare.log")
    environment = dict(os.environ, HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", PYTHONUNBUFFERED="1")
    code = run_logged([PYTHON, "-c", code], log, cwd="/opt/training", env=environment, timeout=220)
    if code:
        raise RuntimeError(log.read_text()[-12000:])
    return json.loads(log.read_text().strip().splitlines()[-1])


@app.function(gpu="L40S", cpu=8, memory=65536, timeout=540, startup_timeout=60,
              retries=0, max_containers=1, scaledown_window=2,
              volumes={"/model-cache": cache, "/results": results})
def gpu_probe(run_id, prepared, outer_deadline, steps, execution_seconds):
    import traceback
    from browser_training.processes import run_logged
    started = time.time()
    if not 120 <= execution_seconds <= 540:
        raise ValueError("Execution budget must be 120..540 seconds")
    deadline = min(outer_deadline, started + execution_seconds - 30)
    if deadline - started < 120:
        raise TimeoutError("Authorization window exhausted")
    results.reload()
    run = Path("/results") / run_id
    if run.exists():
        raise RuntimeError("Refuse replay of an existing run")
    run.mkdir()
    (run / "started.json").write_text(json.dumps({"started": started, "deadline": deadline}))
    results.commit()
    monitor_log = (run / "gpu.csv").open("w")
    monitor = subprocess.Popen(["nvidia-smi", "--query-gpu=timestamp,index,name,utilization.gpu,memory.used,power.draw",
                                "--format=csv", "-l", "1"], stdout=monitor_log)
    try:
        code = run_logged([PYTHON, "scripts/sft_learning_probe.py", "--snapshot", prepared["snapshot"],
                           "--output", str(run / "learning"), "--steps", str(steps)], run / "learning.log",
                          cwd="/opt/training", env=dict(os.environ, HF_HUB_OFFLINE="1",
                              TRANSFORMERS_OFFLINE="1", PYTHONUNBUFFERED="1"), timeout=deadline-time.time())
        if code:
            raise RuntimeError(f"SFT learning probe exited {code}; inspect learning.log")
        learning = json.loads((run / "learning/learning-report.json").read_text())
        report = {"status": learning["status"], "learning": learning}
    except Exception:
        report = {"status": "FAIL", "error": traceback.format_exc()}
    finally:
        monitor.terminate()
        monitor.wait(timeout=5)
        monitor_log.close()
    report.update(run_id=run_id, elapsed_seconds=time.time()-started)
    (run / "report.json").write_text(json.dumps(report, indent=2))
    results.commit()
    return report


def main():
    from dotenv import dotenv_values
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--prepare-only", action="store_true")
    p.add_argument("--steps", type=int, default=32, choices=range(1, 33))
    p.add_argument("--gpu-seconds", type=int, default=600, choices=range(180, 601))
    p.add_argument("--queue-seconds", type=int, default=1800, choices=range(60, 1801))
    a = p.parse_args()
    plan = {"gpu": "L40S", "gpu_count": 1, "maximum_gpu_minutes": a.gpu_seconds/60,
        "startup_timeout_s": 60, "function_timeout_s": a.gpu_seconds-60,
        "queue_allowance_s": a.queue_seconds, "retries": 0, "steps": a.steps,
        "model": MODEL, "revision": REVISION,
        "scope": "Axolotl NF4/BF16 SFT, 64 examples, before/after heldout generation with reloaded adapter; no browser"}
    if a.dry_run:
        print(json.dumps(plan, indent=2))
        return
    for key, value in dotenv_values(ROOT.parent / ".env").items():
        if key in ("MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET") and value:
            os.environ.setdefault(key, value)
    run_id = time.strftime("l40s-sft-learning-%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8]
    local = ROOT / "outputs/modal" / run_id
    local.mkdir(parents=True)
    selected = SOURCES + [ROOT / "envs/sft/pyproject.toml", ROOT / "envs/sft/uv.lock"]
    plan["source_sha256"] = {str(s.relative_to(ROOT)): hashlib.sha256(s.read_bytes()).hexdigest() for s in selected}
    for source in selected:
        dest = local / "sources" / source.relative_to(ROOT)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(source.read_bytes())
    plan["git_commit"] = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    (local / "plan.json").write_text(json.dumps(plan, indent=2))
    with modal.enable_output(), app.run():
        (local / "app.json").write_text(json.dumps({"app_id": app.app_id, "url": app.get_dashboard_url()}))
        prepared = prepare.remote()
        (local / "cache.json").write_text(json.dumps(prepared, indent=2))
        if a.prepare_only:
            return
        deadline = time.time() + a.queue_seconds + a.gpu_seconds
        execution_seconds = a.gpu_seconds - 60
        call = gpu_probe.with_options(timeout=execution_seconds).spawn(run_id, prepared, deadline, a.steps, execution_seconds)
        (local / "call.json").write_text(json.dumps({"call_id": call.object_id, "deadline": deadline}))
        try:
            report = call.get(timeout=max(1, deadline-time.time()))
        finally:
            call.cancel(terminate_containers=True)
        (local / "report.json").write_text(json.dumps(report, indent=2))
        print(json.dumps(report, indent=2))
        if report["status"] != "PASS":
            raise SystemExit(1)


if __name__ == "__main__":
    main()
