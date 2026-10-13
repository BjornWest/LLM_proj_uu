#!/usr/bin/env python3
"""Measure an owned running suite server and publish first/reused capability.

Plan is the default. Execute imports the installed GPU/processor stack only on
an explicitly approved SM120 host; never allocates or generates model tokens.
"""
import argparse
from copy import deepcopy
from hashlib import sha256
from importlib.metadata import distribution, version
import json
import math
import os
from pathlib import Path
import re
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from qwen_suite_qualification import read_pin, pin, publish, owned_listener, raw_get, supported_profile
from qualify_qwen_wire import source_runtime, gpu_check, GEOMETRY, MODEL, REVISION, CONTEXT


def load(row): return json.loads(read_pin(row))


def installed_patch_sources(source):
    files = {'scheduler': source/'distributed/kv_transfer/kv_connector/v1/offloading/scheduler.py',
             'parser': source/'tool_parsers/utils.py'}
    return {key: sha256(path.read_bytes()).hexdigest() for key, path in files.items()}


def resolved_backends(text):
    """Parse decisions actually emitted by pinned vLLM0.28, never argv defaults."""
    patterns = {
        'attention': r'Using ([A-Z_]+) attention backend out of potential backends:',
        'gdn_prefill': r'Using (Triton/FLA|FlashInfer|CuteDSL) GDN prefill kernel ',
        'gdn_decode': r'GDN decode kernel: ([a-zA-Z0-9_]+)',
        'weight': r'Selected ([a-zA-Z0-9_]+) for Fp8LinearMethod',
        'vision': r'Using backend (?:AttentionBackendEnum\.)?([A-Z_]+) for vit attention',
    }
    selected = {}
    for key, expression in patterns.items():
        values = set(re.findall(expression, text))
        if len(values) != 1: raise ValueError('Missing/ambiguous actual backend decision: ' + key)
        selected[key] = values.pop()
    return {'prefill': selected['attention'], 'decode': selected['attention'],
            'linear_attention': 'prefill=' + selected['gdn_prefill'] + ';decode=' + selected['gdn_decode'],
            'weight_compute': selected['weight']}, selected['vision']


def capability(runtime, compatibility, wire, wire_pin, measurement_pin, output):
    """Publish only complete actual wire evidence; CPU fixtures never call this CLI."""
    if (wire.get('passed') is not True or wire.get('synthetic') is not False
            or wire.get('status') != 'wire_qualification_passed'
            or wire.get('wire_serialization') != 'json-insertion-order-v1'
            or wire.get('diagnostic_generation_requests') != 5
            or wire.get('diagnostic_generation_attempts') != 5
            or wire.get('stopped_by_signal')
            or any(wire.get('checks', {}).get(k) is not True for k in runtime['CHECKS'])):
        raise ValueError('Complete actual successful five-generation wire proof required')
    fingerprint = runtime['digest'](compatibility, sorted_keys=True)
    proofs = {}
    for kind in ('qualification', 'deployment', 'processor'):
        proofs[kind] = publish(output / (kind + '-proof.json'), {
            'passed': True, 'synthetic': False, 'proof_kind': kind, 'fingerprint': fingerprint,
            'measurement': measurement_pin, 'wire': wire_pin,
            'scope': 'Owned running server, installed measurements and actual complete wire comparisons.'})
    return publish(output / 'capability.json', {'schema': 'serving-stack-capability-v1',
        'status': 'passed', 'synthetic': False, 'fingerprint': fingerprint,
        'compatibility': compatibility, 'checks': {k: True for k in runtime['CHECKS']}, 'proofs': proofs})


def reused_capability(row, compatibility, runtime):
    value = load(row)
    if (value.get('schema') != 'serving-stack-capability-v1' or value.get('status') != 'passed'
            or value.get('synthetic') is not False or value.get('compatibility') != compatibility
            or value.get('fingerprint') != runtime['digest'](compatibility, sorted_keys=True)
            or any(value.get('checks', {}).get(k) is not True for k in runtime['CHECKS'])
            or set(value.get('proofs', {})) != {'qualification', 'deployment', 'processor'}):
        raise ValueError('Reusable capability differs from this actually measured stack')
    for kind, proof_pin in value['proofs'].items():
        proof = load(proof_pin)
        if (proof.get('passed') is not True or proof.get('synthetic') is not False
                or proof.get('proof_kind') != kind or proof.get('fingerprint') != value['fingerprint']):
            raise ValueError('Original typed actual capability proof required')
    return row


