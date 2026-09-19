"""Explicit later execution only: unchanged original Maps, no network on import."""
import argparse,hashlib,json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[4];HERE=Path(__file__).parent
sys.path.insert(0,str(ROOT))
from data.curation.expansion.webarena_maps_preflight.evidence import ORIGIN,MODES,allowed_request,assess,projection

def dump(path,data):
 with Path(path).open('x') as f:json.dump(data,f,indent=2);f.write('\n')
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def closure(frozen):
 paths=list(HERE.glob('*.py'))+[HERE/'source-pins.json',ROOT/'data/curation/expansion/runtime_snapshot.py',ROOT/'scripts/harness_suite_tasks.py',frozen/'manifest.json']+list((frozen/'intent_browser').glob('*.py'))
 for x in json.loads((HERE/'source-pins.json').read_text())['archives']:paths.append(ROOT/x['path'])
 return {str(p.relative_to(ROOT)):sha(p) for p in paths}
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--execute-local-13030',action='store_true');p.add_argument('--output',type=Path,required=True);p.add_argument('--query',default='Carnegie Mellon University, Pittsburgh');p.add_argument('--from-place',default='Carnegie Mellon University, Pittsburgh');p.add_argument('--to-place',default='University of Pittsburgh, Pittsburgh');p.add_argument('--case',choices=['homepage','search',*MODES],action='append');a=p.parse_args()
 if not a.execute_local_13030:p.error('Explicit --execute-local-13030 required; no browser started')
 a.output.mkdir(parents=True,exist_ok=False)
 from data.curation.expansion.runtime_snapshot import activate
 frozen=activate()
 if frozen is None:raise RuntimeError('Set CURATION_FROZEN_RUNTIME before any intent_browser imports')
 pins=json.loads((HERE/'source-pins.json').read_text())
 for row in pins['archives']:assert sha(ROOT/row['path'])==row['sha256'],'Cached source archive changed'
 before=closure(frozen);dump(a.output/'source-before.json',before)
 os.environ['LD_LIBRARY_PATH']=str(ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu')+':'+os.getenv('LD_LIBRARY_PATH','')
 from browsergym.core.env import BrowserEnv
 from browsergym.core.task import OpenEndedTask
 from intent_browser.actions import make_action_set
 from intent_browser.backend import Completion
 from intent_browser.harness import native_tools_profile
 from intent_browser.runner import run_episode
 from intent_browser.evaluation import Evaluation
 from scripts.harness_suite_tasks import scripted_backend

 class Site(OpenEndedTask):
  def __init__(self,seed,driver):self.driver=driver;super().__init__(seed,ORIGIN,driver.goal)
  def setup(self,page):
   def guard(route):
    r=route.request
    if allowed_request(r.method,r.url):route.continue_()
    else:self.driver.blocked.append({'method':r.method,'url':r.url});route.abort()
   page.context.route('**/*',guard)
   page.on('pageerror',lambda e:self.driver.page_errors.append(str(e)))
   page.on('requestfailed',lambda r:self.driver.network_errors.append({'url':r.url,'error':r.failure}))
   return super().setup(page)
 class Task:
  supported_harness_profiles=('core-tools-v3',)
  def __init__(self,driver):self.driver=driver;self.policy_goal=driver.goal
  def prepare(self,trace):self.driver.trace=trace.directory;return {'source':'webarena-maps-site-preflight','source_image':pins['image'],'training_eligible':False}
  def capture_initial(self,env,obs,info):return {'url':env.unwrapped.page.url}
  def evaluate(self,env,trace,outcome):return Evaluation('maps-site-preflight','diagnostic-v1',trust='unverified',task_completed=None,authorization_satisfied=None,limitations=['Site diagnostics only. No benchmark task accepted.'])
 class Driver:
  def __init__(self,kind):self.kind=kind;self.env=None;self.script=None;self.text='';self.pending=None;self.stage=None;self.targets=[];self.blocked=[];self.page_errors=[];self.network_errors=[];self.goal='Inspect the original local map '+kind+' interface. This is a scripted site preflight, not a benchmark task.'
  @property
  def page(self):return self.env.unwrapped.page
  def ready(self):
   assert closure(frozen)==before,'Source changed before fresh observation'
   if self.pending:
    selector=self.pending;self.pending=None
    self.page.locator(selector).first.wait_for(state='visible',timeout=30000)
   return {'source':'maps-scripted-readiness-no-model'}
  def act(self,loc,op='click',value=None):
   loc.wait_for(state='visible',timeout=10000);bid=loc.get_attribute('bid');assert bid and f'[{bid}]' in self.text,'Target absent from current delivered AX'
   self.targets.append({'bid':bid,'operation':op,'value':value,'delivered_ax':self.text,'url':self.page.url})
   return op+'('+', '.join(repr(v) for v in ([bid] if value is None else [bid,value]))+')'
  def capture(self):
   p=self.page;side=p.locator('#sidebar_content');stage={'kind':self.kind,'url':p.url,'ax':self.text,'sidebar':side.inner_text() if side.count() else '', 'search_results':p.locator('.search_results_entry a.set_position').all_inner_texts(),'tiles':p.locator('img.leaflet-tile').evaluate_all('es=>es.map(e=>({src:e.currentSrc,complete:e.complete,natural_width:e.naturalWidth}))'),'rendered_paths':p.locator('.leaflet-overlay-pane path[d]').count(),'route_rows':p.locator('#sidebar_content tr.turn').all_inner_texts()}
   if self.kind in MODES:stage.update(resolved_from=p.locator('#route_from').input_value(),resolved_to=p.locator('#route_to').input_value(),selected_label=p.locator('select.routing_engines option:checked').inner_text().strip())
   p.screenshot(path=str(self.trace/'site-stage.png'),full_page=True)
   (self.trace/'site-stage.html').write_text(p.content());(self.trace/'site-stage.ax.txt').write_text(self.text)
   dump(self.trace/'stage-private.json',stage);dump(self.trace/'visible-projection.json',projection(stage));self.stage=stage
  def steps(self):
   p=self.page
   if self.kind=='search':
    yield self.act(p.locator('#query'),'fill',a.query)
    self.pending='.search_results_entry a.set_position, .search_results_error'
    yield self.act(p.locator('#query'),'press','Enter')
   elif self.kind in MODES:
    yield self.act(p.locator('.search_form a.switch_link'))
    select=p.locator('select.routing_engines');label=MODES[self.kind][0]
    assert label in self.text,'Engine option absent from delivered AX'
    option=select.locator('option').filter(has_text=label);assert option.count()==1
    yield self.act(select,'select_option',option.get_attribute('value'))
    yield self.act(p.locator('#route_from'),'fill',a.from_place)
    yield self.act(p.locator('#route_to'),'fill',a.to_place)
    self.pending='#sidebar_content tr.turn, #sidebar_content .search_results_error'
    yield self.act(p.locator('#route_to'),'press','Enter')
   self.capture()
   yield 'send_msg_to_user("Read-only site preflight observations captured; task success is unknown.")'
  def complete(self,messages):
   assert closure(frozen)==before
   self.text=messages[-1]['content'].rsplit('CURRENT BROWSER OBSERVATION\n',1)[-1];self.script=self.script or self.steps()
   return Completion(next(self.script),{'source':'privileged_maps_preflight','model_calls':0})
 results=[]
 for kind in a.case or ['homepage','search',*MODES]:
  out=a.output/kind;out.mkdir();driver=Driver(kind);task=Task(driver);backend=scripted_backend(driver);har=out/'network.har';summary=None;trace=None;failure=None
  def factory(video):
   env=BrowserEnv(task_entrypoint=Site,task_kwargs={'driver':driver},headless=True,slow_mo=0,timeout=10000,pre_observation_delay=1,action_mapping=make_action_set().to_python_code,wait_for_user_message=False,pw_context_kwargs={'record_har_path':str(har.resolve()),'record_har_content':'embed','service_workers':'block'});driver.env=env;return env
  try:
   trace,summary=run_episode(factory,backend,{'task':'maps-read-only-preflight','goal':driver.goal,'model':None,'training_eligible':False},output=out/'traces',max_steps=12,episode_task=task,harness_profile=native_tools_profile(parallel_tool_calls=None,compact_feedback=True,reasoning_replay='preserve'),before_observation=driver.ready,observation_text_limit=48000)
   failure=summary.get('error')
  except Exception as e:failure=repr(e)
  finally:backend.client.close()
  entries=json.loads(har.read_text())['log']['entries'] if har.exists() else []
  check=assess(driver.stage,entries,error=failure)
  if driver.blocked or driver.page_errors or driver.network_errors:check['preflight_status']='unknown'
  dump(out/'scripted-targets.json',driver.targets)
  result={'kind':kind,'trace':str(trace) if trace else None,'summary':summary,'error':failure,'check':check,'blocked_requests':driver.blocked,'page_errors':driver.page_errors,'network_errors':driver.network_errors,'source_unchanged':before==closure(frozen),'model_calls':0,'artifact_sha256':{str(f.relative_to(out)):sha(f) for f in out.rglob('*') if f.is_file()}}
  if not result['source_unchanged']:check['preflight_status']='unknown'
  dump(out/'report.json',result);results.append(result)
  if not result['source_unchanged']:break
 dump(a.output/'report.json',{'schema':'maps-read-only-site-preflight-v1','origin':ORIGIN,'source_sha256':before,'cases':results,'task_acceptance':False,'training_eligible':False,'model_calls':0})
 print(json.dumps({'cases':{r['kind']:r['check']['preflight_status'] for r in results},'task_acceptance':False}))
if __name__=='__main__':main()
