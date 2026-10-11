#!/usr/bin/env python3
"""Six finite, GPU-local throughput cohorts; no browser/task quality claims."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import copy
import json
import math
import os
from pathlib import Path
import re
import signal
import socket
import statistics
import subprocess
import sys
import threading
import time
import urllib.request

ARMS = ("dflash", "mtp3", "baseline")
ISL, OSL, BATCH = 60000, 1024, 16
CACHE_BLOCK_SIZE = 1664  # Divisible BF16 draft/FP8 target pages; no runtime code patch.
MODEL = "Qwen/Qwen3.8-27B-FP8"
REVISION = "017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"
DRAFT = "z-lab/Qwen3.8-27B-DFlash2"
DRAFT_REVISION = "50307d4c4cde6860d4eee73e2547cd786fe8e8a4"
MARKER = "SPEC_BENCH_CAPACITY "


def probe_capacity(config, cache, original):
    probe = copy.copy(config)
    probe.model_config = copy.copy(config.model_config)
    length = ISL + OSL + 16
    probe.model_config.max_model_len = length
    if config.speculative_config is not None:
        probe.speculative_config = copy.copy(config.speculative_config)
        probe.speculative_config.draft_model_config = copy.copy(config.speculative_config.draft_model_config)
        probe.speculative_config.draft_model_config.max_model_len = length
    nominal = original(probe, cache)
    if not math.isfinite(nominal) or nominal <= 0:
        raise ValueError("Invalid hybrid cache capacity")
    blocks = round(cache.num_blocks / nominal)
    if blocks < 1 or not math.isclose(nominal, cache.num_blocks / blocks):
        raise ValueError("Non-integral hybrid cache allocation")
    usable = cache.num_blocks - 1
    groups=[]
    for group in getattr(cache,'kv_cache_groups',[]):
        spec=group.kv_cache_spec
        groups.append(dict(kind=type(spec).__name__,layers=len(group.layer_names),
            layer_names=group.layer_names,block_size=spec.block_size,page_bytes=spec.page_size_bytes,
            natural_page_bytes=getattr(spec,'real_page_size_bytes',None),
            admission_blocks=math.ceil(spec.max_memory_usage_bytes(probe)/spec.page_size_bytes)))
    return dict(context_budget=length, groups=groups,pool_blocks=cache.num_blocks,
                usable_pool_blocks=usable, blocks_per_request=blocks,
                cache_max_requests=usable // blocks,
                scheduler_max_requests=config.scheduler_config.max_num_seqs,
                common_batch_predicted_fraction=BATCH * blocks / usable,
                draft_model_dtype=None if config.speculative_config is None else
                    str(getattr(config.speculative_config.draft_model_config, "dtype", "unknown")),
                speculative_kv_override=None if config.speculative_config is None else
                    getattr(config.speculative_config, "kv_cache_dtype", None))


def choose_common_batch(capacity, current=None):
    limit=min(BATCH, capacity['cache_max_requests'], capacity['scheduler_max_requests'])
    if limit<2:raise ValueError("Capacity cannot support distinct batch-1/common-batch cohorts")
    if current is not None and current>limit:
        raise ValueError("Later engine cannot support the already selected common batch")
    return limit if current is None else current


def instrument():
    from vllm.v1.core import kv_cache_utils
    original = kv_cache_utils.get_max_concurrency_for_kv_cache_config
    def wrapped(config, cache):
        actual = original(config, cache)
        print(MARKER + json.dumps(probe_capacity(config, cache, original)), flush=True)
        return actual
    kv_cache_utils.get_max_concurrency_for_kv_cache_config = wrapped


# Spawned engine children re-import this entry point; observe, never mutate cache.
if os.environ.get("SPEC_BENCH_PROBE") == "1":
    instrument()


def command(snapshot, draft, arm):
    if arm not in ARMS:
        raise ValueError("Unknown arm")
    argv = [sys.executable, str(Path(__file__).resolve()), "--serve", "serve", snapshot,
        "--served-model-name", MODEL, "--host", "127.0.0.1", "--port", "8000",
        "--dtype", "bfloat16", "--generation-config", "vllm",
        "--max-model-len", "262144", "--max-num-seqs", "32",
        "--block-size",str(CACHE_BLOCK_SIZE),"--max-num-batched-tokens", "8192", "--gpu-memory-utilization", "0.90",
        "--kv-cache-dtype", "fp8_e4m3", "--enable-prefix-caching",
        "--mamba-cache-mode", "align", "--mamba-cache-dtype", "bfloat16",
        "--mamba-ssm-cache-dtype", "float32", "--gdn-prefill-backend", "triton",
        "--performance-mode", "interactivity", "--enable-prompt-tokens-details",
        "--limit-mm-per-prompt", '{"image":1562,"video":0}',
        "--mm-processor-kwargs", '{"min_pixels":65536,"max_pixels":16777216,"patch_size":16,"merge_size":2,"temporal_patch_size":2}']
    if arm == "mtp3":
        argv += ["--speculative-config", json.dumps(dict(method="mtp", num_speculative_tokens=3))]
    if arm == "dflash":
        argv += ["--speculative-config", json.dumps(dict(method="dflash", model=draft,
                                                       num_speculative_tokens=7, kv_cache_dtype="auto"))]
    return argv


def save(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def fetch(path, payload=None, timeout=15):
    request = urllib.request.Request("http://127.0.0.1:8000" + path,
        data=None if payload is None else json.dumps(payload).encode(),
        headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode()


def metrics():
    from prometheus_client.parser import text_string_to_metric_families
    values = {}
    for family in text_string_to_metric_families(fetch("/metrics", timeout=3)):
        for sample in family.samples:
            name = sample.name
            if name.startswith("vllm:") and not name.endswith(("_bucket", "_created")):
                values[name] = values.get(name, 0) + sample.value
    return values


def request(prompt, index, output_tokens, deadline, directory):
    payload = dict(model=MODEL, prompt=prompt, max_tokens=output_tokens,
                   temperature=0.6, top_p=0.95, top_k=20, seed=3827 + index,
                   ignore_eos=True, stream=True, stream_options={"include_usage":True},
                   logprobs=0, return_tokens_as_token_ids=True)
    started = time.perf_counter()
    first = last = None
    token_ids, events, text = [], [], []
    usage, finish, done = None, None, False
    req = urllib.request.Request("http://127.0.0.1:8000/v1/completions",
        data=json.dumps(payload).encode(), headers={"Content-Type":"application/json"})
    # One absolute watchdog per request, not a renewable per-chunk socket timeout.
    response = None
    def expire():
        if response is not None:
            # Closing the BufferedReader waits for its read lock. Shutting down
            # its socket wakes the reader immediately, including a late stall.
            try: response.fp.raw._sock.shutdown(socket.SHUT_RDWR)
            except (OSError,AttributeError): pass
    remaining = deadline - time.time()
    if remaining <= 0: raise TimeoutError("Expired before inference")
    timer = threading.Timer(remaining, expire); timer.daemon = True; timer.start()
    try:
        with urllib.request.urlopen(req, timeout=min(600, remaining)) as response:
            for raw in response:
                now = time.perf_counter()
                if time.time() >= deadline: raise TimeoutError("Inference deadline")
                if not raw.startswith(b"data: "): continue
                data = raw[6:].strip()
                if data == b"[DONE]": done = True; break
                chunk = json.loads(data)
                if "error" in chunk: raise RuntimeError(chunk["error"])
                if chunk.get("usage"): usage = chunk["usage"]
                for choice in chunk.get("choices", []):
                    text.append(choice.get("text", ""))
                    tokens = (choice.get("logprobs") or {}).get("tokens", [])
                    ids = []
                    for token in tokens:
                        if not isinstance(token, str) or not token.startswith("token_id:"):
                            raise ValueError("Expected actual token IDs, not stream-chunk counts")
                        ids.append(int(token.split(":", 1)[1]))
                    if ids:
                        if first is None: first = now
                        last = now
                        token_ids.extend(ids)
                        events.append(dict(time=now, count=len(ids)))
                    if choice.get("finish_reason"): finish = choice["finish_reason"]
        ended = time.perf_counter()
        if not done or finish != "length" or usage is None or len(token_ids) != output_tokens:
            raise ValueError("Incomplete stream/token accounting")
        if usage["prompt_tokens"] != ISL or usage["completion_tokens"] != output_tokens:
            raise ValueError("Unexpected request geometry")
        row = dict(index=index, started=started, ended=ended, first=first, last=last,
            ttft_seconds=first-started, request_seconds=ended-started,
            token_ids=token_ids, chunk_events=events, usage=usage, finish_reason=finish,
            text="".join(text))
        # Several speculative tokens can arrive together. Exclude the first entire
        # chunk; never treat an SSE chunk as one generated token.
        remainder = output_tokens - events[0]["count"]
        row["stream_decode_tps"] = remainder/(last-first) if last>first and remainder>0 else None
        save(directory / f"request-{index:02d}.json", row)
        return row
    finally:
        timer.cancel()


class Sampler:
    def __init__(self, path):
        self.path, self.rows, self.stop = path, [], threading.Event()
    def __enter__(self):
        def run():
            with self.path.open("w", buffering=1) as out:
                while not self.stop.is_set():
                    row=dict(time=time.perf_counter())
                    try: row["metrics"]=metrics()
                    except Exception as exc: row["error"]=str(exc)
                    self.rows.append(row); out.write(json.dumps(row)+"\n")
                    self.stop.wait(.5)
        self.thread=threading.Thread(target=run,daemon=True);self.thread.start();return self
    def __exit__(self,*args): self.stop.set();self.thread.join(timeout=5)


def summarize(rows, before, after, samples, arm):
    delta = lambda name: after.get(name,0)-before.get(name,0)
    kv=[x["metrics"].get("vllm:kv_cache_usage_perc") for x in samples if "metrics" in x]
    kv=[v for v in kv if v is not None]
    cached=[(r["usage"].get("prompt_tokens_details") or {}).get("cached_tokens",0) for r in rows]
    # Target server counters provide the aggregate rate during a guarded interval
    # after all first chunks and before any final chunks; prefill must be absent.
    lower=max(r["first"] for r in rows)+1
    upper=min(r["last"] for r in rows)-1
    seconds=tokens=0
    for a,b in zip(samples,samples[1:]):
        x,y=a.get("metrics",{}),b.get("metrics",{})
        if not (lower <= a["time"] < b["time"] <= upper): continue
        if any(v.get("vllm:num_requests_running")!=len(rows) or
               v.get("vllm:num_requests_waiting")!=0 for v in (x,y)): continue
        keys=("vllm:generation_tokens_total","vllm:prompt_tokens_total","vllm:num_preemptions_total")
        if any(k not in x or k not in y for k in keys):continue
        dg,dp,pre=[y[k]-x[k] for k in keys]
        if dg<0 or dp!=0 or pre!=0:continue
        seconds+=b["time"]-a["time"];tokens+=dg
    elapsed=max(r["ended"] for r in rows)-min(r["started"] for r in rows)
    preemptions=delta("vllm:num_preemptions_total")
    draft=delta("vllm:spec_decode_num_draft_tokens_total")
    accepted=delta("vllm:spec_decode_num_accepted_tokens_total")
    checks=dict(cached_prefix=all(n>=ISL*.90 for n in cached), no_preemption=preemptions==0,
                speculation_active=(draft>0 and accepted>0) if arm!="baseline" else draft==0)
    return dict(passed=all(checks.values()),checks=checks,requests=len(rows),elapsed_seconds=elapsed,
        aggregate_output_tps=len(rows)*OSL/elapsed,
        median_ttft_seconds=statistics.median(r["ttft_seconds"] for r in rows),
        median_stream_decode_tps=statistics.median(r["stream_decode_tps"] for r in rows),
        guarded_aggregate_decode_tps=tokens/seconds if seconds>=5 and tokens>0 else None,
        guarded_seconds=seconds, cached_tokens_per_request=cached,
        kv_peak_fraction=max(kv) if kv else None,kv_headroom_fraction=1-max(kv) if kv else None,
        spec_draft_tokens=draft,spec_accepted_tokens=accepted,
        spec_acceptance=accepted/draft if draft else None,
        note="GPU-local HTTP timings; token-aware burst accounting; finite batch drains, not sustained replenished throughput")


def run(args):
    root=args.output;root.mkdir(parents=True,exist_ok=False)
    prompts=json.loads(args.prompts.read_text())
    if len(prompts)!=BATCH or any(len(p)!=ISL for p in prompts):raise ValueError("Invalid prompts")
    hardware_code = """
