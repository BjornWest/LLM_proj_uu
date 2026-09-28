#!/usr/bin/env python3
"""Bounded one-L40S NF4 native GRPO loss test. CPU preparation precedes allocation."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import uuid
import modal

ROOT=Path(__file__).resolve().parents[1]
MODEL='greghavens/Qwen3.8-27B-bnb-4bit'
REVISION='26157380225e427827263c34df23018a1e28dff5'
SOURCES=sorted([*ROOT.glob('browser_training/*.py'), ROOT/'configs/sft_qwen38_27b_nf4_qlora.yml', *[ROOT/'scripts'/n for n in (
    'modal_grpo.py','modal_grpo_probe.py','patch_trl_attention.py','patch_trl_policy.py','verify_gpu.py','check_adapter_dtypes.py')]])
image=(modal.Image.debian_slim(python_version='3.12')
    .apt_install('git','libgomp1','build-essential').uv_pip_install('uv==0.10.8')
    .add_local_file(ROOT/'envs/rl/pyproject.toml','/opt/rl/pyproject.toml',copy=True)
    .add_local_file(ROOT/'envs/rl/uv.lock','/opt/rl/uv.lock',copy=True)
    .run_commands('uv python install 3.12.12',
        'cd /opt/rl && uv sync --locked --python 3.12.12 --default-index https://pypi.org/simple',
        'uv pip check --python /opt/rl/.venv/bin/python')
    .env({'HF_HOME':'/model-cache','HF_HUB_CACHE':'/model-cache/hub','HF_XET_HIGH_PERFORMANCE':'1',
        'PYTHONPATH':'/opt/training:/opt/training/scripts','PYTHONUNBUFFERED':'1',
        'TRITON_CACHE_DIR':'/model-cache/compiled/rl-vllm028-torch213-sm89/triton',
        'VLLM_CACHE_ROOT':'/model-cache/compiled/rl-vllm028-torch213-sm89/vllm',
        'VLLM_NO_USAGE_STATS':'1','VLLM_SERVER_DEV_MODE':'1','VLLM_ALLOW_RUNTIME_LORA_UPDATING':'1',
        'VLLM_WORKER_MULTIPROC_METHOD':'spawn','WANDB_MODE':'disabled','TOKENIZERS_PARALLELISM':'false'}))
dependency_image = image
for source in SOURCES:
    image=image.add_local_file(source,'/opt/training/'+str(source.relative_to(ROOT)))
cache=modal.Volume.from_name('browser-training-model-cache',create_if_missing=True)
results=modal.Volume.from_name('browser-training-results',create_if_missing=True)
app=modal.App('browser-training-l40s-grpo',image=image,include_source=False)
PYTHON='/opt/rl/.venv/bin/python'

@app.function(cpu=4,memory=16384,timeout=1200,retries=0,max_containers=1,scaledown_window=2,
              volumes={'/model-cache':cache,'/results':results})
def prepare():
    code=f'''
import json, subprocess, sys
from pathlib import Path
from huggingface_hub import snapshot_download
from transformers import AutoTokenizer
for name in ('patch_trl_policy.py','patch_trl_attention.py'):
    subprocess.run([sys.executable,'/opt/training/scripts/'+name,'--apply'],check=True)
from browser_training.qlora_compat import candidate_module
candidate_module()
snapshot=Path(snapshot_download({MODEL!r},revision={REVISION!r}))
AutoTokenizer.from_pretrained(snapshot,local_files_only=True)
print(json.dumps(dict(snapshot=str(snapshot),weight_bytes=sum(p.stat().st_size for p in snapshot.glob('*.safetensors')))))
'''
    done=subprocess.run([PYTHON,'-c',code],text=True,capture_output=True,timeout=1140)
    print(done.stdout,flush=True)
    if done.returncode:
        print(done.stderr[-16000:],flush=True)
        raise RuntimeError('CPU preparation failed; GPU not started')
    cache.commit()
    return json.loads(done.stdout.strip().splitlines()[-1])

@app.function(gpu='L40S',cpu=8,memory=65536,timeout=360,startup_timeout=60,retries=0,
              max_containers=1,scaledown_window=2,volumes={'/model-cache':cache,'/results':results})
def gpu_probe(run_id,prepared,deadline):
    import traceback
    from browser_training.processes import run_logged
    if time.time()>=deadline:raise TimeoutError('Authorization window expired')
    results.reload();run=Path('/results')/run_id
    if run.exists():raise RuntimeError('Refuse replay of started run')
    run.mkdir();(run/'started.json').write_text(json.dumps({'deadline':deadline,'started':time.time()}));results.commit()
    env=dict(os.environ,HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',USE_HUB_KERNELS='NO')
    log=(run/'gpu.csv').open('w')
    monitor=subprocess.Popen(['nvidia-smi','--query-gpu=timestamp,name,utilization.gpu,memory.used,power.draw','--format=csv','-l','1'],stdout=log)
    started=time.time()
    try:
        for name in ('patch_trl_policy.py','patch_trl_attention.py'):
            assert run_logged([PYTHON,'scripts/'+name,'--apply'],run/(name+'.log'),cwd='/opt/training',env=env,timeout=20)==0
        code=run_logged([PYTHON,'scripts/modal_grpo_probe.py','--snapshot',prepared['snapshot'],
            '--output',str(run/'grpo')],run/'grpo.log',cwd='/opt/training',env=env,timeout=deadline-time.time()-20)
        if code:raise RuntimeError(f'GRPO probe exited {code}')
        report=dict(status='PASS',run_id=run_id,grpo=json.loads((run/'grpo/grpo-report.json').read_text()))
    except Exception:
        report=dict(status='FAIL',run_id=run_id,error=traceback.format_exc())
    finally:
        monitor.terminate();monitor.wait(timeout=5);log.close()
    report['elapsed_seconds']=time.time()-started
    # Preserve kernel compilation work for subsequent allocations of this stack/GPU.
    cache.commit()
    (run/'report.json').write_text(json.dumps(report,indent=2));results.commit()
    return report

def main():
    from dotenv import dotenv_values
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--dry-run',action='store_true')
    p.add_argument('--prepare-only',action='store_true');p.add_argument('--gpu-seconds',type=int,default=360,choices=range(120,361))
    args=p.parse_args()
    plan=dict(model=MODEL,revision=REVISION,gpu='L40S',gpu_count=1,
        absolute_window=args.gpu_seconds,retries=0,scope='NF4 native GRPO loss/backward, BF16 rank16, two steps; no rollout')
    if args.dry_run: print(json.dumps(plan,indent=2));return
    for key,value in dotenv_values(ROOT.parent/'.env').items():
        if key in ('MODAL_TOKEN_ID','MODAL_TOKEN_SECRET') and value: os.environ.setdefault(key,value)
    run_id=time.strftime('l40s-grpo-%Y%m%d-%H%M%S-')+uuid.uuid4().hex[:8]
    local=ROOT/'outputs/modal'/run_id;local.mkdir(parents=True)
    selected=SOURCES+[ROOT/'envs/rl/pyproject.toml',ROOT/'envs/rl/uv.lock',ROOT/'uv.lock']
    plan['source_sha256']={str(s.relative_to(ROOT)):hashlib.sha256(s.read_bytes()).hexdigest() for s in selected}
    for source in selected:
        target=local/'sources'/source.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(source.read_bytes())
    plan['git_commit']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    (local/'plan.json').write_text(json.dumps(plan,indent=2))
    with modal.enable_output(),app.run():
        (local/'app.json').write_text(json.dumps(dict(app_id=app.app_id,url=app.get_dashboard_url())))
        prepared=prepare.remote();(local/'cache.json').write_text(json.dumps(prepared,indent=2))
        if args.prepare_only:return
        deadline=time.time()+args.gpu_seconds
        call=gpu_probe.spawn(run_id,prepared,deadline)
        (local/'call.json').write_text(json.dumps(dict(call_id=call.object_id,deadline=deadline)))
        try: report=call.get(timeout=max(1,deadline-time.time()))
        finally: call.cancel(terminate_containers=True)
        (local/'report.json').write_text(json.dumps(report,indent=2))
        print(json.dumps(report,indent=2))
        if report['status']!='PASS':raise SystemExit(1)

if __name__=='__main__':main()
