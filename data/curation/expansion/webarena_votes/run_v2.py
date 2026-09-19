"""Version2 scripted undo-label correction; isolated native vote diagnostics, with final independent HTML+DB evidence."""
import argparse,hashlib,json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[4];HERE=Path(__file__).parent;sys.path.insert(0,str(ROOT))
from data.curation.expansion.runtime_snapshot import activate,fingerprints
FROZEN=activate();assert FROZEN
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
def closure():
 ps=list(HERE.glob('*.py'))+list(HERE.glob('*source*.json'))+[HERE/'contracts.json',ROOT/'.local/webarena-verified/dataset.json',ROOT/'scripts/harness_suite_tasks.py',ROOT/'data/curation/expansion/webarena/browser_batch.py',ROOT/'data/curation/expansion/webarena/extra_driver.py',ROOT/'data/curation/expansion/webarena/inventory.py',ROOT/'data/curation/expansion/runtime_snapshot.py']+list((ROOT/'.local/webarena-verified/venv/lib').glob('python*/site-packages/webarena_verified/**/*.py'))
 return {**fingerprints(FROZEN,ROOT),**{str(p.relative_to(ROOT)):sha(p)for p in ps}}
BEFORE=closure()
from browsergym.core.env import BrowserEnv
from browsergym.core.task import OpenEndedTask
from intent_browser.actions import make_action_set
from intent_browser.harness import native_tools_profile
from intent_browser.runner import run_episode
from intent_browser.evaluation import Evaluation
from scripts.harness_suite_tasks import scripted_backend
from data.curation.expansion.webarena.browser_batch import Driver,HEADERS
from data.curation.expansion.webarena.extra_driver import ExtraDriver
from data.curation.expansion.webarena_votes.common import *
from data.curation.expansion.webarena_votes.grader import parse_votes,judge
assert closure()==BEFORE
CONTRACT=json.loads((HERE/'contracts.json').read_text())
def dump(p,v):Path(p).write_text(json.dumps(v,indent=2)+'\n')
class BrowserTask(OpenEndedTask):
 def __init__(self,seed,adapter):self.adapter=adapter;super().__init__(seed,ORIGIN,adapter.goal)
 def setup(self,page):page.context.route('**/*',lambda r:r.continue_() if r.request.url.startswith(ORIGIN+'/') else r.abort());return super().setup(page)
class VoteTask:
 supported_harness_profiles=('core-tools-v3',)
 def __init__(self,task,variant):self.task=task;self.variant=variant;self.goal=task['policy_input']['goal'];self.result=None
 def prepare(self,trace):self.trace=trace;dump(trace.directory/'contract.json',self.task);return {'source':'webarena-verified','source_task_id':self.task['source_task_id'],'source_revision':CONTRACT['source_revision'],'verifier':'derived_final_vote_plus_newest_agreement','training_eligible':False}
 def capture_initial(self,env,observation,info):
  d=db_state(self.task['grader_input']['target_id']);assert not d['vote'],'Task source target must start neutral'
  return {'db':d,'container':inspect(),'url':env.unwrapped.page.url}
 def evaluate(self,env,trace,outcome):
  evidence=None
  if self.variant!='missing-evidence':
   url=ORIGIN+'/f/'+self.task['scripted_navigation']['forum_label']+'/new';response=env.unwrapped.page.context.request.get(url,timeout=45000);html=response.text()
   (trace.directory/'privileged-final-forum.html').write_text(html)
   evidence={'requested_url':url,'response_url':response.url,'status':response.status,'forms':parse_votes(html),'db':db_state(self.task['grader_input']['target_id']),'html_sha256':sha(trace.directory/'privileged-final-forum.html'),'scope':'Independent authenticated GET plus readonly owned database query; before browser close; never policy-visible'}
  self.result=judge(evidence,self.task['grader_input']['target_id'],USER);dump(trace.directory/'vote-final-state.json',{'evidence':evidence,'result':self.result,'fault_injection':self.variant if self.variant=='missing-evidence' else None})
  return Evaluation('webarena-votes-derived','final-vote-v1',trust='scoped_authenticated_server_and_database',task_completed=self.result['task_completed'],authorization_satisfied=None,evidence=['vote-final-state.json','contract.json'],limitations=['Publication-time/UI-New disagreements hold original-task completion unknown.','Source-target vote state diagnostic is separate from task completion.','Native historical request grade remains separate.','Full side-effect authorization remains unknown.'])
