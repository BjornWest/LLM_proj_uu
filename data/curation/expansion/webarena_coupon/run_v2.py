"""Native scripted coupon drafts on the full shared shop, GET/HEAD-only."""
import argparse, hashlib, json, os, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[4]; HERE=Path(__file__).parent
sys.path.insert(0,str(ROOT))
from data.curation.expansion.runtime_snapshot import activate, fingerprints
FROZEN=activate(); assert FROZEN is not None
from browsergym.core.env import BrowserEnv
from intent_browser.actions import make_action_set
from intent_browser.evaluation import Evaluation
from intent_browser.harness import native_tools_profile
from intent_browser.runner import run_episode
from scripts.harness_suite_tasks import scripted_backend
from data.curation.expansion.webarena.browser_batch import Driver, ReadOnlyTask, HEADERS
from data.curation.expansion.webarena_coupon.grader_v2 import judge
CONTRACT=json.loads((HERE/'contracts-v2.json').read_text())
SOURCE=ROOT/'.local/webarena-verified/dataset.json'
ORIGIN='http://localhost:7770'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def dump(p,v):p.write_text(json.dumps(v,indent=2)+'\n')
def closure():
    paths=list(HERE.glob('*.py'))+[HERE/'contracts-v2.json',SOURCE,ROOT/'scripts/harness_suite_tasks.py',ROOT/'data/curation/expansion/webarena/browser_batch.py',ROOT/'data/curation/expansion/webarena/inventory.py',ROOT/'data/curation/expansion/runtime_snapshot.py']
    return {**fingerprints(FROZEN,ROOT),**{str(p.relative_to(ROOT)):sha(p) for p in paths}}

class DraftTask:
    supported_harness_profiles=('core-tools-v3',)
    def __init__(self,task,variant,blocked):self.task=task;self.variant=variant;self.blocked=blocked;self.requests=[]
    def prepare(self,trace):
        dump(trace.directory/'contract.json',self.task)
        return {'source_task_id':self.task['source_task_id'],'verifier':'project_derived_final_DOM','training_eligible':False}
    def capture_initial(self,env,observation,info):
        env.unwrapped.page.context.on('request',lambda r:self.requests.append({'url':r.url,'method':r.method}))
        return {'url':env.unwrapped.page.url,'request_scope':'browser events after reset plus blocked routes since setup'}
    def evaluate(self,env,trace,outcome):
        page=env.unwrapped.page; snapshot=None
        if self.variant!='missing-capture':
            form=page.locator('form#contact-form');present=form.count()==1 and form.is_visible()
            snapshot={'url':page.url,'present':present,'fields':form.evaluate("f=>({name:f.elements.namedItem('name').value,email:f.elements.namedItem('email').value,comment:f.elements.namedItem('comment').value})") if present else None}
        requests=self.requests+self.blocked; result=judge(snapshot,requests,self.task['grader_input']['reason'])
        dump(trace.directory/'draft-final-state.json',{'snapshot':snapshot,'requests':requests,'result':result,'capture_timing':'after policy completion before browser close','fault_injection':self.variant if self.variant=='missing-capture' else None})
        return Evaluation('webarena-coupon-derived','final-form-v2',trust='scoped_final_DOM',task_completed=result['task_completed'],authorization_satisfied=None,evidence=['draft-final-state.json','contract.json'],limitations=CONTRACT['limitations'])

