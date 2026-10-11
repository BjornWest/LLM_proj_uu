#!/usr/bin/env python3
"""One bounded Modal RTX PRO job with a declared finite throughput matrix."""
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
sys.path.insert(0,str(ROOT/"scripts"))
from spec_decode_benchmark import ARMS,BATCH,ISL,OSL,MODEL,REVISION,DRAFT,DRAFT_REVISION,CACHE_BLOCK_SIZE,parse_arm_batches,save
PYTHON="/opt/rl/.venv/bin/python"
# One mapping binds uploaded sources and copied build inputs to actual container
# locations. No legacy episode module, relay, parser patch or volume factory.
SOURCE_DESTINATIONS = {
    "scripts/modal_spec_decode.py": "/opt/training/scripts/modal_spec_decode.py",
    "scripts/spec_decode_benchmark.py": "/opt/training/scripts/spec_decode_benchmark.py",
    "scripts/spec_cache_preflight.py": "/opt/training/scripts/spec_cache_preflight.py",
    "scripts/modal_rl_image.py": "/opt/training/scripts/modal_rl_image.py",
    "browser_training/browser_benchmark_prompts.py": "/opt/training/browser_training/browser_benchmark_prompts.py",
    "browser_training/compiler_environment.py": "/opt/training/browser_training/compiler_environment.py",
    "browser_training/__init__.py": "/opt/training/browser_training/__init__.py",
    "envs/rl/pyproject.toml": "/opt/rl/pyproject.toml",
    "envs/rl/uv.lock": "/opt/rl/uv.lock",
}


def source_hashes(root=ROOT):
    return {name: hashlib.sha256((root/name).read_bytes()).hexdigest()
            for name in SOURCE_DESTINATIONS}


def verify_sources(hashes):
    if set(hashes) != set(SOURCE_DESTINATIONS):
        raise ValueError("Incomplete or unexpected image source fingerprint")
    for relative, digest in hashes.items():
        if hashlib.sha256(Path(SOURCE_DESTINATIONS[relative]).read_bytes()).hexdigest() != digest:
            raise ValueError("Image source fingerprint differs: " + relative)


if modal.is_local():
    from modal_rl_image import build_image
    image = build_image(ROOT)
    for relative, destination in SOURCE_DESTINATIONS.items():
        if not relative.startswith("envs/rl/"):
            image = image.add_local_file(ROOT/relative, destination)
else:
    image = None
cache=modal.Volume.from_name("browser-training-model-cache")
results=modal.Volume.from_name("browser-training-results")
app=modal.App("qwen38-spec-decode-six-cohorts",image=image,include_source=False)


@app.function(cpu=4,memory=16384,timeout=1200,retries=0,max_containers=1,scaledown_window=2,
              volumes={"/model-cache":cache})
