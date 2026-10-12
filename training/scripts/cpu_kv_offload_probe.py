#!/usr/bin/env python3
"""Isolated FP8 Qwen + MTP3 CPU KV restore probe; no browser or capacity gate."""
import argparse
import hashlib
import http.client
import json
import math
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import threading
import time
import traceback

from spec_decode_benchmark import CACHE_BLOCK_SIZE, MODEL, REVISION, command as base_command, save

PROMPT_TOKENS = CACHE_BLOCK_SIZE * 36 + 1
OUTPUT_TOKENS = 64
CPU_BYTES = 20 << 30
RESET_ATTEMPTS = 6
MAIN_REQUESTS = 7
MAX_REQUESTS = MAIN_REQUESTS + 5 * (RESET_ATTEMPTS - 1)
RUNNING = 'vllm:num_requests_running'
WAITING = 'vllm:num_requests_waiting'
GENERATION = 'vllm:generation_tokens_total'
LOAD = 'vllm:kv_offload_load_bytes_total'
STORE = 'vllm:kv_offload_store_bytes_total'
HITS = 'vllm:external_prefix_cache_hits_total'
CORRUPTED = 'vllm:corrupted_requests_total'
PREEMPTIONS = 'vllm:num_preemptions_total'
DRAFT_TOKENS = 'vllm:spec_decode_num_draft_tokens_total'
ALLOCATION_FAILURES = 'vllm:kv_offload_allocation_failure_total'
METRICS = {RUNNING, WAITING, GENERATION, LOAD, STORE, HITS, CORRUPTED, PREEMPTIONS,
           DRAFT_TOKENS, 'vllm:kv_cache_usage_perc', ALLOCATION_FAILURES}


def server_command(snapshot):
    argv = base_command(snapshot, '', 'mtp3')
    # Keep the accepted engine arguments, without the benchmark wrapper/probes.
    argv = [sys.executable, '-m', 'vllm.entrypoints.cli.main'] + argv[3:]
    connector = dict(kv_connector='OffloadingConnector', kv_role='kv_both',
        kv_connector_extra_config=dict(cpu_bytes_to_use=CPU_BYTES,
            eviction_policy='lru', offload_prompt_only=True))
    return argv + ['--kv-transfer-config', json.dumps(connector)]


def prompt_hash(prompt):
    return hashlib.sha256(json.dumps(prompt, separators=(',', ':')).encode()).hexdigest()


def selected_metrics(text):
    # Pinned RL environment dependency; keep CPU tests/driver imports light.
    from prometheus_client.parser import text_string_to_metric_families
    values = {}
    for family in text_string_to_metric_families(text):
        for sample in family.samples:
            if (sample.name not in METRICS or sample.labels.get('model_name') != MODEL or sample.labels.get('engine') != '0'
                    or sample.name.endswith(('_bucket', '_created'))):
                continue
            if sample.name in values:
                raise ValueError('Ambiguous selected model/engine metric: ' + sample.name)
            if not math.isfinite(sample.value) or sample.value < 0:
                raise ValueError('Invalid model/engine metric value')
            values[sample.name] = sample.value
    for name in (RUNNING, WAITING, GENERATION, CORRUPTED, PREEMPTIONS, 'vllm:kv_cache_usage_perc'):
        if name not in values:
            raise ValueError('Missing serving metrics: ' + name)
    return values


def validate_server(info, snapshot):
    config = info['vllm_config']
    if config['model_config']['model'] != snapshot:
        raise ValueError('Wrong serving version/model snapshot')
    spec = config['speculative_config']
    extra = config['kv_transfer_config']['kv_connector_extra_config']
    if (spec['method'] != 'mtp' or spec['num_speculative_tokens'] != 3
            or config['kv_transfer_config']['kv_connector'] != 'OffloadingConnector'
            or extra['cpu_bytes_to_use'] != CPU_BYTES or extra['eviction_policy'] != 'lru'
            or extra['offload_prompt_only'] is not True
            or config['cache_config']['block_size'] != CACHE_BLOCK_SIZE
            or config['cache_config']['prefix_match_unit'] is not None):
        raise ValueError('MTP/offloading/cache configuration differs')
    return config


