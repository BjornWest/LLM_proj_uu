"""Eight once-only MiMo episodes with process-isolated queued native admission."""
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
import json,os,runpy,signal,socket,sqlite3,subprocess,sys,tempfile,threading,time,types

def load(p):return json.loads(Path(p).read_bytes())
def save(p,v):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('x') as f:json.dump(v,f,indent=2,ensure_ascii=False,allow_nan=False);f.write('\n')
def pin(p):return {'path':str(Path(p).resolve()),'sha256':sha256(Path(p).read_bytes()).hexdigest()}
def checked(r):
 p=Path(r['path'])
 if p.is_symlink() or pin(p)!=r:raise ValueError('Pinned input changed: '+str(p))
 return p

def helper(s):return runpy.run_path(str(checked(s['helpers'])))
def config_hash(s):return sha256(json.dumps({k:v for k,v in s.items() if k not in ('review','ready','sockets','tokenizer_socket')},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
def source_guard(s,c=None):
 checked(s['driver']);checked(s['helpers']);checked(s['events_helper'])
 if c is not None:checked(c['recipe_manifest'])
 if not Path(s['driver']['path']).read_bytes()==subprocess.check_output(['git','-C',s['caller_root'],'show',s['caller_commit']+':scripts/queued_mimo_suite.py']):raise ValueError('Caller differs from committed source')

def check_release(s):
 source_guard(s)
 if len(s['cases'])!=8 or [c['id'] for c in s['cases']]!=s['start_order'] or s['max_concurrent_episodes']!=3 or s['prewarm_count']!=1 or s['model']!='xiaomi/mimo-v2.6-pro':raise ValueError('Require exact authorized eight/cap three/warm one')
 r=load(checked(s['review']));a=load(checked(s['ready']))
 if r['status']!='approved' or r['configuration_sha256']!=config_hash(s) or a['status']!='passed' or a['driver']!=s['driver'] or {v['case'] for v in a['cases']}!={c['id'] for c in s['cases']}:raise ValueError('Missing reviewed configuration or actual scripted acceptance')
 for v in a['cases']:
  result=load(checked(v['result']))
  if result['result']['viewer_projection']['task_completed'] is not True:raise ValueError('Correct acceptance did not pass')


def execute(s,c,scripted=False):
 if not scripted:
  check_release(s)
  with sqlite3.connect('file:'+str(Path(s['output'])/'completion.sqlite')+'?mode=ro',uri=True) as db:
   if db.execute('SELECT state FROM episodes WHERE suite=? AND id=?',(s['suite_id'],c['id'])).fetchone()!=('running',):raise ValueError('Case not claimed by subscribed supervisor')
 h=helper(s);run=h['configure_case'](s,c);source_guard(s,c)
 from intent_browser.backend import ChatCompletionsBackend
 from intent_browser.runner import run_episode
 from intent_browser.episode_admission import EpisodeAdmissionCancelled
 from intent_browser.model_input_budget import model_matched_input_counter
 from intent_browser.shared_tokenizer import SharedTokenizerConfig
 channel=runpy.run_path(str(checked(s['channel'])))
 out=Path(s['output'])/c['id'];out.mkdir(parents=True,exist_ok=False)
 authority=load(Path(s['output'])/'supervisor-start.json')
 timings={'worker_started_monotonic':time.monotonic(),'reset_calls':0,'policy_requests':0,'formatter_requests':0}
 save(out/'start.json',{'case':c['id'],'pid':os.getpid(),'epoch':time.time(),'monotonic':timings['worker_started_monotonic'],'scripted':scripted})
 connection=socket.socket(socket.AF_UNIX);connection.settimeout(s['suite_timeout']);connection.connect(s['sockets'][c['id']])
 admission=channel['ChildAdmission'](connection,c['id'],EpisodeAdmissionCancelled)
 def deadline(*_):raise TimeoutError('Case startup/active watchdog or termination')
 signal.signal(signal.SIGTERM,deadline);signal.signal(signal.SIGALRM,deadline);signal.alarm(s['startup_timeout'])
 counts={'policy_requests':0,'formatter_requests':0,'reported_cost_usd':0.0,'responses_without_cost':0}
 profile=None
 def guard():
  source_guard(s,c);h['module_origins'](s,c)
  if h['process_identity'](authority['pid'])!=authority['process_start']:raise RuntimeError('Supervisor lost')
 def before(phase):
  guard();admission.before_dispatch()
  now=time.monotonic()
  if phase=='policy':timings.setdefault('first_policy_dispatch_monotonic',now)
  else:timings.setdefault('first_formatter_dispatch_monotonic',now)
  counts[phase+'_requests']+=1
  if phase=='formatter' and counts['formatter_requests']>1:raise RuntimeError('One formatter maximum')
 def record(value):
  with (out/'http-attempts.jsonl').open('a') as f:f.write(json.dumps({'epoch':time.time(),**value})+'\n')
 def backend(phase):
  from dotenv import dotenv_values
  key=os.environ.get('OPENROUTER_API_KEY') or dotenv_values(Path(s['project_root'])/'.env').get('OPENROUTER_API_KEY')
  if not key:raise ValueError('Existing OpenRouter credential missing')
  b=ChatCompletionsBackend('https://openrouter.ai/api/v1',s['model'],key,timeout=s['request_timeout'],max_tokens=s['max_tokens'],supports_images=True,session_routing=True,request_options={'provider':s['provider_options'],'reasoning':{'enabled':phase=='policy'}})
  # Native runner owns policy begin_episode after environment activation.
  if phase=='formatter':admission.before_dispatch();b.begin_episode(s['suite_id']+'-'+c['id']+'-formatter')
  def dispatched(req):before(phase);record({'event':'dispatch','phase':phase,'request_sha256':sha256(req.content).hexdigest()})
  def received(resp):
   resp.read()
   try:v=resp.json()
   except ValueError:v={}
   u=v.get('usage') or {};cost=u.get('cost')
   if type(cost) in (int,float):counts['reported_cost_usd']+=cost
   else:counts['responses_without_cost']+=1
   record({'event':'response','phase':phase,'http_status':resp.status_code,'model':v.get('model'),'provider':v.get('provider'),'usage':u,'response_id':v.get('id')})
  b.client.event_hooks={'request':[dispatched],'response':[received]};return b
 @contextmanager
 def session(*,before_dispatch):
  if scripted:
   import httpx
   b=ChatCompletionsBackend('http://offline.invalid/v1','scripted',supports_images=True);b.client.close()
   answer=load(checked(c['scripted_answer']))['text']
   def dispatched(req):
    before_dispatch();before('policy')
    # Keeps initial active controls alive while the fourth environment parks.
    time.sleep(s.get('scripted_hold_seconds',0))
    return httpx.Response(200,json={'choices':[{'finish_reason':'tool_calls','message':{'role':'assistant','content':None,'tool_calls':[{'id':'positive','type':'function','function':{'name':'send_msg_to_user','arguments':json.dumps({'text':answer})}}]}}],'usage':{}})
   b.client=httpx.Client(transport=httpx.MockTransport(dispatched))
  else:b=backend('policy')
  try:yield b
  finally:b.close()
 class Formatter:
  model='scripted'
  def complete(self,messages):
   before('formatter');payload=json.loads(messages[1]['content'])
   if payload['final_answer']!=load(checked(c['scripted_answer']))['text']:raise ValueError('Scripted delivered answer changed')
   text=json.dumps(load(checked(c['scripted_claims'])))
   return types.SimpleNamespace(text=text,request={'messages':messages},raw={'model':'scripted','choices':[{'finish_reason':'stop','message':{'content':text}}],'usage':{}})
  def close(self):pass
 def environment_ready(ready):
  timings['environment_ready_monotonic']=time.monotonic();timings['ready_episode_id']=ready.episode_id;timings['ready_trace']=str(ready.directory)
  save(out/'warm-ready.json',dict(timings));signal.alarm(0)
  admission.environment_admission(ready)
  timings['activated_monotonic']=time.monotonic();save(out/'activated.json',dict(timings));signal.alarm(180 if scripted else s['episode_timeout'])
 def runner(factory,b,metadata,**kw):
  from dataclasses import replace
  if kw['automatic_grading'].phase!='external':raise ValueError('Attached native automatic grader required')
  p=h['policy_profile'](kw['harness_profile'],discovery=False)
  shared=SharedTokenizerConfig(s['tokenizer_socket'])
  kw['harness_profile']=replace(p,ax_config=replace(p.ax_config,shared_tokenizer=shared))
  sizing=types.SimpleNamespace(model=s['model'],base_url='https://openrouter.ai/api/v1',request_options={'reasoning':{'enabled':True}}) if scripted else b
  kw['input_counter']=model_matched_input_counter(sizing,assets_root=s['counter_assets_root'],shared_tokenizer=shared)
  kw['environment_admission']=environment_ready;kw['retry_policy']=None
  def make_env(video=None):
   timings['environment_creation_monotonic']=time.monotonic();env=factory(video)
   # Count actual reset on this one instance without altering native class/type guards.
   original=env.reset
   def reset(*a,**k):timings['reset_calls']+=1;return original(*a,**k)
   env.reset=reset
   return env
  return run_episode(make_env,b,metadata,**kw)
 def projection(*,trace,grade):
  if not Path(trace).resolve().is_relative_to(out/'live/runs'):raise ValueError('Trace escaped case')
  result=h['verify_projection'](s,trace);save(out/'grade-viewer.json',result);return result
 try:
  result=run(c['argument'],out/'live',policy_session=session,metadata={'suite':s['suite_id'],'source':s['suite_id'],'case':c['id'],'model':'scripted' if scripted else s['model'],'tags':['scripted','queue-acceptance'] if scripted else ['mimo','queue8'],'training_eligible':False},runner_options={'max_steps':1 if scripted else s['max_steps'],'max_input_tokens':s['max_input_tokens'],'trace_screenshots':True,'async_recording':False},viewer_projection=projection,quota_guard=guard,runner=runner,**h['case_options'](c,lambda _:Formatter() if scripted else backend('formatter')))
  if result.get('status')!='graded_and_projected':raise ValueError('Missing automatic grading/HTTP projection: '+str(result))
  if scripted and result['viewer_projection']['task_completed'] is not True:raise ValueError('Scripted positive native grade did not pass')
  if timings['reset_calls']!=1:raise ValueError('Warm activation reset or duplicated environment')
  timings['finished_monotonic']=time.monotonic()
  save(out/'result.json',{'case':c['id'],'result':result,'status':'graded_and_projected','timings':timings,'usage':counts,'scripted':scripted})
 except BaseException as e:
  save(out/'failure.json',{'type':type(e).__name__,'message':str(e),'usage':counts,'timings':timings});raise
 finally:signal.alarm(0);connection.close()


def timing_record(ident,t,start,initially_warming):
 first=t.get('first_policy_dispatch_monotonic')
 return {'case':ident,'initially_warming':initially_warming,
  'process_to_ready_s':t['environment_ready_monotonic']-start,
  'environment_creation_to_ready_s':t['environment_ready_monotonic']-t['environment_creation_monotonic'],
  'parked_ready_s':t['activated_monotonic']-t['environment_ready_monotonic'],
  'activation_to_first_policy_dispatch_s':None if first is None else first-t['activated_monotonic'],
  'process_to_first_policy_dispatch_s':None if first is None else first-start,
  'policy_dispatch_observed':first is not None,'reset_calls':t['reset_calls']}


def supervise(s,scripted=False):
 if not scripted:check_release(s)
 h=helper(s);source_guard(s)
 queue=runpy.run_path(str(checked(s['queue'])));channel=runpy.run_path(str(checked(s['channel'])))
 out=Path(s['output']);out.mkdir(parents=True,exist_ok=False)
 save(out/'supervisor-start.json',{'pid':os.getpid(),'process_start':h['process_identity'](os.getpid()),'epoch':time.time(),'monotonic':time.monotonic()})
 api=runpy.run_path(str(checked(s['events_helper'])));events=api['Events'](out/'completion.sqlite')
 events.register(s['suite_id'],[c['id'] for c in s['cases']])
 if not scripted:
  for c in s['cases']:events.subscribe(s['suite_id']+'-'+c['id'],s['suite_id'],'codex:'+s['thread_id'],episode=c['id'],final=False)
  events.subscribe(s['suite_id']+'-suite',s['suite_id'],'codex:'+s['thread_id'],milestones=[4],final=True)
 h['register_roots'](s)
 stop=threading.Event();service=None;listeners={};clocks={};lock=threading.Lock();delivery_lock=threading.Lock()
 with tempfile.TemporaryDirectory(prefix='mq8-') as tmp:
  os.chmod(tmp,0o700);s=dict(s);s['tokenizer_socket']=str(Path(tmp)/'tokenizer.sock');s['sockets']={}
  assets=[Path(s['counter_assets_root'])/'mimo-v2.6-pro-73875d00/tokenizer.json',checked(s['tokenizer'])]
  manifest=Path(tmp)/'assets.json';save(manifest,[{'path':str(a),'sha256':pin(a)['sha256'],'normalization':'raw'} for a in assets])
  root=s['cases'][0]['root']
  service=subprocess.Popen([s['python'],'-I','-B','-c',"import sys;sys.path.insert(0,sys.argv[1]);from intent_browser.tokenizer_service import main;sys.argv=sys.argv[1:];sys.argv[0]='tokenizer_service';main()",root,'--socket',s['tokenizer_socket'],'--manifest',str(manifest),'--max-clients','4'],stdout=subprocess.PIPE,stderr=(out/'tokenizer-stderr.log').open('x'),text=True,env={**os.environ,'LD_LIBRARY_PATH':s['library_path']})
  try:
   import select
   if not select.select([service.stdout],[],[],30)[0] or json.loads(service.stdout.readline()).get('ready') is not True:raise RuntimeError('Shared tokenizer host not ready')
   for c in s['cases']:
    listener=socket.socket(socket.AF_UNIX);path=str(Path(tmp)/(c['id']+'.sock'));listener.bind(path);listener.listen(1);listener.settimeout(s['startup_timeout']);listeners[c['id']]=listener;s['sockets'][c['id']]=path
   runtime=out/'runtime-spec.json';save(runtime,s)
   def one(c,admission):
    ident=c['id'];events.start(s['suite_id'],ident);started=time.monotonic();process=None;connection=None
    with lock:clocks[ident]={'process_launch_monotonic':started}
    try:
     stdout=(out/(ident+'-stdout.log')).open('x');stderr=(out/(ident+'-stderr.log')).open('x')
     process=subprocess.Popen(['python3',s['launcher']['path'],'--memory-mib','2048','--tasks','256','--receipt',str(out/(ident+'-bounded')),'--','timeout','--kill-after=30s',str(s['suite_timeout'])+'s',s['python'],'-I','-B',s['driver']['path'],'scripted-case' if scripted else 'case',str(runtime),ident],stdout=stdout,stderr=stderr,env={**os.environ,'LD_LIBRARY_PATH':s['library_path']})
     connection,_=listeners[ident].accept();connection.settimeout(s['suite_timeout'])
     # Ready receipt precedes gate; activation reply is emitted only under queue's cap.
     proof=channel['serve_admission'](connection,admission,expected_run_root=out/ident/'live/runs')
     code=process.wait(timeout=60);stdout.close();stderr.close()
     if code!=0:raise RuntimeError('Child lifecycle exited '+str(code))
     result=load(out/ident/'result.json');grade=load(out/ident/'grade-viewer.json')
     if result['status']!='graded_and_projected' or grade['status']!='verified':raise ValueError('Child grading/viewer unavailable')
     task=result['result']['viewer_projection']['task_completed'];payload={'result':pin(out/ident/'result.json'),'viewer':grade,'usage':result['usage'],'task_verdict':'pass' if task is True else 'fail' if task is False else 'inconclusive'}
     events.finish(s['suite_id'],ident,'succeeded',payload)
     if not scripted:
      with delivery_lock:api['flush'](events)
     return {'case':ident,'state':'succeeded','payload':payload,'admission':proof}
    except BaseException as e:
     events.finish(s['suite_id'],ident,'failed',{'system_failure':{'type':type(e).__name__,'message':str(e)},'task_verdict':None})
     if not scripted:
      with delivery_lock:api['flush'](events)
     raise
    finally:
     if connection:connection.close()
     if process and process.poll() is None:
      process.terminate()
      try:process.wait(timeout=35)
      except subprocess.TimeoutExpired:process.kill();process.wait(timeout=10)
     with lock:clocks[ident]['lifecycle_finished_monotonic']=time.monotonic()
   result=queue['run_ordered_suite']({c['id']:c for c in s['cases']},one,max_concurrent_episodes=s['max_concurrent_episodes'],prewarm_count=s['prewarm_count'],start_order=s['start_order'],stop_event=stop)
   result['max_observed_active']=max(e['active'] for e in result['events']);result['max_observed_warming']=max(e['warming_or_ready'] for e in result['events']);result['clocks']=clocks
   if result['max_observed_active']>3 or result['max_observed_warming']>1:raise RuntimeError('Concurrency/warming bound violated')
   save(out/'suite-result.json',result)
   measurements=[]
   warm_ids={e['case'] for e in result['events'] if e['event']=='warmup_started'}
   for ident in s['start_order']:
    path=out/ident/'result.json'
    if not path.is_file():continue
    t=load(path)['timings'];start=clocks[ident]['process_launch_monotonic']
    measurements.append(timing_record(ident,t,start,ident in warm_ids))
   save(out/'suite-measurements.json',{'max_active':result['max_observed_active'],
    'max_warming_or_parked':result['max_observed_warming'],'cases':measurements,
    'qualification':'Setup and activation timing within one cohort of different tasks; not a paired causal speedup experiment.'})
   if any(r['status']!='completed' for r in result['cases'].values()):raise RuntimeError('One or more case infrastructure failures')
   if not scripted:api['flush'](events)
  finally:
   stop.set()
   for listener in listeners.values():listener.close()
   if service and service.poll() is None:service.terminate();service.wait(timeout=10)


def main():
 mode,path,*rest=sys.argv[1:];s=load(path)
 if mode in ('case','scripted-case'):execute(s,next(c for c in s['cases'] if c['id']==rest[0]),mode=='scripted-case')
 elif mode in ('supervise','scripted'):supervise(s,mode=='scripted')
 else:raise ValueError('Unknown mode')
if __name__=='__main__':main()
