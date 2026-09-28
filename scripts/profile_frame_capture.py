"""Local phase/frame profiling. Two-phase marker is an experiment, not runtime adoption."""
import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
import multiprocessing
from pathlib import Path
import pkgutil
import sys
import time
from unittest.mock import patch
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from playwright.sync_api import sync_playwright,Frame
from browsergym.core import observation as core
from intent_browser.trace import write_json

SOURCE=pkgutil.get_data('browsergym.core.observation','javascript/frame_mark_elements.js').decode()
EXPECTED='6ecfbba89d756c37874bdf692e4bf24126459ab79f9120c1f053305b7ba2978a'
assert hashlib.sha256(SOURCE.encode()).hexdigest()==EXPECTED,'Review changed BrowserGym source first'
START=SOURCE.replace('async ([parent_bid, bid_attr_name, tags_to_mark]) => {',
    'async ([parent_bid, bid_attr_name, tags_to_mark, job_key]) => {',1)
a=START.index('    // wait for all elements to be visited for visibility')
b=START.index('    return warning_msgs;',a)+len('    return warning_msgs;')
START=START[:a]+'''    const job = {cancel: () => intersection_observer.disconnect()};
    job.promise = (async () => {
        let visibility_marking_timeout = 1000;
        try { await until(() => elems_to_be_visited.size == 0, visibility_marking_timeout); }
        catch { warning_msgs.push(`Frame marking: not all elements have been visited by the intersection_observer after ${visibility_marking_timeout} ms`); }
        finally { intersection_observer.disconnect(); }
        return warning_msgs;
    })();
    globalThis[job_key] = job;
    return [];
'''+START[b:]
FINISH='''async key => {
 const job=globalThis[key]; if(!job)throw new Error('Capture job document replaced');
 try { return await job.promise; } finally { job.cancel(); delete globalThis[key]; }
}'''
CANCEL='key => { const job=globalThis[key]; if(job){job.cancel();delete globalThis[key];} }'


def parallel_mark(page):
    key='__capture_test_'+uuid4().hex;pending=[];warnings=[]
    def visit(frame,prefix):
        frame.evaluate(START,[prefix,'bid','standard_html',key]);pending.append(frame)
        for child in frame.child_frames:
            if child.is_detached():continue
            element=child.frame_element()
            if element.content_frame()!=child:continue
            sandbox=element.get_attribute('sandbox')
            if sandbox is not None and 'allow-scripts' not in sandbox.split():continue
            bid=element.get_attribute('bid')
            if bid is None:raise core.MarkingError('Cannot mark a child frame without a bid')
            visit(child,bid)
    try:
        visit(page.main_frame,'')
        for frame in pending:warnings.extend(frame.evaluate(FINISH,key))
    finally:
        for frame in pending:
            try:frame.evaluate(CANCEL,key)
            except Exception:pass  # Experiment records errors; never used as a production success fallback.
    return warnings


def run_case(args):
    count,kind,out=args;out=Path(out);out.mkdir(parents=True,exist_ok=False)
    phases=[];frame_events=[];native=Frame.evaluate;variant='setup'
    def evaluate(frame,expression,*a,**kw):
        if expression not in (SOURCE,START,FINISH):return native(frame,expression,*a,**kw)
        started=time.monotonic();error=None
        try:return native(frame,expression,*a,**kw)
        except Exception as exc:error=type(exc).__name__;raise
        finally:frame_events.append({'variant':variant,'operation':'serial' if expression==SOURCE else 'start' if expression==START else 'finish',
            'seconds':time.monotonic()-started,'frame':page.frames.index(frame) if frame in page.frames else None,'error':error})
    def timed(name,fn):
        started=time.monotonic()
        try:return fn()
        finally:
            record={'variant':variant,'phase':name,'seconds':time.monotonic()-started};phases.append(record)
            with (out/'phases.jsonl').open('a') as f:f.write(json.dumps(record)+'\n')
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True);page=browser.new_page()
        def route(r):
            if '/child' in r.request.url:
                stub='<script>window.IntersectionObserver=class {observe(){} disconnect(){}}</script>' if kind=='stalled' else ''
                body=stub+'<h2>Frame content</h2><button>Child action</button><div id=host></div><script>host.attachShadow({mode:"open"}).innerHTML="<input value=shadow>"</script>'
            else:body='<h1>Main</h1><button>Main action</button>'+''.join(
                f'<iframe '+('style="display:none" ' if kind=='hidden' else '')+f'src="http://child.invalid/child{i}"></iframe>' for i in range(count))
            r.fulfill(content_type='text/html',body=body)
        page.route('**/*',route);page.goto('http://main.invalid/',wait_until='load')
        rows=[]
        try:
            with patch.object(Frame,'evaluate',evaluate):
                for variant in ('serial','overlap'):
                    warning_msgs=timed('mark',lambda:core._pre_extract(page) if variant=='serial' else parallel_mark(page))
                    dom=timed('DOM',lambda:core.extract_dom_snapshot(page))
                    ax=timed('AX',lambda:core.extract_merged_axtree(page))
                    timed('cleanup',lambda:core._post_extract(page))
                    timed('screenshot',lambda:core.extract_screenshot(page))
                    visibility=[f.evaluate("()=>Array.from(document.querySelectorAll('[bid]')).map(e=>[e.getAttribute('bid'),e.getAttribute('browsergym_visibility_ratio'),e.getAttribute('value')])") for f in page.frames]
                    # Ignore CDP numeric IDs, compare policy semantics + stable BIDs.
                    semantics=[{k:n[k] for k in ('role','name','value','browsergym_id','ignored') if k in n} for n in ax['nodes']]
                    rows.append({'variant':variant,'documents':len(dom['documents']),'ax':semantics,'visibility':visibility,
                        'warnings':warning_msgs,'timings':{r['phase']:r['seconds'] for r in phases if r['variant']==variant}})
            assert rows[0]['ax']==rows[1]['ax']
            assert rows[0]['visibility']==rows[1]['visibility']
            assert rows[0]['documents']==rows[1]['documents']
        finally:browser.close()
    report={'passed':True,'child_frames':count,'kind':kind,'rows':rows,'frame_events':frame_events,
        'upstream_js_sha256':EXPECTED,'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'model_calls':0,'scope':'Sequential vs overlapped ordinary 1s visibility waits; no runtime promotion, no hard transport deadline claim'}
    write_json(out/'report.json',report);return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    cases=[(n,k,str(a.output/f'{k}-{n}')) for n,k in [(1,'stalled'),(8,'stalled'),(32,'stalled'),(16,'hidden')]]
    with ProcessPoolExecutor(max_workers=3,mp_context=multiprocessing.get_context('spawn')) as pool:results=list(pool.map(run_case,cases))
    write_json(a.output/'report.json',{'passed':True,'cases':results,'model_calls':0})
