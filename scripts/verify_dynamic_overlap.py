"""Real runner/HTTP backend + offline browser fixtures, never paid inference."""
import argparse
from concurrent.futures import ProcessPoolExecutor
from contextlib import nullcontext
import gzip
import hashlib
import json
import multiprocessing
from pathlib import Path
import threading
import time
from unittest.mock import patch

import httpx
from browsergym.core.env import BrowserEnv
from browsergym.core.task import OpenEndedTask
from intent_browser.actions import make_action_set
from intent_browser.backend import ChatCompletionsBackend
from intent_browser.dynamic_preview import DynamicPreview
from intent_browser.observation_pipeline import ObservationPipelineConfig
from intent_browser.standard_profile import standard_profile
from intent_browser.open_internet import open_profile, with_human_handover
from intent_browser.human_handover import HumanHandoverController
from intent_browser.runner import run_episode

CASES=('preview_click','preview_bid_change','preview_replace','search','fast_model','click','document_change','custody','preview_change',
       'late_change','recover_preview','human_message','late_custody','capture_failure','http_error','transport_error','undeclared_backend','disabled')

def case(args):
    mode,directory,windows,products=args
    out=Path(directory);out.mkdir(parents=True,exist_ok=False)
    owner=threading.get_ident();request_started=threading.Event();held={};requests=[];threads=[];effects=[]
    controller=HumanHandoverController()
    profile=with_human_handover(open_profile(standard_profile(helpers=False)),stable_frames=True,
        compact_tabs=True,capture_timeout_mode='diagnostic')
    class Fixture(OpenEndedTask):
        def setup(self,page):
            page.expose_function('recordCommit',lambda:effects.append('commit'))
            rows=''.join(f'<article><h2>Product {i}</h2><p>Stock: {i%5}</p></article>' for i in range(products))
            def route(r):
                body=('<h1 id="title">Storefront</h1><button onclick="recordCommit()">Commit</button><main>'+rows+'</main>'+
                      ''.join(f'<iframe src="http://child{i}.invalid/child"></iframe>' for i in range(3)))
                r.fulfill(content_type='text/html',body=body if r.request.url.endswith('/main') else '<h2>Child</h2><button>Child control</button>')
            page.route('**/*',route)
            return super().setup(page)
    def factory(_):
        env=BrowserEnv(task_entrypoint=Fixture,task_kwargs={'start_url':'http://fixture.invalid/main',
            'goal':'Find Commit, then click it once.'},headless=True,
            action_mapping=make_action_set(profile.tools.names).to_python_code)
        held['env']=env;return env
    def response(req):
        threads.append(threading.get_ident());request=json.loads(req.content);requests.append(request)
        request_started.set()
        time.sleep(.005 if mode=='fast_model' else .15)
        if mode=='http_error':return httpx.Response(503,json={'error':{'message':'Synthetic unavailable'}})
        if mode=='transport_error':raise httpx.ReadTimeout('Synthetic timeout',request=req)
        chosen=('ax_search',{'query':'Commit'})
        if (len(requests)>1 and mode in ('click','late_change')) or mode in ('preview_click','preview_bid_change','preview_replace'):
            # The mock server reads only exact messages, never the live browser.
            def walk(value):
                if isinstance(value,dict):
                    if value.get('name')=='Commit' and value.get('bid'):yield value['bid']
                    for v in value.values():yield from walk(v)
                elif isinstance(value,list):
                    for v in value:yield from walk(v)
            bids=[]
            for message in request['messages']:
                if message['role']==('user' if mode.startswith('preview_') else 'tool'):
                    try:
                        for line in message['content'].splitlines():
                            if line.startswith('{'):bids.extend(walk(json.loads(line)))
                    except (TypeError,ValueError):pass
            if not bids:raise AssertionError('No Commit BID delivered in tool messages')
            chosen=('click',{'bid':bids[-1]})
        return httpx.Response(200,json={'choices':[{'finish_reason':'tool_calls','message':{'role':'assistant','content':None,
            'tool_calls':[{'id':f'call-{len(requests)}','type':'function','function':{'name':chosen[0],'arguments':json.dumps(chosen[1])}}]}}],
            'usage':{'prompt_tokens':100,'completion_tokens':10,'cost':0}})
    class Undeclared(ChatCompletionsBackend):supports_native_tools=True
    cls=Undeclared if mode=='undeclared_backend' else ChatCompletionsBackend
    backend=cls('https://offline.invalid/v1','scripted',supports_images=True)
    backend.client.close();backend.client=httpx.Client(transport=httpx.MockTransport(response))
    original=DynamicPreview.capture; original_preview=DynamicPreview.preview
    def preview(self,previous):
        request_started.clear()
        return original_preview(self,previous)
    def capture(self):
        assert threading.get_ident()==owner
        assert request_started.wait(10),'No overlapping HTTP dispatch'
        if mode=='capture_failure':raise RuntimeError('Synthetic capture failure')
        if mode=='preview_bid_change':held['env'].page.locator('button').first.evaluate("e=>e.setAttribute('bid','999999')")
        if mode=='preview_replace':held['env'].page.locator('button').first.evaluate("e=>e.outerHTML=e.outerHTML")
        if mode=='document_change':held['env'].page.reload()
        if mode=='custody':controller.handover(self.human.active,'Scripted custody boundary')
        if mode=='preview_change' or (mode=='recover_preview' and len(requests)==1):held['env'].page.locator('#title').evaluate("e=>e.textContent='Changed before capture'")
        result=original(self)
        if mode=='human_message':held['env'].chat._js_user_message_received_callback(msg='Stop and inspect first')
        if mode=='late_custody':controller.handover(self.human.active,'Late custody change')
        if mode=='late_change' and len(requests)==2:held['env'].page.locator('#title').evaluate("e=>e.textContent='Changed after capture'")
        return result
    launcher=nullcontext();chrome=None
    if windows:
        from intent_browser.windows_browser import WindowsChrome
        from socket import socket
        with socket() as s:s.bind(('',0));port=s.getsockname()[1]
        chrome=WindowsChrome(out/'windows',port=port,headless=True)
        launcher=chrome.bind_environment()
    try:
        with launcher,patch.object(DynamicPreview,'capture',capture),patch.object(DynamicPreview,'preview',preview):
            path,summary=run_episode(factory,backend,{'driver':'dynamic_overlap_regression','paid_model_calls':0,'tags':['scripted']},
                output=out/'runs',allow_ungraded=True,
                ungraded_reason='model-free browser capture regression; no task outcome is graded',max_steps=2 if mode in ('click','late_change','recover_preview') else 1,harness_profile=profile,
                human_handover=controller,observation_pipeline=ObservationPipelineConfig((),full_capture_only=True,
                    dynamic_preview=mode!='disabled',shallow_depth=2))
    finally:
        backend.close()
        if chrome is not None:chrome.close()
    rows=[json.loads(s) for s in (path/'steps.jsonl').read_text().splitlines()]
    events=[json.loads(s) for s in (path/'events.jsonl').read_text().splitlines()]
    rejected=mode in ('preview_bid_change','preview_replace','document_change','custody','preview_change','late_custody')
    failed=mode in ('capture_failure','http_error','transport_error')
    assert (summary['error'] is not None)==failed,summary
    assert len(rows)==len(requests)
    for row,request in zip(rows,requests):
        assert row['model_request']==request
        if mode!='transport_error':assert row['model_response'] is not None
        overlap=row['observation_pipeline']['overlapped']
        assert overlap==(mode not in ('undeclared_backend','disabled')),(mode,row)
        assert (threads[rows.index(row)]!=owner)==overlap
        if overlap:
            raw=json.loads(gzip.decompress((path/row['observation']['raw']).read_bytes()))
            assert raw['observation_capture']['coverage']=='partial'
            assert raw['dom_object'] is None and row['observation']['screenshot'] is None
            assert raw['observation_capture']['version']=='dynamic-main-preview-v2'
            if mode.startswith('preview_'):
                assert any(n.get('browsergym_id') for n in raw['axtree_object']['nodes'])
            if not failed:assert all(i['confirmed'] for i in row['policy_delivery']['items'])
        if rejected or mode=='recover_preview' and row['step']==0:
            assert row['batch_stop_reason']=='background_preview_invalidated',row
            assert all(not c['action_dispatch_started'] for c in row['batch_calls'])
    if mode=='recover_preview':assert rows[1]['batch_calls'][0]['action_dispatch_started']
    if mode=='human_message':assert rows[0]['batch_stop_reason']=='human_message_pending'
    assert effects==(['commit'] if mode in ('click','preview_click') else []),effects
    if mode=='late_change':
        assert rows[-1]['batch_stop_reason']=='tab_content_changed_since_decision',rows[-1]
    if mode in ('preview_click','search','fast_model','click','undeclared_backend','disabled'):
        assert rows[0]['batch_calls'][0]['action_dispatch_started']
        assert not rows[0]['batch_calls'][0].get('tool_error')
    assert next(i for i,e in enumerate(events) if e['event']=='evaluation_completed')<next(i for i,e in enumerate(events) if e['event']=='environment_close_started')
    report={'passed':True,'case':mode,'trace':str(path),'windows':windows,'products':products,
        'requests':len(requests),'paid_model_calls':0,'effects':effects,'error':summary['error'],
        'pipeline':[r['observation_pipeline'] for r in rows],
        'decision_capture_seconds':[r['observation_capture_seconds'] for r in rows]}
    (out/'report.json').write_text(json.dumps(report,indent=2));return report

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--case',choices=CASES)
    p.add_argument('--windows',action='store_true');p.add_argument('--products',type=int,default=100)
    args=p.parse_args();out=Path(args.output);out.mkdir(parents=True,exist_ok=False)
    files=list(Path('intent_browser').glob('*.py'))+[Path(__file__)]
    hashes=lambda:{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    before=hashes();cases=[args.case] if args.case else CASES
    with ProcessPoolExecutor(max_workers=1 if args.windows else 2,mp_context=multiprocessing.get_context('spawn')) as pool:
        reports=list(pool.map(case,[(c,str(out/c),args.windows,args.products) for c in cases]))
    assert hashes()==before
    report={'passed':True,'cases':reports,'source_sha256':before,'paid_model_calls':0}
    (out/'report.json').write_text(json.dumps(report,indent=2));print(json.dumps({'passed':True,'cases':[r['case'] for r in reports],'paid_model_calls':0}))

if __name__=='__main__':main()