def prepare(source_hashes, prompt_count=BATCH):
    verify_sources(source_hashes)
    code=f"""
import json,hashlib,os
from pathlib import Path
from importlib.metadata import version,distribution
import torch
assert version('torch').split('+')[0]=='2.13.0' and torch.version.cuda=='13.0'
assert version('psutil')=='7.2.2'
from huggingface_hub import snapshot_download
from transformers import AutoTokenizer
from vllm.entrypoints.openai.completion.protocol import CompletionRequest
assert version('vllm')=='0.28.0'
base=Path(snapshot_download({MODEL!r},revision={REVISION!r},local_files_only=True))
index=json.loads((base/'model.safetensors.index.json').read_text())
assert all((base/name).is_file() for name in set(index['weight_map'].values()))
draft=Path(snapshot_download({DRAFT!r},revision={DRAFT_REVISION!r},allow_patterns=['config.json','*.safetensors']))
config=json.loads((draft/'config.json').read_text())
assert config['architectures']==['DFlash2DraftModel'] and config['sliding_window']==2048
assert config['layer_types']==['sliding_attention']*5
from spec_decode_benchmark import command,ARMS,ISL,BATCH
from spec_cache_preflight import verify
cache_fix=verify()
from vllm.entrypoints.openai.cli_args import make_arg_parser,validate_parsed_serve_args
from vllm.utils.argparse_utils import FlexibleArgumentParser
from browser_training.browser_benchmark_prompts import make_prompt
for arm in ARMS:
    argv=command(str(base),str(draft),arm)
    parsed=make_arg_parser(FlexibleArgumentParser()).parse_args(argv[argv.index('serve')+2:])
    validate_parsed_serve_args(parsed)
    req=CompletionRequest.model_validate(dict(model={MODEL!r},prompt=[1]*ISL,
         max_tokens={OSL},temperature=.6,top_p=.95,top_k=20,seed=3827,ignore_eos=True,
         stream=True,stream_options=dict(include_usage=True),logprobs=0,return_tokens_as_token_ids=True))
    assert req.return_tokens_as_token_ids and req.logprobs==0
    req.to_sampling_params(max_tokens={OSL})
from vllm.model_executor.models.registry import ModelRegistry
assert 'DFlash2DraftModel' in ModelRegistry.get_supported_archs()
tok=AutoTokenizer.from_pretrained(base,local_files_only=True)
prompts=[make_prompt(tok,i,ISL) for i in range({prompt_count})]
assert all(len(p)==ISL for p in prompts)
path=Path('/model-cache/spec-decode-60k-v1');path.mkdir(exist_ok=True)
data=json.dumps(prompts).encode();prompt_path=path/'prompts-{prompt_count}.json';prompt_path.write_bytes(data)
cuda=Path(distribution('nvidia-cuda-nvcc').locate_file('nvidia/cu13'))
print(json.dumps(dict(snapshot=str(base),draft=str(draft),prompts=str(prompt_path),
    cache_fix=cache_fix,prompt_sha256=hashlib.sha256(data).hexdigest(),cuda_home=str(cuda),vllm=version('vllm'),
    torch=version('torch'),cuda=torch.version.cuda,transformers=version('transformers'),
    flashinfer=version('flashinfer-python'),psutil=version('psutil'),
    base_revision={REVISION!r},draft_revision={DRAFT_REVISION!r},
    draft_weight_bytes=sum(p.stat().st_size for p in draft.glob('*.safetensors')),
    tokenizer_sha256=hashlib.sha256((base/'tokenizer.json').read_bytes()).hexdigest(),
    template_sha256=hashlib.sha256((base/'chat_template.jinja').read_bytes()).hexdigest())))
"""
    completed=subprocess.run([PYTHON,"-c",code],cwd="/opt/training",text=True,capture_output=True,timeout=1140,
        env=dict(os.environ,VLLM_TARGET_DEVICE="cpu"))
    cache.commit()
    if completed.returncode:raise RuntimeError("CPU preparation failed before GPU allocation:\n"+completed.stderr[-14000:])
    prepared=json.loads(completed.stdout.strip().splitlines()[-1]);cache.commit();return prepared


@app.function(gpu="RTX-PRO-6000",cpu=8,memory=98304,timeout=2760,startup_timeout=60,
              retries=0,max_containers=1,scaledown_window=2,
              volumes={"/model-cache":cache,"/results":results})
