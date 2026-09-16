#!/usr/bin/env python3
"""Bounded one-L40S FP8 lifecycle test. CPU preparation precedes allocation."""
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
MODEL='Qwen/Qwen3.8-27B-FP8'
REVISION='017b9c7af6b5689d5dd426a76e0bc077eb5ca20a'
ADAPTER='l40s-20260915-213026-226491b8/sft/checkpoint-2'
SOURCES=sorted([*ROOT.glob('browser_training/*.py'), *[ROOT/'scripts'/n for n in (
    'modal_inference.py','modal_inference_probe.py','patch_vllm_unload.py','verify_gpu.py')]])
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
for source in SOURCES:
    image=image.add_local_file(source,'/opt/training/'+str(source.relative_to(ROOT)))
cache=modal.Volume.from_name('browser-training-model-cache',create_if_missing=True)
results=modal.Volume.from_name('browser-training-results',create_if_missing=True)
app=modal.App('browser-training-l40s-inference',image=image,include_source=False)
PYTHON='/opt/rl/.venv/bin/python'

@app.function(cpu=4,memory=16384,timeout=1200,retries=0,max_containers=1,scaledown_window=2,
              volumes={'/model-cache':cache,'/results':results})
def prepare():
    code=f'''
import json
from pathlib import Path
from huggingface_hub import snapshot_download
from transformers import AutoTokenizer
from safetensors import safe_open
from browser_training.vllm_compat import patched_source
from importlib.metadata import distribution
p=Path(distribution('vllm').locate_file('vllm/entrypoints/openai/models/serving.py'))
patched_source(p.read_text())
snapshot=Path(snapshot_download({MODEL!r},revision={REVISION!r}))
AutoTokenizer.from_pretrained(snapshot,local_files_only=True)
adapter=Path('/results')/{ADAPTER!r}
assert (adapter/'adapter_config.json').is_file()
with safe_open(adapter/'adapter_model.safetensors',framework='pt',device='cpu') as f:
    assert all(f.get_slice(k).get_dtype()=='BF16' for k in f.keys())
print(json.dumps(dict(snapshot=str(snapshot),weight_bytes=sum(p.stat().st_size for p in snapshot.glob('*.safetensors')),adapter=str(adapter))))
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
def gpu_probe(run_id,prepared,deadline,alternate_rank=32,identity=False,execution_seconds=None):
    import traceback
    import urllib.request
    import threading
    from browser_training.processes import run_logged
    if time.time()>=deadline: raise TimeoutError('Authorization window expired')
    if execution_seconds is not None:
        deadline=min(deadline,time.time()+execution_seconds)
    results.reload(); run=Path('/results')/run_id
    if run.exists(): raise RuntimeError('Refuse replay of started run')
    run.mkdir(); (run/'started.json').write_text(json.dumps({'deadline':deadline,'started':time.time()})); results.commit()
    env=dict(os.environ,HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
    server=None; reader=None; log=None
    monitor_log=(run/'gpu.csv').open('w')
    monitor=subprocess.Popen(['nvidia-smi','--query-gpu=timestamp,name,utilization.gpu,memory.used,power.draw','--format=csv','-l','1'],stdout=monitor_log)
    started=time.time()
    try:
        for name,command in [('hardware',[PYTHON,'scripts/verify_gpu.py','--min-gpus','1']),
                ('patch',[PYTHON,'scripts/patch_vllm_unload.py','--apply'])]:
            assert run_logged(command,run/f'{name}.log',cwd='/opt/training',env=env,timeout=min(30,deadline-time.time()-20))==0
        command=['/opt/rl/.venv/bin/vllm','serve',prepared['snapshot'],'--served-model-name',MODEL,
            '--host','127.0.0.1','--port','8000','--dtype','bfloat16','--language-model-only',
            '--generation-config','vllm','--max-model-len','2048','--max-num-seqs','4',
            '--gpu-memory-utilization','0.85','--enable-lora','--lora-dtype','bfloat16',
            '--max-lora-rank','32','--max-loras','4','--max-cpu-loras','4','--enforce-eager',
            '--no-enable-prefix-caching',
            '--logprobs-mode','processed_logprobs','--worker-extension-cls','browser_training.vllm_probe_worker.ProbeWorker']
        (run/'server-command.json').write_text(json.dumps(command,indent=2))
        log=(run/'server.log').open('w')
        server=subprocess.Popen(command,cwd='/opt/training',env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
            text=True,errors='replace',start_new_session=True)
        def relay():
            for line in server.stdout:
                log.write(line);log.flush();print(line,end='',flush=True)
        reader=threading.Thread(target=relay,daemon=True);reader.start()
        while True:
            if server.poll() is not None: raise RuntimeError(f'vLLM exited {server.returncode}')
            if time.time()>deadline-75: raise TimeoutError('Server startup exhausted test budget')
            try:
                with urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=1) as response:
                    if response.status==200: break
            except (OSError,TimeoutError): time.sleep(1)
        ready=time.time()
        probe_command=[PYTHON,'scripts/modal_inference_probe.py','--source',prepared['adapter'],
            '--output',str(run/'inference'),'--alternate-rank',str(alternate_rank)]
        if identity: probe_command.append('--identity')
        code=run_logged(probe_command,run/'lifecycle.log',cwd='/opt/training',env=env,timeout=deadline-time.time()-20)
        if code: raise RuntimeError(f'Lifecycle exited {code}')
        inference=json.loads((run/'inference/inference-report.json').read_text())
        report=dict(status=inference['status'],run_id=run_id,startup_seconds=ready-started,inference=inference)
    except Exception:
        report=dict(status='FAIL',run_id=run_id,error=traceback.format_exc())
    finally:
        if server:
            try: os.killpg(server.pid,signal.SIGKILL)
            except ProcessLookupError: pass
            server.wait(timeout=10)
        if reader: reader.join(timeout=5)
        if log: log.close()
        monitor.terminate();monitor.wait(timeout=5);monitor_log.close()
    report['elapsed_seconds']=time.time()-started
    # Preserve kernel compilation work for subsequent allocations of this stack/GPU.
    cache.commit()
    (run/'report.json').write_text(json.dumps(report,indent=2));results.commit()
    return report

def main():
    from dotenv import dotenv_values
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--dry-run',action='store_true')
    p.add_argument('--prepare-only',action='store_true');p.add_argument('--gpu-seconds',type=int,default=360,choices=range(120,361))
    p.add_argument('--alternate-rank',type=int,choices=[16,32],default=32)
    p.add_argument('--identity',action='store_true')
    p.add_argument('--queue-seconds',type=int,default=0,choices=range(0,601),
                   help='Additional queue allowance; reserves 60 GPU seconds for container startup')
    args=p.parse_args()
    if args.identity and args.alternate_rank!=16: p.error('--identity requires --alternate-rank 16')
    plan=dict(model=MODEL,revision=REVISION,adapter=ADAPTER,gpu='L40S',gpu_count=1,
        absolute_window=args.gpu_seconds+args.queue_seconds,queue_seconds=args.queue_seconds,
        execution_seconds=args.gpu_seconds-60 if args.queue_seconds else args.gpu_seconds,
        alternate_rank=args.alternate_rank,identity=args.identity,retries=0,scope=f'FP8 inference, BF16 ranks {sorted({16,args.alternate_rank})}, lifecycle, no training')
    if args.dry_run: print(json.dumps(plan,indent=2));return
    for key,value in dotenv_values(ROOT.parent/'.env').items():
        if key in ('MODAL_TOKEN_ID','MODAL_TOKEN_SECRET') and value: os.environ.setdefault(key,value)
    run_id=time.strftime('l40s-inference-%Y%m%d-%H%M%S-')+uuid.uuid4().hex[:8]
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
        deadline=time.time()+args.gpu_seconds+args.queue_seconds
        execution_seconds=args.gpu_seconds-60 if args.queue_seconds else None
        function=gpu_probe.with_options(timeout=execution_seconds) if execution_seconds else gpu_probe
        call=function.spawn(run_id,prepared,deadline,args.alternate_rank,args.identity,execution_seconds)
        (local/'call.json').write_text(json.dumps(dict(call_id=call.object_id,deadline=deadline)))
        try: report=call.get(timeout=max(1,deadline-time.time()))
        finally: call.cancel(terminate_containers=True)
        (local/'report.json').write_text(json.dumps(report,indent=2))
        print(json.dumps(report,indent=2))
        if report['status']!='PASS':raise SystemExit(1)

if __name__=='__main__':main()
