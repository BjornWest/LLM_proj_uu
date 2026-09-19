"""Isolated tasks400–403 native scripted paths and explicitly derived final-read grading."""
import argparse,datetime,hashlib,json,os,subprocess,sys
from pathlib import Path
from urllib.parse import urlsplit
ROOT=Path(__file__).resolve().parents[4];HERE=Path(__file__).parent
sys.path.insert(0,str(ROOT))
from data.curation.expansion.runtime_snapshot import activate
FROZEN=activate()
assert FROZEN is not None,'Copied runtime required'
SOURCE=ROOT/'.local/webarena-verified/dataset.json'
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
def hashes():
 paths=list((FROZEN/'intent_browser').glob('*.py'))+[FROZEN/'manifest.json',SOURCE,ROOT/'data/curation/expansion/runtime_snapshot.py',ROOT/'data/curation/expansion/biography_outcome.py',ROOT/'data/curation/expansion/webarena/browser_batch.py',ROOT/'data/curation/expansion/webarena/inventory.py',ROOT/'scripts/harness_suite_tasks.py']+list(HERE.glob('*.py'))+[HERE/'contracts.json']
 paths+=list((ROOT/'.local/webarena-verified/venv/lib').glob('python*/site-packages/webarena_verified/**/*.py'))
 return {str(p.relative_to(ROOT)):sha(p)for p in paths}
BEFORE=hashes()
from browsergym.core.env import BrowserEnv
from browsergym.core.task import OpenEndedTask
from intent_browser.actions import make_action_set
from intent_browser.harness import native_tools_profile
from intent_browser.runner import run_episode
from intent_browser.evaluation import Evaluation
from scripts.harness_suite_tasks import scripted_backend
from data.curation.expansion.webarena.browser_batch import Driver,HEADERS
from data.curation.expansion.biography_outcome import check_biography
assert hashes()==BEFORE
ORIGIN='http://localhost:19089';CONTAINER='curation-webarena-biography-batch02';USERNAME='MarvelsGrantMan136'
CONTRACTS=json.loads((HERE/'contracts.json').read_text())

def dump(p,v):Path(p).write_text(json.dumps(v,indent=2)+'\n')
def inspect():
 d=json.loads(subprocess.check_output(['docker','inspect',CONTAINER]))[0]
 assert d['Config']['Labels'].get('intent.owner')=='curation-biography-batch02' and not d['Mounts']
 assert d['HostConfig']['PortBindings']['80/tcp']==[{'HostIp':'127.0.0.1','HostPort':'19089'}]
 return {k:d[k]for k in ('Id','Image','Created','Mounts')}

class TaskBrowser(OpenEndedTask):
 def __init__(self,seed,adapter):self.adapter=adapter;super().__init__(seed,ORIGIN,adapter.policy_goal)
 def setup(self,page):
  page.context.route('**/*',lambda r:r.continue_() if urlsplit(r.request.url).netloc=='localhost:19089' else r.abort())
  return super().setup(page)

class FinalReadTask:
 supported_harness_profiles=('core-tools-v3',)
 def __init__(self,task_id,variant):self.variant=variant;self.contract=next(t for t in CONTRACTS['tasks'] if t['source_task_id']==task_id);self.policy_goal=self.contract['policy_input']['goal'];self.requests=[];self.final_entry=None
 def prepare(self,trace):self.trace=trace;dump(trace.directory/'contract.json',self.contract);return {'source':'webarena-verified','source_task_id':self.contract['source_task_id'],'source_revision':CONTRACTS['source_revision'],'grader':'project_derived_final_server_profile','training_eligible':False}
 def capture_initial(self,env,observation,info):
  env.unwrapped.page.on('request',lambda r:self.requests.append({'request':{'method':r.method,'url':r.url},'response':{'status':0,'content':{}}}))
  return {'url':env.unwrapped.page.url,'container':inspect()}
 def evaluate(self,env,trace,outcome):
  if self.variant!='missing-final-read':
   # Independent privileged read, without page navigation or policy delivery.
   response=env.unwrapped.page.context.request.get(ORIGIN+'/user/'+USERNAME,timeout=20000)
   self.final_entry={'startedDateTime':datetime.datetime.now(datetime.timezone.utc).isoformat(),'request':{'method':'GET','url':ORIGIN+'/user/'+USERNAME},'response':{'status':response.status,'content':{'mimeType':response.headers.get('content-type',''),'text':response.text()}},'_provenance':'Independent APIRequestContext read after final policy action, before browser close'}
   dump(trace.directory/'privileged-final-profile-read.json',self.final_entry)
  evidence={'log':{'entries':self.requests+([self.final_entry] if self.final_entry else [])}}
  result=check_biography(evidence,origin=ORIGIN,username=USERNAME,expected=self.contract['grader_input']['expected_biography'])
  dump(trace.directory/'derived-final-evaluation.json',{'result':result,'request_order':self.requests,'final_read':self.final_entry,'fault_injection':'omit independent final read' if self.variant=='missing-final-read' else None})
  return Evaluation('project-derived-webarena-biography','final-server-read-v1',trust='scoped_server_rendered_profile',task_completed=result['task_completed'],authorization_satisfied=None,evidence=['derived-final-evaluation.json','contract.json'],limitations=['Original WebArena native grade remains separately retained.','Full account side-effect authorization is unknown.','Independent rendered server read, not a database snapshot.','Missing-final-read case deliberately omits privileged verification.'])

