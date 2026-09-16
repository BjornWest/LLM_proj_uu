#!/usr/bin/env python3
"""One bounded L40S trainer qualification. --prepare-only allocates no GPU.

Run with training/.venv/bin/python; credentials are loaded ONLY in local main.
"""
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
MODEL = 'greghavens/Qwen3.8-27B-bnb-4bit'
REVISION = '26157380225e427827263c34df23018a1e28dff5'
WEIGHT_BYTES = 19_424_559_530
# Upload only selected source files. No .env, existing data, outputs, or weights.
SOURCES = sorted([*ROOT.glob('browser_training/*.py'),
    ROOT / 'configs/sft_qwen38_27b_nf4_qlora.yml',
    ROOT / 'scripts/modal_training.py', ROOT / 'scripts/modal_trainer_probe.py',
    ROOT / 'scripts/verify_gpu.py', ROOT / 'scripts/check_adapter_dtypes.py'])
image = (modal.Image.debian_slim(python_version='3.12')
    .apt_install('git', 'libgomp1', 'build-essential')
    .uv_pip_install('uv==0.10.8')
    .add_local_file(ROOT / 'envs/sft/pyproject.toml', '/opt/sft/pyproject.toml', copy=True)
    .add_local_file(ROOT / 'envs/sft/uv.lock', '/opt/sft/uv.lock', copy=True)
    .run_commands('uv python install 3.12.12',
        'cd /opt/sft && uv sync --locked --python 3.12.12 --default-index https://pypi.org/simple',
        'uv pip check --python /opt/sft/.venv/bin/python')
    .env({'HF_HOME': '/model-cache', 'HF_HUB_CACHE': '/model-cache/hub',
        'HF_XET_HIGH_PERFORMANCE': '1', 'AXOLOTL_DO_NOT_TRACK': '1',
        'WANDB_MODE': 'disabled', 'TOKENIZERS_PARALLELISM': 'false',
        'PYTHONPATH': '/opt/training:/opt/training/scripts', 'USE_HUB_KERNELS': 'NO'}))
for source in SOURCES:
    image = image.add_local_file(source, '/opt/training/' + str(source.relative_to(ROOT)))
cache = modal.Volume.from_name('browser-training-model-cache', create_if_missing=True)
results = modal.Volume.from_name('browser-training-results', create_if_missing=True)
app = modal.App('browser-training-l40s-preflight', image=image, include_source=False)
PYTHON = '/opt/sft/.venv/bin/python'


def run_logged(command, path, *, cwd, env, timeout):
    """Stream diagnostics while retaining a subprocess/process-group deadline."""
    import signal
    import threading
    if timeout <= 0:
        raise TimeoutError('No subprocess budget remains')
    with Path(path).open('w') as log:
        child = subprocess.Popen(command, cwd=cwd, env=env, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, errors='replace', start_new_session=True)

        def relay():
            for line in child.stdout:
                log.write(line)
                log.flush()
                print(line, end='', flush=True)

        reader = threading.Thread(target=relay, daemon=True)
        reader.start()
        try:
            return child.wait(timeout=timeout)
        finally:
            # Also clean up descendants if the leader exited before its children.
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait()
            reader.join(timeout=5)


@app.function(cpu=4, memory=16384, timeout=900, retries=0, max_containers=1,
              scaledown_window=2, volumes={'/model-cache': cache})
def prepare():
    # Execute with the exact locked training interpreter, not Modal's interpreter.
    code = '''
import json
from pathlib import Path
from huggingface_hub import snapshot_download
from transformers import AutoTokenizer
import axolotl, peft, bitsandbytes, fla
path = Path(snapshot_download(MODEL, revision=REVISION))
size = sum(p.stat().st_size for p in path.glob('*.safetensors'))
assert size == WEIGHT_BYTES, size
assert snapshot_download(MODEL, revision=REVISION, local_files_only=True) == str(path)
AutoTokenizer.from_pretrained(path, local_files_only=True)
print(json.dumps(dict(snapshot=str(path), weight_bytes=size)))
'''
    code = f'MODEL={MODEL!r}\nREVISION={REVISION!r}\nWEIGHT_BYTES={WEIGHT_BYTES}\n' + code
    done = subprocess.run([PYTHON, '-c', code], text=True, capture_output=True, timeout=840)
    print(done.stdout, flush=True)
    if done.returncode:
        print(done.stderr[-16000:], flush=True)
        raise RuntimeError('CPU preparation failed; no GPU invocation permitted')
    cache.commit()
    return json.loads(done.stdout.strip().splitlines()[-1])


@app.function(gpu='L40S', cpu=8, memory=65536, timeout=960, startup_timeout=90,
              retries=0, max_containers=1, scaledown_window=2,
              volumes={'/model-cache': cache, '/results': results})
