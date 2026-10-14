"""Generated-world fast-capture safety regressions in real Chromium (scripted, no provider).

Adapted from the Codex Astra review reproductions of a0d5d06 (findings 1-3).
Cases: control (click executes), cloned_bid (a clone copies a cached BID and
native marking renumbers the original), late_change (page changes after the
background capture, before the response), facts (page changes before the
background capture with fact recording on). Every non-control case must
invalidate the decision, execute nothing and leave decision facts unmapped.

Usage: verify_generated_fast_capture.py CASE OUTPUT_DIR
"""
import json, sys, threading
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
import httpx
from browsergym.core.env import BrowserEnv
from browsergym.core.task import OpenEndedTask
from intent_browser.actions import make_action_set
from intent_browser.backend import ChatCompletionsBackend
from intent_browser.standard_profile import standard_profile
from intent_browser.dynamic_preview import DynamicPreview
from intent_browser.runner import run_episode
from intent_browser.fact_provenance import digest
from intent_browser.evaluation import Evaluation

mode=sys.argv[1]
out=Path(sys.argv[2])
effects=[]; held={}; done=threading.Event(); request_data=[]
profile=standard_profile(helpers=False,data_tools=False)
task=NS(supports_agent_fast_capture=True,supports_observation_pipeline='native_full_only',
        supports_dynamic_preview=True,supports_targeted_observations=True,
        supported_harness_profiles=(profile.name,),prepare=lambda trace:{},
        capture_initial=lambda *a:{},evaluate=lambda *a:Evaluation('none','1',trust='explicitly_ungraded'))
class Fixture(OpenEndedTask):
    def setup(self,page):
        held['page']=page
        page.expose_function('recordEffect',lambda x:effects.append(x))
        page.route('**/*',lambda r:r.fulfill(content_type='text/html',body='''<main><h1 id=news>Price 10</h1><button id=commit onclick="recordEffect(this.id)">Commit</button></main>'''))
        return super().setup(page)
def factory(_):
    env=BrowserEnv(task_entrypoint=Fixture,task_kwargs={'start_url':'http://fixture.invalid/main','goal':'Click Commit only at price 10.'},headless=True,action_mapping=make_action_set(profile.tools.names).to_python_code)
    held['env']=env
    return env
def walk(value):
    if isinstance(value,dict):
        if value.get('name')=='Commit' and value.get('bid'):yield value['bid']
        for child in value.values():yield from walk(child)
    elif isinstance(value,list):
        for child in value:yield from walk(child)
def response(request):
    body=json.loads(request.content);request_data.append(body)
    bids=[]
    for m in body['messages']:
        if isinstance(m.get('content'),str):
            for line in m['content'].splitlines():
                try:bids.extend(walk(json.loads(line)))
                except ValueError:pass
    assert bids, body
    assert done.wait(10),'background did not finish'
    return httpx.Response(200,json={'choices':[{'finish_reason':'tool_calls','message':{'role':'assistant','content':None,'tool_calls':[{'id':'call-1','type':'function','function':{'name':'click','arguments':json.dumps({'bid':bids[-1]})}}]}}],'usage':{'cost':0}})
backend=ChatCompletionsBackend('https://offline.invalid/v1','scripted',supports_images=True)
backend.client.close();backend.client=httpx.Client(transport=httpx.MockTransport(response))
original=DynamicPreview.capture
def capture(self):
    if mode=='facts':
        held['page'].evaluate("document.querySelector('#news').textContent='Price 20'")
    result=original(self)
    if mode=='late_change':
        held['page'].evaluate("document.querySelector('#news').textContent='Price 20'")
    done.set()
    return result
def before():
    if mode=='cloned_bid':
        held['page'].evaluate("const e=document.querySelector('#commit');const clone=e.cloneNode(true);clone.id='decoy';clone.textContent='Decoy';e.before(clone)")
    return {'scripted':True}
class Provider:
    capture_boundary='review-synthetic-v1'
    def before_capture(self,page):
        self.state=page.locator('#news').inner_text()
    def after_capture(self,obs,frame):
        self.frame=frame
    def observe(self,operation):return operation()
    def __call__(self,env,obs,context):
        sources=[]
        for n in obs['axtree_object']['nodes']:
            if n.get('role',{}).get('value')=='button' and n.get('name',{}).get('value')=='Commit':
                sources.append({'id':'commit-source','text':'Commit','sha256':digest('Commit'),
                    'binding':{'snapshot_id':context['snapshot_id'],'document_id':'fixture-document','frame_id':self.frame,'node_id':n['nodeId'],'field':'name'},
                    'opaque_binding':{'state_id':self.state}})
        return {'schema':'ax-fact-sources-v1','sources':sources,'mapping_inventory_complete':False}
provider=Provider()
options=dict(record_fact_provenance=True,fact_source_provider=provider,fact_capture_observer=provider.observe) if mode=='facts' else {}
try:
    with patch.object(DynamicPreview,'capture',capture):
        path,summary=run_episode(factory,backend,{'tags':['scripted'],'review_case':mode},output=out,max_steps=1,
            harness_profile=profile,episode_task=task,before_observation=before,allow_ungraded=True,
            ungraded_reason='Model-free independent review reproduction; no task verdict.',**options)
finally:backend.close()
rows=[json.loads(x) for x in (path/'steps.jsonl').read_text().splitlines()]
result={'mode':mode,'path':str(path),'error':summary['error'],'effects':effects,
    'pipeline':rows[0].get('observation_pipeline'),'batch_stop':rows[0].get('batch_stop_reason'),
    'targeted_guard':rows[0].get('batch_calls',[{}])[0].get('targeted_guard')}
if mode=='facts':
    result['fact_policies']=[json.loads(p.read_text()) for p in path.glob('fact-policy-*.json')]
    result['fact_sources']=[s for p in path.glob('fact-capture-*.json') for s in json.loads(p.read_text())['sources']]
    result['fact_delivery']=[json.loads(x) for x in (path/'fact-delivery.jsonl').read_text().splitlines()]
(out/'result.json').write_text(json.dumps(result,indent=2))
pipeline=result['pipeline'] or {}
assert result['error'] is None,result['error']
if mode=='control':
    assert result['effects']==['commit'] and not pipeline.get('invalidated'),result
else:
    assert result['effects']==[] and pipeline.get('invalidated') is True,result
    assert result['batch_stop']=='background_preview_invalidated',result
if mode=='facts':
    assert all(not p['projections'] for p in result['fact_policies']),result['fact_policies']
print(json.dumps({'case':mode,'passed':True,'invalidated':bool(pipeline.get('invalidated')),
                  'effects':result['effects'],'background_error':pipeline.get('background_error')}))