def measure(context, runtime):
    """Execute in the serving interpreter, exit to release any inspection context."""
    launch = load(context['launch']); owner = load(context['owner']); rental = load(context['rental'])
    now = time.time(); end = rental['deadline_utc']
    if (rental.get('allocation_authorized') is not True or not math.isfinite(end)
            or not rental['allocation_utc'] <= now < end
            or rental['allocation_utc'] + rental['approved_rental_seconds'] != end
            or rental['serving_session_id'] != launch['attempt_id'] or launch['pid'] != owner['pid']
            or launch['command'][0] != sys.executable):
        raise ValueError('Actual approved owned launch and original rental required')
    port = int(launch['launch_settings']['port']); owned_listener(owner, port)
    if Path('/proc/'+str(owner['pid'])+'/exe').resolve()!=Path(sys.executable).resolve():
        raise ValueError('Owned server interpreter differs from measurement interpreter')
    live_env=dict(item.split('=',1) for item in Path('/proc/'+str(owner['pid'])+'/environ').read_bytes().decode().split('\0') if '=' in item)
    if live_env!=launch['serving_environment']:
        raise ValueError('Live serving environment differs from the owned exec receipt')
    gpu_check()  # Inspection child exits; it never retains an extra CUDA context.
    snapshot = Path(launch['command'][5]).resolve(strict=True)
    if snapshot.name != REVISION: raise ValueError('Exact official snapshot required')
    from vllm.transformers_utils.processor import get_processor
    processor = get_processor(str(snapshot), local_files_only=True, **GEOMETRY)
    image = processor.image_processor
    if (image.patch_size != 16 or image.merge_size != 2 or image.temporal_patch_size != 2
            or image.size != {'shortest_edge': 65536, 'longest_edge': 16777216}):
        raise ValueError('Actual official image geometry differs')
    # /tokenizer_info is read-only; bound transport with actual owner before/after.
    info = tokenizer_info(port, min(10, end-time.time()))
    tokenizer = processor.tokenizer
    template = processor.chat_template
    if (not isinstance(template, str) or info.get('chat_template') != template
            or info.get('tokenizer_class') not in {type(tokenizer).__name__,
                'Cached'+type(tokenizer).__name__, 'TokenizerPoolCached'+type(tokenizer).__name__}):
        raise ValueError('Served tokenizer/template differs from loaded official processor')
    assets = {'tokenizer_sha256': sha256(tokenizer.backend_tokenizer.to_str().encode()).hexdigest(),
        'template_sha256': sha256(template.encode()).hexdigest(),
        'processor_sha256': runtime['digest']({'class':type(image).__name__, 'config':image.to_dict()}, sorted_keys=True)}
    source = Path(distribution('vllm').locate_file('vllm'))
    patches = installed_patch_sources(source)
    if (patches['scheduler'] != '599a1613fb6088a28c14b7fb2119b7eabfe5ed5e4085b1c6fd5f4a4c8a23f3ec'
            or patches['parser'] != '93f9b8ec0097f5b4d416e9106442900727a3aa7ca48930469fca88a1fd33c064'):
        raise ValueError('Installed patches differ from reviewed source')
    backends, vision = resolved_backends(read_pin(context['startup_log']).decode())
    package_names = ('transformers','tokenizers','triton','flashinfer-python','flash-linear-attention','kernels','nvidia-cuda-nvcc')
    packages = {name:version(name) for name in package_names}; packages['vision_attention_backend'] = vision
    import torch
    if (version('vllm')!='0.28.0' or torch.__version__!='2.13.0+cu130' or torch.version.cuda!='13.0'
            or packages['transformers']!='5.16.1' or packages['tokenizers']!='0.23.2'
            or packages['flash-linear-attention']!='0.5.2'):
        raise ValueError('Installed critical versions differ from the qualified stack')
    compatibility = {'runtime': {'vllm_version':version('vllm'), 'vllm_source_patch_sha256':runtime['digest'](patches,sorted_keys=True),
        'pytorch_version':torch.__version__, 'cuda_runtime_version':torch.version.cuda,
        'runtime_lock_sha256':context['runtime_lock']['sha256'], 'kernel_versions':packages,
        'counter_projection_sha256':runtime['projection_sha256']()},
        'hardware':{'gpu_architecture':'sm120'}, 'model':{'repository':MODEL,'revision':REVISION}, 'assets':assets,
        'serving':{'context_tokens':CONTEXT,'image_limits':{'limit_mm_per_prompt':{'image':1562,'video':0},'mm_processor_kwargs':GEOMETRY},
            'weight_quantization':'fp8','kv_cache_dtype':'fp8_e4m3','kv_scales_sha256':None,
            'thinking':True,'preserve_thinking':True,'tool_parser':'qwen3_coder','reasoning_parser':'qwen3',
            'mtp_mode':{'method':'mtp','num_speculative_tokens':3},'lora_mode':None,'attention_backend':backends}}
    runtime['validate_compatibility'](compatibility); supported_profile(launch,compatibility)
    if Path(context['runtime_lock']['path']).resolve()!=Path(sys.executable).parent.parent.parent/'uv.lock':
        raise ValueError('Runtime lock must be the actually used serving environment lock')
    for field in ('runtime','launch','owner','rental','runtime_lock','startup_log'): read_pin(context[field])
    owned_listener(owner,port)
    if time.time() >= end: raise TimeoutError('Original rental ended during measurement')
    identity = {'model':MODEL,'serving_revision':REVISION,'tokenizer_sha256':assets['tokenizer_sha256'],
        'template_sha256':assets['template_sha256'],'image_processor_sha256':assets['processor_sha256'],'tool_parser':'qwen3_coder'}
    executable=Path(sys.executable).resolve(strict=True)
    return {'compatibility':compatibility,'identity':identity,'installed_patch_sources':patches,
            'interpreter':{'path':sys.executable,'resolved_path':str(executable),'sha256':sha256(executable.read_bytes()).hexdigest(),'version':sys.version},
            'tokenizer_info':info,'measured_at_utc':time.time(), 'serving_process':owner}


