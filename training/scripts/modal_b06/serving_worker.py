#!/usr/bin/env python3
"""Episode-owned serving process for exactly one corrected-stack B06 run."""
from hashlib import sha256
from pathlib import Path
import argparse
import json
import os
import queue as stdqueue
import secrets
import signal
import subprocess
import sys
import time
import traceback
import uuid
import urllib.request
import urllib.error

import modal

HERE = Path(__file__).resolve().parent
PYTHON = '/opt/rl/.venv/bin/python'
# Modal imports this module again inside each container. Local image assembly
# must never require workstation paths/environment variables on that import.
if modal.is_local():
    OWN_TRAINING = HERE.parents[1]
    # Build entirely from the reviewed owned tree, not mutable shared sources.
    image = (modal.Image.debian_slim(python_version='3.12')
        .apt_install('git','libgomp1','build-essential').uv_pip_install('uv==0.10.8')
        .add_local_file(OWN_TRAINING/'envs/rl/pyproject.toml','/opt/rl/pyproject.toml',copy=True)
        .add_local_file(OWN_TRAINING/'envs/rl/uv.lock','/opt/rl/uv.lock',copy=True)
        .run_commands('uv python install 3.12.12',
            'cd /opt/rl && uv sync --locked --python 3.12.12 --default-index https://pypi.org/simple',
            'uv pip check --python /opt/rl/.venv/bin/python')
        .env({'HF_HOME':'/model-cache','HF_HUB_CACHE':'/model-cache/hub','HF_XET_HIGH_PERFORMANCE':'1',
              'PYTHONPATH':'/opt/training:/opt/training/scripts','PYTHONUNBUFFERED':'1',
              'VLLM_NO_USAGE_STATS':'1','VLLM_WORKER_MULTIPROC_METHOD':'spawn',
              'WANDB_MODE':'disabled','TOKENIZERS_PARALLELISM':'false','PYTHONDONTWRITEBYTECODE':'1'}))
    cache = modal.Volume.from_name('browser-training-model-cache')
    results = modal.Volume.from_name('browser-training-results')
    EXTRA = [(HERE/n,'/opt/training/scripts/'+n) for n in ('pilot_relay.py','pilot_probe.py','serving_worker.py','compiler_environment.py')]
    EXTRA += [(OWN_TRAINING/'browser_training'/n,'/opt/training/browser_training/'+n) for n in ('__init__.py','vllm_qwen_schema_patch.py')]
    EXTRA += [(OWN_TRAINING/'scripts/apply_vllm_qwen_schema_patch.py','/opt/training/scripts/apply_vllm_qwen_schema_patch.py')]
    for source,destination in EXTRA:
        image = image.add_local_file(source,destination)

else:
    image = None
    cache = modal.Volume.from_name('browser-training-model-cache')
    results = modal.Volume.from_name('browser-training-results')
app = modal.App('qwen-b06-corrected-parser-full-episode',image=image,include_source=False)


def save(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False)+'\n')


@app.function(cpu=4, memory=16384, timeout=240, retries=0,
              max_containers=1, scaledown_window=2, volumes={'/model-cache':cache})
