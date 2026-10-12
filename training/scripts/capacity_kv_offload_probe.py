#!/usr/bin/env python3
"""Six logical episodes, real vLLM pressure and sticky turn-boundary parking.

Tool pauses are controlled Python barriers, not BrowserGym episodes. No injected
metrics or cache resets. Test retirement/cleanup and CPU restoration separately.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from browser_training.capacity_control import EpisodeCapacityController, ParkingConfig, SharedMetricsPoller
from apply_vllm_cpu_kv_patch import apply_patch
from cpu_kv_offload_probe import (CPU_BYTES, MODEL, REVISION, PROMPT_TOKENS, OUTPUT_TOKENS, CACHE_BLOCK_SIZE,
    LocalHTTP, selected_metrics, parse_completion, delta, LOAD, HITS, STORE, CORRUPTED,
    ALLOCATION_FAILURES, PREEMPTIONS, DRAFT_TOKENS, GENERATION, RUNNING, WAITING,
    server_command, validate_server, prompt_hash, save)

EPISODES = 6
BURST_OUTPUT = 512
KV_BYTES = 12 << 30
MAX_REQUESTS = EPISODES * 3


def validate_prompts(prompts):
    if (len(prompts)!=EPISODES or any(len(p)!=PROMPT_TOKENS for p in prompts)
            or any(type(t)is not int or t<0 for p in prompts for t in p)
            or len({prompt_hash(p) for p in prompts})!=EPISODES
            or len({prompt_hash(p[:CACHE_BLOCK_SIZE]) for p in prompts})!=EPISODES):
        raise ValueError('Wrong distinct prompt geometry or shared first cache block')


def command(snapshot):
    return server_command(snapshot) + ['--kv-cache-memory-bytes', str(KV_BYTES)]


def wait_for(predicate, deadline, interval=.05):
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(interval)
    raise TimeoutError('Capacity experiment condition watchdog')


def assess(events, rows, resume_rows, metric_before, metric_after, burst_transfer=None):
    parked = {e['episode_id'] for e in events if e['kind'] == 'episode_parked'}
    starts = {e['request_id']: e['sequence'] for e in events if e['kind'] == 'turn_started'}
    finishes = {e['request_id']: e['sequence'] for e in events if e['kind'] == 'turn_finished'}
    grants = {e['episode_id']: e['sequence'] for e in events if e['kind'] == 'resume_granted'}
    resumed = {e['episode_id']: e['sequence'] for e in events if e['kind'] == 'episode_resumed'}
    balanced = starts.keys() == finishes.keys() and all(starts[k] < finishes[k] for k in starts)
    order = all(grants.get(i, float('inf')) < resumed.get(i, -1) < starts.get(i+':resume', -1)
                for i in parked)
    terminal = len(rows) == EPISODES and all(r['done'] and not r['request_id'] and not r['waiting']
                   and not r['parked'] and r['dispatch_retired'] for r in rows.values())
    no_corruption = delta(metric_before, metric_after, CORRUPTED)==0
    allocation_failures=delta(metric_before,metric_after,ALLOCATION_FAILURES)
    burst_transfer=burst_transfer or {}
    burst_restore=burst_transfer.get('cpu_load_bytes',0)>0 and burst_transfer.get('external_hits',0)>0
    restored = [r['episode_id'] for r in resume_rows
                if r['cpu_load_bytes'] > 0 and r['external_hits'] > 0]
    return dict(parking_passed=bool(parked) and balanced and order and terminal,
                model_cache_health_passed=no_corruption and allocation_failures==0,
                parked_episodes=sorted(parked), balanced_permits=balanced,
                completion_before_resume=order, all_terminal=terminal,
                cpu_restored_episodes=restored, natural_cpu_restore_observed=bool(restored) or burst_restore,
                parked_cpu_restore_observed=bool(restored),burst_cpu_restore_observed=burst_restore,
                new_corrupted_requests=delta(metric_before,metric_after,CORRUPTED),
                cpu_allocation_failures=allocation_failures,
                preemptions=delta(metric_before, metric_after, PREEMPTIONS),
                # Preemption can be the pressure being exercised, not a corruption verdict.
                mtp_active=delta(metric_before, metric_after, DRAFT_TOKENS) > 0)


def exercise(root, deadline, prompts, http):
    controller = EpisodeCapacityController(ParkingConfig(max_generation_requests=EPISODES,
        max_active_episodes=EPISODES, high_water=.85, low_water=.70))
    samples, requests, resumed = [], [], []
    dispatched = 0
    metric_index = 0
    lock = threading.Lock()
    def metrics():
        nonlocal metric_index
        text = http.call('/metrics', timeout=3)
        (root/f'phase-{metric_index:03d}-metrics.txt').write_text(text)
        metric_index += 1
        values = selected_metrics(text)
        if any(name not in values for name in (HITS,DRAFT_TOKENS)):
            raise RuntimeError('Required native offload/speculation metrics missing')
        return values
    def observe(snapshot):
        controller.observe(snapshot)
        with lock:
            samples.append(dict(observed_at=snapshot.observed_at,
                capacity_waiting=snapshot.capacity_waiting, kv_usage=snapshot.kv_usage,
                running=snapshot.running, preemptions=snapshot.preemptions))
    poller = SharedMetricsPoller('http://127.0.0.1:8000/metrics', model=MODEL,
        interval=.5, timeout=2, on_snapshot=observe).start()
    barrier = threading.Barrier(EPISODES, timeout=30)
    pool = ThreadPoolExecutor(max_workers=EPISODES)
    def request(episode, phase, tokens, simultaneous=False):
        nonlocal dispatched
        identity = episode+':'+phase
        with controller.turn(episode, identity, timeout=max(.001, min(600, deadline-time.time()))):
            if simultaneous:
                barrier.wait()
            prompt = prompts[int(episode)]
            payload = dict(model=MODEL, prompt=prompt, max_tokens=tokens, temperature=0,
                seed=3827, ignore_eos=True, stream=False, logprobs=0, return_tokens_as_token_ids=True)
            save(root/(identity.replace(':','-')+'-request.json'), payload)
            with lock:
                if dispatched >= MAX_REQUESTS:
                    raise RuntimeError('Finite experiment dispatch allowance exhausted')
                dispatched += 1
            started = time.monotonic()
            data = json.loads(http.call('/v1/completions', payload))
            seconds = time.monotonic()-started
            save(root/(identity.replace(':','-')+'-response.json'), data)
            row = dict(parse_completion(data, prompt, tokens), episode_id=episode,
                       phase=phase, seconds=seconds)
            with lock:
                requests.append(row)
            return row
    def settled(total):
        value = metrics()
        return value if value[GENERATION] >= total and value[RUNNING] == value[WAITING] == 0 else None
    result = {'requests': requests, 'samples': samples, 'resumes': resumed}
    try:
        baseline=metrics()  # Preserve raw startup telemetry even if poller parsing fails.
        wait_for(lambda: controller.status()['telemetry_fresh'], min(deadline,time.time()+15))
        for i in range(EPISODES):
            controller.register_episode(str(i), priority=i)
        # Sequential by design: establish each resident/offloaded history before
        # the single shared-pressure burst. These are dependent test phases.
        cold = [request(str(i), 'seed', OUTPUT_TOKENS) for i in range(EPISODES)]
        wait_for(lambda: settled(baseline[GENERATION]+EPISODES*OUTPUT_TOKENS), min(deadline,time.time()+15),interval=.5)
        seeded_at=time.monotonic()
        def idle_sample():
            status=controller.status();sample=status['telemetry']
            return (status['telemetry_fresh'] and sample['observed_at']>=seeded_at
                and sample['kv_usage']<=controller.config.low_water
                and sample['capacity_waiting']==sample['running']==0)
        # A stale high-water sample could grant only one permit and strand the
        # six-party barrier. Require a new actual idle snapshot before the burst.
        wait_for(idle_sample,min(deadline,time.time()+15))
        burst_before=metrics()
        bursts = [pool.submit(request, str(i), 'burst', BURST_OUTPUT, True) for i in range(EPISODES)]
        burst_rows=[future.result(timeout=max(.001,deadline-time.time()))for future in bursts]
        wait_for(lambda: settled(baseline[GENERATION]+EPISODES*(OUTPUT_TOKENS+BURST_OUTPUT)),
                 min(deadline,time.time()+15),interval=.5)
        burst_after=metrics()
        result['burst_transfer']=dict(cpu_load_bytes=delta(burst_before,burst_after,LOAD),
            external_hits=delta(burst_before,burst_after,HITS),
            output_matches_seed=[row['token_ids'][:OUTPUT_TOKENS]==cold[i]['token_ids']for i,row in enumerate(burst_rows)])
        status = controller.status()
        parked = [i for i, r in status['episodes'].items() if r['parked']]
        if not parked:
            raise RuntimeError('Real sustained capacity pressure did not park any actor; inconclusive')
        result['before_terminal'] = status
        # Every active actor, including parked actors, still occupies lifecycle cap.
        try:
            controller.register_episode('overflow')
        except ValueError:
            result['active_cap_preserved'] = True
        else:
            raise RuntimeError('Parking released the active lifecycle cap')
        # A pending model turn must remain outside vLLM until terminal completion.
        victim = min(parked, key=int)
        before = metrics()
        pending = pool.submit(request, victim, 'resume', OUTPUT_TOKENS)
        wait_for(lambda: controller.status()['episodes'][victim]['waiting'], min(deadline,time.time()+10))
        held_at=time.monotonic();initial_dispatches=dispatched
        wait_for(lambda:sum(s['observed_at']>held_at for s in samples)>=2,min(deadline,time.time()+10))
        held_row=controller.status()['episodes'][victim]
        if pending.done() or held_row['request_id']is not None or not held_row['waiting'] or dispatched!=initial_dispatches:
            raise RuntimeError('Parked request dispatched before a terminal completion')
        result['held_without_dispatch'] = controller.status()
        def finish(actor):
            controller.retire_dispatch(actor)
            controller.finish_episode(actor)
        # No episode ends during burst; the selected drainer now releases exactly
        # one resume credit. Others remain active until their turn in this sequence.
        drainers = sorted(set(status['episodes'])-set(parked), key=int)
        finish(drainers.pop(0))
        for actor in sorted(parked, key=int):
            if actor != victim:
                before = metrics()
                pending = pool.submit(request, actor, 'resume', OUTPUT_TOKENS)
            row = pending.result(timeout=max(.001, deadline-time.time()))
            total = before[GENERATION]+OUTPUT_TOKENS
            wait_for(lambda: settled(total), min(deadline,time.time()+15),interval=.5)
            after = metrics()
            resumed.append(dict(episode_id=actor, cpu_load_bytes=delta(before,after,LOAD),
                external_hits=delta(before,after,HITS), cached_tokens=row['cached_tokens'],
                seed_output_matches=row['token_ids']==cold[int(actor)]['token_ids']))
            finish(actor)
        for actor in drainers:
            finish(actor)
        after = metrics()
        result.update(controller=controller.status(), poller=poller.status(),
                      before_metrics=baseline, after_metrics=after)
        result['checks'] = assess(result['controller']['events'], result['controller']['episodes'], resumed, baseline, after,result['burst_transfer'])
        result['passed'] = (result['checks']['parking_passed'] and result['checks']['mtp_active']
                            and result['checks']['natural_cpu_restore_observed']
                            and result['checks']['model_cache_health_passed']
                            and all(result['burst_transfer']['output_matches_seed'])
                            and all(r['seed_output_matches'] for r in resumed))
        return result
    finally:
        controller.close()
        barrier.abort()
        try:poller.close()
        except Exception:result.update(passed=False,poller_cleanup_error=traceback.format_exc())
        result['poller']=poller.status()
        save(root/'capacity-evidence.json',dict(result,final_controller=controller.status(),dispatched=dispatched))
        # HTTP work has an absolute deadline; no automatic retries or extra turns.
        pool.shutdown(wait=True, cancel_futures=True)
        save(root/'capacity-evidence.json', dict(result, final_controller=controller.status(), dispatched=dispatched))


def run(args):
    root=args.output; root.mkdir(parents=True, exist_ok=False)
    report=dict(status='INCOMPLETE',passed=False,model=MODEL,revision=REVISION,
        metadata={'tags':['model','infrastructure-diagnostic','capacity-offload']},
        allow_ungraded=True,ungraded_reason='Controlled logical episode/cache test; no BrowserGym task verdict',
        qualification='real metrics + controller + model/CPU KV; simulated tool pauses, no native RPC/browser qualification',
        maximum_requests=MAX_REQUESTS, GPU_KV_bytes=KV_BYTES, CPU_KV_bytes=CPU_BYTES)
    server=None
    try:
        report['vllm_backport']=apply_patch(verify_only=True)
        prompts=json.loads(args.prompts.read_text())['main']
        validate_prompts(prompts)
        if args.deadline-time.time()<600:
            raise TimeoutError('Less than ten minutes remain; refuse capacity startup')
        shm=os.statvfs('/dev/shm')
        if shm.f_bavail*shm.f_frsize<CPU_BYTES+(1<<30):
            raise RuntimeError('Insufficient shared memory for CPU KV')
        argv=command(args.snapshot); report['command']=argv; save(root/'plan.json',report)
        with (root/'server.log').open('w') as log:
            server=subprocess.Popen(argv,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            save(root/'server-process.json',dict(pid=server.pid,process_group=server.pid))
            http=LocalHTTP(args.deadline)
            def healthy():
                if server.poll()is not None:raise RuntimeError('vLLM startup exited')
                try:http.call('/health',timeout=2);return True
                except (OSError,RuntimeError):return False
            wait_for(healthy,min(args.deadline-60,time.time()+720))
            info=json.loads(http.call('/server_info?config_format=json',timeout=120))
            save(root/'server-info.json',info)
            config=validate_server(info,args.snapshot)
            if config['cache_config']['kv_cache_memory_bytes']!=KV_BYTES:
                raise RuntimeError('Constrained GPU KV pool not applied')
            if args.deadline-time.time()<240:raise TimeoutError('Less than four minutes remain after startup; refuse episode seeding')
            report.update(exercise(root,args.deadline,prompts,http),status='COMPLETE')
    except BaseException:
        report['error']=traceback.format_exc()
    finally:
        save(root/'report.json',report)
        if server is not None:
            try:
                os.killpg(server.pid,signal.SIGTERM);server.wait(timeout=15)
            except (ProcessLookupError,subprocess.TimeoutExpired):pass
            except Exception:
                report.update(passed=False,cleanup_error=traceback.format_exc())
            finally:
                try:os.killpg(server.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                except Exception:report.update(passed=False,cleanup_error=traceback.format_exc())
                try:server.wait(timeout=5)
                except Exception:report.update(passed=False,cleanup_error=traceback.format_exc())
        save(root/'report.json',report)
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--snapshot',required=True);p.add_argument('--prompts',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--deadline',type=float,required=True)
    result=run(p.parse_args())
    print(json.dumps({k:result.get(k) for k in ('status','passed','checks','error')}))
    raise SystemExit(0 if result['passed'] else 1)
