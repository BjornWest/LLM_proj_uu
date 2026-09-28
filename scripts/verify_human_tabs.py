"""Actual BrowserGym + independent CDP human driver. Local fixtures; no inference/API calls."""
import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import multiprocessing
from pathlib import Path
import socket
import sys
from threading import Event,Thread
from unittest.mock import patch
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import httpx
from playwright.sync_api import sync_playwright, BrowserType
from browsergym.core.env import BrowserEnv
from browsergym.core.task import OpenEndedTask
from intent_browser.actions import make_action_set
from intent_browser.backend import ChatCompletionsBackend
from intent_browser.ax_explorer import AXConfig
from intent_browser.standard_profile import tokenizer_path
from intent_browser.harness import native_tools_profile
from intent_browser.open_internet import open_profile,with_human_handover
from intent_browser.human_handover import HumanHandoverController
from intent_browser.observation_pipeline import ObservationPipelineConfig
from intent_browser.runner import run_episode

CHALLENGE='''<!doctype html><title>Human challenge</title><h1>Awaiting human</h1>
<button id=verify onclick="document.querySelector('h1').textContent='Human verification finished';window.humanClicks++;window.open('/popup');">Human verify</button>
<button id=shared onclick="localStorage.setItem('update',Date.now());window.humanClicks++">Change shared data</button>
<script>window.humanClicks=0</script>'''
WORK='''<!doctype html><title>Agent workspace</title><h1>Agent workspace</h1>
<button id=save onclick="window.commits++;document.querySelector('#status').textContent='Saved'">Save</button>
<p id=status role=status></p><script>window.commits=0;
addEventListener('storage',()=>{document.querySelector('#save').textContent='Delete protected item'});</script>'''


