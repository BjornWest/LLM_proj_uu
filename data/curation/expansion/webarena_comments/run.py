"""Bounded privileged scripted structural diagnostics, original task goals."""
import argparse,gzip,hashlib,json,os,re,subprocess,sys
from pathlib import Path
from urllib.parse import urlsplit
ROOT=Path(__file__).resolve().parents[4];HERE=Path(__file__).parent
sys.path.insert(0,str(ROOT))
from data.curation.expansion.runtime_snapshot import activate,fingerprints
FROZEN=activate();assert FROZEN,'Frozen runtime mandatory'
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
def closure():
 files=list(HERE.glob('*.py'))+[HERE/'contracts.json',ROOT/'.local/webarena-verified/dataset.json',ROOT/'scripts/harness_suite_tasks.py',ROOT/'data/curation/expansion/runtime_snapshot.py',ROOT/'data/curation/expansion/webarena/browser_batch.py',ROOT/'data/curation/expansion/webarena/inventory.py']
 files+=list((ROOT/'.local/webarena-verified/venv/lib').glob('python*/site-packages/webarena_verified/**/*.py'))
 return {**fingerprints(FROZEN,ROOT),**{str(p.relative_to(ROOT)):sha(p)for p in files}}
BEFORE=closure()
from bs4 import BeautifulSoup
from browsergym.core.env import BrowserEnv
from browsergym.core.task import OpenEndedTask
from intent_browser.actions import make_action_set
from intent_browser.evaluation import Evaluation
from intent_browser.harness import native_tools_profile
from intent_browser.runner import run_episode
from scripts.harness_suite_tasks import scripted_backend
from data.curation.expansion.webarena.browser_batch import Driver,HEADERS
from data.curation.expansion.webarena_comments.common import *
from data.curation.expansion.webarena_comments.grader import judge
assert closure()==BEFORE
CONTRACT=json.loads((HERE/'contracts.json').read_text())
def dump(p,v):Path(p).write_text(json.dumps(v,indent=2)+'\n')
def parse_page(html):
 soup=BeautifulSoup(html,'html.parser');post=soup.select_one('article.submission');form=post.select_one('[data-vote-route-value="submission_vote"]')if post else None
 fields={k:(post.select_one(sel).get_text('\n',strip=True)if post and post.select_one(sel)else None)for k,sel in [('title','.submission__title'),('author','.submission__submitter'),('forum','.submission__forum')]}
 comments=[]
 for c in soup.select('article.comment'):
  author=c.select_one('.comment__header a[href^="/user/"]');body=c.select_one('.comment__body')
  comments.append({'id':int(c['id'].split('_')[1]),'author':author.get_text(strip=True)if author else None,'body':body.get_text('\n',strip=True)if body else None})
 return {'confirmed_post_id':int(form['data-vote-id-value'])if form else None,'fields':fields,'comments':comments}
class BrowserTask(OpenEndedTask):
 def __init__(self,seed,adapter):self.adapter=adapter;super().__init__(seed,ORIGIN,adapter.goal)
 def setup(self,page):
  page.context.route('**/*',lambda r:r.continue_()if urlsplit(r.request.url).netloc=='localhost:19079'else r.abort())
  return super().setup(page)
class CommentTask:
 supported_harness_profiles=('core-tools-v3',)
 def __init__(self,contract):self.contract=contract;self.goal=contract['policy_input']['goal']
 def prepare(self,trace):
  self.initial=baseline();self.container=inspect()
  with gzip.open(trace.directory/'baseline.json.gz','wt')as f:json.dump(self.initial,f)
  dump(trace.directory/'contract.json',self.contract)
  return {'source_task_id':self.contract['source_task_id'],'container':self.container,'baseline_sha256':sha(trace.directory/'baseline.json.gz'),'training_eligible':False,'grader':'scoped_final_post_comment_v1'}
 def capture_initial(self,env,obs,info):return {'url':env.unwrapped.page.url,'container':inspect()}
 def evaluate(self,env,trace,outcome):
  evidence=final(self.initial);reads=[]
  for id in sorted({r['id']for r in evidence['posts']}|{r['submission_id']for r in evidence['comments']}):
   parent=post_parent(id);url=ORIGIN+'/f/'+parent['forum_name']+'/'+str(id)
   response=env.unwrapped.page.context.request.get(url,timeout=45000);html=response.text();name=f'privileged-post-{id}.html';(trace.directory/name).write_text(html)
   reads.append({'id':id,'status':response.status,'requested_url':url,'response_url':response.url,'html':name,'html_sha256':sha(trace.directory/name),**parse_page(html)})
  evidence['reads']=reads;evidence['capture_timing']='Owned DB and authenticated page GET after policy, before browser close'
  assert inspect()==self.container
  self.result=judge(evidence,self.contract['grader_input'],self.initial)
  dump(trace.directory/'comment-final-state.json',{'evidence':evidence,'result':self.result})
  return Evaluation('webarena-comments-derived','scoped-final-v1',trust='scoped_database_and_authenticated_page',task_completed=self.result['task_completed'],authorization_satisfied=self.result['authorization_satisfied'],unauthorized_effects=self.result['unauthorized_effects'],evidence=['comment-final-state.json','contract.json'],limitations=['Review semantics unknown; structural completion is not whole-goal success.','Native historical-request score retained separately.','Other account/site effects unknown.'])
