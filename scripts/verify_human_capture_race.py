"""Deterministic local Chromium capture races; no model or external website calls."""
import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
import multiprocessing
from pathlib import Path
import sys
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from browsergym.core.env import BrowserEnv
from browsergym.core.task import OpenEndedTask
from playwright.sync_api import Frame, Error as PlaywrightError
from intent_browser.actions import make_action_set
from intent_browser.batching import DocumentScanInvalidated
from intent_browser.human_browser import HumanBrowser
from intent_browser.native_capture import capture_native
from intent_browser.human_handover import HumanHandoverController
from intent_browser.observation_pipeline import ObservationPipeline, ObservationPipelineConfig
from intent_browser.trace import Trace, write_json

EXPR='() => [location.href, performance.timeOrigin]'
ORIGIN='http://capture.invalid'
HTML='''<!doctype html><title>Capture fixture</title><h1>Consent fixture</h1>
<button id=accept onclick="window.commits++;document.querySelector('h1').textContent='Accepted'">Accept</button>
<iframe srcdoc="<p>Initial child</p>"></iframe><script>window.commits=0</script>'''
MODES=('attach','detach','navigate','during_extraction','main_navigation','sustained','custody','closed','unrelated','runner_recover','runner_exhaustion','runner_postcapture','runner_deadline')


def run_case(args):
    mode,output,baseline=args
    if mode.startswith('runner_'):return run_runner_case(mode,output)
    out=Path(output);out.mkdir(parents=True,exist_ok=False)
    class Task(OpenEndedTask):
        def setup(self,page):
            page.route(ORIGIN+'/**',lambda r:r.fulfill(content_type='text/html',body=HTML))
            return super().setup(page)
    env=BrowserEnv(task_entrypoint=Task,task_kwargs={'start_url':ORIGIN+'/', 'goal':'Local consent fixture'},
        headless=True,action_mapping=make_action_set(('click',)).to_python_code)
    trace=Trace(out/'runs',{'driver':'local_scripted_capture_race','model_calls':0})
    pipeline=ObservationPipeline(env,ObservationPipelineConfig((),full_capture_only=True),trace)
    controller=HumanHandoverController();human=HumanBrowser(env,controller,trace,pipeline)
    injected=[];error=None;obs=None;native=Frame.evaluate;capture=capture_native;calls=0;captures=0;steps=[]
    try:
        env.reset();human.start();initial=human.capture();ticket=human.ticket(initial)
        # Commit a real action BEFORE injecting next-observation churn. Recovery
        # must never replay this action, even when capture ultimately fails.
        bid=env.page.locator('#accept').get_attribute('bid')
        action=f'click({bid!r})';env.step(action);steps.append(action)
        assert env.page.evaluate('window.commits')==1
        page=env.page
        def mutate():
            if mode=='detach':
                frame=next(f for f in page.frames if f is not page.main_frame)
                try:native(frame,"""() => new Promise(resolve => {
                    parent.setTimeout(()=>parent.document.querySelector('iframe').remove(),10);})""")
                except PlaywrightError:pass
            elif mode=='navigate':
                next(f for f in page.frames if f is not page.main_frame).goto(ORIGIN+'/child-new')
            elif mode=='main_navigation':page.goto(ORIGIN+'/new-document')
            elif mode=='custody':controller.handover(human.active,'Test handover during capture')
            elif mode=='closed':page.close()
            elif mode=='unrelated':raise PlaywrightError('Synthetic unrelated JavaScript exception')
            else:page.evaluate("()=>{const f=document.createElement('iframe');f.srcdoc='<p>New child</p>';document.body.append(f)}")
            injected.append(mode)
        def evaluate(frame,expression,*a,**kw):
            nonlocal calls
            if expression==EXPR and frame is page.main_frame:
                calls+=1
                value=native(frame,expression,*a,**kw)
                if mode!='during_extraction' and (not injected or mode=='sustained'):mutate()
                return value
            return native(frame,expression,*a,**kw)
        def extract(view,budget):
            nonlocal captures
            captures+=1
            result=capture(view,budget)
            if mode=='during_extraction' and not injected:mutate()
            return result
        with patch.object(Frame,'evaluate',evaluate),patch('intent_browser.human_browser.capture_native',extract):
            try:obs=human.capture()
            except Exception as exc:
                error={'type':type(exc).__name__,'message':str(exc),'detail':getattr(exc,'detail',None)}
        recoverable=mode in ('attach','detach','navigate','during_extraction','main_navigation')
        if recoverable and not baseline:
            assert error is None,error
            assert obs['human_tab_capture']['attempts']==2
            # Native full extraction includes the final child, rather than
            # omitting frames to make the guard pass.
            names=[n.get('name',{}).get('value','') for n in obs['axtree_object']['nodes']]
            if mode in ('attach','during_extraction'):assert 'New child' in names,names
            if mode=='main_navigation':
                assert human.guard(ticket)=='tab_document_changed'
                assert page.url==ORIGIN+'/new-document'
            else:assert page.evaluate('window.commits')==1
        else:
            assert error is not None,(mode,calls,captures)
            if mode in ('custody','closed','unrelated','runner_recover','runner_exhaustion','runner_postcapture','runner_deadline'):assert calls==1,(mode,calls)
            if mode=='sustained' and not baseline:
                assert error['detail']['attempts']==3,error
        if not page.is_closed() and mode!='main_navigation':assert page.evaluate('window.commits')==1
        result={'case':mode,'baseline':baseline,'passed':True,'error':error,'signature_main_reads':calls,
            'native_captures':captures,'injected':injected,'browser_actions':steps,
            'capture':obs.get('human_tab_capture') if obs else None,'model_calls':0}
    finally:
        human.close();pipeline.close();env.close()
    write_json(out/'report.json',result);return result


