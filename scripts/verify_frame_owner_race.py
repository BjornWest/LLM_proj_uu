"""Offline post-action owner races. Real browser, scripted HTTP, no action replay.

The exact adoption diagnostic is injected after a REAL root navigation; detach
and browser-close cases use the actual Playwright errors. This is controlled
race acceptance, not a claim of naturally reproducing Amazon's precise timing.
"""
import argparse
import asyncio
from concurrent.futures import ProcessPoolExecutor
from contextlib import nullcontext
import hashlib
import json
import multiprocessing
from pathlib import Path
from unittest.mock import patch
import httpx
from playwright.async_api import Frame as AsyncFrame, Page as AsyncPage, Browser as AsyncBrowser
from playwright.sync_api import Error as PlaywrightError
from browsergym.core.env import BrowserEnv
from browsergym.core.task import OpenEndedTask
from intent_browser.actions import make_action_set
from intent_browser.backend import ChatCompletionsBackend
from intent_browser.human_handover import HumanHandoverController
from intent_browser.observation_pipeline import ObservationPipelineConfig
from intent_browser.open_internet import open_profile,with_human_handover
from intent_browser.standard_profile import standard_profile
from intent_browser.runner import run_episode

CASES=('baseline_adoption','root_adoption','detach','closed_transport','persistent_adoption','cleanup_failure','normal')
ADOPTION='Frame.frame_element: Unable to adopt element handle from a different document'

