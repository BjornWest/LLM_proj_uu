"""Read-only original-task browser rehearsals, not teacher/model rollouts.

Uses fresh BrowserGym contexts, ordinary parsed browser actions, and the unchanged
runner. DOM-assisted scripted selectors and answer extraction are privileged test
code; expected answers are never loaded by this driver. Negative controls are
separately generated offline, not mislabeled as wrong-path browser executions.
"""
import argparse,datetime,hashlib,json,os,re,sys,tempfile,faulthandler,signal
from pathlib import Path
from urllib.parse import urlsplit
ROOT=Path(__file__).resolve().parents[4]
sys.path.insert(0,str(ROOT))
from browsergym.core.env import BrowserEnv
from browsergym.core.task import OpenEndedTask
from intent_browser.actions import make_action_set
from intent_browser.backend import Completion
from intent_browser.runner import run_episode
from data.curation.expansion.webarena.inventory import BATCH,digest
ORIGINS={'shopping':'http://localhost:7770','reddit':'http://localhost:9999'}
HEADERS={'shopping':{'X-M2-Customer-Auto-Login':'emma.lopez@gmail.com:Password.123'},'reddit':{'X-Postmill-Auto-Login':'MarvelsGrantMan136:test1234'}}
class ReadOnlyTask(OpenEndedTask):
 def __init__(self,seed,start_url,goal,blocked):super().__init__(seed,start_url,goal);self.blocked=blocked
 def setup(self,page):
  allowed=urlsplit(self.start_url).netloc
  def route(r):
   q=r.request;u=urlsplit(q.url)
   if q.method not in ('GET','HEAD') or (u.scheme in ('http','https') and u.netloc!=allowed):self.blocked.append({'url':q.url,'method':q.method});r.abort()
   else:r.continue_()
  page.context.route('**/*',route);page.goto(self.start_url,timeout=120000);page.wait_for_load_state('load');return self.goal,{}
class Driver:
 def __init__(self,task_id):self.task_id=task_id;self.env=None;self.script=None;self.text='';self.evidence=[];self.response=None
 @property
 def page(self):return self.env.unwrapped.page
 def act(self,loc,op='click',value=None):
  loc.wait_for(state='visible',timeout=12000);bid=loc.get_attribute('bid');assert bid and f'[{bid}]' in self.text,'Target absent from delivered AX';args=[bid]+([] if value is None else [value]);return op+'('+', '.join(repr(x) for x in args)+')'
 def record(self,label,data):self.evidence.append({'label':label,'url':self.page.url,'data':data,'body':self.page.locator('body').inner_text()})
 def finish(self,data=None):
  kind='navigate' if self.task_id in (158,260,324) else 'retrieve';self.response={'task_type':kind,'status':'SUCCESS','retrieved_data':data};return 'send_msg_to_user('+repr(json.dumps(self.response))+')'
 def orders(self):
  yield self.act(self.page.get_by_role('link',name='My Account',exact=True).first)
  yield self.act(self.page.get_by_role('link',name='My Orders',exact=True))
 def rows(self):return self.page.locator('#my-orders-table tbody tr').evaluate_all('(es)=>es.map(e=>Array.from(e.querySelectorAll("td")).map(x=>x.innerText))')
 def steps(self):
  p=self.page;t=self.task_id
  if t in (96,117,188):
   yield from self.orders()
   if t==117:yield self.act(p.locator('#limiter'),'select_option','50')
   rows=self.rows();assert rows;self.record('order_rows',rows)
   if t==96:
    yield self.act(p.locator('#my-orders-table tbody tr').first.get_by_role('link',name='View Order',exact=True));body=p.locator('body').inner_text();self.record('latest_order_detail',body);assert rows[0][3].lower()=='canceled';assert 'tracking' not in body.lower();yield self.finish([{'status':rows[0][3].lower(),'arrival_date':None}])
   elif t==117:
    dates=[datetime.datetime.strptime(r[1],'%m/%d/%y').date() for r in rows];assert len(rows)==37;yield self.finish([min(dates).isoformat()])
   else:
    row=next(r for r in rows if r[3].lower()=='canceled');yield self.finish([float(row[2].replace('$','').replace(',',''))])
  elif t in (21,163):
   yield self.act(p.locator('.reviews-actions .action.view'))
   found=[];allreviews=[]
   for _ in range(20):
    p.locator('.review-item').first.wait_for(state='visible');reviews=p.locator('.review-item').evaluate_all('es=>es.map(e=>({title:e.querySelector(".review-title")?.innerText,body:e.querySelector(".review-content")?.innerText,author:e.querySelector(".review-details-value")?.innerText,ratings:Array.from(e.querySelectorAll(".rating-result")).map(x=>x.getAttribute("title")||x.innerText)}))');allreviews.extend(reviews)
    for r in reviews:
     if t==163:
      rating=float(re.search(r'\d+(?:\.\d+)?',r['ratings'][0]).group());
      if rating<=40:found.append(r['title'])
     elif re.search(r'small.{0,8}ears|ear.{0,100}small|half my ear',r['body'],re.I):
      author=r['author'];half=len(author)//2;author=author[:half] if len(author)%2==0 and author[:half]==author[half:] else author;found.append(author)
    nxt=p.locator('#product-review-container .pages-item-next a:visible').first
    if not nxt.count():break
    yield self.act(nxt)
   else:raise AssertionError('Review pagination exceeded bound')
   self.record('reviews',allreviews);yield self.finish(list(dict.fromkeys(found)))
  elif t==260:
   yield self.act(p.get_by_role('menuitem',name=re.compile('Video Games$')));self.record('category',p.locator('h1').inner_text());assert urlsplit(p.url).path=='/video-games.html';yield self.finish()
  elif t in (158,324):
   query='HEIYING' if t==158 else 'chairs';yield self.act(p.locator('#search'),'fill',query);yield self.act(p.locator('#search'),'press','Enter')
   yield self.act(p.locator('select[data-role="sorter"]').first,'select_option','price')
   if t==158:
    self.record('search_products',p.locator('.product-item').all_inner_texts());loc=p.locator('.product-item-link').filter(has_text=re.compile('HEIYING.*24 Game Card',re.I)).first;yield self.act(loc);body=p.locator('body').inner_text();assert '24' in p.locator('h1').inner_text();self.record('capacity_product',body)
   else:
    asc=p.get_by_role('link',name=re.compile('Set Ascending Direction$')).first
    if asc.count():yield self.act(asc)
    self.record('sorted_listings',{'url':p.url,'titles':p.locator('.product-item-link').all_inner_texts(),'sort':p.locator('select[data-role="sorter"]').first.input_value()})
   yield self.finish()
  elif t in (27,66):
   yield self.act(p.get_by_role('link',name='Forums',exact=True));name='personalfinance' if t==27 else 'books';yield self.act(p.get_by_role('link',name=re.compile('^'+name+' —')))
   if t==27:
    yield self.act(p.get_by_role('button',name='Sort by: Hot',exact=True));yield self.act(p.get_by_role('link',name='New',exact=True));titles=p.locator('.submission__title').all_inner_texts();first=p.locator('.submission').first;author=first.locator('a[href^="/user/"]').first.inner_text();self.record('newest_post_list',{'title':titles[0],'author':author,'first':first.inner_text()});yield self.act(first.locator('a.submission__link'));body=p.locator('body').inner_text();assert 'No comments' in body or p.locator('.comment').count()==0;self.record('newest_post_comments',body);yield self.finish([{'username':author,'post_title':titles[0],'count':0}])
   else:
    titles=p.locator('.submission__title').all_inner_texts()[:10];self.record('top_ten_hot_titles',titles);selected=[s for s in titles if 'The Hobbit' in s or 'A Christmas Carol' in s];assert len(selected)==2
    # Human-selected semantic candidates are then actually opened and retained.
    for title in selected:
     yield self.act(p.get_by_role('link',name=title,exact=True));self.record('recommended_book_post',{'title':title,'body':p.locator('body').inner_text()});yield self.act(p.get_by_role('link',name='/f/books',exact=True))
    yield self.finish(selected)
  else:raise ValueError(t)
 def complete(self,messages):
  self.text=messages[-1]['content'];self.script=self.script or self.steps();return Completion(next(self.script),{'source':'privileged_read_only_script','model_calls':0})
