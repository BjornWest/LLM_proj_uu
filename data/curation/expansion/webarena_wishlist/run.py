"""Native scripted original-goal wishlist diagnostics on dedicated full Magento."""
import argparse,hashlib,json,os,subprocess,sys
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
from data.curation.expansion.webarena_wishlist.common import *
from data.curation.expansion.webarena_wishlist.grader import judge
assert closure()==BEFORE
CONTRACT=json.loads((HERE/'contracts.json').read_text())
def dump(p,v):Path(p).write_text(json.dumps(v,indent=2)+'\n')
def parse_items(html):
 soup=BeautifulSoup(html,'html.parser');items=[]
 for row in soup.select('.products-grid.wishlist li.product-item'):
  name=row.select_one('.product-item-name');qty=row.select_one('input.qty')
  items.append({'item_id':int(row['id'].removeprefix('item_')),'name':name.get_text(' ',strip=True)if name else None,'quantity':qty.get('value')if qty else None})
 return items
class BrowserTask(OpenEndedTask):
 def __init__(self,seed,adapter):self.adapter=adapter;super().__init__(seed,adapter.start_url,adapter.goal)
 def setup(self,page):
  page.context.route('**/*',lambda r:r.continue_()if urlsplit(r.request.url).netloc=='localhost:17770'else r.abort())
  return super().setup(page)
class WishlistTask:
 supported_harness_profiles=('core-tools-v3',)
 def __init__(self,contract,variant):self.contract=contract;self.goal=contract['policy_input']['goal'];self.variant=variant;self.start_url=contract['setup']['start_url'].replace('__SHOPPING__',ORIGIN)
 def prepare(self,trace):
  self.initial=state();assert not self.initial['items'],'Scripted cohort requires empty owned wishlist baseline';self.container=inspect();dump(trace.directory/'baseline.json',self.initial);dump(trace.directory/'contract.json',self.contract)
  return {'source_task_id':self.contract['source_task_id'],'source_start_url':self.contract['setup']['start_url'],'resolved_start_url':self.start_url,'container':self.container,'training_eligible':False}
 def capture_initial(self,env,obs,info):return {'url':env.unwrapped.page.url,'original_goal':self.goal}
 def evaluate(self,env,trace,outcome):
  evidence=None
  if self.variant!='missing-read':
   db=state();r=env.unwrapped.page.context.request.get(ORIGIN+'/wishlist/',timeout=60000);html=r.text();(trace.directory/'privileged-wishlist.html').write_text(html)
   account=env.unwrapped.page.context.request.get(ORIGIN+'/customer/account/',timeout=60000);account_html=account.text();(trace.directory/'privileged-account.html').write_text(account_html)
   soup=BeautifulSoup(account_html,'html.parser');contact=soup.select_one('.box-information .box-content');contact_text=contact.get_text(' ',strip=True)if contact else ''
   evidence={'database':db,'page':{'status':r.status,'url':r.url,'html_sha256':sha(trace.directory/'privileged-wishlist.html'),'items':parse_items(html)},'account_status':account.status,'account_email_confirmed':EMAIL in contact_text,'account_html_sha256':sha(trace.directory/'privileged-account.html'),'capture_timing':'Independent owned database and authenticated pages after final policy action, before browser close'}
  assert inspect()==self.container;self.result=judge(self.initial,evidence,self.contract['grader_input']);dump(trace.directory/'wishlist-final-state.json',{'evidence':evidence,'result':self.result,'fault_injection':self.variant if self.variant=='missing-read'else None})
  return Evaluation('webarena-wishlist-derived','final-membership-v1',trust='scoped_database_and_authenticated_page',task_completed=self.result['task_completed'],authorization_satisfied=self.result['authorization_satisfied'],unauthorized_effects=self.result['unauthorized_effects'],evidence=['wishlist-final-state.json','baseline.json','contract.json'],limitations=['Native historical request grade retained separately.','Quantity unspecified; repeated addition recorded diagnostically.','Other account/site effects unknown.'])