def run_runner_case(mode,output):
    import httpx
    from intent_browser.backend import ChatCompletionsBackend
    from intent_browser.ax_explorer import AXConfig
    from intent_browser.standard_profile import tokenizer_path
    from intent_browser.harness import native_tools_profile
    from intent_browser.open_internet import open_profile,with_human_handover
    from intent_browser.runner import run_episode
    out=Path(output);out.mkdir(parents=True,exist_ok=False)
    holder={};requests=[];actions=[];injections=[];final={};armed=False
    profile=with_human_handover(open_profile(native_tools_profile(parallel_tool_calls=None,compact_feedback=True,
        ax_config=AXConfig(tokenizer_path(),incremental=True),batch_size=8)))
    class Task(OpenEndedTask):
        def setup(self,page):
            page.route(ORIGIN+'/**',lambda r:r.fulfill(content_type='text/html',body=HTML))
            return super().setup(page)
    def factory(_):
        env=BrowserEnv(task_entrypoint=Task,task_kwargs={'start_url':ORIGIN+'/', 'goal':'Accept once, then report Done'},
            headless=True,action_mapping=make_action_set(profile.tools.names).to_python_code)
        holder['env']=env;reset=env.reset;close=env.close
        def traced_reset(*a,**kw):
            result=reset(*a,**kw);step=env.step
            def tracked(action):
                nonlocal armed
                if mode in ('runner_postcapture','runner_deadline') and action.startswith('click('):armed=True
                actions.append(action);return step(action)
            env.step=tracked
            return result
        def traced_close():final['commits']=env.page.evaluate('window.commits');return close()
        env.reset=traced_reset;env.close=traced_close
        return env
    def transport(req):
        requests.append(json.loads(req.content));n=len(requests)
        if n==1:name,args='click',{'bid':holder['env'].page.locator('#accept').get_attribute('bid')}
        else:name,args='send_msg_to_user',{'text':'Done'}
        return httpx.Response(200,json={'choices':[{'finish_reason':'tool_calls','message':{
            'role':'assistant','content':None,'tool_calls':[{'id':f'call-{n}','type':'function',
            'function':{'name':name,'arguments':json.dumps(args)}}]}}]})
    def before_observation():
        nonlocal armed
        armed=len(requests)==1 and mode not in ('runner_postcapture','runner_deadline')
        return {'driver':'local frame race, no pacing'}
    native=Frame.evaluate
    def evaluate(frame,expression,*a,**kw):
        if armed and mode=='runner_deadline' and expression==EXPR:
            return native(frame,'()=>new Promise(()=>{})')
        value=native(frame,expression,*a,**kw)
        if (armed and expression==EXPR and frame is holder['env'].page.main_frame
                and (not injections or mode in ('runner_exhaustion','runner_postcapture','runner_deadline'))):
            native(frame,"()=>{let f=document.createElement('iframe');f.srcdoc='<p>After consent</p>';document.body.append(f)}")
            injections.append('child_attached')
        return value
    backend=ChatCompletionsBackend('https://offline.invalid/v1','mock');backend.client.close()
    backend.client=httpx.Client(transport=httpx.MockTransport(transport));backend.requires_browser_thread=True
    try:
        with patch.object(Frame,'evaluate',evaluate):
            path,summary=run_episode(factory,backend,{'driver':'local_scripted_capture_race','model_calls':0},
                output=out/'runs',max_steps=3,harness_profile=profile,human_handover=HumanHandoverController(),
                observation_pipeline=ObservationPipelineConfig((),full_capture_only=True),before_observation=before_observation)
    finally:backend.close()
    rows=[json.loads(l) for l in (path/'steps.jsonl').read_text().splitlines()]
    events=[json.loads(l) for l in (path/'events.jsonl').read_text().splitlines()]
    assert final['commits']==1 and sum(a.startswith('click(') for a in actions)==1
    first=rows[0]['batch_calls'][0]
    if mode in ('runner_postcapture','runner_deadline'):
        assert not first['browser_stepped'] and first['action_dispatch_started']
        assert first['action_execution']['action_error']==''
        assert first['policy_feedback']['execution']=='action_completed_observation_unavailable'
        assert not first.get('not_executed')
    else:assert first['browser_stepped']
    assert not rows[0]['batch_calls'][0].get('action_error')
    if mode=='runner_deadline':
        assert len(requests)==1 and summary['error'].startswith('CaptureDeadlineExceeded:')
        assert not first.get('not_executed')
    elif mode=='runner_exhaustion':
        assert len(requests)==1 and len(injections)==3 and summary['error']
        assert rows[1]['model_request'] is None and rows[1]['failure_phase']=='observation_capture'
        detail=rows[1]['document_scan_detail']
        assert detail['reason']=='human_tab_capture_attempts_exhausted' and detail['attempts']==3
        assert next(e for e in events if e['event']=='decision_error')['document_scan_detail']==detail
    elif mode=='runner_postcapture':
        assert len(requests)==2 and len(injections)==3 and summary['error'] is None
        assert 'action_completed_observation_unavailable' in json.dumps(requests[1]['messages'])
    else:
        assert len(requests)==2 and len(injections)==1 and summary['error'] is None,summary
        assert any(e['event']=='human_tab_capture_recovered' for e in events)
        assert 'Accepted' in json.dumps(requests[1]['messages'])
        import gzip
        observed=json.loads(gzip.decompress((path/rows[1]['observation']['raw']).read_bytes()))
        assert 'After consent' in json.dumps(observed['axtree_object'])
        assert observed['human_tab_capture']['attempts']==2
    names=[e['event'] for e in events]
    assert names.index('evaluation_completed')<names.index('environment_close_started')
    result={'case':mode,'passed':True,'model_calls':0,'scripted_requests':len(requests),'actions':actions,
        'final':final,'injections':injections,'trace':str(path),'summary':summary}
    write_json(out/'report.json',result);return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--baseline',action='store_true');parser.add_argument('--cases',nargs='+',choices=MODES,default=MODES)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    sources=['intent_browser/human_browser.py','intent_browser/batching.py','intent_browser/runner.py',
        'intent_browser/observation_pipeline.py','intent_browser/native_capture.py','scripts/verify_human_capture_race.py']
    hashes=lambda:{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in sources}
    before=hashes()
    with ProcessPoolExecutor(max_workers=3,mp_context=multiprocessing.get_context('spawn')) as pool:
        results=list(pool.map(run_case,[(m,str(args.output/m),args.baseline) for m in args.cases]))
    assert hashes()==before,'Sources changed during validation'
    write_json(args.output/'report.json',{'passed':True,'cases':results,'source_sha256':before,'model_calls':0,
        'artifacts_sha256':{str(p.relative_to(args.output)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in args.output.rglob('*') if p.is_file()}})
