#!/usr/bin/env python3
"""Bounded two-L40S accumulation/checkpoint/resume acceptance; explicit authorization required."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import threading
import time
import uuid
import modal
from modal_grpo import ROOT, MODEL, REVISION, PYTHON, SOURCES as BASE_SOURCES, image as base_image, cache, results

FP8 = "Qwen/Qwen3.8-27B-FP8"
FP8_REVISION = "017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"
EXTRA = [ROOT / "scripts" / n for n in ("modal_acceptance.py", "grpo_acceptance_probe.py", "patch_vllm_unload.py", "monitor_resources.py")]
SOURCES = BASE_SOURCES + EXTRA
image = base_image
for source in EXTRA:
    image = image.add_local_file(source, "/opt/training/" + str(source.relative_to(ROOT)))
app = modal.App("browser-training-l40s-acceptance", image=image, include_source=False)


@app.function(cpu=4, memory=16384, timeout=180, retries=0, max_containers=1,
              scaledown_window=2, volumes={"/model-cache": cache, "/results": results})
def prepare(resume_run=None, steps=3):
    # Both pinned snapshots are already cached. Fail rather than downloading during this test.
    code = f"""
import faulthandler, json, subprocess, sys
faulthandler.dump_traceback_later(45, repeat=True)
print('CPU prepare: import HF/tokenizer', flush=True)
from huggingface_hub import snapshot_download
from transformers import AutoTokenizer
for name in ('patch_trl_policy.py', 'patch_trl_attention.py', 'patch_vllm_unload.py'):
    print('CPU prepare: '+name, flush=True)
    subprocess.run([sys.executable, '/opt/training/scripts/'+name, '--apply'], check=True)
print('CPU prepare: import audited NF4 trainer', flush=True)
from browser_training.qlora_compat import candidate_module
candidate_module()
from browser_training.trl_monitoring import check_sources
check_sources()
import grpo_acceptance_probe
print('CPU prepare: resolve cached snapshots', flush=True)
paths = {{key: snapshot_download(model, revision=revision, local_files_only=True)
    for key, model, revision in [('trainer', {MODEL!r}, {REVISION!r}), ('rollout', {FP8!r}, {FP8_REVISION!r})]}}
from browser_training.choice_probe import render_prompt_ids
import requests
tokens = []
for path in paths.values():
    ids = render_prompt_ids(AutoTokenizer.from_pretrained(path, local_files_only=True))
    requests.Request('POST', 'http://127.0.0.1:8000/v1/completions', json={{'prompt': ids}}).prepare()
    tokens.append(ids)
assert tokens[0] == tokens[1], 'Trainer and rollout prompt token IDs differ'
print('CPU prepare: both tokenizer request payloads passed serialization', flush=True)
from browser_training.provenance import capture
from pathlib import Path
manifest = capture('/tmp/e2e-provenance-check', {{'stage': 'CPU preparation', 'snapshots': paths}})
record = json.loads(manifest.read_text())
for name in ('pyproject.toml', 'uv.lock'):
    assert '/opt/rl/'+name in record['environment_file_sha256'], 'Missing active environment provenance'
print('CPU prepare: actual image provenance capture passed', flush=True)
if {resume_run!r}:
    import torch
    from browser_training.acceptance_harness import optimizer_digest
    checkpoint = Path('/results') / {resume_run!r} / 'initial' / 'checkpoint-{steps}'
    saved = torch.load(checkpoint / 'optimizer.pt', map_location='cpu', weights_only=True)
    print('CPU prepare: real saved optimizer fingerprint ' + optimizer_digest(saved), flush=True)
    assert json.loads((checkpoint / 'trainer_state.json').read_text())['global_step'] == {steps}