def parse_completion(data, prompt, output_tokens=OUTPUT_TOKENS):
    usage = data['usage']
    choice, = data['choices']
    tokens = choice['logprobs']['tokens']
    if (choice['finish_reason'] != 'length' or len(tokens) != output_tokens
            or usage['prompt_tokens'] != len(prompt) or usage['completion_tokens'] != output_tokens):
        raise ValueError('Incomplete/wrong request token accounting')
    ids = []
    for token in tokens:
        if not isinstance(token, str) or not token.startswith('token_id:'):
            raise ValueError('Expected generated token IDs')
        value = int(token.partition(':')[2])
        if value < 0:
            raise ValueError('Negative token ID')
        ids.append(value)
    cached = (usage.get('prompt_tokens_details') or {}).get('cached_tokens', 0)
    if type(cached) is not int or not 0 <= cached < len(prompt):
        raise ValueError('Invalid cached token count')
    return dict(usage=usage, cached_tokens=cached, token_ids=ids,
                text=choice['text'], prompt_sha256=prompt_hash(prompt))


def delta(before, after, name):
    result = after.get(name, 0) - before.get(name, 0)
    if result < 0:
        raise ValueError('Metric counter reset during phase: ' + name)
    return result


def restore_checks(cold, warm, restored, before, after, warm_before, warm_after, reset_ok, cold_before):
    minimum = (PROMPT_TOKENS // CACHE_BLOCK_SIZE - 2) * CACHE_BLOCK_SIZE
    return dict(gpu_reset=reset_ok is True, minimum_prefix_tokens=minimum,
        identical_prompt=cold['prompt_sha256'] == warm['prompt_sha256'] == restored['prompt_sha256'],
        warm_cached_prefix=warm['cached_tokens'] >= minimum,
        restore_cached_prefix=restored['cached_tokens'] >= minimum,
        cpu_to_gpu_bytes=delta(before, after, LOAD),
        external_hit_tokens=delta(before, after, HITS),
        gpu_warm_used_no_cpu_load=delta(warm_before, warm_after, LOAD) == 0,
        gpu_control_output_matches=cold['token_ids'] == warm['token_ids'],
        restored_output_matches=warm['token_ids'] == restored['token_ids'],
        new_corrupted_requests=delta(cold_before, after, CORRUPTED),
        new_preemptions=delta(cold_before, after, PREEMPTIONS),
        new_allocation_failures=delta(cold_before, after, ALLOCATION_FAILURES),
        cycle_store_bytes=delta(cold_before, after, STORE), mtp_draft_tokens=delta(before, after, DRAFT_TOKENS))


def restore_path_pass(checks):
    return (all(checks[k] for k in ('gpu_reset', 'identical_prompt', 'restore_cached_prefix'))
            and 0 < checks['cpu_to_gpu_bytes'] <= checks['cycle_store_bytes']
            and checks['external_hit_tokens'] >= checks['minimum_prefix_tokens']
            and checks['mtp_draft_tokens'] > 0
            and checks['new_corrupted_requests'] == checks['new_preemptions'] == checks['new_allocation_failures'] == 0)


def restore_pass(checks):
    return (restore_path_pass(checks) and all(checks[k] for k in ('warm_cached_prefix',
            'gpu_warm_used_no_cpu_load', 'gpu_control_output_matches', 'restored_output_matches')))


class LocalHTTP:
    """Dedicated localhost client; body limits and absolute response watchdog."""
    def __init__(self, deadline, port=8000):
        self.deadline, self.port = deadline, port

    def call(self, path, payload=None, timeout=600):
        remaining = min(timeout, self.deadline - time.time())
        if remaining <= 0:
            raise TimeoutError('Probe deadline before HTTP request')
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=remaining)
        timer = None
        try:
            connection.connect()
            sock = connection.sock
            def stop():
                try: sock.shutdown(socket.SHUT_RDWR)
                except OSError: pass
            timer = threading.Timer(max(.001, min(remaining, self.deadline - time.time())), stop)
            timer.daemon = True
            timer.start()
            body = None if payload is None else json.dumps(payload, separators=(',', ':')).encode()
            connection.request('GET' if payload is None else 'POST', path, body,
                headers={'Content-Type':'application/json'})
            response = connection.getresponse()
            data = response.read(8 * 1024 * 1024 + 1)
            if len(data) > 8 * 1024 * 1024 or response.length not in (None, 0):
                raise ValueError('Incomplete/oversize HTTP response')
            if response.status != 200:
                raise RuntimeError(f'HTTP{response.status}: ' + data.decode(errors='replace')[:1000])
            return data.decode()
        finally:
            if timer is not None:
                timer.cancel();timer.join()
            connection.close()