class VoteDriver(Driver):
 def __init__(self,task,variant):super().__init__(task['source_task_id']);self.task=task;self.variant=variant;self.targets=[]
 def act(self,loc,op='click',value=None):
  code=super().act(loc,op,value);self.targets.append({'code':code,'bid':loc.get_attribute('bid'),'current_ax':self.text,'url':self.page.url});return code
 def finish(self,data=None):self.response={'task_type':'mutate','status':'SUCCESS','retrieved_data':None};return 'send_msg_to_user('+repr(json.dumps(self.response))+')'
 def steps(self):
  p=self.page;yield from ExtraDriver.forum(self,self.task['scripted_navigation']['forum_label'])
  yield self.act(p.get_by_role('button',name='Sort by: Hot',exact=True));yield self.act(p.get_by_role('link',name='New',exact=True))
  first=p.locator('.submission').first;form=first.locator('form[data-vote-route-value="submission_vote"]');self.record('browser_derived_newest',{'id':form.get_attribute('data-vote-id-value'),'title':first.locator('.submission__title').inner_text(),'body':first.inner_text()})
  if self.variant!='neutral':
   name='Downvote' if self.variant=='wrong' else 'Upvote';yield self.act(first.get_by_role('button',name=name,exact=True))
   if self.variant=='undo':yield self.act(first.get_by_role('button',name='Retract upvote',exact=True))
  yield self.finish()
 def complete(self,messages):
  from copy import deepcopy
  copy=deepcopy(messages);copy[-1]['content']=copy[-1]['content'].rsplit('CURRENT BROWSER OBSERVATION\n',1)[-1];return super().complete(copy)
def main():
 p=argparse.ArgumentParser();p.add_argument('--task',type=int,choices=range(404,409),required=True);p.add_argument('--variant',choices=['positive','wrong','undo','neutral','missing-evidence'],required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
 os.environ['LD_LIBRARY_PATH']=str(ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu')+':'+os.getenv('LD_LIBRARY_PATH','')
 before=closure();assert before==BEFORE;dump(a.output/'source-before.json',before);owned=inspect();task=next(t for t in CONTRACT['tasks']if t['source_task_id']==a.task);driver=VoteDriver(task,a.variant);adapter=VoteTask(task,a.variant);backend=scripted_backend(driver);profile=native_tools_profile(parallel_tool_calls=None,compact_feedback=True,reasoning_replay='preserve');assert profile.name=='core-tools-v3';har=a.output/'network.har'
 def factory(video):
  env=BrowserEnv(task_entrypoint=BrowserTask,task_kwargs={'adapter':adapter},headless=True,slow_mo=0,timeout=10000,pre_observation_delay=1,action_mapping=make_action_set().to_python_code,wait_for_user_message=False,pw_context_kwargs={'extra_http_headers':HEADERS['reddit'],'record_har_path':str(har.resolve()),'record_har_content':'embed','service_workers':'block'});driver.env=env;return env
 try:trace,summary=run_episode(factory,backend,{'task':'webarena-votes-derived','source_task_id':a.task,'goal':adapter.goal,'variant':a.variant,'model':None,'model_calls':0,'training_eligible':False,'slow_mo_ms':0},output=a.output/'traces',max_steps=40,episode_task=adapter,harness_profile=profile,before_observation=lambda:None,observation_text_limit=48000,terminal_response_instruction='When finished, call send_msg_to_user with a JSON object containing task_type="mutate", status="SUCCESS" or an applicable failure status, and retrieved_data=null.')
 finally:backend.client.close()
 dump(trace/'scripted-targets.json',driver.targets);dump(trace/'driver-evidence.json',driver.evidence);dump(a.output/'response.json',driver.response)
 subprocess.run([str(ROOT/'.local/webarena-verified/venv/bin/python'),str(HERE/'grade_native.py'),str(har),str(a.output/'response.json'),str(a.output/'native-grade.json'),str(a.task)],check=True,timeout=45)
 native=json.loads((a.output/'native-grade.json').read_text());expected_vote=None if a.variant=='missing-evidence' else a.variant=='positive';after=closure();dump(a.output/'source-after.json',after)
 gate=summary['error'] is None and summary['action_error_count']==0 and before==after and owned==inspect() and adapter.result['source_target_upvoted'] is expected_vote
 acceptance=gate and adapter.result.get('chronological_target_agreement') is True
 report={'schema':'webarena-vote-case-v1','task_id':a.task,'variant':a.variant,'diagnostic_passed':gate,'original_task_acceptance_candidate':acceptance,'trace':str(trace),'summary':summary,'derived_result':adapter.result,'native_grade':native,'source_unchanged':before==after,'source_sha256':before,'model_calls':0,'training_eligible':False,'authorization_satisfied':None,'profile':profile.describe(),'container':owned,'artifact_sha256':{str(f.relative_to(a.output)):sha(f)for f in a.output.rglob('*')if f.is_file()}}
 dump(a.output/'report.json',report);print(json.dumps({'task':a.task,'variant':a.variant,'diagnostic_passed':gate,'errors':summary['action_error_count'],'error':summary['error'],'result':adapter.result,'native_score':native['score']}));raise SystemExit(0 if gate else 1)
if __name__=='__main__':main()
