"""Local Chromium frame-detach reproduction and actual-runner batch guards; no API calls."""
import argparse
from concurrent.futures import ProcessPoolExecutor
from contextlib import ExitStack
import hashlib
import json
import multiprocessing
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import httpx
from playwright.sync_api import Frame, sync_playwright
from browsergym.core.env import BrowserEnv
from browsergym.core.task import OpenEndedTask
from intent_browser.actions import make_action_set
from intent_browser.backend import ChatCompletionsBackend
from intent_browser.ax_explorer import AXConfig
from intent_browser.standard_profile import tokenizer_path
from intent_browser.batching import document_signature, DocumentScanInvalidated
from intent_browser.harness import native_tools_profile
from intent_browser.observation_pipeline import ObservationPipelineConfig
from intent_browser.runner import run_episode

EXPR='() => [location.href, performance.timeOrigin]'
DETACH="""() => new Promise(resolve => {
 parent.setTimeout(() => parent.document.querySelector('iframe').remove(), 20);
})"""
ORIGIN='http://guard.invalid'
HTML='''<!doctype html><title>Guard fixture</title><h1>Main page</h1>
<button id=save onclick="window.commits++">Save</button>
<iframe srcdoc="<p>Transient frame</p>"></iframe><script>window.commits=0</script>'''


def run_case(args):
    mode,output=args;out=Path(output);out.mkdir(parents=True,exist_ok=False)
    native_evaluate=Frame.evaluate
    # First reproduce the original comprehension using a real disappearing frame.
    if mode=='original':
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True);page=browser.new_page();page.set_content(HTML)
            def detach(frame,expression,*a,**kw):
                return native_evaluate(frame,DETACH if frame is not page.main_frame and expression==EXPR else expression,*a,**kw)
            with patch.object(Frame,'evaluate',detach):
                try:
                    [(id(p),[(id(f),f.evaluate(EXPR)) for f in p.frames]) for p in page.context.pages]
                except Exception as exc: failure=f'{type(exc).__name__}: {exc}'
                else: raise AssertionError('Original guard did not fail')
            assert 'detached' in failure.lower()
            assert not page.is_closed() and page.locator('h1').inner_text()=='Main page'
            browser.close()
        result={'mode':mode,'passed':True,'original_error':failure,'active_page_remained_usable':True}
    else:
        holder={};requests=[];scans=0;armed=False;injected=[];actions=[];state={}
        when={'initial':1,'pre':2,'post':3,'closed':1}[mode]
        class Task(OpenEndedTask):
            def setup(self,page):
                page.route(ORIGIN+'/**',lambda r:r.fulfill(content_type='text/html',body=HTML))
                return super().setup(page)
        profile=native_tools_profile(parallel_tool_calls=None,batch_size=8,navigation_origins=(ORIGIN,),compact_feedback=True,
            ax_config=AXConfig(tokenizer_path(),incremental=True))
        def factory(_):
            env=BrowserEnv(task_entrypoint=Task,task_kwargs={'start_url':ORIGIN+'/', 'goal':'Local guard validation'},
                headless=True,action_mapping=make_action_set(profile.tools.names).to_python_code)
            holder['env']=env
            # Attach after pipeline's class-override gate during reset.
            original_reset=env.reset
            def reset(*a,**kw):
                result=original_reset(*a,**kw)
                pipeline_step=env.step
                def logged(action): actions.append(action);return pipeline_step(action)
                env.step=logged
                return result
            env.reset=reset
            original_close=env.close
            def close():
                if not env.page.is_closed():state['commits']=env.page.evaluate('window.commits')
                return original_close()
            env.close=close
            return env
        def transport(req):
            value=json.loads(req.content);requests.append(value);n=len(requests)
            if n==1:
                if mode=='post':
                    bid=holder['env'].page.locator('#save').get_attribute('bid')
                    selected=[('click',{'bid':bid}),('click',{'bid':bid})]
                else:selected=[('reload',{}),('noop',{})]
            elif n==2 and mode in ('initial','pre'):selected=[('reload',{})]
            else:selected=[('send_msg_to_user',{'text':'Done'})]
            return httpx.Response(200,json={'choices':[{'finish_reason':'tool_calls','message':{
                'role':'assistant','content':None,'tool_calls':[{'id':f'{n}-{i}','type':'function',
                'function':{'name':name,'arguments':json.dumps(arguments)}} for i,(name,arguments) in enumerate(selected)]}}]})
        def signature(env):
            nonlocal scans,armed
            scans+=1;armed=scans==when
            if armed and mode=='closed':env.page.close()
            try:return document_signature(env)
            finally:armed=False
        def evaluate(frame,expression,*a,**kw):
            if armed and expression==EXPR and frame is not holder['env'].page.main_frame:
                try:return native_evaluate(frame,DETACH,*a,**kw)
                except Exception as exc:
                    injected.append({'error':f'{type(exc).__name__}: {exc}', 'detached':frame.is_detached()})
                    raise
            return native_evaluate(frame,expression,*a,**kw)
        backend=ChatCompletionsBackend('https://offline.invalid/v1','mock');backend.client.close()
        backend.client=httpx.Client(transport=httpx.MockTransport(transport))
        try:
            with patch('intent_browser.batching.document_signature',signature),patch.object(Frame,'evaluate',evaluate):
                path,summary=run_episode(factory,backend,{'driver':'scripted_local_guard','model_calls':0},
                    output=out/'runs',max_steps=3,harness_profile=profile,
                    observation_pipeline=ObservationPipelineConfig((),full_capture_only=True))
        finally:backend.close()
        rows=[json.loads(l) for l in (path/'steps.jsonl').read_text().splitlines()]
        assert len(rows[0]['batch_calls'])==2
        if mode=='closed':
            assert summary['error'] and len(requests)==1 and not actions
            assert all(c['not_executed'] for c in rows[0]['batch_calls'])
        else:
            assert summary['error'] is None,summary
            assert len(injected)==1 and injected[0]['detached']
            assert rows[0]['batch_stop_reason']=='document_scan_invalidated'
            assert rows[0]['batch_calls'][1]['not_executed']
            if mode=='post':
                assert state['commits']==1 and len(requests)==2
                assert rows[0]['batch_calls'][0]['browser_stepped']
                assert sum(a.startswith('click(') for a in actions)==1
            else:
                assert all(c['not_executed'] for c in rows[0]['batch_calls'])
                assert len(requests)==3 and sum(a.startswith('reload(') for a in actions)==1
        events=[json.loads(l)['event'] for l in (path/'events.jsonl').read_text().splitlines()]
        assert events.index('evaluation_completed')<events.index('environment_close_started')
        result={'mode':mode,'passed':True,'trace':str(path),'injected':injected,'actions':actions,'state':state,
                'requests':len(requests),'summary':summary}
    (out/'report.json').write_text(json.dumps(result,indent=2)+'\n');return result

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    sources=[ROOT/p for p in ('intent_browser/batching.py','intent_browser/runner.py','scripts/verify_batch_frame_race.py')]
    before={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    with ProcessPoolExecutor(max_workers=3,mp_context=multiprocessing.get_context('spawn')) as pool:
        cases=list(pool.map(run_case,[(m,str(args.output/m)) for m in ('original','initial','pre','post','closed')]))
    assert before=={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    report={'passed':True,'model_calls':0,'cases':cases,'source_sha256':before,
            'artifacts_sha256':{str(p.relative_to(args.output)):hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in args.output.rglob('*') if p.is_file()}}
    (args.output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