class WishlistDriver(Driver):
 def __init__(self,contract,variant):super().__init__(contract['source_task_id']);self.contract=contract;self.variant=variant;self.targets=[]
 def act(self,loc,op='click',value=None):
  code=super().act(loc,op,value);self.targets.append({'code':code,'bid':loc.get_attribute('bid'),'current_ax':self.text,'url':self.page.url});return code
 def finish(self,data=None):self.response={'task_type':'mutate','status':'SUCCESS','retrieved_data':None};return 'send_msg_to_user('+repr(json.dumps(self.response))+')'
 def search(self,query,title=None):
  p=self.page;yield self.act(p.locator('#search'),'fill',query);yield self.act(p.locator('#search'),'press','Enter');links=p.locator('.product-item-name a')
  wanted=links.filter(has_text=title)if title else links
  for _ in range(8):
   if wanted.count():
    loc=wanted.first;self.record('product_selected_from_search',{'title':loc.inner_text(),'url':loc.get_attribute('href')});yield self.act(loc);return
   nxt=p.get_by_role('link',name='Next',exact=True)
   if not nxt.count():break
   yield self.act(nxt.first)
  raise AssertionError('Original requested product not reachable within search-page bound')
 def add(self):
  p=self.page;self.record('before_wishlist_add',{'title':p.locator('h1').inner_text(),'url':p.url})
  yield self.act(p.locator('.product-social-links').get_by_role('link',name='Add to Wish List',exact=True))
  self.record('after_wishlist_add',{'url':p.url,'items':p.locator('.products-grid.wishlist').inner_text()if p.locator('.products-grid.wishlist').count()else None})
 def steps(self):
  p=self.page;t=self.contract['source_task_id']
  if self.variant=='wrong-product':yield from self.search('Elmwood Inn Fine Teas Orange'if t==465 else'Tide PODS Spring Meadow')
  elif t<500:
   name=self.contract['original']['instantiation_dict']['product'];queries={465:'Tide PODS',466:'Hawaiian Bamboo Orchid',467:'HONGJ Hawaiian Beach Outfits',468:'DkRgVNY Lace',469:'Light Blue Simple Summer'}
   yield from self.search(queries[t],name)
  yield from self.add()
  if self.variant=='remove-after-add':
   row=p.locator('.products-grid.wishlist li.product-item').first
   yield self.act(row.get_by_role('link',name='Remove Item',exact=True))
  elif self.variant=='duplicate':
   yield self.act(p.locator('.products-grid.wishlist .product-item-name a').first);yield from self.add()
  yield self.finish()
 def complete(self,messages):
  from copy import deepcopy
  copied=deepcopy(messages);copied[-1]['content']=copied[-1]['content'].rsplit('CURRENT BROWSER OBSERVATION\n',1)[-1];return super().complete(copied)
def main():
 p=argparse.ArgumentParser();p.add_argument('--task',type=int,choices=[t['source_task_id']for t in CONTRACT['tasks']],required=True);p.add_argument('--variant',choices=['positive','wrong-product','remove-after-add','duplicate','missing-read'],required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
 os.environ['LD_LIBRARY_PATH']=str(ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu')+':'+os.getenv('LD_LIBRARY_PATH','')
 before=closure();assert before==BEFORE;container=inspect();dump(a.output/'source-before.json',before)
 contract=next(t for t in CONTRACT['tasks']if t['source_task_id']==a.task);task=WishlistTask(contract,a.variant);driver=WishlistDriver(contract,a.variant);backend=scripted_backend(driver);profile=native_tools_profile(parallel_tool_calls=None,compact_feedback=True,reasoning_replay='preserve');har=a.output/'network.har'
 def factory(video):
  env=BrowserEnv(task_entrypoint=BrowserTask,task_kwargs={'adapter':task},headless=True,slow_mo=0,timeout=10000,pre_observation_delay=1,action_mapping=make_action_set().to_python_code,wait_for_user_message=False,pw_context_kwargs={'extra_http_headers':HEADERS['shopping'],'record_har_path':str(har.resolve()),'record_har_content':'embed','service_workers':'block'});driver.env=env;return env
 try:trace,summary=run_episode(factory,backend,{'task':'webarena-wishlist-derived','source_task_id':a.task,'goal':task.goal,'variant':a.variant,'model':None,'model_calls':0,'training_eligible':False},output=a.output/'traces',max_steps=24,episode_task=task,harness_profile=profile,before_observation=lambda:None,observation_text_limit=48000,terminal_response_instruction=CONTRACT['terminal_response_instruction'])
 finally:backend.client.close()
 dump(trace/'scripted-targets.json',driver.targets);dump(trace/'driver-evidence.json',driver.evidence);dump(a.output/'response.json',driver.response)
 subprocess.run([str(ROOT/'.local/webarena-verified/venv/bin/python'),str(HERE/'grade_native.py'),str(har),str(a.output/'response.json'),str(a.output/'native-grade.json'),str(a.task)],check=True,timeout=45)
 native=json.loads((a.output/'native-grade.json').read_text());after=closure();dump(a.output/'source-after.json',after);expected=None if a.variant=='missing-read'else a.variant in ['positive','duplicate']
 result=task.result;passed=summary['error']is None and summary['action_error_count']==0 and before==after and inspect()==container and result['task_completed']is expected
 report={'schema':'webarena-wishlist-case-v1','task_id':a.task,'variant':a.variant,'passed':passed,'trace':str(trace),'summary':summary,'derived_result':result,'native_grade':native,'source_sha256':before,'source_unchanged':before==after,'container':container,'model_calls':0,'training_eligible':False,'profile':profile.describe(),'artifact_sha256':{str(f.relative_to(a.output)):sha(f)for f in a.output.rglob('*')if f.is_file()}}
 dump(a.output/'report.json',report);print(json.dumps({'task':a.task,'variant':a.variant,'passed':passed,'error':summary['error'],'action_errors':summary['action_error_count'],'native_score':native['score'],'derived':result}));raise SystemExit(0 if passed else 1)
if __name__=='__main__':main()