def case(args):
    mode,directory,windows=args;out=Path(directory);out.mkdir(parents=True,exist_ok=False)
    state={'commits':0,'injections':0};held={};requests=[]
    profile=with_human_handover(open_profile(standard_profile(helpers=False)),stable_frames=True,
                              compact_tabs=True,capture_timeout_mode='diagnostic')
    class Task(OpenEndedTask):
        def setup(self,page):
            def commit():state['commits']+=1
            page.expose_function('recordCommit',commit)
            def route(r):
                if r.request.url.endswith('/after'):body='<h1>New document after commit</h1><p>Captured destination</p>'
                elif r.request.url.endswith('/child'):body='<p>Child text</p>'
                else:body='<h1>Original document</h1><button onclick="recordCommit()">Apply</button>'+''.join(f'<iframe src="http://child{i}.invalid/child"></iframe>' for i in range(4))
                r.fulfill(content_type='text/html',body=body)
            page.route('**/*',route)
            return super().setup(page)
    def factory(_):
        env=BrowserEnv(task_entrypoint=Task,task_kwargs={'start_url':'http://owner.invalid/main','goal':'Click Apply once then finish.'},
            headless=True,action_mapping=make_action_set(profile.tools.names).to_python_code)
        held['env']=env;return env
    def respond(req):
        requests.append(json.loads(req.content))
        if len(requests)==1:
            name,args='click',{'bid':held['env'].page.get_by_role('button',name='Apply').get_attribute('bid')}
        else:name,args='send_msg_to_user',{'text':'Done'}
        return httpx.Response(200,json={'choices':[{'finish_reason':'tool_calls','message':{'role':'assistant','content':None,
            'tool_calls':[{'id':f'call-{len(requests)}','type':'function','function':{'name':name,'arguments':json.dumps(args)}}]}}]})
    backend=ChatCompletionsBackend('https://offline.invalid/v1','scripted',supports_images=True)
    backend.client.close();backend.client=httpx.Client(transport=httpx.MockTransport(respond));backend.requires_browser_thread=True
    original=AsyncFrame.frame_element
    async def frame_element(frame,*a,**kw):
        if state['commits'] and mode!='normal' and (not state['injections'] or mode=='persistent_adoption'):
            state['injections']+=1
            if mode in ('baseline_adoption','root_adoption','cleanup_failure'):
                # Suspend one owner lookup while the actual main document changes.
                await AsyncPage(held['env'].page._impl_obj).goto('http://owner.invalid/after')
                raise PlaywrightError(ADOPTION)
            if mode=='detach':
                await AsyncPage(held['env'].page._impl_obj).evaluate("()=>document.querySelectorAll('iframe').forEach(f=>f.remove())")
            if mode=='closed_transport':
                await AsyncBrowser(held['env'].browser._impl_obj).close()
            if mode=='persistent_adoption':raise PlaywrightError(ADOPTION)
        return await original(frame,*a,**kw)
    chrome=None;launcher=nullcontext()
    if windows:
        from intent_browser.windows_browser import WindowsChrome
        from socket import socket
        with socket() as s:s.bind(('',0));port=s.getsockname()[1]
        chrome=WindowsChrome(out/'windows',port=port,headless=True);launcher=chrome.bind_environment()
    baseline=patch('intent_browser.native_capture.owner_lookup_invalidation',return_value=None) if mode=='baseline_adoption' else nullcontext()
    try:
        cleanup=patch('intent_browser.native_capture.CaptureBudget.cleanup_failed',return_value=False) if mode=='cleanup_failure' else nullcontext()
        with launcher,patch.object(AsyncFrame,'frame_element',frame_element),baseline,cleanup:
            path,summary=run_episode(factory,backend,{'driver':'frame_owner_race','paid_model_calls':0},output=out/'runs',
                max_steps=1 if mode=='persistent_adoption' else 2,harness_profile=profile,
                human_handover=HumanHandoverController(),observation_pipeline=ObservationPipelineConfig((),full_capture_only=True))
    finally:
        backend.close()
        if chrome:chrome.close()
    rows=[json.loads(s) for s in (path/'steps.jsonl').read_text().splitlines()]
    events=[json.loads(s) for s in (path/'events.jsonl').read_text().splitlines()]
    first=rows[0]['batch_calls'][0]
    assert state['commits']==1,state
    clicks=[e for e in events if e['event']=='tool_started' and e.get('tool')=='click']
    assert len(clicks)==1 and first['action_dispatch_started']
    invalid=[e for e in events if e['event']=='human_tab_capture_invalidated']
    if mode in ('root_adoption','detach','normal'):
        assert summary['error'] is None,summary
        assert first['browser_stepped'] and not first.get('action_error'),first
        assert len(requests)==2
        if mode!='normal':assert invalid
        if mode=='root_adoption':assert 'New document after commit' in json.dumps(requests[1]['messages'])
    else:
        assert not first['browser_stepped']
        assert first['action_execution']['action_error']==''
        assert first['policy_feedback']['execution']=='action_completed_observation_unavailable',first
        assert len(requests)==1
        if mode=='persistent_adoption':assert len(invalid)==3,invalid
        elif mode=='cleanup_failure':
            assert 'retry cleanup failed' in summary['error'] and len(invalid)==1,summary
        else:assert summary['error'] is not None and not invalid,summary
    assert next(i for i,e in enumerate(events) if e['event']=='evaluation_completed')<next(i for i,e in enumerate(events) if e['event']=='environment_close_started')
    result={'passed':True,'case':mode,'windows':windows,'trace':str(path),'state':state,
        'scripted_requests':len(requests),'paid_model_calls':0,'capture_invalidations':len(invalid),
        'action_feedback':first['policy_feedback'],'error':summary['error'],
        'scope':'Real navigation/detach/close; exact adoption message injected at suspended owner lookup'}
    (out/'report.json').write_text(json.dumps(result,indent=2));return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--cases',nargs='+',choices=CASES,default=CASES)
    p.add_argument('--windows',action='store_true');args=p.parse_args();out=Path(args.output);out.mkdir(parents=True,exist_ok=False)
    files=list(Path('intent_browser').glob('*.py'))+[Path(__file__)]
    hashes=lambda:{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    before=hashes()
    with ProcessPoolExecutor(max_workers=2,mp_context=multiprocessing.get_context('spawn')) as pool:
        results=list(pool.map(case,[(c,str(out/c),args.windows) for c in args.cases]))
    assert before==hashes(),'Sources changed during acceptance'
    report={'passed':True,'cases':results,'source_sha256':before,'paid_model_calls':0,
        'artifacts_sha256':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in out.rglob('*') if p.is_file()}}
    (out/'report.json').write_text(json.dumps(report,indent=2));print(json.dumps({'passed':True,'cases':len(results)}))
