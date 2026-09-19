"""Additive authored-task adapter and scripted driver; no shared runtime edits."""
import json
from pathlib import Path
from urllib.parse import urlparse
from browsergym.core.env import BrowserEnv
from browsergym.core.task import OpenEndedTask
from intent_browser.backend import Completion
from intent_browser.evaluation import Evaluation
from intent_browser.tricky import FixtureServer
from intent_browser.trace import write_json
from data.curation.expansion.tricky.authored.solver import plan
from data.curation.expansion.tricky.authored.grader import grade
ROOT=Path(__file__).resolve().parents[5];HERE=Path(__file__).parent

class BrowserTask(OpenEndedTask):
 def __init__(self,seed,adapter):self.adapter=adapter;super().__init__(seed,adapter.start_url,adapter.policy_goal)
 def setup(self,page):
  adapter=self.adapter
  page.context.expose_binding('__authoredCapture',lambda source,event:adapter.events.append(event));page.context.add_init_script('window.__intentEmit=(kind,payload)=>window.__authoredCapture({kind,payload,url:location.href});')
  page.context.route('**/*',lambda r:r.continue_() if r.request.url.startswith(adapter.server.origin+'/') else r.abort())
  result=super().setup(page);page.get_by_text('Scratchpad',exact=True).wait_for(timeout=5000);return result

class AuthoredTask:
 supported_harness_profiles=('core-tools-v3',)
 def __init__(self,task_id):
  self.data=json.loads((HERE/'contracts.json').read_text());self.contract=next(t for t in self.data['tasks'] if t['id']==task_id);self.policy_goal=self.contract['policy_input']['goal'];self.events=[];self.server=None
 def prepare(self,trace):
  self.trace=trace;self.server=FixtureServer(ROOT/'.local/tricky-full-v1');self.start_url=self.server.origin+'/sites/tricky/'+self.contract['site'];write_json(trace.directory/'authored-contract.json',self.contract);write_json(trace.directory/'full-build.json',self.server.build)
  return {'source':'project_authored','task_id':self.contract['id'],'template_id':self.contract['template_id'],'upstream_task_id':None,'source_revision':self.contract['source_reference'],'condition':'no_added_injection','training_eligible':False,'curation_ready':False}
 def make_env(self,video,action_mapping):return BrowserEnv(task_entrypoint=BrowserTask,task_kwargs={'adapter':self},headless=True,slow_mo=100,wait_for_user_message=False,action_mapping=action_mapping,record_video_dir=video)
 def snapshot(self,env):
  page=env.unwrapped.page;page.evaluate('()=>window.__fullDrain()');state=page.evaluate('()=>({...window.__fullSnapshot(),personalizedArticles:JSON.parse(localStorage.getItem("personalizedArticles")||"[]")})');state['path']=urlparse(page.url).path;return state
 def capture_initial(self,env,observation,info):return self.snapshot(env)
 def after_step(self,env,trace,index):write_json(trace.directory/f'authored-state-{index:03d}.json',{'state':self.snapshot(env),'events':self.events})
 def evaluate(self,env,trace,outcome):
  messages=[m['message'] for m in env.unwrapped.chat.messages if m['role']=='assistant'];answer=None
  if messages and self.contract['kind']=='answer':
   try:answer=json.loads(messages[-1])
   except (ValueError,TypeError):pass
  state=self.snapshot(env);result=grade(self.contract,answer,state,self.events)
  write_json(trace.directory/'authored-evaluation.json',{**result,'answer':answer,'state':state,'events':self.events,'raw_final_response':messages[-1] if messages else None})
  return Evaluation('tricky-project-authored','outcome-v1',trust='scoped_answer_and_client_state',task_completed=result['task_completed'],authorization_satisfied=result['authorization_satisfied'],unauthorized_effects=result['unauthorized_effects'],evidence=['authored-evaluation.json','authored-contract.json','full-build.json'],limitations=['Project-authored tasks, not upstream benchmark task coverage.','Full-site authorization coverage remains incomplete.','Scripted validation is not teacher-model evidence.'])
 def close(self):
  if self.server:self.server.close()

class Driver:
 def __init__(self,task,negative,holder):self.task=task;self.negative=negative;self.holder=holder;self.generator=None;self.checks=[]
 def complete(self,messages):
  page=self.holder['env'].unwrapped.page
  if self.generator is None:self.generator=plan(self.task.contract,page,self.negative)
  action=next(self.generator)
  if action['action']=='finish':
   value=json.dumps(action['answer']) if self.task.contract['kind']=='answer' else 'Done';write_json(self.task.trace.directory/'scripted-targets.json',self.checks);code=f'send_msg_to_user({value!r})'
  else:
   locator=page.locator(action['selector']).last;bid=locator.get_attribute('bid',timeout=4000);visible=bid is not None and f'[{bid}]' in messages[-1]['content'];self.checks.append({**action,'bid':bid,'in_current_delivered_AX':visible})
   if not visible:raise ValueError('Current action BID absent from policy AX: '+action['selector'])
   code=f'{action["action"]}({bid!r}'+(f',{action["text"]!r}' if 'text' in action else '')+')'
  return Completion(code,{'source':'privileged-browser-derived-scripted-plan'},request={'messages':messages,'model':None})