def cpu_prepare(binding, hashes):
    for relative, expected in hashes.items():
        path = Path(relative)
        if not (sha256(path.read_bytes()).hexdigest() == expected):
            raise ValueError(relative)
    patched=subprocess.run([PYTHON,'/opt/training/scripts/apply_vllm_qwen_schema_patch.py'],text=True,capture_output=True,timeout=30)
    if patched.returncode:raise RuntimeError('CPU parser patch failed beforeGPU: '+patched.stderr[-3000:])
    patch_receipt=json.loads(patched.stdout.strip().splitlines()[-1])
    path = Path('/tmp/pilot-binding.json')
    save(path, binding)
    completed = subprocess.run([PYTHON, '/opt/training/scripts/pilot_probe.py', '--binding', str(path)],
        text=True, capture_output=True, timeout=210,
        env=dict(os.environ, HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1'))
    if completed.returncode:
        raise RuntimeError('CPU/cache/processor preflight failed; no GPU allocated:\n'+completed.stderr[-14000:])
    receipt=json.loads(completed.stdout.strip().splitlines()[-1]);receipt['parser_patch_cpu_receipt']=patch_receipt
    return receipt


@app.function(gpu='RTX-PRO-6000', cpu=8, memory=98304, timeout=86400,
              startup_timeout=60, retries=0, max_containers=1, scaledown_window=2,
              volumes={'/model-cache':cache,'/results':results})
def gpu_server(run_id, binding, prepared, token, messages, counter_projection):
    started = time.time()
    from compiler_environment import compiler_environment
    from pilot_relay import serve
    deadline = started+86400  # Provider platform maximum; not an episode budget.
    platform_lifetime=dict(mode="episode-owned",expiry_kind="provider-platform-maximum",started_at_utc=started,expires_at_utc=deadline,provider_max_seconds=86400)
    run = Path('/results')/run_id
    server = monitor = log = gpu_log = None
    report = {'status':'INCOMPLETE','run_id':run_id}
    try:
        messages.put({'phase':'started','started':started,'deadline':deadline}, timeout=10, partition='events')
        results.reload()
        run.mkdir(exist_ok=False)
        save(run/'binding.json', binding)
        save(run/'started.json', {'started':started,'deadline':deadline,'platform_lifetime':platform_lifetime})
        results.commit()
        env = compiler_environment(prepared['cuda_home'], '/tmp/pilot-cuda-link',
            dict(os.environ, PATH='/opt/rl/.venv/bin:'+os.environ['PATH'], HF_HUB_OFFLINE='1',
                 TRANSFORMERS_OFFLINE='1', VLLM_CACHE_ROOT='/model-cache/compiled/rl-vllm028-torch213-sm120/vllm',
                 TRITON_CACHE_DIR='/model-cache/compiled/rl-vllm028-torch213-sm120/triton'))
        for key in ('HF_TOKEN','HUGGING_FACE_HUB_TOKEN','VLLM_SERVER_DEV_MODE','VLLM_ALLOW_RUNTIME_LORA_UPDATING'):
            env.pop(key,None)
        patched=subprocess.run([PYTHON,'/opt/training/scripts/apply_vllm_qwen_schema_patch.py'],env=env,text=True,capture_output=True,timeout=30)
        if patched.returncode:raise RuntimeError('Installed server parser patch failed: '+patched.stderr[-3000:])
        patch_receipt=json.loads(patched.stdout.strip().splitlines()[-1])
        regression=dict(passed=patch_receipt['cpu_regression']['passed'],serving_session_id=run_id,patched_source_sha256=patch_receipt['cpu_regression']['source_sha256'],cases=patch_receipt['cpu_regression']['cases'],scope=patch_receipt['cpu_regression']['scope'])
        save(run/'parser-regression.json',regression);save(run/'parser-patch.json',patch_receipt)
        command = list(binding['server_argv'])
        command[0] = '/opt/rl/.venv/bin/vllm'
        command[2] = prepared['snapshot']
        save(run/'server-command.json',command)
        log = (run/'server.log').open('w')
        gpu_log = (run/'gpu.csv').open('w')
        hardware = subprocess.check_output([PYTHON,'-c',
            "import torch,json; p=torch.cuda.get_device_properties(0); print(json.dumps(dict(name=p.name,capability=list(torch.cuda.get_device_capability(0)),vram_bytes=p.total_memory,bf16=torch.cuda.is_bf16_supported(),torch=torch.__version__,cuda=torch.version.cuda,gpus=torch.cuda.device_count())))"],
            env=env, text=True, timeout=30)
        hardware = json.loads(hardware.strip().splitlines()[-1])
        if not (hardware['gpus'] == 1 and hardware['capability'] == [12, 0] and hardware['bf16']):
            raise ValueError(hardware)
        save(run/'hardware.json',hardware)
        monitor = subprocess.Popen(['nvidia-smi','--query-gpu=timestamp,name,utilization.gpu,memory.used,power.draw',
                                     '--format=csv','-l','1'],stdout=gpu_log)
        server = subprocess.Popen(command, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        last_controller=time.monotonic()
        while True:
            control=None
            try:
                control=messages.get(timeout=.01,partition='commands')
            except stdqueue.Empty:pass
            except Exception as exc:
                report["last_control_error"]=type(exc).__name__
                time.sleep(1)
            if control=='heartbeat':last_controller=time.monotonic()
            elif control=='stop':raise InterruptedError('Controller stopped during startup')
            if time.monotonic()-last_controller>180:
                raise TimeoutError('Controller absent during startup')
            if server.poll() is not None:
                raise RuntimeError('vLLM exited '+str(server.returncode)+'\n'+(run/'server.log').read_text()[-16000:])
            if time.time() > started+480:
                raise TimeoutError('vLLM startup exceeded 8-minute cap; no diagnostic dispatched')
            try:
                with urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=1) as response:
                    if response.status == 200:
                        break
            except (OSError,TimeoutError):
                time.sleep(1)
        identity = dict(model=binding['model']['repository'],serving_revision=binding['model']['revision'],
            tokenizer_sha256=binding['tokenizer']['tokenizer.json']['sha256'],
            template_sha256=binding['tokenizer']['chat_template.jinja']['sha256'],
            image_processor_sha256=prepared['image_processor_sha256'],tool_parser='qwen3_coder',
            source_commit=binding['first_case']['commit'])
        qualification = dict(identity=identity, server_context=131072, isl=100000,
            processor=prepared['processor'], hardware=hardware, command=command,
            versions=prepared['versions'], runtime_lock_sha256=binding['runtime']['lock_sha256'],
            platform_lifetime=platform_lifetime,parser_patch_sha256=patch_receipt['vllm_source_patch_sha256'],
            parser_patch_receipt=patch_receipt,parser_regression=regression,counter_projection_sha256=counter_projection,
            startup_seconds=time.time()-started, deadline=deadline, ready=False,
            serving_session_id=run_id, vision=True,native_tools=True,exact_complete_request_counter=False,
            qualification='Awaiting live client token/render/generation parity; not dispatch ready')
        save(run/'server-identity.json',qualification)
        results.commit()
        # Expose only an authenticated allowlist; the actual vLLM listener stays
        # loopback-only and runtime LoRA/development endpoints stay disabled.
        with serve(('0.0.0.0',8888),upstream='http://127.0.0.1:8000',token=token,
                   qualification=qualification,deadline=deadline,transform_tokens=True):
            with modal.forward(8888) as tunnel:
                messages.put({'phase':'ready','tunnel_url':tunnel.url,'qualification':qualification},
                             timeout=10,partition='events')
                last_heartbeat=last_controller
                while time.time() < deadline-30:
                    if server.poll() is not None:
                        raise RuntimeError('Serving process exited after readiness')
                    if time.monotonic()-last_heartbeat>180:
                        report['status']='CONTROLLER_LOST';break
                    try:
                        command_message = messages.get(timeout=2, partition='commands')
                    except stdqueue.Empty:
                        continue
                    except Exception as exc:
                        report["last_control_error"]=type(exc).__name__
                        time.sleep(1)
                        continue
                    if command_message == 'heartbeat':
                        last_heartbeat=time.monotonic();continue
                    if command_message == 'stop':
                        report['status'] = 'STOPPED_BY_CLIENT'
                        break
                else:
                    report['status'] = 'DEADLINE_STOP'
    except Exception:
        report.update(status='FAIL',error=traceback.format_exc())
        try: messages.put({'phase':'failed','report':report},timeout=5,partition='events')
        except Exception as exc: report['queue_error']=type(exc).__name__
    finally:
        def attempt(name,operation):
            try: operation()
            except Exception as exc:
                report.setdefault('cleanup_errors',[]).append({'operation':name,'error':type(exc).__name__})
        def stop(process,group=False):
            try:
                if group: os.killpg(process.pid,signal.SIGTERM)
                else: process.terminate()
                process.wait(timeout=5)
            finally:
                try:
                    if group: os.killpg(process.pid,signal.SIGKILL)
                    elif process.poll() is None: process.kill()
                except ProcessLookupError: pass
                process.wait(timeout=3)
        if server is not None: attempt('server-stop',lambda:stop(server,group=True))
        if monitor is not None: attempt('monitor-stop',lambda:stop(monitor))
        if log is not None: attempt('server-log-close',log.close)
        if gpu_log is not None: attempt('gpu-log-close',gpu_log.close)
        report['elapsed_seconds']=time.time()-started
        if (run/'server.log').is_file():
            attempt('server-log-read',lambda:report.update(server_log_tail=(run/'server.log').read_text()[-16000:]))
        attempt('report-write',lambda:save(run/'report.json',report))
        attempt('results-commit',results.commit)
        attempt('compiled-cache-commit',cache.commit)
    return report


