"""Offline paired capture/recording parity and CPU profile; no inference.

Sequential by design to isolate timing. A fresh output directory is required.
Baseline uses public CDP and the former streaming JSON encoder. Candidate uses
actual harness code, not an alternate benchmark-only implementation.
"""
import argparse
import cProfile
from copy import deepcopy
from contextlib import nullcontext
import gzip
import hashlib
import io
import json
from pathlib import Path
import pstats
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
from PIL import Image
from browsergym.core.env import BrowserEnv
from browsergym.core.task import OpenEndedTask
from browsergym.utils.obs import flatten_axtree_to_str
from intent_browser.native_capture import CaptureBudget, capture_native
from intent_browser.trace import Trace, json_default, write_json


def measure(fn):
    started, cpu = time.perf_counter(), time.process_time()
    result = fn()
    return result, {'wall_seconds': time.perf_counter()-started,
                    'python_cpu_seconds': time.process_time()-cpu}


def canonical(obs):
    result = deepcopy({k:v for k,v in obs.items() if k not in ('screenshot', 'elapsed_time')})
    nodes = result['axtree_object']['nodes']
    aliases = {n['nodeId']:f'inline-text-at-index-{i}' for i,n in enumerate(nodes)
               if str(n['nodeId']).startswith('-')}
    assert all(n['role']['value']=='InlineTextBox' for n in nodes if n['nodeId'] in aliases)
    for node in nodes:
        for key in ('nodeId', 'parentId'):
            if key in node: node[key] = aliases.get(node[key], node[key])
        if 'childIds' in node: node['childIds'] = [aliases.get(v,v) for v in node['childIds']]
    return result


def old_record(trace, index, obs, text):
    stem = f'old-observation-{index:03d}'
    if obs['screenshot'] is not None:
        Image.fromarray(obs['screenshot']).save(trace.directory/f'{stem}.png')
    with gzip.open(trace.directory/f'{stem}.json.gz', 'wt', encoding='utf-8') as f:
        json.dump({k:v for k,v in obs.items() if k!='screenshot'}, f, default=json_default)
    (trace.directory/f'{stem}.txt').write_text(text, encoding='utf-8')
    return {'raw':stem+'.json.gz', 'text':stem+'.txt', 'screenshot':stem+'.png'}


def run(products, out, repetitions):
    body = '<h1>Storefront</h1><button>Commit</button><main>'+''.join(
        f'<article><h2>Product {i}</h2><p>Stock: {i%5}</p></article>' for i in range(products))+'</main>'
    class Fixture(OpenEndedTask):
        def setup(self, page):
            page.route('**/*', lambda route:route.fulfill(content_type='text/html', body=body))
            return super().setup(page)
    env = BrowserEnv(task_entrypoint=Fixture,
        task_kwargs={'start_url':'http://fixture.invalid/main', 'goal':'Inspect only'}, headless=True)
    trace = Trace(out/'traces', {'driver':'capture_json_acceptance', 'products':products, 'model_calls':0})
    rows = []
    def capture():
        budget = CaptureBudget(env.page, trace, enforce=False)
        with budget.rpc_deadline(): return capture_native(env, budget)
    try:
        env.reset(seed=0)
        for rep in range(repetitions):
            captures, timing = {}, {}
            variants = ('public','conversion_only','optimized')
            for variant in variants[rep%3:]+variants[:rep%3]:
                connection_path = (patch('intent_browser.cdp_json._raw_reply_scope',
                    lambda *a:nullcontext()) if variant=='conversion_only' else nullcontext())
                with patch('intent_browser.cdp_json._reviewed_version', return_value=variant!='public'), connection_path:
                    captures[variant], timing[variant] = measure(capture)
            a, b = captures['public'], captures['optimized']
            assert canonical(a)==canonical(b), 'Observation mismatch beyond transient layout IDs/time'
            assert np.array_equal(a['screenshot'], b['screenshot']), 'Pixels changed'
            middle = captures['conversion_only']
            assert canonical(a)==canonical(middle)
            assert np.array_equal(a['screenshot'], middle['screenshot'])
            trace.observation(rep,middle,flatten_axtree_to_str(middle['axtree_object']))
            # Retain both raw captures independently; only time the same input for serialization parity.
            trace.observation(rep, b, flatten_axtree_to_str(b['axtree_object']), phase='decision')
            text = flatten_axtree_to_str(a['axtree_object'])
            saved, recording = {}, {}
            for variant in (('stream','bulk') if rep%2==0 else ('bulk','stream')):
                call = (lambda:old_record(trace,rep,a,text)) if variant=='stream' else (
                    lambda:trace.observation(rep,a,text,phase='background'))
                saved[variant], recording[variant] = measure(call)
            for key in ('raw','text','screenshot'):
                contents = [(trace.directory/saved[v][key]).read_bytes() for v in ('stream','bulk')]
                if key=='raw': contents = [gzip.decompress(v) for v in contents]
                assert contents[0]==contents[1], f'Recording {key} mismatch'
            row = {'products':products, 'ax_nodes':len(a['axtree_object']['nodes']),
                   'pair':rep, 'capture':timing, 'recording':recording, 'parity':True,
                   'trace':str(trace.directory)}
            rows.append(row); print(json.dumps(row), flush=True)
        if products==3000:
            prof = cProfile.Profile(); prof.enable()
            obs = capture(); text = flatten_axtree_to_str(obs['axtree_object'])
            trace.observation(repetitions,obs,text,phase='background')
            prof.disable(); prof.dump_stats(str(out/'optimized.prof'))
            stream = io.StringIO()
            stats = pstats.Stats(prof,stream=stream)
            scans = sum(values[1] for key,values in stats.stats.items()
                        if key[2]=='_replace_guids_with_channels')
            # Full DOM/AX payloads formerly caused >1 million recursive calls.
            # Normal small protocol replies still require reference conversion.
            assert scans < 10000, f'Large payload traversal returned: {scans}'
            write_json(out/'reference-scan-count.json', {'calls':scans,
                'scope':'cProfile recursive calls including ordinary small replies'})
            stats.strip_dirs().sort_stats('cumulative').print_stats(40)
            (out/'optimized-profile.txt').write_text(stream.getvalue())
    finally:
        env.close(); trace.finish({'stop_reason':'scripted_comparison_end','error':None})
    return rows


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(); args.output.mkdir(parents=True, exist_ok=False)
    paths = [*Path('intent_browser').glob('*.py'), Path(__file__)]
    hashes = lambda:{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    before = hashes(); rows = []
    for products in (150,3000): rows.extend(run(products,args.output,3))
    assert hashes()==before, 'Runtime changed during acceptance'
    write_json(args.output/'report.json', {'passed':True, 'model_calls':0, 'rows':rows,
        'source_sha256':before, 'scope':'Warm static Linux-headless fixture; three-way rotated order (public, prior conversion-only, current). CPU profile excluded from timing samples. Sequential performance isolation. Only elapsed time and negative InlineTextBox IDs/edges normalized; all other values and pixels preserved.'})


if __name__=='__main__': main()