def gpu_probe(run_id: str, snapshot: str, deadline: float, sequence_len: int = 1024):
    import traceback
    if time.time() >= deadline:
        raise RuntimeError('Absolute authorization deadline expired')
    run = Path('/results') / run_id
    # A platform preemption must not restart training or reset the time budget.
    results.reload()
    if run.exists():
        raise RuntimeError('Run already started: refusing a replay after interruption')
    run.mkdir()
    (run / 'started.json').write_text(json.dumps({'deadline': deadline, 'started': time.time()}))
    results.commit()
    environment = dict(os.environ, HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', PYTHONUNBUFFERED='1')
    stages = []
    monitor = subprocess.Popen(['nvidia-smi', '--query-gpu=timestamp,name,utilization.gpu,memory.used,power.draw',
        '--format=csv', '-l', '1'], stdout=(run / 'gpu.csv').open('w'), stderr=subprocess.STDOUT)
    try:
        commands = [
            ('hardware', [PYTHON, 'scripts/verify_gpu.py', '--min-gpus', '1']),
            ('sft', [PYTHON, 'scripts/modal_trainer_probe.py', '--snapshot', snapshot, '--output', str(run / 'sft'), '--sequence-len', str(sequence_len)]),
        ]
        for name, command in commands:
            started = time.time()
            remaining = min(900, deadline - started - 30)
            if remaining <= 0:
                raise TimeoutError('No authorized GPU time remains')
            print(f'Starting {name}; {remaining:.0f} seconds remain for this stage', flush=True)
            code = run_logged(command, run / f'{name}.log', cwd='/opt/training',
                env=environment, timeout=remaining)
            stages.append(dict(stage=name, returncode=code, elapsed=time.time()-started))
            results.commit()
            if code:
                raise RuntimeError(f'{name} failed with exit {code}')
        report = dict(status='PASS', stages=stages, run_id=run_id,
            sft=json.loads((run / 'sft/sft-report.json').read_text()))
    except Exception:
        report = dict(status='FAIL', stages=stages, run_id=run_id, error=traceback.format_exc())
    finally:
        monitor.terminate()
        monitor.wait(timeout=10)
    (run / 'report.json').write_text(json.dumps(report, indent=2))
    results.commit()
    return report


def main():
    from dotenv import dotenv_values
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--prepare-only', action='store_true')
    p.add_argument('--dry-run', action='store_true')
    p.add_argument('--gpu-seconds', type=int, default=1080, choices=range(60, 1081), metavar='60..1080')
    p.add_argument('--sequence-len', type=int, choices=[1024, 2048], default=1024)
    args = p.parse_args()
    plan = dict(model=MODEL, revision=REVISION, gpu='L40S', gpu_count=1,
        invocation_timeout_seconds=960, absolute_gpu_window_seconds=args.gpu_seconds, sequence_len=args.sequence_len,
        retries=0, uploaded_files=[str(s.relative_to(ROOT)) for s in SOURCES],
        scope='GPU BF16/FP8 kernels + 27B NF4 Axolotl two steps + intermediate-checkpoint resume')
    if args.dry_run:
        print(json.dumps(plan, indent=2))
        return
    for key, value in dotenv_values(ROOT.parent / '.env').items():
        if key in ('MODAL_TOKEN_ID', 'MODAL_TOKEN_SECRET') and value:
            os.environ.setdefault(key, value)
    if not all(os.environ.get(k) for k in ('MODAL_TOKEN_ID', 'MODAL_TOKEN_SECRET')):
        raise SystemExit('Set MODAL_TOKEN_ID and MODAL_TOKEN_SECRET in the project .env')
    run_id = time.strftime('l40s-%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:8]
    local = ROOT / 'outputs/modal' / run_id
    local.mkdir(parents=True)
    plan['source_sha256'] = {str(s.relative_to(ROOT)): hashlib.sha256(s.read_bytes()).hexdigest() for s in SOURCES}
    plan['lock_sha256'] = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in [ROOT / 'uv.lock', ROOT / 'envs/sft/uv.lock']}
    for name in {**plan['source_sha256'], **plan['lock_sha256']}:
        target = local / 'sources' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / name).read_bytes())
    plan['git_commit'] = subprocess.check_output(['git','rev-parse','HEAD'], cwd=ROOT, text=True).strip()
    (local / 'plan.json').write_text(json.dumps(plan, indent=2))
    with modal.enable_output(), app.run():
        (local / 'app.json').write_text(json.dumps({'app_id': app.app_id, 'url': app.get_dashboard_url()}))
        prepared = prepare.remote()
        (local / 'cache.json').write_text(json.dumps(prepared, indent=2))
        if args.prepare_only:
            return
        deadline = time.time() + args.gpu_seconds
        call = gpu_probe.spawn(run_id, prepared['snapshot'], deadline, args.sequence_len)
        (local / 'call.json').write_text(json.dumps({'call_id': call.object_id, 'deadline': deadline}))
        try:
            report = call.get(timeout=max(1, deadline-time.time()))
        finally:
            # Terminate containers too. This protects against platform replay and
            # leaves 120 seconds of the user's 20 minute cap for teardown.
            call.cancel(terminate_containers=True)
        (local / 'report.json').write_text(json.dumps(report, indent=2))
        print(json.dumps(report, indent=2))
        print(f'Artifacts: {local}; Modal volume browser-training-results/{run_id}')
        if report['status'] != 'PASS':
            raise SystemExit(1)


if __name__ == '__main__':
    main()
