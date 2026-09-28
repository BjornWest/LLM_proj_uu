#!/usr/bin/env python3
"""Offline push-feedback checks plus isolated A/B timings; no model calls."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import statistics
import sys
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
os.environ['LD_LIBRARY_PATH']=str(ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu')+':'+os.environ.get('LD_LIBRARY_PATH','')
from playwright.sync_api import sync_playwright
from intent_browser.browser_events import BrowserEvents
from intent_browser.debug_timings import DebugTimings
from intent_browser.trace import Trace,write_json

PAGE='<html><body><button>Go</button><div role="status" id="status">Ready</div><iframe srcdoc="<p>Child</p>"></iframe></body></html>'


def settle(page,c):
    # Test-only setup barrier, not an inference-path wait/flush.
    until=time.monotonic()+3
    while c.tasks and time.monotonic()<until:page.wait_for_timeout(10)
    assert not c.tasks
    assert not c.errors,c.errors
    c.drain()


def browser_case(kind):
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        context=browser.new_context();context.route('http://127.0.0.1/**',lambda r:r.fulfill(status=200,content_type='text/html',body=PAGE));page=context.new_page();page.goto('http://127.0.0.1/fixture')
        active=[page];timings=DebugTimings(True);c=BrowserEvents(debug_timings=timings)
        if kind=='custody':c.page_filter=lambda p:p is active[0]
        c.start(context);settle(page,c)
        if kind=='late':
            page.evaluate("setTimeout(()=>document.querySelector('#status').textContent='Late notice',200)")
            first=c.drain();assert 'Late notice' not in json.dumps(first)
            page.wait_for_timeout(260);second=c.drain()
            assert 'Late notice' in json.dumps(second);assert not c.drain()['events']
            evidence={'first':first,'second':second}
        elif kind=='custody':
            other=context.new_page();other.goto('http://127.0.0.1/fixture');settle(other,c)
            other.evaluate("document.querySelector('#status').textContent='Human-only change'")
            other.wait_for_timeout(50);assert 'Human-only' not in json.dumps(c.drain())
            active[0]=other
            other.evaluate("document.querySelector('#status').textContent='New active change'")
            other.wait_for_timeout(50);result=c.drain();assert 'New active change' in json.dumps(result)
            # Existing initial documents also work after adopting a tab again.
            active[0]=page
            page.evaluate("document.querySelector('#status').textContent='Returned active change'")
            page.wait_for_timeout(50);back=c.drain();assert 'Returned active change' in json.dumps(back)
            evidence={'adopted':result,'returned':back}
        elif kind=='quota':
            for round in range(3):
                page.evaluate("n=>{for(let i=0;i<100;i++){let p=document.createElement('p');p.role='alert';p.textContent='Notice '+n+' '+i;document.body.append(p)}}",round)
                page.wait_for_timeout(350);batch=c.drain()
                assert len(batch['events'])<=64
                assert batch['omitted'] or any(x['kind']=='capture_gap' for x in batch['events'])
            page.evaluate("document.querySelector('#status').textContent='After three overflow windows'")
            page.wait_for_timeout(50);result=c.drain();assert 'After three overflow' in json.dumps(result)
            evidence={'last_overflow':batch,'recovered':result}
        elif kind=='initial_timeout':
            # Cancel diagnostic installs without changing a browser action.
            c.close(context_closing=True)
            page.evaluate("setTimeout(()=>{const end=performance.now()+900;while(performance.now()<end){}},0)")
            c=BrowserEvents(debug_timings=timings);c.context=context
            c.loop=context._impl_obj._loop
            import asyncio
            c.semaphore=asyncio.Semaphore(4)
            c._schedule('blocked_install',lambda:page._impl_obj.evaluate('42'),page=page)
            page.wait_for_timeout(600)
            result=c.drain();assert 'blocked_install_unavailable' in result['capture_warnings']
            c.close(context_closing=True);page.wait_for_timeout(400)
            assert not c.tasks
            evidence={'timeout':result}
        elif kind=='shutdown':
            import asyncio
            async def never():await asyncio.sleep(30)
            c._schedule('pending',never,page=page)
            page.wait_for_timeout(10);assert c.tasks
            started=time.monotonic();c.close(context_closing=True);elapsed=time.monotonic()-started
            page.wait_for_timeout(10);assert not c.tasks
            evidence={'close_seconds':elapsed}
        else:raise AssertionError(kind)
        c.close(context_closing=True);context.close();browser.close()
        return {'case':kind,'passed':True,'evidence':evidence,'timings':timings.report()}


def blocked_ab():
    # Sequential by design: compare delivery barriers without CPU contention.
    rows=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True);context=browser.new_context();context.route('http://127.0.0.1/**',lambda r:r.fulfill(status=200,content_type='text/html',body=PAGE));page=context.new_page()
        page.goto('http://127.0.0.1/fixture');c=BrowserEvents();c.start(context);settle(page,c)
        frame=page.frames[1]
        for mode in ('push','serial_flush')*3:
            frame.evaluate("()=>setTimeout(()=>{const end=performance.now()+500;while(performance.now()<end){}},0)")
            time.sleep(.05) # Host sleep allows child JS to become unresponsive.
            started=time.monotonic()
            if mode=='serial_flush':
                # Original barrier structure, exact installed flush function.
                for f in page.frames:
                    if f.evaluate('(key)=>!!window[key]',c.key):
                        f.evaluate('async(key)=>window[key].flush()',c.key)
            c.drain();elapsed=time.monotonic()-started
            page.evaluate('1') # Prove browser remains usable; outside timing.
            rows.append({'mode':mode,'seconds':elapsed})
        c.close(context_closing=True);context.close();browser.close()
    med={mode:statistics.median(r['seconds'] for r in rows if r['mode']==mode) for mode in ('push','serial_flush')}
    assert med['push']<.02 and med['serial_flush']>.25,med
    return {'samples':rows,'median_seconds':med}


def debug_ab(output):
    # Same synthetic trace operation, alternated mode, no browser/HTTP variance.
    rows=[]
    for enabled in (False,True)*4:
        trace=Trace(output/'timing-traces',{},debug_timings=enabled,async_recording=True)
        c=BrowserEvents(debug_timings=trace.timings);page=object();frame=object()
        obs={'screenshot':None,'axtree_object':{'nodes':[{'name':'Item','id':i} for i in range(1000)]}}
        started=time.monotonic()
        for turn in range(100):
            for i in range(20):c._append(page,frame,{'kind':'page_announcement','text':'Public notice'})
            c.drain()
            trace.observation(turn,obs,'A public preview')
            for phase in ('prepare','AX','extras','cleanup'):
                trace.event('observation_capture_phase',seconds=.0001,phase=phase)
            trace.append({'step':turn,'messages':[]})
        hot=time.monotonic()-started
        started=time.monotonic();trace.finish({'stop_reason':'synthetic'});shutdown=time.monotonic()-started
        rows.append({'enabled':enabled,'hot_path_seconds':hot,'finish_seconds':shutdown,
                     'trace':str(trace.directory),'records':len(trace.timings.rows)})
    med={str(flag):statistics.median(r['hot_path_seconds'] for r in rows if r['enabled']==flag) for flag in (False,True)}
    return {'turns_per_sample':100,'rows':rows,'median_hot_path_seconds':med,
            'median_added_seconds_per_turn':(med['True']-med['False'])/100,
            'scope':'Alternated 1000-node immutable serialization/write workload. Includes background writer backpressure; not a live-model/browser overhead estimate.'}


def main(output):
    output.mkdir(parents=True,exist_ok=False)
    paths=[ROOT/'intent_browser'/name for name in ('browser_events.py','debug_timings.py','trace.py','runner.py','browser_feedback.py','feedback_presentation.py')]+[Path(__file__)]
    sources={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    # Independent browser cases, separate contexts/process connections, bounded 2.
    with ThreadPoolExecutor(max_workers=2) as pool:cases=list(pool.map(browser_case,('late','custody','quota','initial_timeout','shutdown')))
    report={'passed':True,'cases':cases,'blocked_iframe_comparison':blocked_ab(),'debug_overhead':debug_ab(output),'model_calls':0,'source_sha256':sources}
    assert sources=={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    write_json(output/'report.json',report)
    print(json.dumps({k:v for k,v in report.items() if k not in ('cases','source_sha256')},indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True,type=Path)
    main(parser.parse_args().output)
