"""Finite MiMo/Luna comparison cases sharing one capped, prewarming queue."""
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
import json,math,os,runpy,signal,socket,sqlite3,subprocess,sys,tempfile,threading,time,types,importlib.util

class EpisodeDeadline(BaseException):
 """Termination must bypass optional recording's ordinary error fallback."""

class CaseDeadline(RuntimeError):
 """Legacy independent watchdog error; Qwen retains cohort stop on unverified capacity cleanup."""


def signal_deadline(*_):
 for kind in (signal.SIGTERM,signal.SIGINT,signal.SIGALRM):signal.signal(kind,signal.SIG_IGN)
 signal.alarm(0)
 raise EpisodeDeadline('Case startup/active watchdog or termination')


def subscription_guard(guard_type, output):
 # The frozen guard owns its loop-safe fresh RPC reader. A custom asyncio.run
 # callback breaks admission inside the bridge backend's active event loop.
 return guard_type(output,remaining_floor=1)


def load(p):return json.loads(Path(p).read_bytes())
def save(p,v):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('x') as f:json.dump(v,f,indent=2,ensure_ascii=False,allow_nan=False);f.write('\n')
def pin(p):return {'path':str(Path(p).resolve()),'sha256':sha256(Path(p).read_bytes()).hexdigest()}
def checked(r):
 p=Path(r['path'])
 if p.is_symlink() or pin(p)!=r:raise ValueError('Pinned input changed: '+str(p))
 return p

def qwen_mode(s):return s.get('runtime_mode')=='qwen-private-v1'

def qwen_modules(s):
 for value in s['qwen_sources'].values():checked(value)
 runtime=runpy.run_path(str(checked(s['qwen_sources']['runtime'])))
 observer=runpy.run_path(str(checked(s['qwen_sources']['observer'])))
 return runtime,observer

def capacity_modules(s):
 # One isolated controller namespace; telemetry uses that exact class copy.
 name='_qwen_suite_capacity_frozen'
 if name in sys.modules:raise RuntimeError('Capacity namespace already loaded')
 package=types.ModuleType(name);package.__path__=[];sys.modules[name]=package
 result={}
 try:
  for key,relative in (('control','capacity_control'),('telemetry','serving_telemetry')):
   location=checked(s['qwen_sources'][key])
   spec=importlib.util.spec_from_file_location(name+'.'+relative,location)
   module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module);result[key]=module
  result['rpc']=types.SimpleNamespace(**runpy.run_path(str(checked(s['qwen_sources']['rpc']))))
  return result
 except BaseException:
  for key in (name,name+'.capacity_control',name+'.serving_telemetry'):sys.modules.pop(key,None)
  raise

def validate_qwen_limits(s):
 if (s.get('max_steps') is not None or s.get('episode_timeout') is not None
     or s.get('max_input_tokens')!=250000 or s.get('server_context_tokens')!=262144
     or type(s.get('max_tokens')) is not int or not 0<s['max_tokens']<=16384
     or type(s.get('request_timeout')) is not int or not 0<s['request_timeout']<=600
     or type(s.get('startup_timeout')) is not int or not 0<s['startup_timeout']<=900):
  raise ValueError('Explicit Qwen native context/input/headroom and request/startup limits required')
 if any(c.get('policy_model')!='Qwen/Qwen3.8-27B-FP8' or c.get('max_input_tokens')!=250000
        or c.get('id')!='qwen-'+c.get('task_id','') for c in s['cases']):
  raise ValueError('One exact Qwen model and task identity per finite case required')
 if not s.get('shared_tokenizer') or not s.get('shared_chromium'):
  raise ValueError('This prospective Qwen composition requires the qualified pooled runtime')
 canaries=s.get('canary_task_ids')
 if canaries!=['B02','B14','H03','H05'] or s.get('start_order',[])[:4]!=['qwen-'+i for i in canaries]:raise ValueError('Four declared canaries must lead the queue')
 for case in s['cases']:checked(case['recipe_manifest'])
 for row in s['qwen_sources'].values():checked(row)

def qwen_live(s):
 runtime,_=qwen_modules(s);admission=runtime['ServingAdmission'](s['serving_live'])
 if admission.fingerprint!=s['serving_compatibility_fingerprint']:
  raise ValueError('Expected reviewed serving compatibility differs from current instance')
 return runtime,admission


def helper(s):return runpy.run_path(str(checked(s['helpers'])))
def config_hash(s):
 excluded={'review','sockets','tokenizer_socket'}
 if qwen_mode(s):excluded|={'serving_live','rental_deadline_utc','capacity_bindings','chromium_descriptor'}
 return sha256(json.dumps({k:v for k,v in s.items() if k not in excluded},sort_keys=True,ensure_ascii=False).encode()).hexdigest()

