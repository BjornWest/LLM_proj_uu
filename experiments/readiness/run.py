"""Scripted event-driven readiness comparison. Real Chromium/local HTTP; no model."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import statistics
import subprocess
import sys
import threading
import time
from urllib.parse import parse_qs, urlsplit

HTML = '''<!doctype html><meta charset="utf-8"><title>Readiness fixture</title>
<main id="region" aria-busy="false"><label><input type="checkbox" id="toggle">Optional extra</label>
<button id="run">Update basket</button><button id="nav" onclick="location.href='/next'">Next page</button>
<output id="result">before</output><p id="status" role="status"></p></main><aside id="noise"></aside>
<script>
window.cfg={};window.dispatches=0;window.applied=0;const statusEl=document.getElementById('status');
function publish(){result.textContent='after';applied++;region.setAttribute('aria-busy','false')}
run.onclick=()=>{
 dispatches++;
 const c={...cfg},api=globalThis.__intentReadinessV1.app;
 const op=c.custom?api.begin('basket'):null;
 const extra=c.multiple?api.begin('basket'):null;
 if(c.busy!==false)region.setAttribute('aria-busy','true');
 if(c.hang)return;
 const work=async()=>{
  try{
   const response=await fetch('/api?delay='+(c.delay||0)+'&fail='+(c.fail?'1':'0'));
   if(!response.ok)throw Error('fixture request failed');await response.json();
   if(c.earlySignal&&op)api.end(op);
   const done=()=>{publish();if(op&&!c.earlySignal)api.end(op);if(extra)setTimeout(()=>api.end(extra),120)};
   if(c.renderDelay)setTimeout(done,c.renderDelay);else done();
  }catch(e){statusEl.textContent='Update failed';region.setAttribute('aria-busy','false');if(op)api.end(op,false);if(extra)api.end(extra,false)}
 };
 if(c.debounce)setTimeout(work,c.debounce);else work();
};
window.pulse=()=>{let i=0;window.noiseTimer=setInterval(()=>noise.textContent='Advertisement '+i++,15)};
</script>'''


def write(path,value):path.write_text(json.dumps(value,indent=2,default=str))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


class Server:
    def __init__(self):
        self.requests=0;self.lock=threading.Lock();owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                url=urlsplit(self.path);q=parse_qs(url.query)
                if url.path=='/api':
                    with owner.lock:owner.requests+=1
                    time.sleep(int(q.get('delay',['0'])[0])/1000)
                    code=503 if q.get('fail')==['1'] else 200
                    body=b'{"ok":true}';content='application/json'
                else:code=200;body=HTML.encode();content='text/html'
                self.send_response(code);self.send_header('Content-Type',content)
                self.send_header('Content-Length',str(len(body)));self.end_headers()
                try:self.wfile.write(body)
                except (BrokenPipeError,ConnectionResetError):pass
        self.http=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.thread=threading.Thread(target=self.http.serve_forever,daemon=True);self.thread.start()
        self.url=f'http://127.0.0.1:{self.http.server_port}'
    def close(self):self.http.shutdown();self.http.server_close();self.thread.join()


def load(source):
    spec=importlib.util.spec_from_file_location('tested_readiness',source)
    module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
    return module


def child(args):
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
    m=load(args.module);Readiness,Spec=m.Readiness,m.ReadinessSpec
    out=args.output;out.mkdir(parents=True,exist_ok=False)
    checks=[];rows=[];server=Server()
    def check(name,passed,**detail):
        checks.append(dict(name=name,passed=bool(passed),**detail));write(out/'checks.json',checks)
        if not passed:raise AssertionError(name)
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        context=browser.new_context(viewport={'width':1000,'height':700})
        page=context.new_page();page.goto(server.url)
        ready=Readiness(page)
        def reset(config=None,noise=False):
            page.goto(server.url);page.evaluate('(c)=>window.cfg=c',config or {})
            if noise:page.evaluate('pulse()')
        def state():return page.evaluate('({text:result.textContent,dispatches,applied,busy:region.getAttribute("aria-busy")})')
        condition={'kind':'text','selector':'#result','expected':'after'}
        def run(config,*,custom=False,expect=True,timeout=1800,noise=False):
            reset(config,noise)
            result=ready.perform(lambda:page.locator('#run').click(),Spec(scope='#region',
                condition=condition if expect else None,signal_scope='basket' if custom else None,timeout_ms=timeout))
            rows.append(dict(config=config,custom=custom,expect=expect,**result,state=state()))
            write(out/'samples.json',rows)
            return result['readiness']
        try:
            if args.case=='correctness':
                reset()
                result=ready.perform(lambda:page.locator('#toggle').check(),Spec(scope='#region',condition={'kind':'checked','selector':'#toggle','expected':True}))['readiness']
                check('native immediate checkbox condition',result['status']=='ready' and page.locator('#toggle').is_checked())
                r=run({'delay':80});check('generic public condition waits for response',r['status']=='ready' and state()['applied']==1)
                r=run({'delay':850});check('response longer than 500ms completes before ready',r['status']=='ready' and r['wait_seconds']>.5)
                r=run({'custom':True,'debounce':650,'delay':80},custom=True,expect=False)
                check('custom begin spans debounce before network starts',r['status']=='ready' and r['wait_seconds']>.5 and state()['applied']==1)
                r=run({'delay':80},noise=True);check('continuous unrelated mutations do not block scoped readiness',r['status']=='ready' and r['wait_seconds']<.5)
                r=run({'custom':True,'multiple':True,'delay':20},custom=True,expect=False)
                check('all nested matching operations must finish',r['status']=='ready' and r['wait_seconds']>=.1)
                r=run({'custom':True,'earlySignal':True,'busy':False,'delay':10,'renderDelay':650},custom=True)
                check('early completion signal cannot override unmet public condition',r['status']=='ready' and r['wait_seconds']>.5 and state()['text']=='after')
                r=run({'custom':True,'hang':True},custom=True,expect=False,timeout=180)
                check('hung operation is pending rather than success',r['status']=='pending' and r['pending_operations']==1 and state()['dispatches']==1)
                check('readiness does not assign task grade',r['task_success'] is None)
                r=run({'custom':True,'fail':True},custom=True,expect=False)
                check('application failure remains distinct from ready',r['status']=='failed' and state()['applied']==0 and state()['dispatches']==1)
                r=run({'delay':750,'busy':False},custom=False,expect=False)
                check('quiet page without contract is explicitly unknown',r['status']=='unknown' and r['reason']=='region_quiet_without_completion_contract' and state()['applied']==0)
                r=run({'delay':0},custom=True,expect=False,timeout=120)
                check('missing expected application signal cannot be guessed ready',r['status']=='unknown' and not r['observed_operation'])
                reset({'custom':True,'delay':0})
                page.evaluate("()=>{window.other=__intentReadinessV1.app.begin('advertising')}")
                r=ready.perform(lambda:page.locator('#run').click(),Spec(scope='#region',signal_scope='basket'))['readiness']
                check('unrelated custom operation does not block',r['status']=='ready')
                page.evaluate('()=>__intentReadinessV1.app.end(other)')
                check('duplicate end signals rejected',page.evaluate('()=>__intentReadinessV1.app.end(other)') is False)
                reset({'custom':True,'delay':500})
                r=ready.perform(lambda:page.locator('#run').click(),Spec(scope='#region',signal_scope='basket',timeout_ms=80))['readiness']
                check('timeout does not replay or cancel website request',r['status']=='pending' and state()['dispatches']==1)
                page.wait_for_function('applied===1')
                check('pending operation may complete later exactly once',state()['dispatches']==1 and state()['applied']==1)
                reset();r=ready.perform(lambda:page.locator('#nav').click(),Spec(scope='#region',condition=condition))['readiness']
                check('navigation cannot reuse old-document readiness',r['status']=='unknown' and r['reason']=='document_changed')
                reset()
                try:ready.perform(lambda:page.locator('#missing').click(timeout=60),Spec(scope='#region'));failed=False
                except PlaywrightTimeout:failed=True
                d=page.evaluate('__intentReadinessV1.diagnostics()')
                check('action exception preserved and listeners cleaned',failed and d['waiters']==0 and d['subscribers']==0)
                reset();ticket=ready.arm(Spec(scope='#region',signal_scope='basket',timeout_ms=100))
                check('explicit cancellation releases waiter',ready.cancel(ticket) and page.evaluate('__intentReadinessV1.diagnostics().waiters')==0)
                check('foreign-document token cannot finish an operation',page.evaluate("()=>__intentReadinessV1.app.end('old-document-token')") is False)
                reset();page.evaluate("()=>{let f=document.createElement('iframe');f.srcdoc='<button>Inside</button>';document.body.append(f)}")
                page.wait_for_function('document.querySelector("iframe").contentDocument.readyState==="complete"')
                try:ready.arm(Spec());failed=False
                except ValueError:failed=True
                check('unsupported frames explicit before action',failed)
                reset()
                for bad in [Spec(timeout_ms=True),Spec(quiet_ms=0),Spec(condition={'kind':'eval','selector':'body','expected':'bad'}),Spec(condition={'kind':'checked','selector':'#toggle','expected':1})]:
                    try:ready.perform(lambda:page.locator('#run').click(),bad);failed=False
                    except ValueError:failed=True
                    check('invalid config rejects before dispatch '+repr(bad),failed and state()['dispatches']==0)
                # Event-driven timeout is bounded even with continuous scoped mutations.
                reset();page.evaluate("()=>{setInterval(()=>statusEl.textContent=String(Math.random()),10)}")
                r=ready.perform(lambda:None,Spec(scope='#region',condition=condition,timeout_ms=140))['readiness']
                check('scoped perpetual activity bounded by deadline',r['status']=='unknown' and r['wait_seconds']<.6 and r['observed_changes']>0)
                check('all finished wait listeners cleaned',page.evaluate('__intentReadinessV1.diagnostics().subscribers')==0)
                reset()
                r=ready.perform(lambda:page.locator('#run').evaluate("el=>el.setAttribute('aria-expanded','true')"),Spec(scope='#region',condition={'kind':'attribute','selector':'#run','name':'aria-expanded','expected':'true'}))['readiness']
                check('public attribute condition',r['status']=='ready')
                r=ready.perform(lambda:page.locator('#region').evaluate("el=>el.insertAdjacentHTML('beforeend','<p class=added>New row</p>')"),Spec(scope='#region',condition={'kind':'count','selector':'.added','expected':1}))['readiness']
                check('public count condition',r['status']=='ready')
                reset()
                r=ready.perform(lambda:page.locator('#region').evaluate('el=>el.remove()'),Spec(scope='#region',condition=condition,timeout_ms=80))['readiness']
                check('lost scope is unknown not ready',r['status']=='unknown' and r['reason']=='scope_unavailable')
                reset()
                r=ready.perform(lambda:page.evaluate("()=>{const f=document.createElement('iframe');f.srcdoc='<p>new frame</p>';document.body.append(f)}"),Spec(scope='#region',timeout_ms=100))['readiness']
                check('frames added during action do not silently pass',r['status']=='unknown' and r['reason']=='unsupported_frames')
                reset()
                ticket=ready.arm(Spec(scope='#region',signal_scope='basket',timeout_ms=200))
                ready.close()
                check('close cancels subscriptions',page.evaluate('__intentReadinessV1.diagnostics().subscribers')==0)
                # The same public-state path can operate after an arbitrary existing operation.
                reset();page.evaluate("()=>{window.previous=__intentReadinessV1.app.begin('basket');setTimeout(()=>__intentReadinessV1.app.end(previous),80)}")
                r=ready.perform(lambda:None,Spec(scope='#region',signal_scope='basket'))['readiness']
                check('existing scoped operation observed at arm',r['status']=='ready' and r['observed_operation'])
                reset({'custom':True,'hang':True})
                def add_frame_later():
                    page.locator('#run').click()
                    page.evaluate("()=>setTimeout(()=>{let f=document.createElement('iframe');f.srcdoc='<p>late frame</p>';document.body.append(f)},50)")
                r=ready.perform(add_frame_later,Spec(scope='#region',signal_scope='basket',timeout_ms=500))['readiness']
                check('frame appearing during wait invalidates readiness',r['status']=='unknown' and r['reason']=='unsupported_frames')
                # Plain HTTP hostname is intentionally not a secure localhost origin;
                # Playwright fulfills it locally, with no external request.
                page.route('http://readiness-fixture.invalid/**',lambda route:route.fulfill(status=200,content_type='text/html',body=HTML))
                page.goto('http://readiness-fixture.invalid/')
                r=ready.perform(lambda:page.locator('#toggle').check(),Spec(scope='#region',condition={'kind':'checked','selector':'#toggle','expected':True}))['readiness']
                check('plain HTTP insecure-origin readiness supported',not page.evaluate('isSecureContext') and r['status']=='ready')
                # A library can also be attached before the first real navigation.
                blank=context.new_page();blank_ready=Readiness(blank)
                check('install before navigation supports about:blank',blank.evaluate('__intentReadinessV1.version')==1)
                blank_ready.close();blank.close()
                write(out/'result.json',dict(passed=True,checks=checks,model_calls=0,http_requests=server.requests))
            else:
                cases=[('immediate',{},False),('fast_request',{'delay':80},False),
                       ('slow_request',{'delay':850},False),('debounce',{'custom':True,'debounce':650,'delay':80},True),
                       ('unrelated_activity',{'delay':80},False)]
                for name,config,custom in cases:
                    for repeat in range(3):
                        for mode in (['events','fixed500'] if repeat%2==0 else ['fixed500','events']):
                            reset(config,name=='unrelated_activity')
                            start=time.perf_counter()
                            if name=='immediate':
                                action=lambda:page.locator('#toggle').check()
                                spec=Spec(scope='#region',condition={'kind':'checked','selector':'#toggle','expected':True})
                            else:
                                action=lambda:page.locator('#run').click()
                                spec=Spec(scope='#region',condition=None if custom else condition,signal_scope='basket' if custom else None)
                            if mode=='events':
                                result=ready.perform(action,spec);status=result['readiness']['status'];wait=result['readiness']['wait_seconds']
                            else:
                                action();wait_start=time.perf_counter();page.wait_for_timeout(500);wait=time.perf_counter()-wait_start;status='unchecked'
                            total=time.perf_counter()-start
                            complete=page.locator('#toggle').is_checked() if name=='immediate' else state()['applied']==1
                            rows.append(dict(case=name,mode=mode,repeat=repeat,total_seconds=total,wait_seconds=wait,status=status,complete_at_observation=complete))
                            write(out/'samples.json',rows)
                            if mode=='events':check(f'{name} event completion {repeat}',status=='ready' and complete)
                summary=[]
                for name,_,_ in cases:
                    for mode in ['events','fixed500']:
                        group=[x for x in rows if x['case']==name and x['mode']==mode]
                        summary.append(dict(case=name,mode=mode,total_seconds=statistics.median(x['total_seconds'] for x in group),wait_seconds=statistics.median(x['wait_seconds'] for x in group),complete=sum(x['complete_at_observation'] for x in group),samples=len(group)))
                write(out/'result.json',dict(passed=True,checks=checks,summary=summary,model_calls=0))
        finally:ready.close();browser.close();server.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--module',type=Path,default=Path('intent_browser/readiness.py'))
    parser.add_argument('--case',choices=['correctness','performance'])
    args=parser.parse_args();args.output=args.output.resolve();args.module=args.module.resolve()
    if args.case:return child(args)
    args.output.mkdir(parents=True,exist_ok=False)
    shutil.copy2(args.module,args.output/'readiness.py');shutil.copy2(__file__,args.output/'run.py')
    sources={n:sha(args.output/n) for n in ['readiness.py','run.py']}
    write(args.output/'manifest.json',dict(source_sha256=sources,model_calls=0))
    root=Path(__file__).resolve().parents[2]
    env={**os.environ,'LD_LIBRARY_PATH':str(root/'.local/system-libs/usr/lib/x86_64-linux-gnu'),'PYTHONDONTWRITEBYTECODE':'1'}
    def run(label,case):
        with (args.output/(label+'.log')).open('x') as log:
            proc=subprocess.Popen([sys.executable,str(args.output/'run.py'),'--module',str(args.output/'readiness.py'),'--case',case,'--output',str(args.output/label)],env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            try:code=proc.wait(timeout=180)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid,signal.SIGKILL);proc.wait();raise RuntimeError(label+' timed out')
            if code:raise RuntimeError(label+' failed; see retained log')
        print(label,'passed',flush=True)
    with ThreadPoolExecutor(2) as pool:list(pool.map(lambda i:run('correctness-'+str(i),'correctness'),range(2)))
    # Deliberate performance isolation, not simultaneous competing browsers.
    run('performance','performance')
    write(args.output/'closure.json',dict(source_unchanged=all(sha(args.output/n)==h for n,h in sources.items())))


if __name__=='__main__':main()
