"""Back-to-back live-page captures, ordered synchronous/background recording.

No model calls or page actions. Sequential blocks intentionally isolate timing.
Output directory must be new. Includes final flush in measured throughput.
"""
import argparse
import gc
import gzip
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from browsergym.core.env import BrowserEnv
from browsergym.core.task import OpenEndedTask
from browsergym.utils.obs import flatten_axtree_to_str
from intent_browser.native_capture import CaptureBudget, capture_native
from intent_browser.trace import Trace, write_json
from intent_browser.observation_writer import write_payload


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--url', default='https://www.prisjakt.nu/')
    p.add_argument('--captures', type=int, default=5)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    paths = [*Path('intent_browser').glob('*.py'), Path(__file__)]
    hashes = lambda: {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    before = hashes()
    env = BrowserEnv(task_entrypoint=OpenEndedTask, task_kwargs={'start_url':'about:blank','goal':'Inspect only'},headless=True)
    blocks = []
    try:
        env.reset(seed=0)
        start = time.perf_counter()
        response = env.page.goto(args.url, wait_until='domcontentloaded',timeout=60000)
        navigation = {'seconds':time.perf_counter()-start, 'status':response.status, 'url':env.page.url}
        env.page.wait_for_timeout(5000)
        (args.output/'initial-text.txt').write_text(env.page.inner_text('body'))
        env.page.screenshot(path=str(args.output/'initial.png'))
        modes = [(False,False),(True,False),(False,True),(True,True)]
        for rotation in range(2):
            # Reverse mode order on repeat to reduce page-age/order effects.
            for asynchronous, screenshots in (modes if rotation==0 else list(reversed(modes))):
                trace = Trace(args.output/'traces',{'benchmark':'back_to_back_recording','model_calls':0},async_recording=asynchronous)
                rows, writes = [], []
                def timed_write(*a):
                    start = time.perf_counter()
                    write_payload(*a)
                    writes.append({'stem':a[1], 'started_at':start,'finished_at':time.perf_counter()})
                gc.collect()  # Only between blocks; no GC pauses inserted between captures.
                wall, cpu = time.perf_counter(), time.process_time()
                try:
                    with patch('intent_browser.observation_writer.write_payload',timed_write):
                        for i in range(args.captures):
                            start = time.perf_counter()
                            budget = CaptureBudget(env.page,trace,enforce=False)
                            with budget.rpc_deadline():obs = capture_native(env,budget,screenshots=screenshots)
                            captured = time.perf_counter()
                            text = flatten_axtree_to_str(obs['axtree_object'])
                            flattened = time.perf_counter()
                            ref = trace.observation(i,obs,text)
                            returned = time.perf_counter()
                            rows.append({'index':i,'capture_start':start,'capture_end':captured,
                                'flatten_seconds':flattened-captured,'recording_foreground_seconds':returned-flattened,
                                'returned_at':returned,'ax_nodes':len(obs['axtree_object']['nodes']),
                                'dom_documents':len(obs['dom_object']['documents']),'reference':ref})
                        drain_start = time.perf_counter()
                        trace.flush_observations()
                        ended = time.perf_counter()
                    block = {'rotation':rotation,'async_recording':asynchronous,'screenshots':screenshots,
                        'wall_seconds_including_drain':ended-wall,'python_cpu_seconds':time.process_time()-cpu,
                        'final_drain_seconds':ended-drain_start,'rows':rows,'writes':writes,'trace':str(trace.directory)}
                    # Writer interval intersecting a LATER capture proves actual overlap.
                    overlaps = []
                    for i, write in enumerate(writes):
                        seconds = sum(max(0,min(write['finished_at'],row['capture_end'])-max(write['started_at'],row['capture_start'])) for row in rows[i+1:])
                        overlaps.append(seconds)
                    block['write_overlap_with_later_capture_seconds'] = sum(overlaps)
                    block['writes_overlapping_later_capture'] = sum(v>0 for v in overlaps)
                    for row in rows:
                        ref = row['reference']
                        stored=json.loads(gzip.decompress((trace.directory/ref['raw']).read_bytes()))
                        assert len(stored['axtree_object']['nodes']) == row['ax_nodes']
                        assert (trace.directory/ref['text']).is_file()
                        assert bool(ref['screenshot']) == screenshots
                        if screenshots: assert (trace.directory/ref['screenshot']).is_file()
                    assert asynchronous or not any(overlaps)
                    block['artifacts_complete'] = True
                finally:
                    trace.finish({'stop_reason':'scripted_benchmark_end'})
                blocks.append(block)
                write_json(args.output/'partial.json',blocks)
                print(json.dumps({k:v for k,v in block.items() if k not in ('rows','writes')}),flush=True)
    finally:
        env.close()
    assert hashes() == before, 'Runtime changed during benchmark'
    summary=[]
    for asynchronous,screenshots in modes:
        matching=[b for b in blocks if b['async_recording']==asynchronous and b['screenshots']==screenshots]
        rows=[r for b in matching for r in b['rows']]
        summary.append({'async_recording':asynchronous,'screenshots':screenshots,
            'amortized_wall_seconds_per_capture':sum(b['wall_seconds_including_drain'] for b in matching)/len(rows),
            'median_capture_seconds':statistics.median(r['capture_end']-r['capture_start'] for r in rows),
            'median_foreground_recording_seconds':statistics.median(r['recording_foreground_seconds'] for r in rows),
            'total_overlap_seconds':sum(b['write_overlap_with_later_capture_seconds'] for b in matching),
            'overlapping_writes':sum(b['writes_overlapping_later_capture'] for b in matching),
            'possible_overlapping_writes':len(rows)-len(matching),
            'final_drain_seconds':[b['final_drain_seconds'] for b in matching]})
    write_json(args.output/'report.json',{'passed':True,'model_calls':0,'navigation':navigation,
        'source_sha256':before,'blocks':blocks,'summary':summary,
        'scope':'Live page may change; two reversed-order blocks per mode, consecutive captures with no sleeps or inference, atomic complete files and final drain checked. Python CPU excludes Chromium/Node. Single browser, sequential performance isolation.'})
    print(json.dumps(summary,indent=2),flush=True)


if __name__=='__main__':main()