def main():
 faulthandler.register(signal.SIGUSR1,all_threads=True)
 p=argparse.ArgumentParser();p.add_argument('--task',type=int,choices=BATCH,action='append');p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
 lib=ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu';os.environ['LD_LIBRARY_PATH']=str(lib)+':'+os.getenv('LD_LIBRARY_PATH','')
 dataset=json.loads((ROOT/'.local/webarena-verified/dataset.json').read_text());results=[]
 for tid in a.task or BATCH:
  task=next(x for x in dataset if x['task_id']==tid);site=task['sites'][0];origin=ORIGINS[site];start=task['start_urls'][0].replace('__'+site.upper()+'__',origin);blocked=[];driver=Driver(tid)
  with tempfile.TemporaryDirectory(prefix='wav-expansion-') as tmp:
   har=Path(tmp)/'network.har'
   def factory(video):
    env=BrowserEnv(task_entrypoint=ReadOnlyTask,task_kwargs={'start_url':start,'goal':task['intent'],'blocked':blocked},headless=True,slow_mo=100,timeout=10000,pre_observation_delay=1,action_mapping=make_action_set().to_python_code,pw_context_kwargs={'extra_http_headers':HEADERS[site],'record_har_path':str(har),'record_har_content':'embed','service_workers':'block'},wait_for_user_message=False);driver.env=env;return env
   trace,summary=run_episode(factory,driver,{'task':'webarena-verified.expansion-read-only','source_task_id':tid,'source_template_id':task['intent_template_id'],'goal':task['intent'],'driver':'privileged_scripted_validation','model':None,'training_eligible':False,'verifier':None,'network_model_calls':0},output=a.output/'traces',max_steps=50,observation_text_limit=120000)
   if har.exists():(trace/'network.har').write_bytes(har.read_bytes())
   result={'task_id':tid,'trace':str(trace),'summary':summary,'derived_response':driver.response,'blocked_requests':blocked,'browser_positive':summary['error'] is None and summary['action_error_count']==0 and driver.response is not None,'browser_negative':None,'model_tested':False,'training_ready':False,'authorization_preserved':None,'evidence':driver.evidence,'script_sha256':digest(Path(__file__)),'source_sha256':digest(ROOT/'.local/webarena-verified/dataset.json')}
   (trace/'read-only-validation.json').write_text(json.dumps(result,indent=2));results.append({k:v for k,v in result.items() if k!='evidence'});print(json.dumps({'task_id':tid,'positive':result['browser_positive'],'trace':str(trace),'error':summary['error']}),flush=True)
 (a.output/'report.json').write_text(json.dumps({'schema':'webarena-read-only-browser-v1','model_calls':0,'tasks':results,'scope':'DOM-assisted scripted positive paths; not model evidence, native grader not yet applied; no negative browser case'},indent=2))
if __name__=='__main__':main()