faulthandler.cancel_dump_traceback_later()
print(json.dumps(paths))
"""
    from browser_training.processes import run_logged
    log = Path('/tmp/e2e-cpu-prepare.log')
    env = dict(os.environ, HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', USE_HUB_KERNELS='NO')
    status = run_logged([PYTHON, '-c', code], log, cwd='/opt/training', env=env, timeout=160)
    if status:
        raise RuntimeError(log.read_text()[-12000:])
    return json.loads(log.read_text().strip().splitlines()[-1])


@app.function(gpu="L40S:2", cpu=12, memory=98304, timeout=840, startup_timeout=60,
              retries=0, max_containers=1, scaledown_window=2,
              volumes={"/model-cache": cache, "/results": results})
def gpu_probe(run_id, prepared, outer_deadline, steps, execution_seconds=840, resume_run=None, browser_frozen=None):
    import traceback
    import urllib.request
    from browser_training.processes import run_logged
    started = time.time()
    if not 120 <= execution_seconds <= 840:
        raise ValueError('Execution budget must be between 120 and 840 seconds')
    deadline = min(outer_deadline, started + execution_seconds - 30)
    if deadline - started < 120:
        raise TimeoutError("Authorization window exhausted before GPU function started")
    results.reload()
    run = Path("/results") / run_id
    if run.exists():
        raise RuntimeError("Refuse replay of an existing run")
    run.mkdir()
    (run / "started.json").write_text(json.dumps({"started": started, "deadline": deadline}))
    results.commit()
    env = dict(os.environ, HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", USE_HUB_KERNELS="NO")
    server = reader = server_log = None
    monitor_log = (run / "gpu.csv").open("w")
    monitor = subprocess.Popen(["nvidia-smi", "--query-gpu=timestamp,index,name,utilization.gpu,memory.used,power.draw",
                                "--format=csv", "-l", "1"], stdout=monitor_log)
    try:
        for name in ("patch_trl_policy.py", "patch_trl_attention.py", "patch_vllm_unload.py"):
            assert run_logged([PYTHON, "scripts/"+name, "--apply"], run/(name+".log"),
                              cwd="/opt/training", env=env, timeout=30) == 0
        cmd = ["/opt/rl/.venv/bin/vllm", "serve", prepared["rollout"], "--served-model-name", FP8,
               "--host", "127.0.0.1", "--port", "8000", "--dtype", "bfloat16", "--language-model-only",
               "--generation-config", "vllm", "--max-model-len", "8192" if browser_frozen else "2048", "--max-num-seqs", "4",
               "--gpu-memory-utilization", "0.85", "--enable-lora", "--lora-dtype", "bfloat16",
               "--max-lora-rank", "32", "--max-loras", "4", "--max-cpu-loras", "4",
               "--enforce-eager", "--no-enable-prefix-caching", "--logprobs-mode", "processed_logprobs"]
        (run / "server-command.json").write_text(json.dumps(cmd, indent=2))
        server_log = (run / "server.log").open("w")
        server = subprocess.Popen(cmd, cwd="/opt/training", env=dict(env, CUDA_VISIBLE_DEVICES="0"),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace", start_new_session=True)
        def relay():
            for line in server.stdout:
                server_log.write(line)
                server_log.flush()
                print(line, end="", flush=True)
        reader = threading.Thread(target=relay, daemon=True)
        reader.start()
        while True:
            if server.poll() is not None:
                raise RuntimeError(f"vLLM exited: {server.returncode}")
            if time.time() > deadline-(120 if resume_run else 180):
                raise TimeoutError("Insufficient budget remains after server startup")
            try:
                with urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=1) as response:
                    if response.status == 200:
                        break
            except (OSError, TimeoutError):
                time.sleep(1)
        stages = {}
        # Sequential by necessity: stage two restores stage one's actual checkpoint.
        selected_stages = (("resumed", steps * 2),) if resume_run else (("initial", steps), ("resumed", steps * 2))
        if browser_frozen:
            selected_stages = (("browser", steps),)
        for stage, total_steps in selected_stages:
            command = [PYTHON, "scripts/grpo_acceptance_probe.py", "--snapshot", prepared["trainer"],
                       "--output", str(run/stage), "--run-id", resume_run or run_id, "--steps", str(total_steps),
                       "--trainer-gpu", "1", "--rollout-gpu", "0"]
            if browser_frozen:
                command += ["--browser-frozen", browser_frozen]
            if stage == "resumed":
                source = Path("/results") / resume_run if resume_run else run
                command += ["--resume", str(source/"initial"/f"checkpoint-{steps}")]
            code = run_logged(command, run/(stage+".log"), cwd="/opt/training",
                              env=dict(env, CUDA_VISIBLE_DEVICES="1"), timeout=max(1, deadline-time.time()))
            results.commit()
            if code:
                raise RuntimeError(f"{stage} exited {code}; inspect {stage}.log")
            stages[stage] = json.loads((run/stage/"acceptance-report.json").read_text())
        report = {"status": "PASS", "stages": stages}
    except Exception:
        report = {"status": "FAIL", "error": traceback.format_exc()}
    finally:
        if server:
            try:
                os.killpg(server.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            server.wait(timeout=10)
        if reader:
            reader.join(timeout=5)
        if server_log:
            server_log.close()
        monitor.terminate()
        monitor.wait(timeout=5)
        monitor_log.close()
    report.update(run_id=run_id, elapsed_seconds=time.time()-started)
    (run/"report.json").write_text(json.dumps(report, indent=2))
    results.commit()
    return report


def main():
    from dotenv import dotenv_values
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--prepare-only", action="store_true")
    p.add_argument("--resume-run", help="Existing acceptance run with an initial checkpoint; skip redoing its updates")
    p.add_argument("--steps", type=int, default=3, choices=range(3, 5))
    p.add_argument("--gpu-seconds", type=int, default=900, choices=range(300, 901),
                   help="Per-GPU allowance including 60s startup; a fresh authorization budget is not implied")
    p.add_argument("--queue-seconds", type=int, default=600, choices=range(60, 1801),
                   help="Separate queue allowance; does not increase GPU execution time")
    a = p.parse_args()
    if a.resume_run:
        import re
        if not re.fullmatch(r"l40s-acceptance-[a-z0-9-]+", a.resume_run):
            p.error("Invalid source acceptance run")
    plan = {"gpu": "L40S:2", "maximum_gpu_minutes": 2*a.gpu_seconds/60, "startup_timeout_s": 60,
            "function_timeout_s": a.gpu_seconds-60, "queue_allowance_s": a.queue_seconds, "retries": 0, "steps": a.steps,
            "trainer": [MODEL, REVISION], "rollout": [FP8, FP8_REVISION],
            "scope": "Native two-turn OpenEnv/GRPO accumulation, monitoring, real checkpoint restore; synthetic task",
            "resume_run": a.resume_run}
    if a.dry_run:
        print(json.dumps(plan, indent=2))
        return
    for key, value in dotenv_values(ROOT.parent/".env").items():
        if key in ("MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET") and value:
            os.environ.setdefault(key, value)
    run_id = time.strftime("l40s-acceptance-%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8]
    local = ROOT/"outputs/modal"/run_id
    local.mkdir(parents=True)
    selected = SOURCES + [ROOT/"envs/rl/pyproject.toml", ROOT/"envs/rl/uv.lock"]
    plan["source_sha256"] = {str(s.relative_to(ROOT)): hashlib.sha256(s.read_bytes()).hexdigest() for s in selected}
    for source in selected:
        dest = local/"sources"/source.relative_to(ROOT)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(source.read_bytes())
    plan["git_commit"] = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    (local/"plan.json").write_text(json.dumps(plan, indent=2))
    with modal.enable_output(), app.run():
        (local/"app.json").write_text(json.dumps({"app_id": app.app_id, "url": app.get_dashboard_url()}))
        prepared = prepare.remote(a.resume_run, a.steps)
        (local/"cache.json").write_text(json.dumps(prepared, indent=2))
        if a.prepare_only:
            return
        deadline = time.time()+a.queue_seconds+a.gpu_seconds
        execution_seconds = a.gpu_seconds-60
        call = gpu_probe.with_options(timeout=execution_seconds).spawn(run_id, prepared, deadline, a.steps, execution_seconds, a.resume_run)
        (local/"call.json").write_text(json.dumps({"call_id": call.object_id, "deadline": deadline}))
        try:
            report = call.get(timeout=max(1, deadline-time.time()))
        finally:
            call.cancel(terminate_containers=True)
        (local/"report.json").write_text(json.dumps(report, indent=2))
        print(json.dumps(report, indent=2))
        if report["status"] != "PASS":
            raise SystemExit(1)


if __name__ == "__main__":
    main()