class CouponDriver(Driver):
    def __init__(self,task,variant):super().__init__(int(task['source_task_id']));self.task=task;self.variant=variant;self.targets=[]
    def act(self,loc,op='click',value=None):
        result=super().act(loc,op,value);self.targets.append({'action':result,'bid':loc.get_attribute('bid'),'current_ax':self.text,'url':self.page.url});return result
    def finish(self,data=None):
        self.response={'task_type':'mutate','status':'SUCCESS','retrieved_data':None}
        return 'send_msg_to_user('+repr(json.dumps(self.response))+')'
    def steps(self):
        p=self.page
        yield self.act(p.get_by_role('link',name='Contact Us',exact=True))
        text='Wrong final draft' if self.variant=='wrong' else self.task['grader_input']['reason']
        yield self.act(p.locator('#comment'),'fill',text)
        if self.variant=='correct-then-wrong':yield self.act(p.locator('#comment'),'fill','Wrong final draft')
        if self.variant=='blank-name':yield self.act(p.locator('#name'),'fill','')
        if self.variant=='wrong-email':yield self.act(p.locator('#email'),'fill','someone-else@example.invalid')
        if self.variant=='abandon':yield self.act(p.locator('a.logo'))
        if self.variant=='blocked-submit':yield self.act(p.get_by_role('button',name='Submit',exact=True))
        yield self.finish()
    def complete(self,messages):
        from copy import deepcopy
        copied=deepcopy(messages);copied[-1]['content']=copied[-1]['content'].rsplit('CURRENT BROWSER OBSERVATION\n',1)[-1]
        return super().complete(copied)

def main():
    p=argparse.ArgumentParser();p.add_argument('--task',type=int,choices=range(689,694),required=True);p.add_argument('--variant',choices=['positive','wrong','correct-then-wrong','abandon','blocked-submit','missing-capture','blank-name','wrong-email'],required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    os.environ['LD_LIBRARY_PATH']=str(ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu')+':'+os.getenv('LD_LIBRARY_PATH','')
    task=next(t for t in CONTRACT['tasks'] if int(t['source_task_id'])==a.task)
    original=next(t for t in json.loads(SOURCE.read_text()) if t['task_id']==a.task)
    assert task['policy_input']['goal']==original['intent']
    before=closure();dump(a.output/'source-before.json',before)
    blocked=[];adapter=DraftTask(task,a.variant,blocked);driver=CouponDriver(task,a.variant);backend=scripted_backend(driver)
    profile=native_tools_profile(parallel_tool_calls=None,compact_feedback=True,reasoning_replay='preserve');assert profile.name=='core-tools-v3'
    har=a.output/'network.har'
    def factory(video):
        env=BrowserEnv(task_entrypoint=ReadOnlyTask,task_kwargs={'start_url':ORIGIN,'goal':task['policy_input']['goal'],'blocked':blocked},headless=True,slow_mo=0,timeout=10000,pre_observation_delay=1,action_mapping=make_action_set().to_python_code,wait_for_user_message=False,pw_context_kwargs={'extra_http_headers':HEADERS['shopping'],'record_har_path':str(har.resolve()),'record_har_content':'embed','service_workers':'block'});driver.env=env;return env
    try:
        trace,summary=run_episode(factory,backend,{'task':'webarena-coupon-derived','source_task_id':a.task,'goal':task['policy_input']['goal'],'variant':a.variant,'model':None,'model_calls':0,'slow_mo_ms':0,'training_eligible':False},output=a.output/'traces',max_steps=12,episode_task=adapter,harness_profile=profile,before_observation=lambda:None,observation_text_limit=48000,terminal_response_instruction='When finished, call send_msg_to_user with a JSON object containing task_type="mutate", status="SUCCESS" or an applicable failure status, and retrieved_data=null.')
    finally:backend.client.close()
    dump(trace/'scripted-targets.json',driver.targets)
    expected=True if a.variant=='positive' else None if a.variant=='missing-capture' else False
    after=closure();dump(a.output/'source-after.json',after)
    passed=summary['error'] is None and summary['action_error_count']==0 and summary['evaluation']['task_completed'] is expected and before==after
    report={'schema':'webarena-coupon-scripted-case-v2','task_id':str(a.task),'variant':a.variant,'passed':passed,'expected_completion':expected,'trace':str(trace),'summary':summary,'source_unchanged':before==after,'profile':profile.describe(),'model_calls':0,'training_eligible':False,'authorization_satisfied':None,'artifact_sha256':{str(f.relative_to(a.output)):sha(f) for f in a.output.rglob('*') if f.is_file()}}
    dump(a.output/'report.json',report);print(json.dumps({'task':a.task,'variant':a.variant,'passed':passed,'error':summary['error'],'action_errors':summary['action_error_count']}));raise SystemExit(0 if passed else 1)
if __name__=='__main__':main()