def benchmark(run_id,prepared,deadline,claims,arm_batches=None):
    if claims.get(timeout=5)!="start-once":raise ValueError("Invalid invocation claim")
    if time.time()>=deadline:raise TimeoutError("Expired before GPU work")
    run=Path("/results")/run_id;run.mkdir(exist_ok=False)
    save(run/"started.json",dict(started=time.time(),deadline=deadline,prepared=prepared));results.commit()
    child=None
    def stop_descendants():
        # psutil belongs to the pinned RL venv, not Modal's system interpreter.
        cleanup_code="""
import json,os,signal,sys,psutil
from pathlib import Path
root_pid=int(sys.argv[1]); own_pid=os.getpid()
for process in reversed(psutil.Process(root_pid).children(recursive=True)):
    if process.pid==own_pid:continue
    try:process.kill()
    except psutil.NoSuchProcess:pass
try:os.killpg(int(sys.argv[3]),signal.SIGKILL)
except ProcessLookupError:pass
for path in (Path(sys.argv[2])/'benchmark').glob('*/server-process.json'):
    record=json.loads(path.read_text())
    try:
        leader=psutil.Process(record['pid'])
        if leader.create_time()!=record['created']:continue
    except psutil.NoSuchProcess:pass
    try:os.killpg(record['pid'],signal.SIGKILL)
    except ProcessLookupError:pass
"""
        result=subprocess.run([PYTHON,'-c',cleanup_code,str(os.getpid()),str(run),str(child.pid)],
            capture_output=True,text=True,timeout=10)
        if result.returncode:raise RuntimeError('Owned cleanup failed: '+result.stderr[-2000:])
    def expire():
        # No imports, subprocesses or filesystem work at the hard deadline.
        try:
            if child is not None:os.killpg(child.pid,signal.SIGKILL)
        except ProcessLookupError:pass
        finally:
            try:os.kill(os.getpid(),signal.SIGKILL)
            finally:os._exit(124)
    guard=threading.Timer(max(0,deadline-time.time()),expire);guard.daemon=True;guard.start()
    from browser_training.compiler_environment import compiler_environment
    env=compiler_environment(prepared['cuda_home'],"/tmp/spec-cuda-link",
        dict(os.environ,PATH="/opt/rl/.venv/bin:"+os.environ["PATH"],OMP_NUM_THREADS="1",
             HF_HUB_OFFLINE="1",TRANSFORMERS_OFFLINE="1",VLLM_SERVER_DEV_MODE="1",
             VLLM_LOG_STATS_INTERVAL="1",
             VLLM_CACHE_ROOT="/model-cache/compiled/spec028-sm120/vllm",
             TRITON_CACHE_DIR="/model-cache/compiled/spec028-sm120/triton"))
    # Localhost-only reset API; no adapter publication or credentials in worker.
    for key in ('HF_TOKEN','HUGGING_FACE_HUB_TOKEN','VLLM_ALLOW_RUNTIME_LORA_UPDATING'):
        env.pop(key,None)
    data=Path(prepared['prompts']).read_bytes()
    if hashlib.sha256(data).hexdigest()!=prepared['prompt_sha256']:raise ValueError("Prompt fingerprint differs")
    command=[PYTHON,"/opt/training/scripts/spec_decode_benchmark.py","--snapshot",prepared['snapshot'],
        "--draft",prepared['draft'],"--prompts",prepared['prompts'],"--output",str(run/"benchmark"),
        "--deadline",str(deadline-30)]
    for value in arm_batches or []:
        command.extend(["--arm-batch",value])
    report=dict(status="INCOMPLETE")
    try:
        with (run/"worker.log").open("w") as log:
            child=subprocess.Popen(command,cwd="/opt/training",env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            forwarded=0
            while child.poll() is None:
                if time.time()>=deadline-20:raise TimeoutError("Worker execution deadline")
                time.sleep(3)
                try:text=(run/'worker.log').read_text(errors='replace')
                except OSError:continue
                if len(text)>forwarded:
                    print(text[forwarded:],end='',flush=True);forwarded=len(text)
            code=child.wait(timeout=5)
        report=json.loads((run/"benchmark/report.json").read_text())
        report['worker_exit_code']=code
        if code:report['status']='INCOMPLETE'
    except Exception:report.update(error=traceback.format_exc())
    finally:
        if child is not None:
            try:
                stop_descendants()
                child.wait(timeout=5)
            except Exception:
                report.update(status="INCOMPLETE",cleanup_error=traceback.format_exc())
        report.update(run_id=run_id,prepared=prepared,deadline=deadline)
        save(run/"report.json",report);cache.commit();results.commit()
    archive=io.BytesIO()
    with tarfile.open(fileobj=archive,mode="w:gz") as tar:
        tar.add(run,arcname=run_id)
    guard.cancel()
    return report,archive.getvalue()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--env-file",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--prepare-only",action="store_true")
    p.add_argument("--dry-run",action="store_true")
    p.add_argument("--job-cap-seconds",type=int,default=2700)
    p.add_argument("--arm-batch",action="append",help="Explicit finite ARM=BATCH[,BATCH] matrix")
    a=p.parse_args()
    try:matrix=parse_arm_batches(a.arm_batch)
    except ValueError as exc:p.error(str(exc))
    prompt_count=max(n for batches in matrix.values() for n in batches) if matrix else BATCH
    requests=sum(sum(batches) for batches in matrix.values()) if matrix else 3*(1+BATCH)
    if not 300<=a.job_cap_seconds<=2700:p.error("Job cap must be 300..2700 seconds")
    dirty=subprocess.check_output(["git","status","--porcelain"],cwd=ROOT,text=True).strip()
    if dirty:raise RuntimeError("Refuse an uncommitted benchmark source tree")
    hashes=source_hashes()
    plan=dict(model=MODEL,revision=REVISION,draft=DRAFT,draft_revision=DRAFT_REVISION,
        gpu="RTX-PRO-6000",gpu_count=1,job_cap_seconds=a.job_cap_seconds,retries=0,
        cache_block_size=CACHE_BLOCK_SIZE,cache_fix="configuration-only; CPU allocator regression + GPU realised-spec gate",
        arms=list(matrix) if matrix else list(ARMS),
        arm_batches=matrix,batches=None if matrix else [1,"common selected from DFlash capacity, maximum 16"],
        measured_cohorts=sum(len(batches) for batches in matrix.values()) if matrix else 6,input_tokens=ISL,output_tokens=OSL,
        measured_requests_upper_bound=requests,warmup_requests_upper_bound=requests,warmup_output_tokens=64,source_sha256=hashes,
        allow_ungraded=True,ungraded_reason="Explicit throughput benchmark; no browser/task episode or task-success claim",
        git_commit=subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip(),
        note="Synthetic text-only browser histories; vision-capable engine; warmed prefixes; no browser/task quality claims")
    if a.dry_run:print(json.dumps(plan,indent=2));return
    from dotenv import dotenv_values
    for key,value in dotenv_values(a.env_file).items():
        if key in ("MODAL_TOKEN_ID","MODAL_TOKEN_SECRET") and value:os.environ.setdefault(key,value)
    a.output.mkdir(parents=True,exist_ok=False)
    # The volume is shared across projects/cohorts, unlike a local parent path.
    # Preserve historical directories and bind an unpredictable unique remote ID.
    plan["run_id"]=a.output.name+"-"+uuid.uuid4().hex
    save(a.output/"plan.json",plan)
    for name in SOURCE_DESTINATIONS:
        target=a.output/"sources"/name;target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes((ROOT/name).read_bytes())
    with modal.enable_output(),app.run():
        save(a.output/"app.json",dict(app_id=app.app_id,url=app.get_dashboard_url()))
        prepared=prepare.remote(hashes,prompt_count);save(a.output/"prepared.json",prepared)
        if a.prepare_only:return
        deadline=time.time()+a.job_cap_seconds
        with modal.Queue.ephemeral() as claims:
            claims.put("start-once")
            call=benchmark.spawn(plan["run_id"],prepared,deadline,claims,a.arm_batch)
            save(a.output/"call.json",dict(call_id=call.object_id,deadline=deadline))
            try:
                report,data=call.get(timeout=max(1,deadline-time.time()))
                save(a.output/"report.json",report)
                (a.output/"results.tar.gz").write_bytes(data)
                with tarfile.open(fileobj=io.BytesIO(data),mode="r:gz") as tar:
                    tar.extractall(a.output/"collected",filter="data")
                print(json.dumps(report,indent=2))
            finally:call.cancel(terminate_containers=True)
    if report['status']!='COMPLETE':raise SystemExit(1)


if __name__=="__main__":main()