def run_case(args):
    mode,out=args;out=Path(out);out.mkdir(parents=True,exist_ok=False)
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body=(WORK if self.path.startswith('/work') else '<h1>Human popup</h1>' if self.path.startswith('/popup') else CHALLENGE).encode()
            self.send_response(200);self.send_header('Content-Type','text/html');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        def log_message(self,*a):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}'
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));cdp_port=sock.getsockname()[1]
    controller=HumanHandoverController();held={};requests=[];human_errors=[];human_ready=Event();trigger=Event();human_done=Event();finish=Event();state={}
    profile=with_human_handover(open_profile(native_tools_profile(parallel_tool_calls=None,compact_feedback=True,
        ax_config=AXConfig(tokenizer_path(),incremental=True),batch_size=8)))
    class Task(OpenEndedTask):
        def setup(self,page):
            result=super().setup(page)
            work=page.context.new_page();work.goto(origin+'/work')
            page.evaluate("window.dispatchEvent(new Event('pageshow'))")
            held['human']=page;held['work']=work
            return result
    def factory(_):
        env=BrowserEnv(task_entrypoint=Task,task_kwargs={'start_url':origin+'/challenge','goal':'Yield the challenged tab, work elsewhere, and inspect returned state.'},
            headless=True,
            action_mapping=make_action_set(profile.tools.names).to_python_code)
        held['env']=env
        original_close=env.close
        def close():
            state['commits']=held['work'].evaluate('window.commits') if not held['work'].is_closed() else None
            state['humanClicks']=held['human'].evaluate('window.humanClicks') if not held['human'].is_closed() else None
            state['controller']=controller.snapshot();finish.set()
            return original_close()
        env.close=close
        return env
    def human():
        try:
            # Separate Playwright connection/thread, like an independent human
            # browser client. Never pass runner's Playwright objects across threads.
            with sync_playwright() as pw:
                remote=pw.chromium.connect_over_cdp(f'http://127.0.0.1:{cdp_port}')
                pages=remote.contexts[0].pages
                a=next(p for p in pages if p.url.endswith('/challenge'));b=next(p for p in pages if p.url.endswith('/work'))
                human_ready.set()
                if not trigger.wait(25):raise TimeoutError('No model overlap trigger')
                controller.signal('tab-1','start')
                a.bring_to_front()
                if mode=='concurrent':
                    a.locator('#verify').click();controller.signal('tab-1','complete')
                elif mode=='shared_change':a.locator('#shared').click()
                elif mode=='close_human':a.close()
                elif mode=='close_agent':b.close()
                elif mode=='reload_agent':b.reload()
                elif mode=='cancel':controller.signal('tab-1','cancel')
                elif mode=='owned_rejection':pass
                human_done.set()
                finish.wait(30)
                # Stopping this client connection does not close the shared browser.
        except Exception as exc:
            human_errors.append(f'{type(exc).__name__}: {exc}');human_ready.set();human_done.set()
    human_thread=None
    def transport(req):
        nonlocal human_thread
        request=json.loads(req.content);requests.append(request);n=len(requests)
        if n==1:
            human_thread=Thread(target=human,daemon=True);human_thread.start()
            assert human_ready.wait(15) and not human_errors,human_errors
            assert held['env'].page is held['human']
            selected=[('handover_tab',{'tab_id':'tab-1','reason':'Please handle the verification while I work in the other tab.'})]
        elif n==2:
            assert held['env'].page is held['work']
            bid=held['work'].locator('#save').get_attribute('bid')
            trigger.set();assert human_done.wait(15) and not human_errors,human_errors
            # Human actions above occurred AFTER this model request was recorded.
            selected=[('tab_focus',{'tab_id':'tab-1'})] if mode=='owned_rejection' else [('click',{'bid':bid})]
        elif n==3 and mode in ('concurrent','cancel'):
            selected=[('tab_focus',{'tab_id':'tab-1'})]
        else:selected=[('send_msg_to_user',{'text':'Finished local fixture inspection.'})]
        return httpx.Response(200,json={'choices':[{'finish_reason':'tool_calls','message':{'role':'assistant','content':None,
            'tool_calls':[{'id':f'{n}-{i}','type':'function','function':{'name':name,'arguments':json.dumps(value)}} for i,(name,value) in enumerate(selected)]}}]})
    backend=ChatCompletionsBackend('https://offline.invalid/v1','mock');backend.client.close();backend.client=httpx.Client(transport=httpx.MockTransport(transport));backend.requires_browser_thread=True
    original_launch=BrowserType.launch
    def launch(browser_type,**kwargs):
        kwargs['args']=[*kwargs.get('args',[]),f'--remote-debugging-port={cdp_port}']
        return original_launch(browser_type,**kwargs)
    try:
      with patch.object(BrowserType,'launch',launch):
        path,summary=run_episode(factory,backend,{'driver':'scripted_local_human_concurrency','model_calls':0},output=out/'runs',max_steps=4,
            harness_profile=profile,human_handover=controller,observation_pipeline=ObservationPipelineConfig((),full_capture_only=True))
    finally:
        finish.set()
        if human_thread:human_thread.join(timeout=10)
        backend.close();server.shutdown();server.server_close()
    rows=[json.loads(l) for l in (path/'steps.jsonl').read_text().splitlines()]
    assert not human_errors,human_errors
    assert summary['error'] is None,summary
    assert rows[0]['batch_calls'][0]['tool_output']['execution']=='call_completed'
    second=rows[1]['batch_calls'][0]
    if mode in ('shared_change','close_agent','reload_agent'):
        assert second['not_executed'],second
        assert not second['action_dispatch_started']
        assert state['commits'] in (0,None),state
    elif mode=='owned_rejection':
        assert 'human-owned' in second['tool_error'],second
        assert state['commits']==0,state
    else:
        assert second['browser_stepped'] and not second.get('action_error'),second
        assert state['commits']==1,state
    if mode in ('concurrent','cancel'):
        assert rows[2]['batch_calls'][0]['tool_output']['active_tab_id']=='tab-1'
        delivered=rows[3]['messages'][-1]['content']
        assert ('Human verification finished' if mode=='concurrent' else 'Awaiting human') in json.dumps(delivered)
        transitions=[json.loads(l) for l in (path/'events.jsonl').read_text().splitlines()]
        assert any(e['event']=='human_tab_return_observed' for e in transitions)
        if mode=='concurrent':
            assert 'Human verification finished' not in json.dumps(requests[2]['messages'])
            tabs=state['controller']['tabs']
            assert len(tabs)==3 and tabs[2]['state'] in ('awaiting_human','closed'),tabs
    assert all(r['model_request']['tools']==rows[0]['model_request']['tools'] for r in rows)
    result={'passed':True,'case':mode,'trace':str(path),'summary':summary,'state':state,'model_calls':0,
            'scope':'Independent native CDP human actions during scripted inference; no external page or model calls'}
    (out/'report.json').write_text(json.dumps(result,indent=2)+'\n');return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--cases',nargs='+',default=['concurrent','owned_rejection','shared_change','close_human','close_agent','reload_agent','cancel']);a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=False)
    sources=list((ROOT/'intent_browser').glob('*.py'))+[Path(__file__).resolve()]
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    with ProcessPoolExecutor(max_workers=3,mp_context=multiprocessing.get_context('spawn')) as pool:
        cases=list(pool.map(run_case,[(mode,str(a.output/mode)) for mode in a.cases]))
    assert hashes=={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    report={'passed':True,'cases':cases,'model_calls':0,'source_sha256':hashes,
        'artifacts_sha256':{str(p.relative_to(a.output)):hashlib.sha256(p.read_bytes()).hexdigest() for p in a.output.rglob('*') if p.is_file()}}
    (a.output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