def case_binding(c):
 # Scripted answers/journeys are control inputs, not real-case identity.
 return sha256(json.dumps({k:v for k,v in c.items() if not k.startswith('scripted_') and k!='accepted_trace'},sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()

def execution_binding(s,c):
 excluded={'review','ready','cases','start_order','output','completion_db','suite_id','spec_path','sockets','tokenizer_socket','chromium_descriptor','scripted_hold_seconds','case_dependencies'}
 if qwen_mode(s):excluded|={'serving_live','rental_deadline_utc','capacity_bindings','chromium_descriptor'}
 fields={k:v for k,v in s.items() if k not in excluded}
 fields['case_dependencies']=s.get('case_dependencies',{}).get(c['id'],[])
 return sha256(json.dumps(fields,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()

def verify_ready_case(s,c,row):
 if row.get('case')!=c['id']:raise ValueError('Acceptance belongs to another case')
 result=load(checked(row['result']))
 if (result.get('case')!=c['id'] or result.get('scripted') is not True
     or result.get('case_binding_sha256')!=case_binding(c)
     or result.get('execution_binding_sha256')!=execution_binding(s,c)
     or result.get('caller_driver')!=s['driver']
     or result.get('caller_commit')!=s['caller_commit']
     or result.get('status')!='graded_and_projected'
     or result['result']['viewer_projection'].get('task_completed') is not True):
  raise ValueError('Acceptance does not bind this scripted case/driver/recipe')

class CaseWatchdog:
 """Parent-owned wall-clock limits, independent of child's signal handling.

 Startup ends at validated ready. Parked warm actors have no active budget;
 activation starts the agreed episode budget. Expiry stops the owned bounded
 launcher and closes its control socket. Containment is not native cleanup.
 """
 def __init__(self,process,connection_holder,*,startup_seconds,episode_seconds,cleanup_grace_seconds=30,stop_event=None,clock=time.monotonic,rental_deadline=None):
  for value in (startup_seconds,cleanup_grace_seconds)+(() if episode_seconds is None else (episode_seconds,)):
   if type(value) not in (int,float) or not math.isfinite(value) or value<=0:raise ValueError('Positive finite case watchdog limits required')
  if episode_seconds is None and (type(rental_deadline) not in (int,float) or not math.isfinite(rental_deadline) or rental_deadline<=clock()):raise ValueError('No episode ceiling requires a future finite rental deadline')
  self.rental_deadline=rental_deadline
  self.process,self.connections,self.clock=process,connection_holder,clock
  self.episode_seconds=episode_seconds;self.grace=cleanup_grace_seconds;self.suite_stop=stop_event
  self.deadline=clock()+startup_seconds+cleanup_grace_seconds
  if rental_deadline is not None:self.deadline=min(self.deadline,rental_deadline+cleanup_grace_seconds)
  self.phase='startup';self.failure=None;self.lock=threading.Lock();self.stop=threading.Event()
  self.thread=threading.Thread(target=self._run,daemon=True);self.thread.start()
 def ready(self):
  with self.lock:
   if self.failure is not None:raise CaseDeadline(str(self.failure))
   self.phase='parked';self.deadline=None if self.rental_deadline is None else self.rental_deadline+self.grace
 def activate(self):
  with self.lock:
   if self.failure is not None:raise CaseDeadline(str(self.failure))
   self.phase='active';self.deadline=(self.rental_deadline if self.episode_seconds is None else self.clock()+self.episode_seconds)+self.grace
 def _run(self):
  while not self.stop.wait(.05):
   with self.lock:
    if self.process.poll() is not None:return
    if self.suite_stop is not None and self.suite_stop.is_set() and self.phase!='suite_stop':
     self.phase='suite_stop';self.deadline=self.clock()+self.grace
     connection=self.connections.get('connection')
     if connection is not None:
      try:connection.shutdown(socket.SHUT_RDWR)
      except OSError:pass
    if self.deadline is None or self.clock()<self.deadline:continue
    self.failure={'phase':self.phase,'reason':'independent_case_deadline','observed_monotonic':self.clock()}
   try:self.process.terminate() # Popen owns/reaps the launcher PID; it kills its bounded scope.
   except ProcessLookupError:pass
   finally:
    connection=self.connections.get('connection')
    if connection is not None:
     try:connection.shutdown(socket.SHUT_RDWR)
     except OSError:pass
   return
 def close(self):
  self.stop.set();self.thread.join(2)
  if self.thread.is_alive():raise RuntimeError('Case watchdog did not stop')

class CanaryBarrier:
 def __init__(self,case_ids,stop_event):
  self.ids=set(case_ids);self.stop=stop_event;self.completed=set();self.event=threading.Event();self.lock=threading.Lock()
  if not self.ids:raise ValueError('Explicit nonempty canary cohort required')
 def wait(self,ident):
  if ident in self.ids:return
  while not self.event.wait(.05):
   if self.stop.is_set():raise RuntimeError('Canary qualification aborted; remainder not dispatched')
  if self.stop.is_set():raise RuntimeError('Suite stopped before remainder activation')
 def fail(self,ident):
  if ident in self.ids:self.stop.set();self.event.set()
 def complete(self,ident):
  if ident not in self.ids:return
  with self.lock:
   if ident in self.completed:raise RuntimeError('Duplicate canary completion')
   self.completed.add(ident)
   if self.completed==self.ids:self.event.set()


class WatchedAdmission:
 def __init__(self,admission,watchdog):self.admission,self.watchdog=admission,watchdog
 def __getattr__(self,name):return getattr(self.admission,name)
 def environment_ready(self,ready=None):
  self.watchdog.ready();self.admission.environment_ready(ready);self.watchdog.activate()
def source_guard(s,c=None):
 checked(s['driver']);checked(s['helpers']);checked(s['events_helper'])
 if c is not None:
  checked(c['recipe_manifest'])
  if 'source_export' in c:
   if not qwen_mode(s):raise ValueError('Exported cases require explicit Qwen mode')
   helper(s)['verify_source_export'](c['root'],c['commit'],c['source_export'],{})
 if qwen_mode(s):
  for row in s['qwen_sources'].values():checked(row)
 if 'authorization' in s:checked(s['authorization'])
 if 'transport' in s:
  for row in s['transport']['files']:checked(row)
  for name in ('node','bridge_worker','pi'):checked(s[name])
 if 'source_export' in s:
  if not qwen_mode(s):raise ValueError('Exported sources require explicit Qwen mode')
  required={'scripts/comparison_suite.py':s['driver']['sha256'],'scripts/comparison_suite_helpers.py':s['helpers']['sha256']}
  for row in s['qwen_sources'].values():
   location=Path(row['path']).resolve()
   if location.is_relative_to(Path(s['caller_root']).resolve()):required[str(location.relative_to(Path(s['caller_root']).resolve()))]=row['sha256']
  helper(s)['verify_source_export'](s['caller_root'],s['caller_commit'],s['source_export'],required)
 elif not Path(s['driver']['path']).read_bytes()==subprocess.check_output(['git','-C',s['caller_root'],'show',s['caller_commit']+':scripts/comparison_suite.py']):raise ValueError('Caller differs from committed source')

def check_release(s):
 source_guard(s)
 if qwen_mode(s):return check_qwen_release(s)
 authorized=load(checked(s['authorization']))
 if ([c['id'] for c in s['cases']]!=s['start_order'] or s['start_order']!=[i for i in authorized['case_ids'] if i in {c['id'] for c in s['cases']}]
     or len(set(s['start_order']))!=len(s['cases']) or s['max_concurrent_episodes']!=authorized['max_active_combined'] or s['prewarm_count']!=authorized['prewarm_count']
     or any(c['policy_model'] not in ('xiaomi/mimo-v2.6-pro','gpt-6-luna') for c in s['cases'])):
  raise ValueError('Require exact authorized subset/order and concurrency/warming limits')
 for c in s['cases']:
  if c['max_input_tokens']!=authorized['max_input_tokens'][c['policy_model']]:raise ValueError('Input capacity changed')
  prefix={'xiaomi/mimo-v2.6-pro':'mimo','gpt-6-luna':'luna'}[c['policy_model']]
  if not isinstance(c.get('task_id'),str) or c['id']!=prefix+'-'+c['task_id']:raise ValueError('Case/model/task identity mismatch')
 r=load(checked(s['review']));a=load(checked(s['ready']))
 if r['status']!='approved' or r['configuration_sha256']!=config_hash(s) or a['status']!='passed' or a['driver']!=s['driver'] or {v['case'] for v in a['cases']}!={c['id'] for c in s['cases']}:raise ValueError('Missing reviewed configuration or actual scripted acceptance')
 if len(a['cases'])!=len(s['cases']):raise ValueError('Duplicate acceptance case')
 by_id={c['id']:c for c in s['cases']}
 for v in a['cases']:verify_ready_case(s,by_id[v['case']],v)


def check_qwen_release(s):
 validate_qwen_limits(s)
 authorized=load(checked(s['authorization']))
 ids=[c['id'] for c in s['cases']]
 if (len(set(ids))!=len(ids) or ids!=s['start_order'] or ids!=authorized['case_ids']
     or authorized.get('dispatch_authorized') is not True
     or authorized.get('allocation_authorized') is not True
     or authorized['max_active_combined']!=s['max_concurrent_episodes']
     or authorized['prewarm_count']!=s['prewarm_count']
     or authorized.get('max_input_tokens')!=250000):
  raise ValueError('Actual finite Qwen episode/rental authorization required')
 review=load(checked(s['review']));ready=load(checked(s['ready']))
 if (review.get('status')!='approved' or review.get('configuration_sha256')!=config_hash(s)
     or ready.get('status')!='passed' or ready.get('driver')!=s['driver']
     or len(ready['cases'])!=len(ids) or {v['case'] for v in ready['cases']}!=set(ids)):
  raise ValueError('Exact reviewed Qwen configuration and actual scripted case acceptance required')
 for row in ready['cases']:verify_ready_case(s,next(c for c in s['cases'] if c['id']==row['case']),row)
 _,live=qwen_live(s)
 if live.live.get('dispatch_authorized') is not True:raise ValueError('Current live contract cannot dispatch')
 if authorized['approved_rental_seconds']!=live.deployment['approved_rental_seconds']:
  raise ValueError('Actual allocation rental differs from finite approval')
 live.readiness()



def address_projection_result(trace, result):
 """Adapt the scoped address publisher's verified result, retaining its scope."""
 canonical=load(Path(trace)/'evaluation.json')
 expected={'pass':True,'fail':False,'inconclusive':None}
 verdict=result.get('native_verdict')
 if result.get('status')!='verified' or verdict not in expected or canonical.get('task_completed') is not expected[verdict]:
  raise ValueError('Address publisher/canonical verdict disagreement')
 return {**result,'task_completed':canonical['task_completed'],
  'automatic':pin(Path(trace)/'automatic-grading.json'),'canonical':pin(Path(trace)/'evaluation.json')}

def flush_completions(s,events,api):
 if not qwen_mode(s):return api['flush'](events)
 # Remote VM has no Codex daemon or subscription credentials. Preserve notices
 # pending; workstation delivery uses the existing Events helper on this snapshot.
 out=Path(s['output']);folder=out/'completion-snapshots';folder.mkdir(exist_ok=True)
 destination=folder/(str(time.time_ns())+'.sqlite');destination.touch(exist_ok=False)
 source=sqlite3.connect('file:'+str(Path(s['completion_db']).resolve())+'?mode=ro',uri=True)
 target=sqlite3.connect(destination)
 try:source.backup(target)
 finally:target.close();source.close()
 with (out/'completion-return.jsonl').open('a') as stream:
  stream.write(json.dumps({'schema':'qwen-completion-return-v1','snapshot':pin(destination),
   'notices':events.notices(),'delivery_owner':'workstation existing Events helper',
   'remote_delivery_attempts':0})+'\n')

def file_digest(path):
 result=sha256()
 with Path(path).open('rb') as stream:
  for chunk in iter(lambda:stream.read(1024*1024),b''):result.update(chunk)
 return result.hexdigest()

def terminal_inventory(s):
 out=Path(s['output'])
 if not out.is_dir():return
 rows=[];rejected=[]
 for path in sorted(out.rglob('*')):
  if path.is_symlink():rejected.append(str(path.relative_to(out)));continue
  if path.is_file() and path.name!='terminal-artifacts.json':
   rows.append({'relative_path':str(path.relative_to(out)),'bytes':path.stat().st_size,
                'sha256':file_digest(path)})
 save(out/'terminal-artifacts.json',{'schema':'qwen-suite-terminal-artifacts-v1','private':True,
  'suite_id':s['suite_id'],'source_driver':s['driver'],'files':rows,'rejected_symlinks':rejected,
  'qualification':'Transport inventory only; individual infrastructure/task outcomes remain in Events and canonical grades.'})


def record_capacity(out,row):
 with (out/'capacity-events.jsonl').open('a') as stream:stream.write(json.dumps(row)+'\n')


def execute(s,c,scripted=False):
 if type(s.get('shared_chromium',False)) is not bool:raise ValueError('shared_chromium must be boolean')
 if s.get('shared_chromium') and not scripted and not qwen_mode(s):raise ValueError('Pooled comparison caller is model-free qualification only')
 if not scripted:
  check_release(s)
  with sqlite3.connect('file:'+str(Path(s.get('completion_db',str(Path(s['output'])/'completion.sqlite'))))+'?mode=ro',uri=True) as db:
   if db.execute('SELECT state FROM episodes WHERE suite=? AND id=?',(s['suite_id'],c['id'])).fetchone()!=('running',):raise ValueError('Case not claimed by subscribed supervisor')
 h=helper(s);run=h['configure_case'](s,c);source_guard(s,c)
 from intent_browser.backend import ChatCompletionsBackend
 from intent_browser.runner import run_episode
 from intent_browser.episode_admission import EpisodeAdmissionCancelled
 from intent_browser.model_input_budget import model_matched_input_counter
 from intent_browser.shared_tokenizer import SharedTokenizerConfig
 from intent_browser.input_budget import OpaqueReasoningInputCounter,QwenInputCounter
 channel=runpy.run_path(str(checked(s['channel'])))
 out=Path(s['output'])/c['id'];out.mkdir(parents=True,exist_ok=False)
 authority=load(Path(s['output'])/'supervisor-start.json')
 timings={'worker_started_monotonic':time.monotonic(),'reset_calls':0,'policy_requests':0,'formatter_requests':0}
 save(out/'start.json',{'case':c['id'],'pid':os.getpid(),'epoch':time.time(),'monotonic':timings['worker_started_monotonic'],'scripted':scripted})
 connection=socket.socket(socket.AF_UNIX);connection.settimeout(s['suite_timeout']);connection.connect(s['sockets'][c['id']])
 admission=channel['ChildAdmission'](connection,c['id'],EpisodeAdmissionCancelled)
 signal.signal(signal.SIGTERM,signal_deadline);signal.signal(signal.SIGALRM,signal_deadline);signal.alarm(s['startup_timeout'])
 recording=None;native_run=run_episode
 inspection_out=out/'inspection';inspection_out.mkdir()
 try:
  receipt=load(checked(s['inspection_package']))
  loader=runpy.run_path(str(checked(receipt['loader'])))
  recording,pins=loader['load_recording'](receipt['package_root'],receipt['relative_source_sha256'])
  native_run=recording.recording_runner(run_episode,enabled=True,expected_sources=pins,report=inspection_out/'recording-status.json')
 except (TimeoutError,KeyboardInterrupt,SystemExit):
  if recording is not None:recording.release_package()
  raise
 except Exception as error:
  if recording is not None:recording.release_package();recording=None
  save(inspection_out/'setup-failure.json',{'status':'disabled','reason':str(error),'error_type':type(error).__name__,'native_grade_unchanged':True})
 counts={'policy_requests':0,'formatter_requests':0,'reported_cost_usd':0.0,'responses_without_cost':0}
 profile=None;lease=None;pooled=None;capacity_client=None;factories=None;environment_holder={};pending_snapshot={}
 qwen=None;serving=None
 model=c['policy_model']
 if model=='gpt-6-luna' and not scripted:
  ExternalAgentBackend,BridgeServer,EpisodeConcurrency,SuiteEpisode,SubscriptionQuotaGuard,read_quota,normalize=h['load_transport'](s)
  quota=subscription_guard(SubscriptionQuotaGuard,out/'subscription-quota')
  lease=SuiteEpisode(EpisodeConcurrency(s['suite_id']+'-luna',s['max_concurrent_episodes'],s['luna_case_count']),
   Path(s['transport']['subscription_lock']),quota,model=model,reasoning_effort='medium',
   formatter_reasoning_effort='low',provider_output_limit=False)
 def guard():
  source_guard(s,c);h['module_origins'](s,c)
  if h['process_identity'](authority['pid'])!=authority['process_start']:raise RuntimeError('Supervisor lost')
  if lease is not None:h['transport_origins'](s)
 def before(phase):
  guard();admission.before_dispatch()
  now=time.monotonic()
  if phase=='policy':timings.setdefault('first_policy_dispatch_monotonic',now)
  else:timings.setdefault('first_formatter_dispatch_monotonic',now)
  counts[phase+'_requests']+=1
  if phase=='formatter' and counts['formatter_requests']>1:raise RuntimeError('One formatter maximum')
 def record(value):
  if qwen_mode(s) and value.get('event')=='response':counts['responses_without_cost']+=1
  with (out/'http-attempts.jsonl').open('a') as f:f.write(json.dumps({'epoch':time.time(),**value})+'\n')
 def backend(phase,consumer_before_dispatch=None):
  def dispatched_guard():
   if consumer_before_dispatch is not None:consumer_before_dispatch()
   before(phase)
  if model=='gpt-6-luna':
   if lease is None:raise RuntimeError('Missing case-owned subscription lease')
   raw=ExternalAgentBackend(model,out/(phase+'-transport'),reasoning_effort='medium' if phase=='policy' else 'low',
    timeout=s['request_timeout'],max_tokens=s['max_tokens'],provider_output_limit=False,
    command=[str(checked(s['node'])),str(checked(s['bridge_worker']))],pi_cli=str(checked(s['pi'])),
    before_dispatch=dispatched_guard,suite_episode=lease,episode_phase=phase)
   if phase=='formatter':raw.begin_episode(s['suite_id']+'/'+c['id']+'/formatter')
   return raw
  from dotenv import dotenv_values
  key=os.environ.get('OPENROUTER_API_KEY') or dotenv_values(Path(s['project_root'])/'.env').get('OPENROUTER_API_KEY')
  if not key:raise ValueError('Existing OpenRouter credential missing')
  selected=model if phase=='policy' else 'qwen/qwen3.8-27b'
  provider=s['provider_options'] if phase=='policy' else s['extractor_provider_options']
  b=ChatCompletionsBackend('https://openrouter.ai/api/v1',selected,key,timeout=s['request_timeout'],max_tokens=s['max_tokens'],supports_images=True,session_routing=True,request_options={'provider':provider,'reasoning':{'enabled':True}})
  if phase=='formatter':b.begin_episode(s['suite_id']+'-'+c['id']+'-formatter')
  def dispatched(req):dispatched_guard();record({'event':'dispatch','phase':phase,'request_sha256':sha256(req.content).hexdigest()})
  def received(resp):
   resp.read()
   try:v=resp.json()
   except ValueError:v={}
   if not isinstance(v,dict):v={}
   u=v.get('usage') or {}
   if not isinstance(u,dict):u={}
   cost=u.get('cost')
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
   journey=load(checked(c['scripted_journey'])) if c.get('scripted_journey') else None
   journey_index=0
   def dispatched(req):
    nonlocal journey_index
    before_dispatch();before('policy')
    # Keeps initial active controls alive while the fourth environment parks.
    time.sleep(s.get('scripted_hold_seconds',0))
    if journey is not None:
     if journey_index>=len(journey):raise ValueError('Scripted journey exhausted; no replay')
     response=journey[journey_index];journey_index+=1
     return httpx.Response(200,json=response)
    return httpx.Response(200,json={'choices':[{'finish_reason':'tool_calls','message':{'role':'assistant','content':None,'tool_calls':[{'id':'positive','type':'function','function':{'name':'send_msg_to_user','arguments':json.dumps({'text':answer})}}]}}],'usage':{}})
   b.client=httpx.Client(transport=httpx.MockTransport(dispatched))
  elif qwen_mode(s):
   with factories.policy_session(before_dispatch=before_dispatch) as b:yield b
   return
  else:b=backend('policy',before_dispatch)
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
  timings['activated_monotonic']=time.monotonic();save(out/'activated.json',dict(timings));signal.alarm(180 if scripted else max(1,math.ceil(serving.deadline-time.time())) if qwen_mode(s) else s['episode_timeout'])
  if lease is not None:
   proof=lease.begin_episode(c['id']);save(out/'subscription-admission.json',proof)
 def runner(factory,b,metadata,**kw):
  nonlocal pooled
  if s.get('shared_chromium'):
   from intent_browser.chromium_pool import PoolClient
   pooled=PoolClient.from_file(s['chromium_descriptor']).episode(s['suite_id']+'/'+c['id'])
   factory=pooled.wrap(factory)
  from dataclasses import replace
  if kw['automatic_grading'].phase!='external':raise ValueError('Attached native automatic grader required')
  p=h['policy_profile'](kw['harness_profile'],discovery=False)
  shared=SharedTokenizerConfig(s['tokenizer_socket'])
  kw['harness_profile']=replace(p,ax_config=replace(p.ax_config,shared_tokenizer=shared))
  if qwen_mode(s):
   kw['input_counter']=QwenInputCounter(checked(s['tokenizer']),shared_tokenizer=shared) if scripted else serving.runner_count
  elif model=='gpt-6-luna':
   kw['input_counter']=OpaqueReasoningInputCounter(QwenInputCounter(checked(s['tokenizer']),shared_tokenizer=shared))
  else:
   sizing=types.SimpleNamespace(model=model,base_url='https://openrouter.ai/api/v1',request_options={'reasoning':{'enabled':True}}) if scripted else b
   kw['input_counter']=model_matched_input_counter(sizing,assets_root=s['counter_assets_root'],shared_tokenizer=shared)
  kw['environment_admission']=environment_ready;kw['retry_policy']=None
  def make_env(video=None):
   timings['environment_creation_monotonic']=time.monotonic();env=factory(video);environment_holder['env']=env
   # Count actual reset on this one instance without altering native class/type guards.
   original=env.reset
   def reset(*a,**k):timings['reset_calls']+=1;return original(*a,**k)
   env.reset=reset
   return env
  return native_run(make_env,b,metadata,**kw)
 def projection(*,trace,grade):
  if not Path(trace).resolve().is_relative_to(out/'live/runs'):raise ValueError('Trace escaped case')
  result=h['project'](s,out,{**c,'id':c['task_id']},trace=trace,grade=grade)
  if c['task_id'] in ('H01','H02'):result=address_projection_result(trace,result)
  save(out/'grade-viewer.json',result);return result
 def browser_snapshot():
  env=environment_holder['env'];page=env.unwrapped.page
  if page.is_closed():raise RuntimeError('Browser closed before native dispatch')
  old_alarm=signal.alarm(max(1,math.ceil(min(5,serving.deadline-time.time()))));started=time.monotonic()
  try:value=page.evaluate("() => ({url:location.href,text:document.body.innerText,fields:Array.from(document.querySelectorAll('input,select,textarea')).map(e=>[e.tagName,e.name,e.type,e.value,e.checked])})")
  finally:signal.alarm(max(1,math.ceil(min(serving.deadline-time.time(),max(1,old_alarm-(time.monotonic()-started))))))
  return sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
 @contextmanager
 def qwen_turn(phase):
  if phase=='policy':pending_snapshot['before']=browser_snapshot()
  with capacity_client.turn(phase):yield
 def fresh(phase):
  # Final source/admission guards run once in before(), after count.
  if phase=='policy':
   current=browser_snapshot()
   if current!=pending_snapshot['before']:raise RuntimeError('Browser state changed while parked; stale policy request not dispatched')
   record({'event':'fresh_after_capacity_wait','phase':phase,'browser_semantic_sha256':current})
 try:
  if qwen_mode(s) and not scripted:
   qwen,serving=qwen_live(s)
   _,observer_module=qwen_modules(s)
   rpc=types.SimpleNamespace(**runpy.run_path(str(checked(s['qwen_sources']['rpc']))))
   capacity_client=observer_module['connect_client'](rpc,s['capacity_bindings'][c['id']],deadline=time.monotonic()+serving.deadline-time.time(),on_event=lambda row:record_capacity(out,row))
  if qwen_mode(s) and not scripted:
   factories=qwen['QwenFactories'](backend_class=ChatCompletionsBackend,admission=serving,
    before_policy=lambda:before('policy'),before_formatter=lambda:before('formatter'),meter=record,freshness_guard=fresh,
    max_output_tokens=s['max_tokens'],request_timeout=s['request_timeout'],turn=qwen_turn)
  result=run(c['argument'],out/'live',policy_session=session,metadata={'suite':s['suite_id'],'source':s['suite_id'],'case':c['id'],'model':'scripted' if scripted else model,'tags':['scripted','queue-acceptance'] if scripted else ['comparison',model,c['task_id']],'training_eligible':False},runner_options={'max_steps':c.get('scripted_max_steps',1) if scripted else s['max_steps'],'max_input_tokens':c['max_input_tokens'],'trace_screenshots':True,'async_recording':False},viewer_projection=projection,quota_guard=guard,runner=runner,**h['case_options']({**c,'id':c['task_id']},lambda path:Formatter() if scripted else factories.extraction_backend_factory(path) if qwen_mode(s) else backend('formatter')))
  if result.get('status')!='graded_and_projected':raise ValueError('Missing automatic grading/HTTP projection: '+str(result))
  if scripted and result['viewer_projection']['task_completed'] is not True:raise ValueError('Scripted positive native grade did not pass')
  if timings['reset_calls']!=1:raise ValueError('Warm activation reset or duplicated environment')
  timings['finished_monotonic']=time.monotonic()
  save(out/'result.json',{'case':c['id'],'result':result,'status':'graded_and_projected','timings':timings,'usage':counts,'scripted':scripted,'case_binding_sha256':case_binding(c),'execution_binding_sha256':execution_binding(s,c),'caller_driver':s['driver'],'caller_commit':s['caller_commit']})
 except BaseException as e:
  save(out/'failure.json',{'type':type(e).__name__,'message':str(e),'usage':counts,'timings':timings});raise
 finally:
  signal.alarm(0);connection.close()
  try:
   if lease is not None:lease.close()
  finally:
   try:
    if recording is not None:recording.release_package()
   finally:
    try:
     if pooled is not None:pooled.close()
    finally:
     if capacity_client is not None:capacity_client.close()
  save(out/'cleanup.json',{'status':'passed','case':c['id'],'wrapper_finalizers_returned':True,'recording_released':True,'pool_lease_released':pooled is not None,'capacity_channel_closed':capacity_client is not None,'capacity_infrastructure_error':None if capacity_client is None else capacity_client.infrastructure_error})


def timing_record(ident,t,start,initially_warming):
 first=t.get('first_policy_dispatch_monotonic')
 return {'case':ident,'initially_warming':initially_warming,
  'process_to_ready_s':t['environment_ready_monotonic']-start,
  'environment_creation_to_ready_s':t['environment_ready_monotonic']-t['environment_creation_monotonic'],
  'parked_ready_s':t['activated_monotonic']-t['environment_ready_monotonic'],
  'activation_to_first_policy_dispatch_s':None if first is None else first-t['activated_monotonic'],
  'process_to_first_policy_dispatch_s':None if first is None else first-start,
  'policy_dispatch_observed':first is not None,'reset_calls':t['reset_calls']}


def stop_pool_service(spec, root, output, process):
 """Ask the private broker to drain while its bounded launcher stays alive."""
 failure=None
 try:
  if process.poll() is not None:raise RuntimeError('Pool service exited before planned shutdown: '+str(process.returncode))
  if process.poll() is None:
   # Admin capability remains in the private service directory; it never enters
   # argv, worker descriptors, logs or the policy context.
   code="import sys,json;from pathlib import Path;sys.path.insert(0,sys.argv[1]);from intent_browser.chromium_pool import PoolClient;p=Path(sys.argv[2]);worker=PoolClient.from_file(p/'descriptor.json');cfg=json.loads((p/'config.json').read_bytes());PoolClient({**worker.descriptor,'secret':cfg['admin_secret']}).request('shutdown')"
   subprocess.run([spec['python'],'-I','-B','-c',code,str(root),str(Path(spec['chromium_descriptor']).parent)],check=True,timeout=15,stdout=subprocess.DEVNULL)
   process.wait(timeout=45)
  if process.returncode!=0:raise RuntimeError('Pool service exited abnormally: '+str(process.returncode))
 except BaseException as error:
  failure=error
 finally:
  if process.poll() is None:
   # The launcher kills its owned scope; this is failure containment only.
   process.terminate()
   try:process.wait(timeout=15)
   except subprocess.TimeoutExpired:process.kill();process.wait(timeout=10)
 if failure is not None:raise RuntimeError('Pool service failed graceful shutdown') from failure


def supervise(s,scripted=False):
 if type(s.get('shared_chromium',False)) is not bool:raise ValueError('shared_chromium must be boolean')
 if s.get('shared_chromium') and not scripted and not qwen_mode(s):raise ValueError('Pooled comparison caller is model-free qualification only')
 stop=threading.Event();previous={kind:signal.getsignal(kind) for kind in (signal.SIGTERM,signal.SIGINT,signal.SIGALRM)}
 def terminate_suite(*args):stop.set();signal_deadline(*args)
 try:
  signal.signal(signal.SIGTERM,terminate_suite);signal.signal(signal.SIGINT,terminate_suite)
  return _supervise(s,scripted,stop)
 finally:
  for kind,handler in previous.items():signal.signal(kind,handler)

def _supervise(s,scripted=False,stop=None):
 if type(s.get('shared_chromium',False)) is not bool:raise ValueError('shared_chromium must be boolean')
 if s.get('shared_chromium') and not scripted and not qwen_mode(s):raise ValueError('Pooled comparison caller is model-free qualification only')
 if qwen_mode(s):validate_qwen_limits(s)
 for name in (('startup_timeout','suite_timeout') if qwen_mode(s) else ('startup_timeout','episode_timeout','suite_timeout')):
  if type(s.get(name)) is not int or not 0<s[name]<2**31:raise ValueError('Positive integer '+name+' required before any case claim')
 grace=s.get('shutdown_grace_seconds',30)
 if type(grace) is not int or not 1<=grace<=120:raise ValueError('Explicit cleanup grace must be1..120 seconds')
 if not scripted:check_release(s)
 h=helper(s);source_guard(s)
 queue=runpy.run_path(str(checked(s['queue'])));channel=runpy.run_path(str(checked(s['channel'])))
 out=Path(s['output']);out.mkdir(parents=True,exist_ok=False)
 save(out/'supervisor-start.json',{'pid':os.getpid(),'process_start':h['process_identity'](os.getpid()),'epoch':time.time(),'monotonic':time.monotonic()})
 api=runpy.run_path(str(checked(s['events_helper'])));events=api['Events'](s.get('completion_db',out/'completion.sqlite'))
 members=load(checked(s['authorization']))['case_ids'] if not scripted else [c['id'] for c in s['cases']]
 events.register(s['suite_id'],members)
 if not scripted:
  for ident in members:events.subscribe(s['suite_id']+'-'+ident,s['suite_id'],'codex:'+s['thread_id'],episode=ident,final=False)
  events.subscribe(s['suite_id']+'-suite',s['suite_id'],'codex:'+s['thread_id'],milestones=[10,20,30,35,40,50],final=True)
 h['register_roots'](s)
 stop=stop if stop is not None else threading.Event();service=None;pool_service=None;pool_log=None;listeners={};clocks={};lock=threading.Lock();delivery_lock=threading.Lock();capacity_host=None;serving=None;canary_barrier=CanaryBarrier(['qwen-'+i for i in s['canary_task_ids']],stop) if qwen_mode(s) else None
 with tempfile.TemporaryDirectory(prefix='mq8-') as tmp:
  os.chmod(tmp,0o700);s=dict(s);s['tokenizer_socket']=str(Path(tmp)/'tokenizer.sock');s['sockets']={}
  assets=[checked(s['tokenizer'])] if qwen_mode(s) else [Path(s['counter_assets_root'])/'mimo-v2.6-pro-73875d00/tokenizer.json',checked(s['tokenizer'])]
  manifest=Path(tmp)/'assets.json';save(manifest,[{'path':str(a),'sha256':pin(a)['sha256'],'normalization':'raw'} for a in assets])
  root=s['cases'][0]['root']
  service=subprocess.Popen([s['python'],'-I','-B','-c',"import sys;sys.path.insert(0,sys.argv[1]);from intent_browser.tokenizer_service import main;sys.argv=sys.argv[1:];sys.argv[0]='tokenizer_service';main()",root,'--socket',s['tokenizer_socket'],'--manifest',str(manifest),'--max-clients',str(s['max_concurrent_episodes']+s['prewarm_count'])],stdout=subprocess.PIPE,stderr=(out/'tokenizer-stderr.log').open('x'),text=True,env={**os.environ,'LD_LIBRARY_PATH':s['library_path']})
  try:
   import select
   if not select.select([service.stdout],[],[],30)[0] or json.loads(service.stdout.readline()).get('ready') is not True:raise RuntimeError('Shared tokenizer host not ready')
   if s.get('shared_chromium'):
    pool_log=(out/'chromium-pool-stderr.log').open('x')
    pool_directory=(Path(tmp)/'chromium-pool').resolve()
    service_driver=checked(s['pool_service_driver'])
    if 'source_export' in s:h['verify_source_export'](s['caller_root'],s['caller_commit'],s['source_export'],{'scripts/shared_chromium_service.py':s['pool_service_driver']['sha256']})
    elif service_driver.read_bytes()!=subprocess.check_output(['git','-C',s['caller_root'],'show',s['caller_commit']+':scripts/shared_chromium_service.py']):raise ValueError('Pool service driver differs from committed source')
    checked(s['launcher'])
    for case in s['cases']:
     manifest=h['recipe_check'](case)
     required={'intent_browser/chromium_pool.py','intent_browser/assets/chromium_pool.cjs','intent_browser/shared_browsergym.py','intent_browser/browser_shutdown.py','intent_browser/runner.py'}
     if not required<=manifest['source_sha256'].keys():raise ValueError('Recipe omits pooled runtime source pins')
    owner=load(out/'supervisor-start.json')
    s['chromium_descriptor']=str(pool_directory/'descriptor.json')
    pool_service=subprocess.Popen(['python3',s['launcher']['path'],'--memory-mib','3072','--tasks','512','--receipt',str(out/'chromium-pool-bounded'),'--','timeout','--kill-after=30s',str(s['suite_timeout'])+'s',s['python'],'-I','-B',str(service_driver),'--source-root',root,'--owner-pid',str(owner['pid']),'--owner-start',owner['process_start'],'--directory',str(pool_directory),'--max-leases',str(2*(s['max_concurrent_episodes']+s['prewarm_count'])),'--per-server',str(s['max_concurrent_episodes']+s['prewarm_count'])],stdout=subprocess.PIPE,stderr=pool_log,text=True,env={**os.environ,'LD_LIBRARY_PATH':s['library_path']})
    if not select.select([pool_service.stdout],[],[],45)[0]:raise RuntimeError('Chromium pool service did not become ready')
    descriptor=pool_service.stdout.readline().strip()
    if descriptor!=str(pool_directory/'descriptor.json') or not Path(descriptor).is_file():raise RuntimeError('Chromium pool descriptor differs')
    s['chromium_descriptor']=descriptor
   if qwen_mode(s) and not scripted:
    _,serving=qwen_live(s);modules=capacity_modules(s);_,observer_module=qwen_modules(s)
    capacity_host=observer_module['CapacityHost'](rpc=modules['rpc'],control=modules['control'],telemetry=modules['telemetry'],source=s,output=out,case_ids=s['start_order'],cap=s['max_concurrent_episodes'],deadline=time.monotonic()+serving.deadline-time.time(),stop_event=stop,directory=tmp,qualification=serving)
    s['capacity_bindings']={ident:capacity_host.child_binding(ident) for ident in s['start_order']}
    save(out/'observer-transport.json',{'socket':str(capacity_host.observer_rpc.path),'epoch':capacity_host.journal.epoch,'observer_id':capacity_host.observer.observer_id,'session_id':serving.session,'journal':str(out/'serving-telemetry.jsonl'),'maximum_batch_rows':120,'WandB_owner':'workstation controller; no credentials here'})
   for c in s['cases']:
    listener=socket.socket(socket.AF_UNIX);path=str(Path(tmp)/(c['id']+'.sock'));listener.bind(path);listener.listen(1);listener.settimeout(s['startup_timeout']);listeners[c['id']]=listener;s['sockets'][c['id']]=path
   # Capability-bearing child spec lives in the private temporary transport tree.
   runtime=Path(tmp)/'runtime-spec.json';save(runtime,s)
   save(out/'runtime-spec.redacted.json',{k:v for k,v in s.items() if k not in {'capacity_bindings','sockets','tokenizer_socket','chromium_descriptor'}})
   def one(c,admission):
    ident=c['id'];events.start(s['suite_id'],ident);started=time.monotonic();process=None;connection=None;watchdog=None;connections={};stdout=None;stderr=None
    with lock:clocks[ident]={'process_launch_monotonic':started}
    try:
     stdout=(out/(ident+'-stdout.log')).open('x');stderr=(out/(ident+'-stderr.log')).open('x')
     if capacity_host is not None:capacity_host.begin_relay(ident)
     process=subprocess.Popen(['python3',s['launcher']['path'],'--memory-mib','2048','--tasks','256','--receipt',str(out/(ident+'-bounded')),'--','timeout','--kill-after=30s',str(s['suite_timeout'])+'s',s['python'],'-I','-B',s['driver']['path'],'scripted-case' if scripted else 'case',str(runtime),ident],stdout=stdout,stderr=stderr,env={**os.environ,'LD_LIBRARY_PATH':s['library_path']})
     watchdog=CaseWatchdog(process,connections,startup_seconds=s['startup_timeout'],episode_seconds=180 if scripted else s['episode_timeout'],cleanup_grace_seconds=grace,stop_event=stop,rental_deadline=None if serving is None else time.monotonic()+serving.deadline-time.time())
     connection,_=listeners[ident].accept();connection.settimeout(s['suite_timeout'])
     connections['connection']=connection
     # Ready receipt precedes gate; activation reply is emitted only under queue's cap.
     watched=WatchedAdmission(admission,watchdog)
     if capacity_host is not None or canary_barrier is not None:
      original=watched.environment_ready
      def ready(value=None):
       original(value)
       if canary_barrier is not None:canary_barrier.wait(ident)
       if capacity_host is not None:capacity_host.activate(ident,priority=s['start_order'].index(ident))
      watched.environment_ready=ready
     proof=channel['serve_admission'](connection,watched,expected_run_root=out/ident/'live/runs')
     code=process.wait(timeout=60);stdout.close();stderr.close()
     if watchdog.failure is not None:raise CaseDeadline(str(watchdog.failure))
     if code!=0:raise RuntimeError('Child lifecycle exited '+str(code))
     result=load(out/ident/'result.json');grade=load(out/ident/'grade-viewer.json')
     if result['status']!='graded_and_projected' or grade['status']!='verified':raise ValueError('Child grading/viewer unavailable')
     task=result['result']['viewer_projection']['task_completed'];payload={'result':pin(out/ident/'result.json'),'viewer':grade,'usage':result['usage'],'task_verdict':'pass' if task is True else 'fail' if task is False else 'inconclusive'}
     if capacity_host is not None:
      def cleanup():
       marker=load(out/ident/'cleanup.json')
       return process.poll()==0 and marker.get('status')=='passed' and marker.get('case')==ident and marker.get('capacity_channel_closed') is True and marker.get('capacity_infrastructure_error') is None
      capacity_host.finish(ident,verify_cleanup=cleanup,record_terminal=lambda:result['status']=='graded_and_projected' and grade['status']=='verified')
     events.finish(s['suite_id'],ident,'succeeded',payload)
     if not scripted:
      with delivery_lock:flush_completions(s,events,api)
     if canary_barrier is not None:canary_barrier.complete(ident)
     return {'case':ident,'state':'succeeded','payload':payload,'admission':proof}
    except BaseException as e:
     if canary_barrier is not None:canary_barrier.fail(ident)
     if watchdog is not None and watchdog.failure is not None:
      deadline_error=CaseDeadline(str(watchdog.failure));deadline_error.__cause__=e;e=deadline_error
     if capacity_host is not None:capacity_host.failed(ident,e,infrastructure=not isinstance(e,queue['QueueCancelled']))
     events.finish(s['suite_id'],ident,'failed',{'system_failure':{'type':type(e).__name__,'message':str(e)},'task_verdict':None})
     if not scripted:
      with delivery_lock:flush_completions(s,events,api)
     raise e
    finally:
     try:
      if watchdog is not None:
       watchdog.close();save(out/(ident+'-watchdog.json'),{'failure':watchdog.failure,'final_phase':watchdog.phase,'native_cleanup_not_inferred':True})
     finally:
      try:
       if connection:connection.close()
      finally:
       if process and process.poll() is None:
        process.terminate()
        try:process.wait(timeout=35)
        except subprocess.TimeoutExpired:process.kill();process.wait(timeout=10)
       if stdout is not None:stdout.close()
       if stderr is not None:stderr.close()
       with lock:clocks[ident]['lifecycle_finished_monotonic']=time.monotonic()
   result=queue['run_ordered_suite']({c['id']:c for c in s['cases']},one,max_concurrent_episodes=s['max_concurrent_episodes'],prewarm_count=s['prewarm_count'],start_order=s['start_order'],stop_event=stop)
   result['max_observed_active']=max(e['active'] for e in result['events']);result['max_observed_warming']=max(e['warming_or_ready'] for e in result['events']);result['clocks']=clocks
   if result['max_observed_active']>s['max_concurrent_episodes'] or result['max_observed_warming']>s['prewarm_count']:raise RuntimeError('Concurrency/warming bound violated')
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
   if not scripted:flush_completions(s,events,api)
  finally:
   stop.set()
   for listener in listeners.values():listener.close()
   try:
    if capacity_host is not None:
     try:save(out/'capacity-terminal.json',{'status':capacity_host.controller.status(),'parent_errors':capacity_host.parent.errors,'cleanup_failures':capacity_host.parent.cleanup_failures,'finished':sorted(capacity_host.parent.finished),'stop_cause':capacity_host.parent.stop_cause})
     finally:capacity_host.close()
   finally:
    try:
     if service and service.poll() is None:service.terminate();service.wait(timeout=10)
    finally:
     try:
      if pool_service is not None:
       try:
        stop_pool_service(s,root,out,pool_service)
        save(out/'chromium-pool-shutdown.json',{'status':'passed','returncode':pool_service.returncode,'private_transport_cleanup':'verified_by_service_zero_exit'})
       except BaseException as error:
        save(out/'chromium-pool-shutdown.json',{'status':'failed','returncode':pool_service.poll(),'type':type(error).__name__,'message':str(error),'forced_containment_may_leave_private_transport':True})
        raise
       finally:
        import shutil
        if (pool_directory/'events.jsonl').is_file():shutil.copyfile(pool_directory/'events.jsonl',out/'chromium-pool-events.jsonl')
     finally:
      if pool_log is not None:pool_log.close()



def main():
 mode,path,*rest=sys.argv[1:];s=load(path)
 if mode in ('case','scripted-case'):execute(s,next(c for c in s['cases'] if c['id']==rest[0]),mode=='scripted-case')
 elif mode in ('supervise','scripted'):
  prior_output=Path(s['output']).exists()
  try:supervise(s,mode=='scripted')
  finally:
   owner_path=Path(s['output'])/'supervisor-start.json'
   primary=sys.exception()
   try:
    if qwen_mode(s) and not prior_output and owner_path.is_file() and load(owner_path).get('pid')==os.getpid():terminal_inventory(s)
   except BaseException as inventory_error:
    if primary is None:raise
    primary.add_note('Terminal inventory also failed: '+repr(inventory_error))
 elif mode=='prepare-qwen':
  if not qwen_mode(s):raise ValueError('Explicit Qwen runtime mode required')
  validate_qwen_limits(s);source_guard(s)
  h=helper(s)
  for c in s['cases']:h['recipe_check'](c)
  print(json.dumps({'status':'source_prepared_NOT_runtime_ready','cases':[c['id'] for c in s['cases']],'models':0,'provider_requests':0,'caller':s['driver']}))
 else:raise ValueError('Unknown mode')
if __name__=='__main__':main()