class BiographyDriver(Driver):
 def __init__(self,contract,variant):super().__init__(contract['source_task_id']);self.contract=contract;self.variant=variant;self.targets=[]
 def act(self,loc,op='click',value=None):
  result=super().act(loc,op,value);self.targets.append({'action':result,'bid':loc.get_attribute('bid'),'current_ax':self.text,'url':self.page.url});return result
 def finish(self,data=None):
  self.response={'task_type':'mutate','status':'SUCCESS','retrieved_data':None};return 'send_msg_to_user('+repr(json.dumps(self.response))+')'
 def steps(self):
  p=self.page
  yield self.act(p.get_by_role('button',name=USERNAME,exact=True))
  yield self.act(p.get_by_role('link',name='Profile',exact=True))
  values=['Wrong biography for negative validation'] if self.variant=='wrong' else [self.contract['grader_input']['expected_biography']]
  if self.variant=='correct-then-wrong':values.append('Wrong biography after initially correct save')
  for value in values:
   yield self.act(p.get_by_role('link',name='Edit biography',exact=True))
   yield self.act(p.locator('textarea'),'fill',value)
   yield self.act(p.get_by_role('button',name='Save',exact=True))
   yield self.act(p.get_by_role('link',name='/u/'+USERNAME,exact=True))
   self.record('saved_profile',{'biography':p.locator('.user-bio__biography').inner_text()})
  yield self.finish()
 def complete(self,messages):
  from copy import deepcopy
  copied=deepcopy(messages);copied[-1]['content']=copied[-1]['content'].rsplit('CURRENT BROWSER OBSERVATION\n',1)[-1]
  return super().complete(copied)

def main():
 p=argparse.ArgumentParser();p.add_argument('--task',type=int,choices=range(400,404),required=True);p.add_argument('--variant',required=True,choices=['positive','wrong','correct-then-wrong','missing-final-read']);p.add_argument('--output',required=True,type=Path);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
 os.environ['LD_LIBRARY_PATH']=str(ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu')+':'+os.getenv('LD_LIBRARY_PATH','')
 before=hashes();container=inspect();dump(a.output/'source-before.json',before)
 task=FinalReadTask(a.task,a.variant);driver=BiographyDriver(task.contract,a.variant);backend=scripted_backend(driver);profile=native_tools_profile(parallel_tool_calls=None,compact_feedback=True,reasoning_replay='preserve');assert profile.name=='core-tools-v3'
 har=a.output/'network.har'
 def factory(video):
  env=BrowserEnv(task_entrypoint=TaskBrowser,task_kwargs={'adapter':task},headless=True,slow_mo=0,timeout=10000,pre_observation_delay=1,action_mapping=make_action_set().to_python_code,wait_for_user_message=False,pw_context_kwargs={'extra_http_headers':HEADERS['reddit'],'record_har_path':str(har.resolve()),'record_har_content':'embed','service_workers':'block'});driver.env=env;return env
 try:
  trace,summary=run_episode(factory,backend,{'task':'webarena-biography-derived','source_task_id':a.task,'goal':task.policy_goal,'variant':a.variant,'model':None,'model_calls':0,'slow_mo_ms':0,'training_eligible':False},output=a.output/'traces',max_steps=24,episode_task=task,harness_profile=profile,before_observation=lambda:None,observation_text_limit=48000,terminal_response_instruction=task.contract['policy_input']['response_protocol'])
 finally:backend.client.close()
 dump(trace/'scripted-targets.json',driver.targets);dump(trace/'driver-evidence.json',driver.evidence)
 browserhar=json.loads(har.read_text());dump(a.output/'response.json',driver.response)
 subprocess.run([str(ROOT/'.local/webarena-verified/venv/bin/python'),str(HERE/'grade_native.py'),str(har),str(a.output/'response.json'),str(a.output/'native-grade.json'),str(a.task)],check=True,timeout=40)
 native=json.loads((a.output/'native-grade.json').read_text())
 # Independent retained full-HAR replay; missing-final-read is an explicit evidence gate.
 merged={'log':{'entries':browserhar['log']['entries']+([task.final_entry] if task.final_entry else [])}}
 replay=check_biography(merged,origin=ORIGIN,username=USERNAME,expected=task.contract['grader_input']['expected_biography']) if task.final_entry else {'task_completed':None,'reason':'Independent final server read absent'}
 expected={'positive':True,'wrong':False,'correct-then-wrong':False,'missing-final-read':None}[a.variant]
 passed=summary['error'] is None and summary['action_error_count']==0 and summary['evaluation']['task_completed'] is expected and replay['task_completed'] is expected and before==hashes() and inspect()==container
 report={'schema':'webarena-biography-batch02-case-v1','source_task_id':a.task,'variant':a.variant,'passed':passed,'expected_completion':expected,'trace':str(trace),'summary':summary,'native_grade':native,'full_har_plus_independent_read_replay':replay,'profile':profile.describe(),'model_calls':0,'authorization_satisfied':None,'training_eligible':False,'source_unchanged':before==hashes(),'source_sha256':before,'container':container,'artifact_sha256':{str(f.relative_to(a.output)):sha(f)for f in a.output.rglob('*')if f.is_file()}}
 dump(a.output/'report.json',report);print(json.dumps({'variant':a.variant,'passed':passed,'error':summary['error'],'native_score':native.get('score'),'derived_completed':summary['evaluation']['task_completed']}));raise SystemExit(0 if passed else 1)
if __name__=='__main__':main()
