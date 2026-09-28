"""Local real-browser capture/guard regression; scripted HTTP and sandbox stub."""
import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
import multiprocessing
from pathlib import Path
from unittest.mock import patch
import httpx
from browsergym.core.env import BrowserEnv
from browsergym.core.task import OpenEndedTask
from intent_browser.actions import make_action_set
from intent_browser.backend import ChatCompletionsBackend
from intent_browser.data_tools import DataSession,DockerPython
from intent_browser.standard_profile import standard_profile
from intent_browser.open_internet import open_profile,with_human_handover
from intent_browser.human_handover import HumanHandoverController
from intent_browser.observation_pipeline import ObservationPipelineConfig
from intent_browser.runner import run_episode

CASES=('python','dataset','mixed_click','extract','document_replaced','human_owned')

def case(args):
 mode,directory=args;out=Path(directory);out.mkdir(parents=True,exist_ok=False)
 profile=with_human_handover(open_profile(standard_profile(helpers=False)),stable_frames=True,compact_tabs=True,capture_timeout_mode='diagnostic')
 controller=HumanHandoverController();held={};requests=[];calculations=[]
 class Fixture(OpenEndedTask):
  def setup(self,page):
   page.route('**/*',lambda r:r.fulfill(content_type='text/html',body=(
    '<h1>Numbers</h1><p>40</p><p>2</p><button onclick="document.querySelector(\'h1\').textContent=\'Clicked\'">Commit</button><iframe src="http://fixture.invalid/child"></iframe>'
    if r.request.url.endswith('/main') else '<h2>Child content</h2>')))
   return super().setup(page)
 def factory(_):
  env=BrowserEnv(task_entrypoint=Fixture,task_kwargs={'start_url':'http://fixture.invalid/main','goal':'Inspect and calculate.'},headless=True,action_mapping=make_action_set(profile.tools.names).to_python_code)
  held['env']=env;return env
 init=DataSession.__init__
 def initialize(self,*a,**kw):init(self,*a,**kw);held['data']=self
 def sandbox(self,code,datasets):
  calculations.append({'code':code,'datasets':list(datasets)})
  return {'execution':'completed','stdout':'42\n','stderr':'','exit_code':0}
 def response(req):
  requests.append(json.loads(req.content));page=held['env'].page
  calculate=('run_python',{'code':'print(40+2)','datasets':[]})
  extract=('extract_page',{'ref':held['data'].explorer.ref(0),'format':'tree'})
  if mode=='dataset':
   chosen=[extract,('run_python',{'code':'print(len(datasets["data1"]["nodes"]))','datasets':['data1']})]
  elif mode=='mixed_click':chosen=[calculate,('click',{'bid':page.get_by_role('button',name='Commit').get_attribute('bid')})]
  elif mode=='extract':chosen=[extract]
  else:chosen=[calculate]
  if mode=='document_replaced':page.reload()
  if mode=='human_owned':controller.handover(controller.snapshot()['tabs'][0]['tab_id'],'Scripted custody boundary')
  return httpx.Response(200,json={'choices':[{'finish_reason':'tool_calls','message':{'role':'assistant','content':None,'tool_calls':[
   {'id':f'call-{i}','type':'function','function':{'name':name,'arguments':json.dumps(args)}} for i,(name,args) in enumerate(chosen)]}}]})
 backend=ChatCompletionsBackend('https://offline.invalid/v1','scripted',supports_images=True);backend.client.close();backend.client=httpx.Client(transport=httpx.MockTransport(response));backend.requires_browser_thread=True
 try:
  with patch.object(DataSession,'__init__',initialize),patch.object(DockerPython,'run',sandbox):
   path,summary=run_episode(factory,backend,{'driver':'scripted_capture_regression','model_calls':0,'sandbox_stub':True},output=out/'runs',max_steps=1,harness_profile=profile,human_handover=controller,observation_pipeline=ObservationPipelineConfig((),full_capture_only=True))
 finally:backend.close()
 rows=[json.loads(s) for s in (path/'steps.jsonl').read_text().splitlines()];events=[json.loads(s) for s in (path/'events.jsonl').read_text().splitlines()]
 assert summary['error'] is None,summary
 assert len(rows)==len(requests)==1
 captures=[e for e in events if e['event']=='native_capture_completed']
 guards=[e for e in captures if e.get('observed_at',{}).get('phase')=='batch_guard']
 assert len(guards)==(1 if mode in ('extract','dataset','mixed_click') else 0),guards
 record=rows[0]['batch_calls'];blocked=mode in ('document_replaced','human_owned')
 assert len(calculations)==(0 if blocked or mode=='extract' else 1),calculations
 if blocked:
  assert record[0]['not_executed'] and not record[0]['action_dispatch_started']
  assert rows[0]['batch_stop_reason'] in ('tab_document_changed','tab_ownership_or_target_changed'),rows[0]['batch_stop_reason']
 else:
  assert all(not x.get('not_executed') and not x.get('action_error') and not x.get('tool_error') for x in record),record
  for r in record:
   if r['action'].startswith('run_python'):
    assert r['observation_reused'] and not r['browser_stepped']
 if mode=='dataset':assert calculations[0]['datasets']==['data1']
 if mode=='mixed_click':assert record[1]['browser_stepped']
 report={'passed':True,'case':mode,'trace':str(path),'capture_count':len(captures),'guard_capture_count':len(guards),'calculations':len(calculations),'stop_reason':rows[0]['batch_stop_reason'],'model_calls':0,'sandbox_stub':True}
 (out/'report.json').write_text(json.dumps(report,indent=2));return report

def main():
 p=argparse.ArgumentParser();p.add_argument('--output',required=True);args=p.parse_args();out=Path(args.output);out.mkdir(parents=True,exist_ok=False)
 paths=[Path('intent_browser/runner.py'),Path(__file__)]
 hashes=lambda:{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
 before=hashes()
 with ProcessPoolExecutor(max_workers=3,mp_context=multiprocessing.get_context('spawn')) as pool:
  results=list(pool.map(case,[(c,str(out/c)) for c in CASES]))
 assert before==hashes()
 (out/'report.json').write_text(json.dumps({'passed':True,'cases':results,'source_sha256':before,'model_calls':0},indent=2));print(json.dumps(results))

if __name__=='__main__':main()