class CommentDriver(Driver):
 def __init__(self,contract,variant):super().__init__(contract['source_task_id']);self.contract=contract;self.variant=variant;self.targets=[]
 def act(self,loc,op='click',value=None):
  code=super().act(loc,op,value);self.targets.append({'code':code,'bid':loc.get_attribute('bid'),'current_ax':self.text,'url':self.page.url});return code
 def finish(self,data=None):
  self.response={'task_type':'mutate','status':'SUCCESS','retrieved_data':None};return 'send_msg_to_user('+repr(json.dumps(self.response))+')'
 def steps(self):
  p=self.page;wanted=self.contract['original']['instantiation_dict']
  yield self.act(p.get_by_role('link',name='Submit',exact=True).first)
  yield self.act(p.get_by_label('Title',exact=False),'fill',wanted['book'])
  yield self.act(p.get_by_label('Body',exact=True),'fill',CONTRACT['scripted_diagnostic_body'])
  yield self.act(p.get_by_role('combobox').first)
  yield self.act(p.locator('input.select2-search__field'),'fill','books')
  yield self.act(p.get_by_role('option',name='books',exact=True))
  yield self.act(p.get_by_role('button',name='Create submission',exact=True),'press','Enter')
  self.record('created_post',{'url':p.url})
  if self.variant=='wrong-parent':
   created_path=urlsplit(p.url).path
   yield self.act(p.locator('article.submission .submission__forum'))
   candidates=p.locator('article.submission .submission__title a')
   target=next(candidates.nth(i)for i in range(candidates.count())if candidates.nth(i).get_attribute('href')!=created_path)
   self.record('wrong_parent_chosen_from_current_page',{'href':target.get_attribute('href'),'title':target.inner_text()})
   yield self.act(target)
  if self.variant!='missing-comment':
   yield self.act(p.locator('form[name^="reply_to_submission_"] textarea'),'fill',wanted['content'])
   yield self.act(p.get_by_role('button',name='Post',exact=True),'press','Enter')
   self.record('after_comment',{'url':p.url})
  yield self.finish()
 def complete(self,messages):
  from copy import deepcopy
  copied=deepcopy(messages);copied[-1]['content']=copied[-1]['content'].rsplit('CURRENT BROWSER OBSERVATION\n',1)[-1]
  return super().complete(copied)
def main():
 p=argparse.ArgumentParser();p.add_argument('--task',type=int,choices=[610],default=610);p.add_argument('--variant',choices=['positive','wrong-parent','missing-comment'],required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
 os.environ['LD_LIBRARY_PATH']=str(ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu')+':'+os.getenv('LD_LIBRARY_PATH','')
 before=closure();assert before==BEFORE;container=inspect();dump(a.output/'source-before.json',before)
 contract=next(t for t in CONTRACT['tasks']if t['source_task_id']==a.task);task=CommentTask(contract);driver=CommentDriver(contract,a.variant);backend=scripted_backend(driver);profile=native_tools_profile(parallel_tool_calls=None,compact_feedback=True,reasoning_replay='preserve');har=a.output/'network.har'
 def factory(video):
  env=BrowserEnv(task_entrypoint=BrowserTask,task_kwargs={'adapter':task},headless=True,slow_mo=0,timeout=10000,pre_observation_delay=1,action_mapping=make_action_set().to_python_code,wait_for_user_message=False,pw_context_kwargs={'extra_http_headers':HEADERS['reddit'],'record_har_path':str(har.resolve()),'record_har_content':'embed','service_workers':'block'});driver.env=env;return env
 try:trace,summary=run_episode(factory,backend,{'task':'webarena-comments-structural','source_task_id':a.task,'goal':task.goal,'variant':a.variant,'model':None,'model_calls':0,'training_eligible':False},output=a.output/'traces',max_steps=20,episode_task=task,harness_profile=profile,before_observation=lambda:None,observation_text_limit=48000,terminal_response_instruction=CONTRACT['terminal_response_instruction'])
 finally:backend.client.close()
 dump(trace/'scripted-targets.json',driver.targets);dump(trace/'driver-evidence.json',driver.evidence);dump(a.output/'response.json',driver.response)
 subprocess.run([str(ROOT/'.local/webarena-verified/venv/bin/python'),str(HERE/'grade_native.py'),str(har),str(a.output/'response.json'),str(a.output/'native-grade.json'),str(a.task)],check=True,timeout=45)
 native=json.loads((a.output/'native-grade.json').read_text());after=closure();dump(a.output/'source-after.json',after)
 result=task.result;expected=a.variant=='positive';passed=summary['error']is None and summary['action_error_count']==0 and before==after and inspect()==container and result['structural_completion']is expected and result['task_completed']is(None if expected else False)
 report={'schema':'webarena-comments-structural-case-v1','task_id':a.task,'variant':a.variant,'passed':passed,'trace':str(trace),'summary':summary,'derived_result':result,'native_grade':native,'source_sha256':before,'source_unchanged':before==after,'container':container,'model_calls':0,'training_eligible':False,'accepted':False,'profile':profile.describe(),'artifact_sha256':{str(f.relative_to(a.output)):sha(f)for f in a.output.rglob('*')if f.is_file()}}
 dump(a.output/'report.json',report);print(json.dumps({'variant':a.variant,'passed':passed,'error':summary['error'],'action_errors':summary['action_error_count'],'native_score':native['score'],'derived':result}));raise SystemExit(0 if passed else 1)
if __name__=='__main__':main()