class Probe:
    def __init__(self, root, deadline, prompts, tick):
        self.root, self.deadline, self.prompts, self.tick = root, deadline, prompts, tick
        self.http = LocalHTTP(deadline)
        self.requests = []
        self.resets = []

    def metrics(self, label):
        text = self.http.call('/metrics', timeout=3)
        (self.root / f'{label}-metrics.txt').write_text(text)
        return selected_metrics(text)

    def request(self, label, prompt, *, tick=False):
        if len(self.requests) >= MAX_REQUESTS:
            raise ValueError('Finite probe request allowance exhausted')
        before = self.metrics(label + '-before')
        payload = dict(model=MODEL, prompt=prompt, max_tokens=1 if tick else OUTPUT_TOKENS,
            temperature=0, seed=3827, ignore_eos=True, stream=False,
            logprobs=0, return_tokens_as_token_ids=True)
        save(self.root / f'{label}-request.json', payload)
        started = time.monotonic()
        raw = self.http.call('/v1/completions', payload)
        seconds = time.monotonic()-started
        data = json.loads(raw)
        save(self.root / f'{label}-response.json', data)
        row = parse_completion(data, prompt, 1 if tick else OUTPUT_TOKENS)
        row.update(label=label, seconds=seconds, tick=tick,
            request_body_sha256=hashlib.sha256(json.dumps(payload,separators=(',', ':')).encode()).hexdigest())
        self.requests.append(row)
        # Metric publication is asynchronous. Await actual generation accounting,
        # not elapsed sleep alone, before attributing transfer/hit deltas.
        end = min(self.deadline, time.time()+10)
        while True:
            after = self.metrics(label + '-after')
            if after[GENERATION] >= before[GENERATION]+payload['max_tokens'] and after[RUNNING] == after[WAITING] == 0:
                break
            if time.time() >= end:
                raise TimeoutError('Serving metrics did not account completed request')
            time.sleep(.2)
        print(json.dumps(dict(phase=label,seconds=row['seconds'],cached_tokens=row['cached_tokens'],
            cpu_load_bytes=delta(before,after,LOAD),external_hits=delta(before,after,HITS))),flush=True)
        return row, before, after

    def reset(self, label, external):
        for attempt in range(RESET_ATTEMPTS):
            response = json.loads(self.http.call('/reset_prefix_cache?reset_external=' +
                str(external).lower() + '&reset_running_requests=false', {}, timeout=5))
            self.resets.append(dict(label=label,attempt=attempt,reset_external=external,response=response))
            if response.get('success') is True:
                return True
            if attempt + 1 < RESET_ATTEMPTS:
                self.request(f'{label}-drain-{attempt}', self.tick, tick=True)
        raise RuntimeError('Cache reset never succeeded after bounded transfer drain')


