"""Actual runner/BrowserGym pipeline acceptance; local scripted model transport."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import sys
import threading
from unittest.mock import patch
from contextlib import nullcontext
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import httpx
from browsergym.core.env import BrowserEnv
from browsergym.core.task import OpenEndedTask
from intent_browser.actions import make_action_set
from intent_browser.backend import ChatCompletionsBackend
from intent_browser.harness import native_tools_profile
from intent_browser.ax_explorer import AXConfig
from intent_browser.standard_profile import tokenizer_path
from intent_browser.vision import VisionConfig
from intent_browser.observation_pipeline import ObservationPipelineConfig, ObservationPipeline
from intent_browser.runner import run_episode
from intent_browser.trace import write_json

ORIGIN='http://pipeline.invalid'
HTML='''<!doctype html><title>Pipeline fixture</title><main><h1>Pipeline fixture</h1>
<label>Note <input id=note></label><label><input id=extra type=checkbox>Extra</label>
<a href=/next>Next page</a></main>'''


def public_objects(messages):
    def visit(value):
        if isinstance(value,dict):
            yield value
            for v in value.values():yield from visit(v)
        elif isinstance(value,list):
            for v in value:yield from visit(v)
    for message in messages:
        content=message.get('content')
        text=(content if isinstance(content,str) else '\n'.join(p.get('text','') for p in content or [] if p.get('type')=='text'))
        for match in re.finditer(r'\{',text):
            try:obj,_=json.JSONDecoder().raw_decode(text[match.start():])
            except ValueError:continue
            yield from visit(obj)


def run(out,*,scripted_site=False,screenshots=False,cards=0, fault=None):
    profile=native_tools_profile(parallel_tool_calls=None,compact_feedback=True,
        ax_config=AXConfig(tokenizer_path(),incremental=True),batch_size=8,vision_config=VisionConfig('retain'))
    requests=[];owners=[];held={};prior=[];note_ref=None
    owner=threading.get_ident()
    class Task(OpenEndedTask):
        def setup(self,page):
            def route(r):
                html=('<!doctype html><title>Next</title><main><h1>Finish</h1></main>' if '/next' in r.request.url else HTML)
                if cards and '/next' not in r.request.url:
                    html=html.replace('<a href=/next>Next page</a>','')
                    html+=''.join(f'<article><h2>Product {i}</h2><p>Details {i}</p><button>Inspect {i}</button></article>' for i in range(cards))
                    html+='<a href=/next>Next page</a>'
                r.fulfill(content_type='text/html',body=html,headers={} if scripted_site else
                    {'Content-Security-Policy':"default-src 'none'; style-src 'unsafe-inline'"})
            page.route(ORIGIN+'/**',route)
            return super().setup(page)
        def validate(self,page,messages):
            if page.url==ORIGIN+'/':prior.append((page.locator('#note').input_value(),page.locator('#extra').is_checked()))
            return super().validate(page,messages)
    def factory(_):
        env=BrowserEnv(task_entrypoint=Task,task_kwargs={'start_url':ORIGIN+'/',
            'goal':'Write a note, select Extra, inspect, and go to the next page.'},headless=True,
            action_mapping=make_action_set().to_python_code)
        held['env']=env;return env
    def transport(req):
        nonlocal note_ref
        request=json.loads(req.content);requests.append(request);owners.append(threading.get_ident())
        n=len(requests);time.sleep(.5 if n==1 else .03) # Simulated inference, no network.
        public=list(public_objects(request['messages']))
        def target(name):
            candidates=[v for v in public if str(v.get('name','')).strip()==name and v.get('bid') is not None]
            if not candidates:raise AssertionError(f'No delivered public target {name}')
            return candidates[-1]
        if n==1:calls=[('ax_search',{'query':['Note','Extra','Next page'],'limit':5})]
        elif n==2:
            note_ref=target('Note')['ref']
            calls=[('fill',{'bid':target('Note')['bid'],'value':'Kept value'}),('check',{'bid':target('Extra')['bid']})]
        elif n==3:calls=[('ax_read',{'node_ref':note_ref,'view':'node'})]
        elif n==4:calls=[('scroll_into_view',{'bid':target('Next page')['bid']}),('screenshot',{})]
        elif n==5:calls=[('click',{'bid':target('Next page')['bid']})]
        elif n==6:calls=[('ax_search',{'query':'Finish'})]
        else:calls=[('send_msg_to_user',{'text':'Done'})]
        return httpx.Response(200,json={'choices':[{'finish_reason':'tool_calls','message':{
            'role':'assistant','content':None,'tool_calls':[{'id':f'call-{n}-{i}','type':'function',
                'function':{'name':name,'arguments':json.dumps(args)}} for i,(name,args) in enumerate(calls)]}}],
            'usage':{'cost':0}})
    backend=ChatCompletionsBackend('https://offline.invalid/v1','scripted-pipeline',supports_images=True)
    backend.client.close();backend.client=httpx.Client(transport=httpx.MockTransport(transport))
    config=ObservationPipelineConfig((ORIGIN,),trace_screenshots=screenshots)
    original_prefetch=ObservationPipeline.prefetch
    def changed_prefetch(controller):
        if fault=='capture':raise RuntimeError('Scripted full capture failure')
        result=original_prefetch(controller)
        if fault=='stale':controller.page.locator('#note').fill('Changed during inference')
        return result
    started=time.monotonic()
    try:
        with (patch.object(ObservationPipeline,'prefetch',changed_prefetch) if fault else nullcontext()):
            path,summary=run_episode(factory,backend,{'task':'scripted-pipeline','paid_model_calls':0},
                output=out,max_steps=8,harness_profile=profile,observation_pipeline=config)
    finally:backend.close()
    elapsed=time.monotonic()-started
    write_json(out/'summary.json',summary)
    rows=[json.loads(line) for line in (path/'steps.jsonl').read_text().splitlines()]
    if fault:
        assert summary['error'] is not None
        assert summary['browser_step_count']==0
        assert rows[0]['model_response']['usage']['cost']==0
        assert rows[0]['model_request']==requests[0]
        assert rows[0]['failure_phase']=='background_observation'
        assert all(item['confirmed'] for item in rows[0]['policy_delivery']['items'])
        assert not rows[0].get('batch_calls')
        assert not hasattr(held['env'],'_intent_observation_pipeline')
        return {'passed':True,'fault':fault,'trace':str(path.resolve()),'model_calls':0,
                'seconds':elapsed,'error':summary['error']}
    assert summary['error'] is None,summary['error']
    assert summary['action_error_count']==0
    assert ('Kept value',True) in prior
    assert not any(c.get('tool_error') for row in rows for c in row.get('batch_calls',[]))
    assert rows[2]['batch_calls'][0]['tool_output'].get('error') is None
    assert 'Finish' in json.dumps(rows[5]['batch_calls'][0]['tool_output'])
    initial=json.loads(gzip.open(path/rows[0]['observation']['raw'],'rt').read())
    if not scripted_site:
        assert initial['observation_capture']['coverage']=='partial'
        assert initial['dom_object'] is None
        assert rows[0]['observation_pipeline']['overlapped']
        assert owners[0]!=owner
        assert list(path.glob('background-observation-*.json.gz'))
        if not screenshots:assert rows[0]['observation']['screenshot'] is None
    else:
        assert initial['observation_capture']['mode']=='native_fallback'
        assert not rows[0]['observation_pipeline']['overlapped']
        assert owners[0]==owner
    for row in rows:
        assert all(item['confirmed'] for item in row['policy_delivery']['items'])
    for row in rows:
        for call in row.get('batch_calls',[]):
            if call.get('browser_feedback_raw_artifact'):
                feedback=json.loads((path/call['browser_feedback_raw_artifact']).read_text())
                if feedback.get('scope','').startswith('Partial AX'):
                    assert 'removed_or_changed' not in feedback
    assert rows[3]['batch_calls'][0]['positioning']['status']=='in_viewport'
    visual=json.loads(next(path.glob('visual-readiness-*.json')).read_text())
    assert visual['screenshot_saved']
    events=[json.loads(line) for line in (path/'events.jsonl').read_text().splitlines()]
    names=[e['event'] for e in events]
    assert names.index('evaluation_completed')<names.index('environment_close_started')
    assert not hasattr(held['env'],'_intent_observation_pipeline')
    return {'passed':True,'trace':str(path.resolve()),'seconds':elapsed,'cards':cards,
        'scripted_site':scripted_site,'trace_screenshots':screenshots,'steps':len(rows),
        'model_calls':0,'threads':owners,'browser_owner':owner}


def run_generated(out):
    from environments.procedural_commerce.dense_preview import make_runtime
    runtime=make_runtime('large');before=runtime.snapshot();origin=runtime.origins['nordhem']
    product=origin+'/products/shoe-42-black';requests=[]
    profile=native_tools_profile(parallel_tool_calls=None,compact_feedback=True,
        navigation_origins=tuple(runtime.origins.values()),
        ax_config=AXConfig(tokenizer_path(),incremental=True),batch_size=8)
    def transport(req):
        request=json.loads(req.content);requests.append(request);n=len(requests)
        public=list(public_objects(request['messages']))
        def target(name,role):
            found=[v for v in public if str(v.get('name','')).strip()==name and v.get('role')==role and v.get('bid') is not None]
            if not found:raise AssertionError('Missing delivered public target '+name)
            return found[-1]['bid']
        if n==1:calls=[('ax_search',{'query':['Search the store','Search'],'limit':10})]
        elif n==2:calls=[('fill',{'bid':target('Search the store','searchbox'),'value':'shoe'}),('click',{'bid':target('Search','button')})]
        elif n==3:calls=[('goto',{'url':product})]
        elif n==4:calls=[('ax_search',{'query':['View 2','Add to cart'],'limit':10})]
        elif n==5:calls=[('click',{'bid':target('View 2','radio')}),('click',{'bid':target('Add to cart','button')})]
        elif n==6:calls=[('ax_search',{'query':'Go to cart'})]
        elif n==7:calls=[('click',{'bid':target('Go to cart','link')})]
        else:calls=[('send_msg_to_user',{'text':'Added one product and opened the cart.'})]
        return httpx.Response(200,json={'choices':[{'finish_reason':'tool_calls','message':{
            'role':'assistant','content':None,'tool_calls':[{'id':f'call-{n}-{i}','type':'function',
            'function':{'name':name,'arguments':json.dumps(args)}} for i,(name,args) in enumerate(calls)]}}], 'usage':{'cost':0}})
    backend=ChatCompletionsBackend('https://offline.invalid/v1','scripted-generated-world')
    backend.client.close();backend.client=httpx.Client(transport=httpx.MockTransport(transport))
    def factory(_):return BrowserEnv(task_entrypoint=OpenEndedTask,
        task_kwargs={'start_url':product,'goal':'Search for shoe, return to this product, inspect View 2, add one to cart and open the cart. Do not place an order.'},
        headless=True,action_mapping=make_action_set(profile.tools.names).to_python_code)
    try:
        path,summary=run_episode(factory,backend,{'task':'generated-storefront-scripted-pipeline'},output=out,
            max_steps=9,harness_profile=profile,observation_pipeline=ObservationPipelineConfig(tuple(runtime.origins.values()),trace_screenshots=False))
        after=runtime.snapshot();write_json(out/'world-before.json',before);write_json(out/'world-after.json',after)
        assert summary['error'] is None,summary['error']
        assert summary['action_error_count']==0
        assert after['carts']['nordhem']['quantity']==1 and not after['orders']
        assert all(after['carts'][s]==before['carts'][s] for s in runtime.retailer_ids if s!='nordhem')
        rows=[json.loads(line) for line in (path/'steps.jsonl').read_text().splitlines()]
        assert any(row['observation_pipeline']['overlapped'] for row in rows)
        assert not any(c.get('tool_error') for row in rows for c in row.get('batch_calls',[]))
        return {'passed':True,'trace':str(path.resolve()),'model_calls':0,'steps':len(rows),'cart_quantity':1,'orders':0}
    finally:backend.close();runtime.close()


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    p.add_argument('--case',choices=['static','recorded','fallback','dense','capture','stale','generated'],default='static');a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=False)
    paths=[*Path('intent_browser').glob('*.py'),*Path('environments/procedural_commerce').glob('*.py'),Path('intent_browser/observation_revision.js'),Path(__file__)]
    hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    result=run_generated(a.output) if a.case=='generated' else run(a.output,scripted_site=a.case=='fallback',screenshots=a.case=='recorded',cards=2000 if a.case=='dense' else 0,fault=a.case if a.case in ('capture','stale') else None)
    result['source_sha256']=hashes
    result['sources_unchanged']=hashes=={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    write_json(a.output/'report.json',result)
    assert result['sources_unchanged']

if __name__=='__main__':main()