import json,torch
from importlib.metadata import version
assert torch.cuda.device_count()==1 and torch.cuda.get_device_capability()==(12,0)
assert version('vllm')=='0.28.0' and version('torch').split('+')[0]=='2.13.0' and torch.version.cuda=='13.0'
print(json.dumps(dict(name=torch.cuda.get_device_name(),capability=list(torch.cuda.get_device_capability()),
 vram_bytes=torch.cuda.get_device_properties(0).total_memory,torch=version('torch'),cuda=torch.version.cuda,vllm=version('vllm'))))
"""
    hardware=json.loads(subprocess.check_output([sys.executable,'-c',hardware_code],text=True,timeout=30).strip().splitlines()[-1])
    save(root/"hardware.json",hardware)
    report=dict(status="INCOMPLETE",arms=[],input_tokens=ISL,output_tokens=OSL,
        requested_common_batch=BATCH,common_batch=None,
        hardware=hardware,sampling=dict(temperature=.6,top_p=.95,top_k=20,ignore_eos=True),
        caveat="Forced fixed-length generation after natural EOS may affect speculative acceptance")
    save(root/"report.json",report)
    monitor_log=(root/"gpu.csv").open("w")
    monitor=subprocess.Popen(["nvidia-smi","--query-gpu=timestamp,name,utilization.gpu,memory.used,power.draw,clocks.sm,clocks.mem","--format=csv","-l","1"],stdout=monitor_log)
    try:
        for arm in ARMS:
            directory=root/arm;directory.mkdir()
            print(json.dumps(dict(phase="engine-start",arm=arm,time=time.time())),flush=True)
            argv=command(args.snapshot,args.draft,arm)
            save(directory/"command.json",argv)
            env=dict(os.environ,SPEC_BENCH_PROBE="1",OMP_NUM_THREADS="1")
            log=(directory/"server.log").open("w")
            proc=subprocess.Popen(argv,stdout=log,stderr=subprocess.STDOUT,env=env,start_new_session=True)
            import psutil
            save(directory/'server-process.json',dict(pid=proc.pid,created=psutil.Process(proc.pid).create_time()))
            try:
                startup=time.time()
                while True:
                    if proc.poll() is not None:raise RuntimeError(f"{arm} startup exited {proc.returncode}")
                    if time.time()>=min(args.deadline-30,startup+720):raise TimeoutError("Server startup watchdog")
                    try: fetch("/health",timeout=2);break
                    except OSError:time.sleep(1)
                matches=re.findall(re.escape(MARKER)+r"(\{[^\n]+\})",(directory/"server.log").read_text())
                if not matches:raise ValueError("No group-aware capacity receipt")
                capacity=json.loads(matches[-1])
                save(directory/"capacity-raw.json",capacity)
                if arm=="dflash":
                    draft_groups=[g for g in capacity['groups'] if g['kind']=='SlidingWindowSpec']
                    if not draft_groups or any(g['block_size']!=832 or g['natural_page_bytes']!=g['page_bytes'] for g in draft_groups):
                        raise ValueError("DFlash cache fix not realised; retained raw capacity receipt")
                common=choose_common_batch(capacity,report['common_batch'])
                report['common_batch']=common
                capacity['requested_batch_predicted_fraction']=capacity['common_batch_predicted_fraction']
                capacity['common_batch_predicted_fraction']=common*capacity['blocks_per_request']/capacity['usable_pool_blocks']
                capacity['selected_common_batch']=common
                save(directory/"capacity.json",capacity)
                if arm=="dflash" and capacity["draft_model_dtype"]!="torch.bfloat16":raise ValueError("Draft model is not BF16")
                print(json.dumps(dict(phase="engine-ready",arm=arm,capacity=capacity)),flush=True)
                result=dict(arm=arm,capacity=capacity,startup_seconds=time.time()-startup,cohorts=[])
                report["arms"].append(result);save(root/"report.json",report)
                for count in (1,common):
                    cohort=directory/f"batch-{count}";cohort.mkdir()
                    if time.time()>=args.deadline-30:raise TimeoutError("Job deadline")
                    # Reset between cohorts, retaining no unrelated cached histories.
                    # The developer-mode endpoint is local-only and never exposed.
                    if not json.loads(fetch("/reset_prefix_cache",{},timeout=10)).get("success"):
                        raise RuntimeError("Cache reset rejected")
                    print(json.dumps(dict(phase="warmup",arm=arm,batch=count)),flush=True)
                    warm=cohort/"warmup";warm.mkdir()
                    warm_before=metrics()
                    with ThreadPoolExecutor(max_workers=count) as pool:
                        list(pool.map(lambda i: request(prompts[i],i,64,min(args.deadline-20,time.time()+600),warm),range(count)))
                    print(json.dumps(dict(phase="measure",arm=arm,batch=count)),flush=True)
                    before=metrics()
                    if before.get('vllm:num_preemptions_total')!=warm_before.get('vllm:num_preemptions_total'):
                        raise RuntimeError("Preemption during warmup")
                    save(cohort/"metrics-before.json",before)
                    with Sampler(cohort/"metrics.jsonl") as sampler,ThreadPoolExecutor(max_workers=count) as pool:
                        rows=list(pool.map(lambda i: request(prompts[i],i,OSL,min(args.deadline-20,time.time()+600),cohort),range(count)))
                    after=metrics();save(cohort/"metrics-after.json",after)
                    summary=summarize(rows,before,after,sampler.rows,arm)
                    result["cohorts"].append(dict(batch=count,**summary));save(cohort/"summary.json",summary)
                    save(root/"report.json",report);print(json.dumps(dict(arm=arm,batch=count,**summary)),flush=True)
                    # A cache miss or poor draft acceptance is a benchmark result.
                    # Preserve its failed check and collect the other approved arms;
                    # geometry/stream errors and startup safety gates still fail closed.
                    if not summary["passed"]:
                        print(json.dumps(dict(phase="cohort-check-failed",arm=arm,batch=count,
                            checks=summary["checks"],action="retain result; continue finite remaining cohorts")),flush=True)
            finally:
                try:os.killpg(proc.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                proc.wait(timeout=10);log.close()
        report["status"]="COMPLETE"
        report["all_checks_passed"]=all(c["passed"] for a in report["arms"] for c in a["cohorts"])
    except Exception:
        import traceback
        report["error"]=traceback.format_exc();raise
    finally:
        monitor.terminate();monitor.wait(timeout=5);monitor_log.close()
        save(root/"report.json",report)


if __name__=="__main__":
    if "--serve" in sys.argv:
        sys.argv.remove("--serve")
        from vllm.entrypoints.cli.main import main
        main()
    else:
        p=argparse.ArgumentParser(description=__doc__)
        p.add_argument("--snapshot",required=True);p.add_argument("--draft",required=True)
        p.add_argument("--prompts",type=Path,required=True);p.add_argument("--output",type=Path,required=True)
        p.add_argument("--deadline",type=float,required=True)
        run(p.parse_args())