def run(args):
    root=args.output;root.mkdir(parents=True, exist_ok=False)
    report=dict(status='INCOMPLETE',passed=False,model=MODEL,revision=REVISION,
        mtp_tokens=3,CPU_bytes=CPU_BYTES,input_tokens=PROMPT_TOKENS,output_tokens=OUTPUT_TOKENS,
        metadata={'tags':['model','infrastructure-diagnostic','cpu-kv-offload']},
        allow_ungraded=True,ungraded_reason='Inference/cache infrastructure probe, no browser task or learning claim',
        qualification='GPU-only cache reset proves restoration, not natural LRU eviction or browser capacity control')
    server=None
    try:
        from importlib.metadata import version
        if version('vllm') != '0.28.0':raise ValueError('Wrong installed vLLM version')
        report['vllm_version']=version('vllm')
        from apply_vllm_cpu_kv_patch import apply_patch
        report['vllm_backport']=apply_patch(verify_only=True)
        prompts=json.loads(args.prompts.read_text())
        if (len(prompts['main']) != 2 or any(len(p) != PROMPT_TOKENS for p in prompts['main'])
                or not prompts['tick'] or len(prompts['tick']) > 64
                or any(type(t) is not int or t < 0 for p in [*prompts['main'], prompts['tick']] for t in p)
                or len({prompt_hash(p) for p in prompts['main']}) != 2):
            raise ValueError('Wrong/distinct prompt geometry')
        if args.deadline-time.time() < 300:
            raise TimeoutError('Less than five minutes remain; refuse model startup')
        shm=os.statvfs('/dev/shm');report['shm_free_bytes']=shm.f_bavail*shm.f_frsize
        if report['shm_free_bytes'] < CPU_BYTES+(1<<30):
            raise RuntimeError('Insufficient /dev/shm for20GiB CPU KV tier')
        argv=server_command(args.snapshot);report['command']=argv
        save(root/'plan.json',report)
        print(json.dumps(dict(phase='engine-start',mtp=3,CPU_GiB=20)),flush=True)
        with (root/'server.log').open('w') as log:
            server=subprocess.Popen(argv,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            save(root/'server-process.json', dict(pid=server.pid, process_group=server.pid))
            probe=Probe(root,args.deadline,prompts['main'],prompts['tick'])
            report['requests']=probe.requests;report['resets']=probe.resets
            startup_end=min(args.deadline-60,time.time()+720)
            while True:
                if server.poll() is not None:raise RuntimeError(f'Serving startup exited{server.returncode}')
                try:probe.http.call('/health',timeout=2);break
                except (OSError,RuntimeError):pass
                if time.time()>=startup_end:raise TimeoutError('Serving startup watchdog')
                time.sleep(1)
            info=json.loads(probe.http.call('/server_info?config_format=json',timeout=120))
            save(root/'server-info.json',info);validate_server(info,args.snapshot)
            report['cycles']=[]
            for index,prompt in enumerate(prompts['main']):
                probe.reset(f'cycle-{index}-full-reset',True)
                cold,cb,ca=probe.request(f'cycle-{index}-cold',prompt)
                warm,wb,wa=probe.request(f'cycle-{index}-gpu-warm',prompt)
                reset=probe.reset(f'cycle-{index}-gpu-reset',False)
                restored,rb,ra=probe.request(f'cycle-{index}-cpu-restore',prompt)
                checks=restore_checks(cold,warm,restored,rb,ra,wb,wa,reset,cb)
                checks['cold_was_uncached']=cold['cached_tokens']==0 and delta(cb,ca,HITS)==delta(cb,ca,LOAD)==0
                report['cycles'].append(dict(index=index,checks=checks,
                    restore_path_passed=restore_path_pass(checks),
                    passed=restore_pass(checks) and checks['cold_was_uncached']))
                save(root/'report.json',report)
            probe.reset('negative-full-reset',True)
            negative,nb,na=probe.request('negative-cold',prompts['main'][1])
            report['negative_control']=dict(cached_tokens=negative['cached_tokens'],
                external_hits=delta(nb,na,HITS),cpu_load_bytes=delta(nb,na,LOAD),
                new_corrupted_requests=delta(nb,na,CORRUPTED),new_preemptions=delta(nb,na,PREEMPTIONS),
                new_allocation_failures=delta(nb,na,ALLOCATION_FAILURES))
            negative_pass=all(value==0 for value in report['negative_control'].values())
            report.update(status='COMPLETE',passed=all(c['passed'] for c in report['cycles']) and negative_pass,
                restore_path_passed=all(c['restore_path_passed'] for c in report['cycles']) and negative_pass)
    except BaseException:
        report['error']=traceback.format_exc()
    finally:
        # Persist results before shutdown; slow cleanup must not erase evidence.
        save(root/'report.json',report)
        if server is not None:
            try:
                os.killpg(server.pid,signal.SIGTERM)
                server.wait(timeout=15)
            except ProcessLookupError:pass
            except subprocess.TimeoutExpired:pass
            except Exception:report['cleanup_error']=traceback.format_exc();report['passed']=False
            finally:
                # Kill the session even when its leader has exited: engine-core
                # children can otherwise survive and become reparented.
                try:os.killpg(server.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                except Exception:report['cleanup_error']=traceback.format_exc();report['passed']=False
                try:server.wait(timeout=5)
                except Exception:report['cleanup_error']=traceback.format_exc();report['passed']=False
        save(root/'report.json',report)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot',required=True)
    parser.add_argument('--prompts',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--deadline',type=float,required=True)
    args=parser.parse_args()
    result=run(args)
    print(json.dumps({'status':result['status'],'passed':result['passed'],'error':result.get('error')}))
    raise SystemExit(0 if result['passed'] else 1)
