#!/usr/bin/env python3
"""One isolated, bounded MTP3 + native CPU KV restore check on Modal."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tarfile
import threading
import time
import traceback
import uuid
import modal

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from cpu_kv_offload_probe import MODEL, REVISION, PROMPT_TOKENS, OUTPUT_TOKENS, CPU_BYTES, MAX_REQUESTS, save
PYTHON='/opt/rl/.venv/bin/python'
SOURCES={
    'scripts/modal_cpu_kv_offload.py':'/opt/training/scripts/modal_cpu_kv_offload.py',
    'scripts/cpu_kv_offload_probe.py':'/opt/training/scripts/cpu_kv_offload_probe.py',
    'scripts/spec_decode_benchmark.py':'/opt/training/scripts/spec_decode_benchmark.py',
    'scripts/modal_rl_image.py':'/opt/training/scripts/modal_rl_image.py',
    'browser_training/compiler_environment.py':'/opt/training/browser_training/compiler_environment.py',
    'browser_training/browser_benchmark_prompts.py':'/opt/training/browser_training/browser_benchmark_prompts.py',
    'browser_training/__init__.py':'/opt/training/browser_training/__init__.py',
    'envs/rl/pyproject.toml':'/opt/rl/pyproject.toml','envs/rl/uv.lock':'/opt/rl/uv.lock',
}

def hashes():
    return {name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in SOURCES}


def verify_sources(expected):
    if set(expected)!=set(SOURCES):raise ValueError('Incomplete source identity')
    for name,path in SOURCES.items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=expected[name]:
            raise ValueError('Container source mismatch: '+name)


def forward_log(path, offset):
    try:text=path.read_text(errors='replace')
    except OSError:return offset
    if len(text)>offset:print(text[offset:],end='',flush=True)
    return len(text)


if modal.is_local():
    from modal_rl_image import build_image
    image=build_image(ROOT)
    for name,path in SOURCES.items():
        if not name.startswith('envs/rl/'):image=image.add_local_file(ROOT/name,path)
else:image=None
cache=modal.Volume.from_name('browser-training-model-cache')
results=modal.Volume.from_name('browser-training-results')
app=modal.App('qwen38-mtp3-cpu-kv-restore',image=image,include_source=False)


@app.function(cpu=4,memory=16384,timeout=900,retries=0,max_containers=1,scaledown_window=2,
    volumes={'/model-cache':cache})
def prepare(expected):
    verify_sources(expected)
    code=f'''
import hashlib,json
from pathlib import Path
from importlib.metadata import version,distribution
from huggingface_hub import snapshot_download
from transformers import AutoTokenizer
from safetensors import safe_open
from cpu_kv_offload_probe import server_command,PROMPT_TOKENS
from browser_training.browser_benchmark_prompts import make_prompt
from vllm.entrypoints.openai.cli_args import make_arg_parser,validate_parsed_serve_args
from vllm.utils.argparse_utils import FlexibleArgumentParser
from vllm.entrypoints.openai.completion.protocol import CompletionRequest
import torch
assert version('vllm')=='0.28.0' and version('torch').split('+')[0]=='2.13.0' and torch.version.cuda=='13.0'
base=Path(snapshot_download({MODEL!r},revision={REVISION!r},local_files_only=True))
index=json.loads((base/'model.safetensors.index.json').read_text())
assert all((base/name).is_file() for name in set(index['weight_map'].values()))
fp8=None
for name in sorted(index['weight_map']):
    if '.layers.' not in name or not name.endswith('.weight'):continue
    with safe_open(str(base/index['weight_map'][name]),framework='pt',device='cpu')as shard:
        dtype=shard.get_slice(name).get_dtype()
    if dtype.startswith('F8'):
        fp8=dict(name=name,dtype=dtype);break
assert fp8 is not None,'No representative FP8 layer weight found in cached checkpoint'
argv=server_command(str(base))
parsed=make_arg_parser(FlexibleArgumentParser()).parse_args(argv[argv.index('serve')+2:])
validate_parsed_serve_args(parsed)
req=CompletionRequest.model_validate(dict(model={MODEL!r},prompt=[1]*PROMPT_TOKENS,
    max_tokens={OUTPUT_TOKENS},temperature=0,seed=3827,ignore_eos=True,stream=False,
    logprobs=0,return_tokens_as_token_ids=True))
req.to_sampling_params(max_tokens={OUTPUT_TOKENS})
tok=AutoTokenizer.from_pretrained(base,local_files_only=True)
prompts=dict(main=[make_prompt(tok,i,PROMPT_TOKENS)for i in range(2)],tick=tok.encode('Hello',add_special_tokens=False))
data=json.dumps(prompts,separators=(',',':')).encode();sha=hashlib.sha256(data).hexdigest()
folder=Path('/model-cache/cpu-kv-offload-prompts-v1');folder.mkdir(exist_ok=True)
path=folder/(sha+'.json')
if path.exists():assert path.read_bytes()==data
else:
    import uuid
    temporary=folder/(sha+'-'+uuid.uuid4().hex+'.tmp');temporary.write_bytes(data);temporary.replace(path)
cuda=Path(distribution('nvidia-cuda-nvcc').locate_file('nvidia/cu13'))
assert (cuda/'bin/nvcc').is_file() and (cuda/'lib/libcudart.so.13').is_file()
print(json.dumps(dict(snapshot=str(base),revision={REVISION!r},prompts=str(path),prompt_sha256=sha,
    cuda_home=str(cuda),fp8_weight=fp8,vllm=version('vllm'),torch=version('torch'),cuda=torch.version.cuda,
    transformers=version('transformers'),checkpoint_config_sha256=hashlib.sha256((base/'config.json').read_bytes()).hexdigest())))
'''
    proc=subprocess.run([PYTHON,'-c',code],text=True,capture_output=True,timeout=840,
        env=dict(os.environ,VLLM_TARGET_DEVICE='cpu',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1'))
    if proc.returncode:raise RuntimeError('Cached model/CPU preflight failed before GPU allocation:\n'+proc.stderr[-9000:])
    prepared=json.loads(proc.stdout.strip().splitlines()[-1]);cache.commit();return prepared


@app.function(gpu='RTX-PRO-6000',cpu=8,memory=98304,timeout=1260,startup_timeout=60,
    retries=0,max_containers=1,scaledown_window=2,volumes={'/model-cache':cache,'/results':results})
def probe(run_id,expected,prepared,deadline,claims):
    if claims.get(timeout=5)!='start-once':raise ValueError('Invalid invocation claim')
    verify_sources(expected)
    if deadline-time.time()<360:raise TimeoutError('Less than six minutes remain; refuse GPU preparation')
    if prepared['revision']!=REVISION:raise ValueError('Wrong checkpoint revision')
    if hashlib.sha256(Path(prepared['prompts']).read_bytes()).hexdigest()!=prepared['prompt_sha256']:
        raise ValueError('Prompt file differs')
    if hashlib.sha256((Path(prepared['snapshot'])/'config.json').read_bytes()).hexdigest()!=prepared['checkpoint_config_sha256']:
        raise ValueError('Checkpoint configuration changed after CPU preparation')
    root=Path('/results')/run_id;root.mkdir(exist_ok=False)
    report={'status':'INCOMPLETE','passed':False};child=None
    def expire():
        try:
            if child is not None:os.killpg(child.pid,signal.SIGKILL)
        except ProcessLookupError:pass
        finally:
            try:os.kill(os.getpid(),signal.SIGKILL)
            finally:os._exit(124)
    guard=threading.Timer(max(.001,deadline-time.time()),expire);guard.daemon=True;guard.start()
    try:
        save(root/'started.json',dict(prepared=prepared,deadline=deadline,source_sha256=expected));results.commit()
        from browser_training.compiler_environment import compiler_environment
        env=compiler_environment(prepared['cuda_home'],'/tmp/cpu-offload-cuda-link',dict(os.environ,
            PATH='/opt/rl/.venv/bin:'+os.environ['PATH'],HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',
            VLLM_SERVER_DEV_MODE='1',VLLM_COMPUTE_NANS_IN_LOGITS='1',VLLM_USE_SIMPLE_KV_OFFLOAD='0',
            VLLM_LOG_STATS_INTERVAL='1',OMP_NUM_THREADS='1',
            VLLM_CACHE_ROOT='/model-cache/compiled/spec028-sm120/vllm',TRITON_CACHE_DIR='/model-cache/compiled/spec028-sm120/triton'))
        for key in ('HF_TOKEN','HUGGING_FACE_HUB_TOKEN','WANDB_API_KEY'):env.pop(key,None)
        hardware=subprocess.run(['nvidia-smi','--query-gpu=name,memory.total,compute_cap,driver_version',
            '--format=csv,noheader,nounits'],capture_output=True,text=True,check=True,timeout=10)
        (root/'GPU.txt').write_text(hardware.stdout)
        with(root/'worker.log').open('w')as log:
            child=subprocess.Popen([PYTHON,'/opt/training/scripts/cpu_kv_offload_probe.py',
                '--snapshot',prepared['snapshot'],'--prompts',prepared['prompts'],'--output',str(root/'probe'),
                '--deadline',str(deadline-40)],stdout=log,stderr=subprocess.STDOUT,env=env,start_new_session=True)
            forwarded=0;server_forwarded=0;last_commit=time.monotonic()
            while child.poll()is None:
                if time.time()>=deadline-15:raise TimeoutError('Probe cleanup reserve')
                time.sleep(2)
                forwarded=forward_log(root/'worker.log',forwarded)
                server_forwarded=forward_log(root/'probe/server.log',server_forwarded)
                if time.monotonic()-last_commit>=30:
                    results.commit();last_commit=time.monotonic()
            forward_log(root/'worker.log',forwarded);forward_log(root/'probe/server.log',server_forwarded)
            report=json.loads((root/'probe/report.json').read_text());report['exit_code']=child.returncode
    except BaseException:report.update(error=traceback.format_exc())
    finally:
        if child is not None:
            cleanup='''
import os,signal,sys,psutil
import json
from pathlib import Path
own=os.getpid()
for process in reversed(psutil.Process(int(sys.argv[1])).children(recursive=True)):
    if process.pid==own:continue
    try:process.kill()
    except psutil.NoSuchProcess:pass
try:os.killpg(int(sys.argv[2]),signal.SIGKILL)
except ProcessLookupError:pass
receipt=Path(sys.argv[3])
if receipt.exists():
    try:os.killpg(int(json.loads(receipt.read_text())['process_group']),signal.SIGKILL)
    except ProcessLookupError:pass
'''
            try:
                subprocess.run([PYTHON,'-c',cleanup,str(os.getpid()),str(child.pid),str(root/'probe/server-process.json')],check=True,timeout=10)
                child.wait(timeout=5)
            except Exception:report.update(passed=False,cleanup_error=traceback.format_exc())
        report.update(run_id=run_id,prepared=prepared);save(root/'report.json',report)
        cache.commit();results.commit()
    archive=io.BytesIO()
    with tarfile.open(fileobj=archive,mode='w:gz')as tar:tar.add(root,arcname=run_id)
    guard.cancel()
    return report,archive.getvalue()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--dry-run',action='store_true')
    parser.add_argument('--prepare-only',action='store_true',help='Remote CPU/cache checks only; never spawn a GPU')
    parser.add_argument('--job-cap-seconds',type=int,default=1200)
    args=parser.parse_args()
    if not 600<=args.job_cap_seconds<=1200:parser.error('Job cap must be600..1200seconds')
    plan=dict(model=MODEL,revision=REVISION,gpu='RTX-PRO-6000',GPU_count=1,CPU_bytes=CPU_BYTES,
        mtp=3,input_tokens=PROMPT_TOKENS,output_tokens=OUTPUT_TOKENS,request_upper_bound=MAX_REQUESTS,
        main_requests=7,retries=0,model_downloads=False,prepare_only=args.prepare_only,job_cap_seconds=args.job_cap_seconds,
        allow_ungraded=True,ungraded_reason='Isolated inference/KV restoration diagnostic, no browser task quality claims',
        source_sha256=hashes(),git_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip())
    if args.dry_run:print(json.dumps(plan,indent=2));return
    if subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip():
        raise RuntimeError('Refuse uncommitted experiment source')
    from dotenv import dotenv_values
    for key,value in dotenv_values(args.env_file).items():
        if key in ('MODAL_TOKEN_ID','MODAL_TOKEN_SECRET')and value:os.environ.setdefault(key,value)
    args.output.mkdir(parents=True,exist_ok=False)
    run_id=args.output.name+'-'+uuid.uuid4().hex
    plan['run_id']=run_id;save(args.output/'plan.json',plan)
    for name in SOURCES:
        target=args.output/'sources'/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes((ROOT/name).read_bytes())
    with modal.enable_output(),app.run():
        save(args.output/'app.json',dict(app_id=app.app_id,url=app.get_dashboard_url()))
        prepared=prepare.remote(plan['source_sha256']);save(args.output/'prepared.json',prepared)
        if args.prepare_only:
            print(json.dumps({'status':'CPU_PREPARED','gpu_allocated':False}));return
        deadline=time.time()+args.job_cap_seconds
        with modal.Queue.ephemeral()as claims:
            claims.put('start-once');call=probe.spawn(run_id,plan['source_sha256'],prepared,deadline,claims)
            save(args.output/'call.json',dict(call_id=call.object_id,deadline=deadline))
            try:
                report,data=call.get(timeout=max(1,deadline-time.time()))
                save(args.output/'report.json',report);(args.output/'results.tar.gz').write_bytes(data)
                with tarfile.open(fileobj=io.BytesIO(data),mode='r:gz')as tar:tar.extractall(args.output/'collected',filter='data')
            finally:call.cancel(terminate_containers=True)
    print(json.dumps({'passed':report['passed'],'status':report['status'],'run_id':run_id}))
    if not report['passed']:raise SystemExit(1)


if __name__=='__main__':main()
