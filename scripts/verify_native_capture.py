"""Local native-capture parity/deadline checks. No inference or public websites."""
import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib,json,multiprocessing
from pathlib import Path
import sys,time
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from browsergym.core.env import BrowserEnv
from browsergym.core.task import OpenEndedTask
from playwright.sync_api import Frame,CDPSession
from intent_browser.trace import Trace,write_json
from intent_browser.human_browser import HumanBrowser
from intent_browser.human_handover import HumanHandoverController
from intent_browser.observation_pipeline import ObservationPipeline,ObservationPipelineConfig
from intent_browser.native_capture import CaptureBudget,CaptureDeadlineExceeded

MODES=('plain','hidden16','stalled32','nested','blocked_frame','blocked_screenshot','cleanup_error','wait_budget')

def run_case(args):
    mode,out=args;out=Path(out);out.mkdir(parents=True,exist_ok=False)
    class Task(OpenEndedTask):
        def setup(self,page):
            def route(r):
                body='<h1>Main</h1><button id=accept>Accept</button><div id=host></div><script>host.attachShadow({mode:"open"}).innerHTML="<input value=shadow>"</script>'
                if '/child' in r.request.url:
                    body='<h2>Child content</h2><button>Child action</button><input value=child>'
                    if mode=='stalled32':body='<script>window.IntersectionObserver=class {observe(){} disconnect(){}}</script>'+body
                    if mode=='nested' and '/child0' in r.request.url:body+='<iframe src="http://nested.invalid/child1"></iframe>'
                r.fulfill(content_type='text/html',body=body)
            page.route('**/*',route);return super().setup(page)
    env=BrowserEnv(task_entrypoint=Task,task_kwargs={'start_url':'http://main.invalid/','goal':'Local capture parity'},headless=True)
    trace=Trace(out/'runs',{'driver':'native_capture_acceptance','model_calls':0})
    human=pipeline=None;result={}
    try:
        env.reset();page=env.page
        count={'hidden16':16,'stalled32':32,'nested':3}.get(mode,0)
        if count:
            page.evaluate('''({count,hidden})=>Promise.all(Array.from({length:count},(_,i)=>new Promise(resolve=>{
              let f=document.createElement('iframe');f.onload=resolve;f.src='http://child.invalid/child'+i;
              if(hidden)f.style.display='none';document.body.append(f);
            })))''',{'count':count,'hidden':mode=='hidden16'})
        compare=mode in ('plain','hidden16','stalled32','nested')
        if compare:
            start=time.monotonic();baseline=env._get_obs();baseline_seconds=time.monotonic()-start
        pipeline=ObservationPipeline(env,ObservationPipelineConfig((),full_capture_only=True),trace)
        human=HumanBrowser(env,HumanHandoverController(),trace,pipeline);human.start()
        if compare:
            timings=[]
            for _ in range(2):
                start=time.monotonic();current=human.capture();timings.append(time.monotonic()-start)
                sem=lambda o:[{k:n[k] for k in ('role','name','value','browsergym_id','ignored','properties') if k in n} for n in o['axtree_object']['nodes']]
                assert sem(current)==sem(baseline),'AX semantic mismatch'
                assert current['extra_element_properties']==baseline['extra_element_properties'],'Visibility/geometry mismatch'
                assert len(current['dom_object']['documents'])==len(baseline['dom_object']['documents'])
            result={'baseline_seconds':baseline_seconds,'capture_seconds':timings,'parity':True,'frames':len(page.frames)}
        elif mode=='wait_budget':
            def wait(frame,*a,**kw):return frame.evaluate('()=>new Promise(()=>{})')
            start=time.monotonic()
            with patch.object(Frame,'wait_for_load_state',wait):human.wait()
            seconds=time.monotonic()-start
            assert .9<=seconds<2.0,seconds
            human.capture()
            result={'wait_seconds':seconds,'capture_after_wait_succeeded':True}
        else:
            original_evaluate=Frame.evaluate;original_send=CDPSession.send
            def evaluate(frame,expression,*a,**kw):
                if mode=='blocked_frame' and expression=='() => [location.href, performance.timeOrigin]':
                    expression='()=>new Promise(()=>{})'
                return original_evaluate(frame,expression,*a,**kw)
            def send(session,method,*a,**kw):
                if mode=='blocked_screenshot' and method=='Page.captureScreenshot':return page.evaluate('()=>new Promise(()=>{})')
                if mode=='cleanup_error' and method=='DOMSnapshot.captureSnapshot':raise RuntimeError('Synthetic DOM phase error')
                return original_send(session,method,*a,**kw)
            start=time.monotonic()
            with patch.object(Frame,'evaluate',evaluate),patch.object(CDPSession,'send',send):
                try:human.capture()
                except Exception as exc:error={'type':type(exc).__name__,'message':str(exc),'detail':getattr(exc,'document_scan_detail',None)}
                else:raise AssertionError('Failure was hidden')
            seconds=time.monotonic()-start
            if mode!='cleanup_error':
                assert error['type']=='CaptureDeadlineExceeded',error
                assert 4.9<=seconds<7.0,seconds
            else:assert error['type']=='RuntimeError'
            assert page.evaluate('()=>42')==42,'Connection damaged by cancellation'
            assert not page.locator('[aria-roledescription^="browsergym_id_"]').count()
            assert page.evaluate("()=>Object.keys(globalThis).filter(k=>k.startsWith('__intent_capture_')).length")==0
            # A fresh explicit read is possible; no browser action was replayed.
            human.capture()
            result={'error':error,'seconds':seconds,'connection_reusable':True,'cleanup_checked':True}
    finally:
        if human:human.close()
        if pipeline:pipeline.close()
        env.close()
    result.update(case=mode,passed=True,model_calls=0,trace=str(trace.directory))
    write_json(out/'report.json',result);return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True,type=Path);p.add_argument('--cases',nargs='+',choices=MODES,default=MODES);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    sources=[*Path('intent_browser').glob('*.py'),Path(__file__)];hashes=lambda:{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources};before=hashes()
    with ProcessPoolExecutor(max_workers=3,mp_context=multiprocessing.get_context('spawn')) as pool:
        results=list(pool.map(run_case,[(m,str(a.output/m)) for m in a.cases]))
    assert hashes()==before
    write_json(a.output/'report.json',{'passed':True,'cases':results,'source_sha256':before,'model_calls':0})