def tokenizer_info(port, timeout):
    # Fixed private address, no proxy or DNS and an overall time limit.
    import http.client
    import threading
    from qwen_suite_qualification import close_socket
    if not 0 < timeout <= 10: raise TimeoutError('Original rental ended')
    conn = http.client.HTTPConnection('127.0.0.1',port,timeout=timeout); timer=None
    try:
        conn.connect(); timer=threading.Timer(timeout,close_socket,(conn.sock,)); timer.daemon=True;timer.start()
        conn.request('GET','/tokenizer_info');response=conn.getresponse();data=response.read((2<<20)+1)
        if response.status != 200 or len(data) > 2<<20: raise ValueError('Bounded tokenizer info required')
        return json.loads(data)
    finally:
        if timer is not None:timer.cancel()
        conn.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--context',type=Path,required=True);parser.add_argument('--context-sha256',required=True)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--execute',action='store_true')
    args=parser.parse_args();context_pin={'path':str(args.context.absolute()),'sha256':args.context_sha256};context=load(context_pin)
    runtime=source_runtime(context['runtime'])
    for name in ('runtime','launch','owner','rental','runtime_lock','startup_log'):read_pin(context[name])
    if not args.execute:
        print(json.dumps({'status':'plan_only','context':context_pin,'GPU_HTTP_or_dispatch':False}));return
    os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',PYTHONDONTWRITEBYTECODE='1')
    parent=args.output.parent
    if not parent.is_dir() or parent.stat().st_uid!=os.geteuid() or parent.stat().st_mode&0o077:
        raise ValueError('Existing private owned output parent required')
    args.output.mkdir(mode=0o700,exist_ok=False)
    measured=measure(context,runtime);measurement_pin=publish(args.output/'measurement.json',measured)
    compat=measured['compatibility'];rental=load(context['rental']);launch=load(context['launch'])
    if context.get('reuse_capability') is not None:
        if context.get('wire') is not None:raise ValueError('Reuse cannot claim new diagnostic generations')
        cap=reused_capability(context['reuse_capability'],compat,runtime)
    else:
        wire_pin=context['wire'];proof=load(wire_pin)
        if (proof['serving_session_id']!=launch['attempt_id'] or proof['deadline_utc']!=rental['deadline_utc']
                or any(proof['inputs'][k]!=context[k] for k in ('runtime','launch','owner','rental'))):
            raise ValueError('Wire proof differs from current owned session/source/lifetime')
        cap=capability(runtime,compat,proof,wire_pin,measurement_pin,args.output)
    deployment={'passed':True,'synthetic':False,'serving_session_id':launch['attempt_id'],
        'identity':measured['identity'],'observed_compatibility':compat,'serving_process':measured['serving_process'],
        'launch_receipt':context['launch'],'server_context':CONTEXT,'vision_configured':True,'native_tools_configured':True,
        'exact_request_counter':True,'measurement':measurement_pin,
        **{k:rental[k] for k in ('run_id','instance_id','deadline_utc','allocation_utc','approved_rental_seconds')}}
    result={'capability':cap,'deployment':publish(args.output/'deployment.json',deployment),'measurement':measurement_pin}
    publish(args.output/'measurement-result.json',result);print(json.dumps(result))


if __name__=='__main__':main()
