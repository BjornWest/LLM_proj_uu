"""Finite MiMo/Luna comparison cases sharing one capped, prewarming queue."""
from contextlib import contextmanager,nullcontext
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
def hosted_qwen_mode(s):return s.get('runtime_mode')=='qwen-openrouter-v1'
def pooled_model_mode(s):return qwen_mode(s) or hosted_qwen_mode(s)
def hosted_runtime(s):return runpy.run_path(str(checked(s['hosted_runtime'])))

def queue_cases(spec):
    # Only hosted resume selects a subset. Other modes retain the queue's
    # exact-order validation, including scripted diagnostics.
    return {case['id']:case for case in spec['cases']
            if not hosted_qwen_mode(spec) or case['id'] in spec['start_order']}


def hosted_counter_bindings(s,cases):
 readiness=load(checked(s['hosted_readiness']))
 expected={Path(row['path']).name:row['sha256']for row in readiness['exact_existing_asset_and_counter_pins']}
 for case in cases:
  root=Path(case['root']).resolve()
  required={}
  for name in ('model_input_budget.py','input_budget.py','model_tokenizers.json'):
   relative='intent_browser/'+name;required[relative]=expected[name]
   checked({'path':str(root/relative),'sha256':expected[name]})
  if 'source_export' in case:helper(s)['verify_source_export'](root,case['commit'],case['source_export'],required)
  else:
   for relative,digest in required.items():
    if sha256(subprocess.check_output(['git','-C',str(root),'show',case['commit']+':'+relative])).hexdigest()!=digest:
     raise ValueError('Actual hosted counter differs from committed case source')
  registry=load(root/'intent_browser/model_tokenizers.json');entry=registry['models']['qwen/qwen3.8-27b']
  if entry['repository']!=readiness['official_tokenizer_repository'] or entry['revision']!=readiness['official_tokenizer_revision']:
   raise ValueError('Hosted counter registry revision differs from CPU qualification')
  bundle=Path(s['counter_assets_root'])/entry['bundle']
  if bundle.is_symlink() or not bundle.is_dir():raise ValueError('Actual hosted tokenizer bundle missing')
  for name in ('tokenizer.json','tokenizer_config.json','chat_template.jinja'):
   if entry['files'][name]['sha256']!=expected[name]:raise ValueError('Actual hosted tokenizer registry asset differs')
   checked({'path':str(bundle/name),'sha256':expected[name]})
 if s['tokenizer']['sha256']!=expected['tokenizer.json']:raise ValueError('Shared AX/input tokenizer must match hosted qualification')
 checked(s['tokenizer'])

def capture_options(spec):
 mode=spec.get('observation_pipeline','auto')
 if type(mode) is not str or mode not in ('auto','native'):
  raise ValueError('Observation pipeline must be auto or native')
 screens=spec.get('trace_screenshots',False)
 asynchronous=spec.get('async_recording',True)
 capture=spec.get('recording_capture','pipeline' if mode=='auto' else 'native')
 if type(screens) is not bool or type(asynchronous) is not bool or capture not in ('pipeline','native'):
  raise ValueError('Explicit screenshot/async booleans and recording capture mode required')
 if mode=='auto' and capture!='pipeline':
  raise ValueError('Auto observation mode needs pipeline-bound fact recording')
 return {'observation_pipeline':mode,'trace_screenshots':screens,'async_recording':asynchronous,'recording_capture':capture}


def owner_completion_backend(backend):
 """Keep unqualified comparison/scripted transports on the browser owner.

 A generic background flag does not qualify their guards or total deadline.
 Qwen's reviewed wrappers opt into background completion separately.
 """
 backend.requires_browser_thread=True
 return backend


def browser_step_context(admission,emit,*,guarded):
 """Trusted runner hook; no env.step replacement or additional browser reads."""
 sequence=0
 @contextmanager
 def step(step,tool):
  nonlocal sequence
  sequence+=1
  if guarded:admission.step_started()
  emit('tool_started',sequence=sequence,execution_index=step,tool=tool)
  original=None
  try:yield
  except BaseException as error:
   original=error;emit('tool_error',sequence=sequence,execution_index=step,tool=tool,stage='tool')
   raise
  finally:
   try:
    if guarded:admission.step_finished()
   except BaseException as cleanup:
    if original is not None:original.add_note('Browser step acknowledgement also failed: '+repr(cleanup))
    else:raise
   finally:emit('tool_finished',sequence=sequence,execution_index=step,tool=tool)
 return step


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

def runtime_limits(s):
 cap=s['max_concurrent_episodes']
 value=s.get('runtime_limits')
 if value is None:return cap
 if not qwen_mode(s):raise ValueError('Runtime limit updates require the private Qwen parent')
 if (type(value) is not dict or set(value)!={'max_active_ceiling','max_generation_ceiling','initial_generation_requests'}
     or any(type(v) is not int or v<1 for v in value.values())
     or type(cap) is not int or not 1<=cap<=value['max_active_ceiling']
     or value['initial_generation_requests']>value['max_generation_ceiling']):
  raise ValueError('Explicit fixed episode/generation ceilings and initial targets required')
 return value['max_active_ceiling']

def private_read_wait_policy(s):
 value=s.get('private_read_wait_policy','bounded_request')
 if (type(value)is not str or value not in ('bounded_request','rental_bounded')
     or ('private_read_wait_policy'in s and not qwen_mode(s))):
  raise ValueError('Private-only explicit buffered read policy required')
 return value

def validate_qwen_limits(s):
 private_read_wait_policy(s)
 if (s.get('max_steps') is not None or s.get('episode_timeout') is not None
     or s.get('max_input_tokens')!=250000 or s.get('server_context_tokens')!=262144
     or type(s.get('max_tokens')) is not int or not 0<s['max_tokens']<=16384
     or type(s.get('request_timeout')) is not int or not 0<s['request_timeout']<=600
     or type(s.get('startup_timeout')) is not int or not 0<s['startup_timeout']<=900):
  raise ValueError('Explicit Qwen native context/input/headroom and request/startup limits required')
 runtime_limits(s)
 if any(c.get('policy_model')!='Qwen/Qwen3.8-27B-FP8' or c.get('max_input_tokens')!=250000
        or c.get('id')!='qwen-'+c.get('task_id','') for c in s['cases']):
  raise ValueError('One exact Qwen model and task identity per finite case required')
 if not s.get('shared_tokenizer') or not s.get('shared_chromium'):
  raise ValueError('This prospective Qwen composition requires the qualified pooled runtime')
 private_admission_policy(s)
 for row in s['qwen_sources'].values():checked(row)

def private_admission_policy(s):
 """Future private suites have one continuously replenished finite cohort."""
 if s.get('admission_policy','continuous-v1')!='continuous-v1':
  raise ValueError('Private Qwen requires continuous-v1 admission')
 if s.get('canary_task_ids') not in (None,[]) or s.get('canary_enabled',False) is not False:
  raise ValueError('Private Qwen model canaries are disabled; remove the historical selection')
 return 'continuous-v1'


def make_canary_barrier(s,stop,scripted):
 if qwen_mode(s):
  private_admission_policy(s)
  return None
 if hosted_qwen_mode(s) and not scripted:
  return CanaryBarrier(['qwen-'+i for i in s['canary_task_ids']],stop,admission_only=True,
   require_formatter=s.get('hosted_limit_profile')!='finite-task-limits-v1' and
    any(i not in ('B17','B19','H01','H02','A03','A04') for i in s['canary_task_ids']))
 return None


def phase_writer(s,ident,output,filename):
 """Trusted boundary timestamps; policy text and private capabilities stay out."""
 if not qwen_mode(s):return lambda phase,**values:None
 path=Path(output)/filename;path.parent.mkdir(parents=True,exist_ok=True)
 lock=threading.Lock();fingerprint=config_hash(s)
 def emit(phase,**values):
  emit.last_phase=phase
  if phase.endswith('_error') and emit.error_stage is None:emit.error_stage=values.get('stage',child_error_stage(phase))
  row={'schema':'qwen-suite-phase-v1','case':ident,'phase':phase,
   'epoch':time.time(),'monotonic':time.monotonic(),'caller_commit':s['caller_commit'],
   'driver_sha256':s['driver']['sha256'],'configuration_sha256':fingerprint,**values}
  try:
   with lock,path.open('a') as stream:stream.write(json.dumps(row,allow_nan=False)+'\n')
  except OSError as error:
   if emit.failure is None:
    emit.failure={'case':ident,'phase':phase,'type':type(error).__name__,'message':str(error)}
    print(json.dumps({'phase_recording_error':emit.failure}),file=sys.stderr)
 emit.failure=None;emit.last_phase='not_started';emit.error_stage=None
 return emit


def record_browser_steps(env,emit):
 """Legacy unit-test compatibility only; execute uses browser_step_context."""
 original=env.step;sequence=0
 def step(*args,**kwargs):
  nonlocal sequence
  sequence+=1;emit('tool_started',sequence=sequence)
  try:return original(*args,**kwargs)
  except BaseException:
   emit('tool_error',sequence=sequence,stage='tool');raise
  finally:emit('tool_finished',sequence=sequence)
 env.step=step
 return env


def verified_case_cleanup(s,ident,output,process):
 """No cleanup credit from termination alone or an unacknowledged permit."""
 if process is None or process.poll() is None:return False
 if not (Path(output)/ident/'cleanup.json').is_file() or not (Path(output)/(ident+'-bounded')/'result.json').is_file():
  return False # The child never reached its cleanup finally: unverifiable.
 marker=load(Path(output)/ident/'cleanup.json')
 guardian=load(Path(output)/(ident+'-bounded')/'result.json')
 return (marker.get('status')=='passed' and marker.get('case')==ident
  and marker.get('wrapper_finalizers_returned') is True
  and marker.get('pool_lease_released') is True
  and marker.get('capacity_channel_closed') is True
  and marker.get('capacity_infrastructure_error') is None
  and guardian.get('cleanup_verified') is True
  and guardian.get('source_sha256')==s['launcher']['sha256'])


class CaseInfrastructureError(RuntimeError):
 """A case error is never a model task verdict or a job cancellation."""


class SharedServiceUnhealthy(RuntimeError):
 """Job-level evidence that a shared service failed, independent of one case."""
 def __init__(self,problems):
  self.problems=list(problems);super().__init__('Shared services unhealthy: '+', '.join(self.problems))


def case_error_stage(error, watchdog, output, ident, fallback):
 if isinstance(error,TimeoutError) or watchdog is not None and watchdog.failure is not None:return 'timeout'
 failure=Path(output)/ident/'failure.json'
 if failure.is_file():
  child=load(failure)
  return child.get('stage',fallback)
 return fallback


def bounded_case_cleanup(s,process,connection):
 """Contain only the failed process; containment alone is not native cleanup."""
 if connection is not None:
  try:connection.shutdown(socket.SHUT_RDWR)
  except OSError:pass
 if process is None:return {'process_created':False,'process_terminal':True}
 grace=min(s.get('shutdown_grace_seconds',30),max(0,s['rental_deadline_utc']-time.time()))
 if process.poll() is None:
  try:process.wait(timeout=max(.1,grace)) # Give acknowledged native cancellation a bounded cleanup window.
  except subprocess.TimeoutExpired:
   try:process.terminate()
   except ProcessLookupError:pass
   try:process.wait(timeout=5)
   except subprocess.TimeoutExpired:
    try:process.kill()
    except ProcessLookupError:pass
    try:process.wait(timeout=10)
    except subprocess.TimeoutExpired:pass
 return {'process_created':True,'process_terminal':process.poll() is not None,
         'returncode':process.poll(),'native_cleanup_not_inferred':True}


def private_claim_gate(s,deadline_utc,grace,stop,job_stop,cancelled,*,now=time.time):
 """Private rental expiry is a job-lifetime stop; never claim a case that cannot start."""
 margin=s['startup_timeout']+grace
 if now()>=deadline_utc-margin:job_stop('rental_deadline',deadline_utc=deadline_utc,claim_margin_seconds=margin)
 if stop.is_set():raise cancelled('Job stopped before case claim')


SHARED_HEALTH_RECHECKS=5
SHARED_HEALTH_RECHECK_SECONDS=2


def isolate_case_error(s,ident,error,stage,output,process,connection,host,admission,shared_health=None):
 """Persist error, reserve unknown resources, and never set a job stop flag.

 shared_health() returns job-level problems with shared services. Any problem
 keeps this case's reservation; the caller owns the job-level disposition.
 """
 partial=sorted(str(p) for p in (Path(output)/ident/'live/runs').glob('*') if p.is_dir())
 proof=Path(output)/(ident+'-case-failure.json')
 save(proof,{'schema':'qwen-case-infrastructure-failure-v2','case':ident,
  'stage':stage,'type':type(error).__name__,'message':str(error),'task_verdict':None,
  'epoch':time.time(),'monotonic':time.monotonic(),'partial_traces':partial,
  'caller_commit':s['caller_commit'],'driver':s['driver'],'configuration_sha256':config_hash(s)})
 receipt=pin(proof)
 admission.quarantine({'case_failure':receipt,'stage':stage})
 secondary=[]
 try:
  if host is not None:host.quarantine_case(ident,error)
 except BaseException as problem:secondary.append({'stage':'capacity_quarantine','type':type(problem).__name__,'message':str(problem)})
 try:cleanup=bounded_case_cleanup(s,process,connection)
 except BaseException as problem:
  secondary.append({'stage':'process_containment','type':type(problem).__name__,'message':str(problem)})
  cleanup={'process_created':process is not None,'process_terminal':False,'cleanup_error':secondary[-1]}
 save(Path(output)/(ident+'-case-containment.json'),cleanup)
 def verified():
  if process is None:return True # No child was created, so no browser/model side effects.
  return verified_case_cleanup(s,ident,output,process)
 recovered=False;recovery_error=None;health=[]
 try:
  # Shared health first: a case failing because serving died usually still
  # holds a sent request, and that is exactly the outage to report.
  if shared_health is not None:
   health=shared_health()
   if health:raise SharedServiceUnhealthy(health)
  if secondary:raise RuntimeError('Case containment/quarantine unverified')
  if host is not None:
   # A sent/uncertain request stays quarantined. Finalization cannot infer an
   # HTTP abort merely from a process exit or a generic cleanup receipt.
   problems=host.case_recovery_problems(ident)
   if problems:raise RuntimeError('Case resources remain quarantined: '+', '.join(problems))
   host.finish_isolated_case(ident,verify_cleanup=verified,
    record_terminal=lambda:load(checked(receipt)).get('task_verdict') is None)
  recovered=admission.recover_quarantine(verified)
 except BaseException as problem:
  recovery_error={'type':type(problem).__name__,'message':str(problem)}
  health=list(getattr(problem,'problems',None) or [])
 answer={'stage':stage,'type':type(error).__name__,'message':str(error),
  'evidence':receipt,'quarantined':not recovered,'task_verdict':None,'shared_health_problems':health}
 try:
  save(Path(output)/(ident+'-case-isolation.json'),{'case':ident,'stage':stage,
   'error':receipt,'resource_quarantine_retained':not recovered,'cleanup_verified':recovered,
   'recovery_error':recovery_error,'shared_health_problems':health,'secondary_errors':secondary,
   'no_job_stop_requested':True,'no_model_retry':True})
 except BaseException as problem:
  # Diagnostics must not change resource accounting after verified recovery.
  answer['evidence_error']={'type':type(problem).__name__,'message':str(problem)}
 return answer


def child_error_stage(phase):
 if phase in ('tool_started','tool_finished','tool_error'):return 'tool'
 if phase.startswith('grade_projection'):return 'projection'
 if phase.startswith('grading') or phase=='native_grade_available':return 'grader'
 if phase.startswith('environment_creation'):return 'setup'
 if phase in ('environment_ready','worker_started'):return 'readiness'
 if phase.startswith('generation'):return 'policy_or_formatter'
 return 'lifecycle'


def qwen_live(s):
 runtime,_=qwen_modules(s);admission=runtime['ServingAdmission'](s['serving_live'])
 if admission.fingerprint!=s['serving_compatibility_fingerprint']:
  raise ValueError('Expected reviewed serving compatibility differs from current instance')
 return runtime,admission


def helper(s):return runpy.run_path(str(checked(s['helpers'])))
def config_hash(s):
 excluded={'review','sockets','tokenizer_socket'}
 if hosted_qwen_mode(s):excluded|={'suite_deadline_utc','chromium_descriptor'}
 if qwen_mode(s):excluded|={'serving_live','rental_deadline_utc','capacity_bindings','chromium_descriptor'}
 return sha256(json.dumps({k:v for k,v in s.items() if k not in excluded},sort_keys=True,ensure_ascii=False).encode()).hexdigest()

def case_binding(c):
 # Scripted answers/journeys are control inputs, not real-case identity.
 return sha256(json.dumps({k:v for k,v in c.items() if not k.startswith('scripted_') and k!='accepted_trace'},sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()

def execution_binding(s,c):
 excluded={'review','ready','cases','start_order','output','completion_db','suite_id','spec_path','sockets','tokenizer_socket','chromium_descriptor','scripted_hold_seconds','case_dependencies','caller_acceptance'}
 if qwen_mode(s):excluded|={'serving_live','rental_deadline_utc','capacity_bindings','chromium_descriptor'}
 if hosted_qwen_mode(s):excluded|={'suite_deadline_utc'}
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

def verify_finite_ready_case(s,c,row):
 # Independent native controls retain their actual producer; never relabel them
 # as executions of this hosted caller. Frozen caller/counter checks are separate.
 if (row.get('case')!=c['id'] or row.get('recipe_manifest')!=c['recipe_manifest']
     or row.get('prepared_receipt')!=c['prepared_receipt']
     or row.get('native_source_root')!=c['root']):
  raise ValueError('Native acceptance belongs to another prepared/source instance')
 control=load(checked(row['control']))
 result=load(checked(row['result']));canonical=load(checked(row['canonical']))
 http=load(checked(row['HTTP']));metadata=load(checked(row['metadata']))
 task=load(checked(row['public_task']))
 trace=Path(result['trace']).resolve()
 expected={'canonical':'evaluation.json','metadata':'metadata.json','public_task':'policy-task.json'}
 if (control.get('status')!='passed' or control.get('expected_verdict') is not True
     or control.get('external_provider_requests')!=0
     or control['instance'].get('case_id')!=c['task_id']
     or control['instance'].get('max_input_tokens')!=c['max_input_tokens']
     or Path(control['instance']['prepared']).resolve()!=Path(c['argument']).resolve()
     or Path(control['trace']).resolve()!=trace
     or result.get('status')!='graded_and_projected'
     or result['native_grade'].get('structured_claims_correct') is not True
     or canonical.get('task_completed') is not True
     or canonical.get('technical_error') is not None
     or 'scripted' not in metadata.get('tags',[])
     or task.get('user_message')!=c['public_request']
     or any(checked(row[key]).resolve()!=trace/name for key,name in expected.items())
     or http.get('recording_id')!=trace.name
     or http.get('derived_evaluation',{}).get('episode_id')!=trace.name
     or http.get('derived_evaluation',{}).get('binding_status')!='verified'
     or http['derived_evaluation'].get('structured_claims_correct') is not True):
  raise ValueError('Actual positive native/canonical/HTTP/public binding is incomplete')
 checked(row['producer'])
 producer=load(checked(row['producer_acceptance']))
 proofs=[p for p in producer['cases'] if p.get('case_id')==c['task_id']]
 if (len(proofs)!=1 or producer.get('passed')!=len(producer['cases'])
     or proofs[0].get('trace')!=str(trace)
     or row['producer'] not in producer['inputs']
     or any(row[key] not in proofs[0]['evidence'] for key in ('result','canonical','HTTP','recipe_manifest','prepared_receipt'))):
  raise ValueError('Native control evidence differs from pinned producer acceptance')


def browser_step_options(spec):
 seconds=spec.get('browser_step_watchdog_seconds')
 if seconds is not None and (type(seconds) is not int or not 1<=seconds<=600):
  raise ValueError('Browser-step watchdog must be None or integer1..600 seconds')
 telemetry=spec.get('env_step_telemetry')
 if telemetry is not None and type(telemetry) is not bool:
  raise ValueError('Explicit boolean env_step_telemetry required')
 return seconds,telemetry


def watch_browser_steps(env,admission):
 """Legacy unit-test compatibility only; execute uses browser_step_context."""
 original=env.step
 def step(*args,**kwargs):
  admission.step_started()
  try:result=original(*args,**kwargs)
  except BaseException:
   # Preserve the native failure, including a signal. Parent containment still
   # applies if the end acknowledgement is lost during cleanup.
   try:admission.step_finished()
   except BaseException:pass
   raise
  admission.step_finished()
  return result
 env.step=step
 return env

class CaseWatchdog:
 """Parent-owned wall-clock limits, independent of child's signal handling.

 Startup ends at validated ready. Parked warm actors have no active budget;
 activation starts the agreed episode budget. Expiry stops the owned bounded
 launcher and closes its control socket. Containment is not native cleanup.
 """
 def __init__(self,process,connection_holder,*,startup_seconds,episode_seconds,cleanup_grace_seconds=30,stop_event=None,clock=time.monotonic,rental_deadline=None,browser_step_seconds=None):
  for value in (startup_seconds,cleanup_grace_seconds)+(() if episode_seconds is None else (episode_seconds,)):
   if type(value) not in (int,float) or not math.isfinite(value) or value<=0:raise ValueError('Positive finite case watchdog limits required')
  if episode_seconds is None and (type(rental_deadline) not in (int,float) or not math.isfinite(rental_deadline) or rental_deadline<=clock()):raise ValueError('No episode ceiling requires a future finite rental deadline')
  if browser_step_seconds is not None and (type(browser_step_seconds) not in (int,float) or not math.isfinite(browser_step_seconds) or browser_step_seconds<=0):raise ValueError('Positive finite browser-step deadline required')
  self.browser_step_seconds=browser_step_seconds;self.open_step=None;self.active_deadline=None;self.step_sequence=0
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
   self.active_deadline=self.deadline
 def step_started(self,sequence):
  with self.lock:
   if (self.failure is not None or self.phase!='active' or self.open_step is not None
       or self.browser_step_seconds is None or type(sequence) is not int
       or sequence!=self.step_sequence+1 or self.clock()>=self.deadline):
    raise CaseDeadline('Browser-step watchdog unavailable or invalid boundary')
   self.step_sequence=sequence;self.open_step=sequence;self.phase='browser_step'
   self.deadline=min(self.active_deadline,self.clock()+self.browser_step_seconds+self.grace)
 def step_finished(self,sequence):
  with self.lock:
   if self.failure is not None or self.phase!='browser_step' or type(sequence) is not int or self.open_step!=sequence or self.clock()>=self.deadline:
    raise CaseDeadline('Browser-step expired or mismatched; effects unknown')
   self.open_step=None;self.phase='active';self.deadline=self.active_deadline
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
    self.failure={'phase':self.phase,'reason':'independent_case_deadline','observed_monotonic':self.clock(),
     **({'browser_step_sequence':self.open_step,'effects':'unknown'}if self.open_step is not None else {})}
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
 def __init__(self,case_ids,stop_event,*,admission_only=False,require_formatter=True):
  self.require_formatter=require_formatter
  self.ids=set(case_ids);self.stop=stop_event;self.completed=set();self.event=threading.Event();self.lock=threading.Lock();self.failed=False;self.admission_only=admission_only;self.formatter_exercised=False
  if not self.ids:raise ValueError('Explicit nonempty canary cohort required')
 def wait(self,ident):
  if ident in self.ids:return
  while not self.event.wait(.05):
   if self.stop.is_set():raise RuntimeError('Canary qualification aborted; remainder not dispatched')
  if self.stop.is_set() or self.failed:raise RuntimeError('Suite stopped before remainder activation')
 def fail(self,ident):
  if ident in self.ids or self.admission_only:
   self.failed=True
   if not self.admission_only:self.stop.set()
   self.event.set()
 def complete(self,ident,*,formatter_exercised=True):
  if ident not in self.ids:return
  with self.lock:
   if ident in self.completed:raise RuntimeError('Duplicate canary completion')
   self.completed.add(ident);self.formatter_exercised|=formatter_exercised
   if self.completed==self.ids:
    if self.admission_only and self.require_formatter and not self.formatter_exercised:self.failed=True
    self.event.set()


class WatchedAdmission:
 def __init__(self,admission,watchdog,phase=None):
  self.admission,self.watchdog=admission,watchdog;self.phase=phase or (lambda *a,**k:None)
 def __getattr__(self,name):return getattr(self.admission,name)
 def environment_ready(self,ready=None):
  self.watchdog.ready();self.admission.environment_ready(ready);self.watchdog.activate()
 def step_started(self,sequence):
  self.watchdog.step_started(sequence);self.phase('tool_started',sequence=sequence)
 def step_finished(self,sequence):
  self.watchdog.step_finished(sequence);self.phase('tool_finished',sequence=sequence)
def source_guard(s,c=None):
 checked(s['driver']);checked(s['helpers']);checked(s['events_helper'])
 if c is not None:
  checked(c['recipe_manifest'])
  if 'source_export' in c:
   if not pooled_model_mode(s):raise ValueError('Exported cases require explicit Qwen mode')
   helper(s)['verify_source_export'](c['root'],c['commit'],c['source_export'],{})
 if qwen_mode(s):
  for row in s['qwen_sources'].values():checked(row)
 if hosted_qwen_mode(s):
  location=checked(s['hosted_runtime']);relative='scripts/openrouter_qwen_runtime.py'
  if location.resolve()!=Path(s['caller_root']).resolve()/relative:raise ValueError('Hosted runtime must be inside committed caller root')
  if 'source_export' not in s and location.read_bytes()!=subprocess.check_output(['git','-C',s['caller_root'],'show',s['caller_commit']+':'+relative]):raise ValueError('Hosted runtime differs from committed caller')
  hosted_counter_bindings(s,[c]if c is not None else s['cases'])
 if 'authorization' in s:checked(s['authorization'])
 if hosted_qwen_mode(s):hosted_authorization(s)
 if 'transport' in s:
  for row in s['transport']['files']:checked(row)
  for name in ('node','bridge_worker','pi'):checked(s[name])
 if 'source_export' in s:
  if not pooled_model_mode(s):raise ValueError('Exported sources require explicit Qwen mode')
  required={'scripts/comparison_suite.py':s['driver']['sha256'],'scripts/comparison_suite_helpers.py':s['helpers']['sha256']}
  for row in (s['qwen_sources'].values() if qwen_mode(s) else [s['hosted_runtime']]):
   location=Path(row['path']).resolve()
   if location.is_relative_to(Path(s['caller_root']).resolve()):required[str(location.relative_to(Path(s['caller_root']).resolve()))]=row['sha256']
  helper(s)['verify_source_export'](s['caller_root'],s['caller_commit'],s['source_export'],required)
 elif not Path(s['driver']['path']).read_bytes()==subprocess.check_output(['git','-C',s['caller_root'],'show',s['caller_commit']+':scripts/comparison_suite.py']):raise ValueError('Caller differs from committed source')

def check_release(s):
 private_read_wait_policy(s)
 browser_step_options(s)
 capture_options(s)
 pool_resource_options(s)
 source_guard(s)
 if qwen_mode(s):return check_qwen_release(s)
 if hosted_qwen_mode(s):return check_hosted_release(s)
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

def hosted_authorization(spec):
 """Apply pinned concurrency-only amendments without replacing cohort identity."""
 effective=load(checked(spec['authorization']));previous=None;seen=set()
 amendments=spec.get('authorization_amendments',[])
 if type(amendments)is not list:raise ValueError('Pinned authorization amendment list required')
 for binding in amendments:
  path=checked(binding)
  if str(path)in seen:raise ValueError('Duplicate authorization amendment')
  seen.add(str(path));amendment=load(path)
  if (amendment.get('schema')!='hosted-qwen-finite-authorization-amendment-v1'
      or amendment.get('base_authorization')!=spec['authorization']
      or amendment.get('previous_amendment')!=previous
      or type(amendment.get('id'))is not str or not amendment['id']
      or type(amendment.get('changes'))is not dict
      or set(amendment['changes'])!={'max_active_combined'}):
   raise ValueError('Invalid concurrency-only authorization amendment chain')
  cap=amendment['changes']['max_active_combined']
  if type(cap)is not int or not 1<=cap<=len(effective['case_ids']):
   raise ValueError('Finite positive amended concurrency required')
  effective={**effective,'max_active_combined':cap};previous=binding
 return effective


def pool_source_case(spec):
 order=spec.get('start_order',[])
 if not order:raise ValueError('Nonempty attempt order required for shared services')
 ident=spec.get('shared_service_case_id',order[0]) if qwen_mode(spec) else order[0]
 matches=[case for case in spec['cases']if case['id']==ident]
 if len(matches)!=1:raise ValueError('First attempt case must resolve uniquely')
 return matches[0]


def check_pool_source_pins(spec,case=None):
 required={'intent_browser/chromium_pool.py','intent_browser/assets/chromium_pool.cjs','intent_browser/shared_browsergym.py','intent_browser/browser_shutdown.py','intent_browser/runner.py'}
 first=pool_source_case(spec)
 expected={name:pin(Path(first['root'])/name)['sha256']for name in required}
 if qwen_mode(spec) and case is None:
  # Shared service identity is independent of any task's recipe/readiness.
  if 'source_export' in first:
   helper(spec)['verify_source_export'](first['root'],first['commit'],first['source_export'],expected)
  else:
   for name in required:
    if (Path(first['root'])/name).read_bytes()!=subprocess.check_output(['git','-C',first['root'],'show',first['commit']+':'+name]):
     raise ValueError('Shared service source differs from committed baseline')
  return expected
 selected=[case] if case is not None else [first] if qwen_mode(spec) else queue_cases(spec).values()
 for case in selected:
  if case.get('source_binding')=='current':
   # One checkout: the pool and the task import the same files by construction.
   if Path(case['root']).resolve()!=Path(first['root']).resolve() or case['commit']!=first['commit']:
    raise ValueError('Single-version case differs from the shared service checkout')
   continue
  declared=load(checked(case['recipe_manifest'])).get('source_sha256',{})
  missing={name:digest for name,digest in expected.items() if name not in declared}
  if any(name in declared and declared[name]!=digest for name,digest in expected.items()):
   raise ValueError('Pending case pooled runtime source pins disagree')
  if missing:
   if spec.get('hosted_limit_profile')!='finite-task-limits-v1' or 'source_export' not in case:
    raise ValueError('Pending case pooled runtime source pins disagree')
   # New task-instance collectors may omit optional shared-harness modules.
   # The explicit frozen execution index supplements absences only; a native
   # declaration is never overwritten and actual bytes/modes remain checked.
   helper(spec)['verify_source_export'](case['root'],case['commit'],case['source_export'],missing)
  for name,digest in expected.items():checked({'path':str(Path(case['root'])/name),'sha256':digest})
 return expected


def task_caps(spec):
 """Thread-count caps are workstation protection; deployments turn them off (0)."""
 value=spec.get('task_caps',True)
 if type(value) is not bool:raise ValueError('task_caps must be boolean')
 return value


def pool_resource_options(spec):
 memory=spec.get('pool_memory_mib',3072);tasks=spec.get('pool_tasks',512)
 if not task_caps(spec):
  if type(memory)is not int or memory<1024:raise ValueError('Explicit shared-pool memory limit required')
  return memory,0
 if type(memory)is not int or not 1024<=memory<=8192 or type(tasks)is not int or not 128<=tasks<=512:
  raise ValueError('Finite explicit shared-pool resource limits required')
 return memory,tasks

def hosted_prior_specs(s):
 # This finite hosted cohort keeps approved attempt specs beside its immutable
 # user authorization. Discover launched attempts; an omitted resume record
 # must not turn an earlier measured native failure into spending permission.
 cohort=checked(s['authorization']).parent;found={}
 for path in cohort.glob('launch-spec-approved-v*.json'):
  prior=load(path)
  if prior.get('runtime_mode')!='qwen-openrouter-v1' or prior.get('authorization')!=s['authorization']:continue
  out=Path(prior['output']).resolve()
  if out==Path(s['output']).resolve():continue
  if not (out/'supervisor-start.json').is_file():continue
  if prior.get('suite_id')==s['suite_id']:raise ValueError('Attempt ID reused with different output')
  found[str(path.resolve())]=prior
 return found

def hosted_attempt_ids(s,authorization):
 ids=[c['id']for c in s['cases']]
 resume=s.get('resume');discovered=hosted_prior_specs(s)
 if resume is None:
  for prior in discovered.values():
   with sqlite3.connect('file:'+str(prior['completion_db'])+'?mode=ro',uri=True)as db:
    states=[r[0]for r in db.execute('SELECT state FROM episodes WHERE suite=?',(prior['suite_id'],))]
   if not states or any(v in ('pending','running')for v in states):raise ValueError('Prior attempt still active')
   if any(load(p).get('status')=='graded_and_projected'and load(p).get('scripted')is False for p in Path(prior['output']).glob('qwen-*/result.json')):raise ValueError('Measured prior outcomes require explicit resume')
  if s.get('resume_attempts')or s['start_order']!=ids:raise ValueError('Initial attempt must include all34 cases')
  return ids
 attempts=s.get('resume_attempts')
 if type(resume)is not list or type(attempts)is not list or not attempts:raise ValueError('Authoritative prior attempt snapshots required')
 if {str(checked(a['spec']).resolve())for a in attempts}!=set(discovered):raise ValueError('Every prior launched attempt must be bound')
 authoritative={};seen_attempts=set()
 for attempt in attempts:
  spec_path=checked(attempt['spec']);prior=load(spec_path);suite=prior.get('suite_id')
  if suite in seen_attempts or suite==s['suite_id']or prior.get('runtime_mode')!='qwen-openrouter-v1' or prior.get('authorization')!=s['authorization']:
   raise ValueError('Invalid prior attempt identity/authorization')
  seen_attempts.add(suite);out=Path(prior['output']).resolve()
  database=checked(attempt['completion_db'])
  if database.resolve()!=Path(prior['completion_db']).resolve()or database.resolve()!=out/'completion.sqlite':raise ValueError('Prior completion database escaped its output')
  terminal=load(checked(attempt['terminal_inventory']))
  if terminal.get('suite_id')!=suite or terminal.get('source_driver')!=prior['driver'] or terminal.get('rejected_symlinks')!=[]:raise ValueError('Prior terminal inventory incomplete')
  inventory={row['relative_path']:row for row in terminal['files']}
  if inventory.get('completion.sqlite',{}).get('sha256')!=attempt['completion_db']['sha256']:raise ValueError('Prior database differs from terminal inventory')
  with sqlite3.connect('file:'+str(database)+'?mode=ro',uri=True)as db:
   members=db.execute('SELECT episodes FROM suites WHERE id=?',(suite,)).fetchone()
   states=dict(db.execute('SELECT id,state FROM episodes WHERE suite=?',(suite,)))
  if members is None or load_json_list(members[0])!=prior['start_order']or set(states)!=set(prior['start_order'])or any(v not in ('succeeded','failed','interrupted','not_started')for v in states.values()):
   raise ValueError('Prior attempt membership is incomplete or still active')
  # Grade-complete results survive even a later cleanup/Events failure. Do not
  # treat state=failed as permission to repeat a measured native outcome.
  for previous in prior['cases']:
   ident=previous['id'];path=out/ident/'result.json'
   if not path.is_file():
    if states.get(ident)=='succeeded':raise ValueError('Succeeded prior case lacks its result')
    continue
   result=load(path)
   if result.get('scripted')is not False or result.get('status')!='graded_and_projected':continue
   relative=str(path.relative_to(out));record=inventory.get(relative)
   if record is None or pin(path)['sha256']!=record['sha256']:raise ValueError('Prior measured result differs from terminal inventory')
   current=next((c for c in s['cases']if c['id']==ident),None)
   viewer_path=out/ident/'grade-viewer.json';viewer=load(viewer_path)
   view_record=inventory.get(str(viewer_path.relative_to(out)))
   if (current is None or case_binding(current)!=case_binding(previous)
       or result.get('case')!=ident or result.get('caller_driver')!=prior['driver']or result.get('caller_commit')!=prior['caller_commit']
       or result.get('case_binding_sha256')!=case_binding(previous)or result.get('execution_binding_sha256')!=execution_binding(prior,previous)
       or view_record is None or pin(viewer_path)['sha256']!=view_record['sha256']or viewer.get('status')!='verified'):
    raise ValueError('Prior completed case provenance disagrees')
   trace=Path(result['result']['trace']).resolve()
   if not trace.is_relative_to(out/ident/'live/runs')or checked(viewer['canonical']).resolve()!=trace/'evaluation.json'or checked(viewer['automatic']).resolve()!=trace/'automatic-grading.json':
    raise ValueError('Prior viewer belongs to another case/trace')
   canonical=load(checked(viewer['canonical']));automatic=load(checked(viewer['automatic']))
   if (automatic.get('status')!='graded'or canonical.get('technical_error')is not None
       or canonical.get('task_completed')is not result['result']['viewer_projection']['task_completed']
       or viewer.get('task_completed')is not canonical.get('task_completed')):raise ValueError('Prior canonical/native outcome disagrees')
   authoritative[ident]=(pin(spec_path),pin(path),pin(viewer_path))
 retained={}
 for row in resume:
  result_path=checked(row['result']);result=load(result_path);ident=result.get('case')
  if ident in retained or ident not in authoritative or (row['spec'],row['result'],row['viewer'])!=authoritative[ident]:
   raise ValueError('Retained list omits/misbinds authoritative case evidence')
  retained[ident]=row
 if set(retained)!=set(authoritative):raise ValueError('Every prior measured native outcome must be retained')
 pending=[ident for ident in ids if ident not in retained]
 if not pending or s['start_order']!=pending:raise ValueError('Attempt must contain exactly remaining cases, in original order')
 return pending

def finite_dispatch_claim_path(authorized):
 return checked(authorized['request']).parent/('.finite-task-dispatch-'+authorized['request']['sha256']+'.json')

def check_finite_dispatch_claim(s,authorized):
 claim=finite_dispatch_claim_path(authorized)
 if not claim.exists():return
 stored=load(claim);authority_path=Path(s['output'])/'supervisor-start.json'
 if (stored.get('suite_id')!=s['suite_id'] or stored.get('output')!=s['output']
     or stored.get('configuration_sha256')!=config_hash(s) or not authority_path.is_file()):
  raise ValueError('Finite tasks do not authorize an automatic repeat')
 authority=load(authority_path)
 if (stored['pid']!=authority['pid'] or stored['process_start']!=authority['process_start']
     or helper(s)['process_identity'](authority['pid'])!=authority['process_start']):
  raise ValueError('Finite task dispatch owner is no longer active; no automatic repeat')


def load_json_list(value):
 result=json.loads(value)
 if type(result)is not list or any(type(x)is not str for x in result):raise ValueError('Invalid prior membership')
 return result

def check_hosted_release(s):
 hosted_runtime(s)['validate_limits'](s)
 authorized=hosted_authorization(s);ids=[c['id'] for c in s['cases']]
 if s.get('hosted_limit_profile')=='finite-task-limits-v1':
  request=load(checked(authorized['request']));requested=request['cases']
  if (authorized.get('schema')!='hosted-finite-task-authorization-v1'
      or not 1<=len(ids)<=34 or len(set(ids))!=len(ids)
      or ids!=authorized['case_ids'] or len(requested)!=len(ids)
      or authorized.get('dispatch_authorized') is not True
      or authorized.get('automatic_retries') is not False
      or s.get('resume') is not None or s.get('resume_attempts')
      or s.get('authorization_amendments')
      or s['start_order']!=ids
      or authorized.get('policy_model')!='qwen/qwen3.8-27b'
      or authorized.get('formatter_model')!='qwen/qwen3.8-27b'
      or request.get('policy_and_formatter_model')!='qwen/qwen3.8-27b'
      or authorized.get('max_active_combined')!=s['max_concurrent_episodes']
      or request.get('concurrency')!=s['max_concurrent_episodes']
      or request.get('request_timeout_seconds')!=s['request_timeout']
      or authorized.get('prewarm_count')!=s['prewarm_count']):
   raise ValueError('Exact once-only finite hosted task authorization required')
  for c,row in zip(s['cases'],requested):
   if (c['task_id']!=row['id'] or c['public_request']!=row['public_request']
       or c['max_input_tokens']!=row['maximum_complete_input_tokens']
       or c['max_steps']!=row['max_steps'] or s['max_tokens']!=row['max_output_tokens']
       or c.get('family')!=row['family']
       or Path(c['argument']).resolve()!=Path(row['prepared']).resolve()
       or Path(c['root']).resolve()!=Path(request['source_root']).resolve()
       or c['callable']['module']!='environments.website_world.task_instances'
       or c['callable']['symbol']!='run'
       or checked(c['recipe_manifest'])!=Path(row['prepared']).resolve()/'recipe/manifest.json'
       or c['recipe_manifest']['sha256']!=row['manifest_sha256']
       or checked(c['prepared_receipt'])!=Path(row['prepared']).resolve()/'prepared-instance.json'
       or c['prepared_receipt']['sha256']!=row['prepared_receipt_sha256']):
    raise ValueError('Finite task/prose/recipe/input/turn limits differ from authorized selection')
  check_finite_dispatch_claim(s,authorized)
  attempt=ids
 else:
  if (len(ids)!=34 or len(set(ids))!=34 or ids!=authorized['case_ids']
      or authorized.get('dispatch_authorized') is not True
      or authorized.get('policy_model')!='qwen/qwen3.8-27b'
      or authorized.get('formatter_model')!='qwen/qwen3.8-27b'
      or authorized.get('max_input_tokens')!=150000
      or authorized.get('max_active_combined')!=s['max_concurrent_episodes']
      or authorized.get('prewarm_count')!=s['prewarm_count']):
   raise ValueError('Exact new finite34 hosted Qwen authorization required')
  request=load(checked(authorized['request']))
  requested=request['finite_episode_list']
  if (len(requested)!=34 or [c['task_id'] for c in s['cases']]!=[row['id'] for row in requested]
      or any(c['public_request']!=row['request']for c,row in zip(s['cases'],requested))):
   raise ValueError('Hosted cases/public requests differ from newly authorized finite list')
  attempt=hosted_attempt_ids(s,authorized)
 canaries=s.get('canary_task_ids')
 if canaries!=[ident.removeprefix('qwen-')for ident in attempt[:min(4,len(attempt))]]:
  raise ValueError('Explicit four leading parallel canaries required before hosted remainder')
 readiness=load(checked(s['hosted_readiness']))
 order=[row.get('configured_name') for row in readiness.get('endpoints_in_existing_order',[])]
 if (readiness.get('status')!='read_only_model_key_assets_and_CPU_counter_verified_no_provider_completion'
     or readiness.get('model')!='qwen/qwen3.8-27b'
     or readiness.get('key_authentication_HTTP')!=200
     or readiness.get('common_context_ceiling')!=262144
     or 'image' not in readiness.get('architecture',{}).get('input_modalities',[])
     or not order or len(set(order))!=len(order)
     or any(row.get('required_tools_and_structured_parameters_present') is not True
       or row.get('context_length',0)<262144 or row.get('max_completion_tokens',0)<s['max_tokens']
       for row in readiness['endpoints_in_existing_order'])
     or readiness.get('exact_existing_request_options',{}).get('provider',{}).get('only')!=order
     or readiness['exact_existing_request_options'].get('reasoning')!={'enabled':True}
     or any(options!=readiness['exact_existing_request_options']['provider']
       for options in (s['provider_options'],s['extractor_provider_options']))):
  raise ValueError('Exact hosted model/provider/counter readiness required')
 smoke=readiness['counter_smoke'];checked({'path':smoke['path'],'sha256':smoke['sha256']})
 if load(smoke['path']).get('status')!='passed':raise ValueError('Actual hosted counter smoke must pass')
 # Source/asset pins are checked at their actual case/runtime paths by source_guard,
 # not at Training's temporary worktree paths.
 review=load(checked(s['review']));ready=load(checked(s['ready']))
 if (review.get('status')!='approved' or review.get('configuration_sha256')!=config_hash(s)
     or ready.get('status')!='passed'
     or (s.get('hosted_limit_profile')!='finite-task-limits-v1' and ready.get('driver')!=s['driver'])
     or (s.get('hosted_limit_profile')=='finite-task-limits-v1' and ready.get('schema')!='finite-hosted-native-controls-v1')
     or len(ready['cases'])!=len(attempt) or {v['case']for v in ready['cases']}!=set(attempt)):
  raise ValueError('Reviewed hosted configuration and exact actual native/HTTP acceptances required' if s.get('hosted_limit_profile')=='finite-task-limits-v1' else 'Reviewed hosted configuration and all34 actual native/HTTP acceptances required')
 verifier=verify_finite_ready_case if s.get('hosted_limit_profile')=='finite-task-limits-v1' else verify_ready_case
 for row in ready['cases']:verifier(s,next(c for c in s['cases']if c['id']==row['case']),row)
 if s.get('hosted_limit_profile')=='finite-task-limits-v1':
  accepted=load(checked(s['caller_acceptance']))
  first=s['cases'][:min(4,len(s['cases']))]
  if (accepted.get('schema')!='finite-hosted-caller-controls-v1'
      or accepted.get('status')!='passed' or accepted.get('driver')!=s['driver']
      or [row['case']for row in accepted['cases']]!=[c['id']for c in first]):
   raise ValueError('Exact shared caller/queue/recording/projection acceptance required')
  for c,row in zip(first,accepted['cases']):verify_ready_case(s,c,row)


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
 review=load(checked(s['review']))
 if review.get('status')!='approved' or review.get('configuration_sha256')!=config_hash(s):
  raise ValueError('Exact reviewed Qwen configuration required')
 # Each case proves readiness before its first dispatch. A missing or failed
 # case binding is not authority to cancel other authorized episodes.
 _,live=qwen_live(s)
 if live.live.get('dispatch_authorized') is not True:raise ValueError('Current live contract cannot dispatch')
 if authorized['approved_rental_seconds']!=live.deployment['approved_rental_seconds']:
  raise ValueError('Actual allocation rental differs from finite approval')
 live.readiness()


def check_private_case(s,c,*,scripted=False):
 # Case-local source/native acceptance; never dispatch an unbound episode.
 source_guard(s,c)
 helper(s)['recipe_check'](c)
 if s.get('shared_chromium'):check_pool_source_pins(s,c)
 if not scripted:
  ready=load(checked(s['ready']))
  rows=[row for row in ready.get('cases',[]) if row.get('case')==c['id']]
  if ready.get('driver')!=s['driver'] or len(rows)!=1:
   raise ValueError('Exact case readiness binding missing or duplicated')
  verify_ready_case(s,c,rows[0])



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
 if s.get('shared_chromium') and not scripted and not pooled_model_mode(s):raise ValueError('Pooled comparison caller is model-free qualification only')
 if not scripted:
  check_release(s)
  if qwen_mode(s):check_private_case(s,c)
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
 phase_event=phase_writer(s,c['id'],out,'child-phases.jsonl');phase_event('worker_started')
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
  native_run=recording.recording_runner(run_episode,enabled=True,expected_sources=pins,report=inspection_out/'recording-status.json',capture=capture_options(s)['recording_capture'])
 except (TimeoutError,KeyboardInterrupt,SystemExit):
  if recording is not None:recording.release_package()
  raise
 except Exception as error:
  if recording is not None:recording.release_package();recording=None
  save(inspection_out/'setup-failure.json',{'status':'disabled','reason':str(error),'error_type':type(error).__name__,'native_grade_unchanged':True})
 counts={'policy_requests':0,'formatter_requests':0,'reported_cost_usd':0.0,'responses_without_cost':0}
 profile=None;lease=None;pooled=None;capacity_client=None;factories=None;environment_holder={}
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
  phase_event('generation_dispatch',episode_phase=phase)
  counts[phase+'_requests']+=1
  if phase=='formatter' and counts['formatter_requests']>1:raise RuntimeError('One formatter maximum')
 def record(value):
  if qwen_mode(s) and value.get('event')=='response':counts['responses_without_cost']+=1
  with (out/'http-attempts.jsonl').open('a') as f:f.write(json.dumps({'epoch':time.time(),**value})+'\n')
 def backend(phase,consumer_before_dispatch=None,directory=None):
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
  b.client.event_hooks={'request':[dispatched],'response':[received]}
  if hosted_qwen_mode(s):
   try:
    shared=SharedTokenizerConfig(s['tokenizer_socket'])
    module=hosted_runtime(s)
    counter=module['MemoizedCounter'](model_matched_input_counter(b,assets_root=s['counter_assets_root'],shared_tokenizer=shared))
    wrapper=module['BackgroundHostedQwenBackend'] if capture_options(s)['observation_pipeline']=='auto' else module['HostedQwenBackend']
    return wrapper(b,counter,phase=phase,maximum=s['max_tokens'],
     deadline=s['suite_deadline_utc'],timeout=s['request_timeout'],directory=directory,meter=record,
     quote_pair_schema=s.get('formatter_quote_pair_schema',False) if phase=='formatter' else False,
     input_limit=c['max_input_tokens'])
   except BaseException:b.close();raise
  return owner_completion_backend(b)
 @contextmanager
 def session(*,before_dispatch):
  if scripted:
   import httpx
   b=ChatCompletionsBackend('http://offline.invalid/v1','scripted',supports_images=True);b.client.close()
   answer=load(checked(c['scripted_answer']))['text']
   journey=load(checked(c['scripted_journey'])) if c.get('scripted_journey') else None
   journey_index=0
   def response(req):
    nonlocal journey_index
    before_dispatch();before('policy')
    # Keeps initial active controls alive while the fourth environment parks.
    time.sleep(s.get('scripted_hold_seconds',0))
    if journey is not None:
     if journey_index>=len(journey):raise ValueError('Scripted journey exhausted; no replay')
     response=journey[journey_index];journey_index+=1
     return httpx.Response(200,json=response)
    return httpx.Response(200,json={'choices':[{'finish_reason':'tool_calls','message':{'role':'assistant','content':None,'tool_calls':[{'id':'positive','type':'function','function':{'name':'send_msg_to_user','arguments':json.dumps({'text':answer})}}]}}],'usage':{}})
   def dispatched(req):
    with capacity_client.turn('policy') if capacity_client is not None else nullcontext():
     return response(req)
   b.client=httpx.Client(transport=httpx.MockTransport(dispatched))
   b=owner_completion_backend(b)
  elif qwen_mode(s):
   with factories.policy_session(before_dispatch=before_dispatch) as b:yield b
   return
  else:b=backend('policy',before_dispatch)
  try:yield b
  finally:b.close()
 class Formatter:
  model='scripted'
  def complete(self,messages):
   with capacity_client.turn('formatter') if capacity_client is not None else nullcontext():
    return self._complete(messages)
  def _complete(self,messages):
   before('formatter');payload=json.loads(messages[1]['content'])
   if payload['final_answer']!=load(checked(c['scripted_answer']))['text']:raise ValueError('Scripted delivered answer changed')
   text=json.dumps(load(checked(c['scripted_claims'])))
   return types.SimpleNamespace(text=text,request={'messages':messages},raw={'model':'scripted','choices':[{'finish_reason':'stop','message':{'content':text}}],'usage':{}})
  def close(self):pass
 def environment_ready(ready):
  phase_event('environment_ready')
  timings['environment_ready_monotonic']=time.monotonic();timings['ready_episode_id']=ready.episode_id;timings['ready_trace']=str(ready.directory)
  save(out/'warm-ready.json',dict(timings));signal.alarm(0)
  admission.environment_admission(ready)
  phase_event('activated')
  timings['activated_monotonic']=time.monotonic();save(out/'activated.json',dict(timings));signal.alarm(180 if scripted else max(1,math.ceil(serving.deadline-time.time())) if qwen_mode(s) else max(1,math.ceil(s['suite_deadline_utc']-time.time())) if hosted_qwen_mode(s) else s['episode_timeout'])
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
  elif hosted_qwen_mode(s) and not scripted:
   kw['input_counter']=b.counter
  elif model=='gpt-6-luna':
   kw['input_counter']=OpaqueReasoningInputCounter(QwenInputCounter(checked(s['tokenizer']),shared_tokenizer=shared))
  else:
   sizing=types.SimpleNamespace(model=model,base_url='https://openrouter.ai/api/v1',request_options={'reasoning':{'enabled':True}}) if scripted else b
   kw['input_counter']=model_matched_input_counter(sizing,assets_root=s['counter_assets_root'],shared_tokenizer=shared)
  kw['environment_admission']=environment_ready;kw['retry_policy']=None
  def make_env(video=None):
   timings['environment_creation_monotonic']=time.monotonic();phase_event('environment_creation_started')
   env=factory(video);environment_holder['env']=env;phase_event('environment_created')
   # Count actual reset on this one instance without altering native class/type guards.
   original=env.reset
   def reset(*a,**k):timings['reset_calls']+=1;return original(*a,**k)
   env.reset=reset
   return env
  kw['browser_step_context']=browser_step_context(admission,phase_event,guarded=browser_step_options(s)[0] is not None)
  _,telemetry=browser_step_options(s)
  if telemetry is not None:kw['env_step_telemetry']=telemetry
  return native_run(make_env,b,metadata,**kw)
 def projection(*,trace,grade):
  phase_event('native_grade_available');phase_event('grade_projection_started')
  if not Path(trace).resolve().is_relative_to(out/'live/runs'):raise ValueError('Trace escaped case')
  try:
   result=h['project'](s,out,{**c,'id':c['task_id']},trace=trace,grade=grade)
   if c['task_id'] in ('H01','H02'):result=address_projection_result(trace,result)
   save(out/'grade-viewer.json',result);phase_event('grade_projection_finished');return result
  except BaseException:
   phase_event('projection_error',stage='projection');raise
 @contextmanager
 def qwen_turn(phase):
  phase_event('generation_wait_started',episode_phase=phase)
  try:
   with capacity_client.turn(phase):
    phase_event('generation_permitted',episode_phase=phase)
    try:yield
    except BaseException as error:
     phase_event('generation_error',episode_phase=phase,stage='timeout' if isinstance(error,TimeoutError) else 'formatter' if phase=='formatter' else 'policy_transport');raise
    finally:phase_event('generation_operation_finished',episode_phase=phase)
  finally:phase_event('generation_scope_finished',episode_phase=phase)
 def fresh(phase):
  # Source/session/admission checks remain; browser revision/target validation
  # belongs to the owner pipeline AFTER completion, never the request worker.
  record({'event':'non_browser_request_guard','phase':phase})
 def extraction_backend(path):
  phase_event('grading_extraction_started')
  return Formatter() if scripted else factories.extraction_backend_factory(path) if qwen_mode(s) else backend('formatter',directory=path)
 try:
  if qwen_mode(s) and (not scripted or s.get('runtime_limits') is not None):
   if not scripted:qwen,serving=qwen_live(s)
   _,observer_module=qwen_modules(s)
   rpc=types.SimpleNamespace(**runpy.run_path(str(checked(s['qwen_sources']['rpc']))))
   binding=s['capacity_bindings'][c['id']]
   expiry=binding['deadline_utc'] if scripted else serving.deadline
   if type(expiry) not in (int,float) or not math.isfinite(expiry) or expiry<=time.time():
    raise ValueError('Future parent capacity deadline required')
   capacity_client=observer_module['connect_client'](rpc,binding,deadline=time.monotonic()+expiry-time.time(),on_event=lambda row:record_capacity(out,row))
  if qwen_mode(s) and not scripted:
   factories=qwen['QwenFactories'](backend_class=ChatCompletionsBackend,admission=serving,
    before_policy=lambda:before('policy'),before_formatter=lambda:before('formatter'),meter=record,freshness_guard=fresh,
    max_output_tokens=s['max_tokens'],request_timeout=s['request_timeout'],
    read_wait_policy=private_read_wait_policy(s),turn=qwen_turn,
    background_completion=capture_options(s)['observation_pipeline']=='auto',sampling=s.get('sampling'))
  result=run(c['argument'],out/'live',policy_session=session,metadata={'suite':s['suite_id'],'source':s['suite_id'],'case':c['id'],'model':'scripted' if scripted else model,'tags':['scripted','queue-acceptance'] if scripted else ['comparison',model,c['task_id']],'training_eligible':False},runner_options={'max_steps':c.get('scripted_max_steps',1) if scripted else c['max_steps'] if s.get('hosted_limit_profile')=='finite-task-limits-v1' else s['max_steps'],'max_input_tokens':c['max_input_tokens'],**{k:v for k,v in capture_options(s).items() if k!='recording_capture'}},viewer_projection=projection,quota_guard=guard,runner=runner,**h['case_options']({**c,'id':c['task_id']},extraction_backend))
  if result.get('status')!='graded_and_projected':raise ValueError('Missing automatic grading/HTTP projection: '+str(result))
  # A negative scripted task verdict is a completed control, not a job error.
  if timings['reset_calls']!=1:raise ValueError('Warm activation reset or duplicated environment')
  timings['finished_monotonic']=time.monotonic()
  save(out/'result.json',{'case':c['id'],'result':result,'status':'graded_and_projected','timings':timings,'usage':counts,'scripted':scripted,'case_binding_sha256':case_binding(c),'execution_binding_sha256':execution_binding(s,c),'caller_driver':s['driver'],'caller_commit':s['caller_commit']})
 except BaseException as e:
  save(out/'failure.json',{'type':type(e).__name__,'message':str(e),'stage':(phase_event.error_stage or ('grader' if counts['formatter_requests'] else child_error_stage(phase_event.last_phase))) if qwen_mode(s) else 'lifecycle','usage':counts,'timings':timings});raise
 finally:
  phase_event('cleanup_started')
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
  # Reached only after every acquired resource's close returned, so a case
  # that failed before acquiring a lease/channel has nothing left to release.
  save(out/'cleanup.json',{'status':'passed','case':c['id'],'wrapper_finalizers_returned':True,'recording_released':True,'pool_lease_released':True,'pool_lease_acquired':pooled is not None,'capacity_channel_closed':True,'capacity_channel_opened':capacity_client is not None,'capacity_infrastructure_error':None if capacity_client is None else capacity_client.infrastructure_error})
  phase_event('cleanup_finished')
  if qwen_mode(s):save(out/'phase-recording-status.json',{'status':'passed' if phase_event.failure is None else 'failed','error':phase_event.failure,'native_grade_unchanged':True})


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
 if s.get('shared_chromium') and not scripted and not pooled_model_mode(s):raise ValueError('Pooled comparison caller is model-free qualification only')
 stop=threading.Event();previous={kind:signal.getsignal(kind) for kind in (signal.SIGTERM,signal.SIGINT,signal.SIGALRM)}
 def terminate_suite(*args):stop.set();signal_deadline(*args)
 try:
  signal.signal(signal.SIGTERM,terminate_suite);signal.signal(signal.SIGINT,terminate_suite)
  return _supervise(s,scripted,stop)
 finally:
  for kind,handler in previous.items():signal.signal(kind,handler)

def _supervise(s,scripted=False,stop=None):
 browser_step_options(s)
 capture_options(s)
 pool_resource_options(s)
 if type(s.get('shared_chromium',False)) is not bool:raise ValueError('shared_chromium must be boolean')
 if s.get('shared_chromium') and not scripted and not pooled_model_mode(s):raise ValueError('Pooled comparison caller is model-free qualification only')
 if qwen_mode(s):validate_qwen_limits(s)
 if hosted_qwen_mode(s):hosted_runtime(s)['validate_limits'](s)
 for name in (('startup_timeout','suite_timeout') if pooled_model_mode(s) else ('startup_timeout','episode_timeout','suite_timeout')):
  if type(s.get(name)) is not int or not 0<s[name]<2**31:raise ValueError('Positive integer '+name+' required before any case claim')
 grace=s.get('shutdown_grace_seconds',30)
 if type(grace) is not int or not 1<=grace<=120:raise ValueError('Explicit cleanup grace must be1..120 seconds')
 if not scripted:check_release(s)
 h=helper(s);source_guard(s)
 if s.get('shared_chromium'):check_pool_source_pins(s)
 queue=runpy.run_path(str(checked(s['queue'])));channel=runpy.run_path(str(checked(s['channel'])))
 if not scripted and s.get('hosted_limit_profile')=='finite-task-limits-v1':
  authorized=hosted_authorization(s)
  save(finite_dispatch_claim_path(authorized),{'suite_id':s['suite_id'],'output':s['output'],
   'configuration_sha256':config_hash(s),'pid':os.getpid(),'process_start':h['process_identity'](os.getpid())})
 out=Path(s['output']);out.mkdir(parents=True,exist_ok=False)
 save(out/'supervisor-start.json',{'pid':os.getpid(),'process_start':h['process_identity'](os.getpid()),'epoch':time.time(),'monotonic':time.monotonic()})
 api=runpy.run_path(str(checked(s['events_helper'])));events=api['Events'](s.get('completion_db',out/'completion.sqlite'))
 members=s['start_order'] if hosted_qwen_mode(s) else load(checked(s['authorization']))['case_ids'] if not scripted else [c['id'] for c in s['cases']]
 events.register(s['suite_id'],members)
 if not scripted:
  for ident in members:events.subscribe(s['suite_id']+'-'+ident,s['suite_id'],'codex:'+s['thread_id'],episode=ident,final=False)
  events.subscribe(s['suite_id']+'-suite',s['suite_id'],'codex:'+s['thread_id'],milestones=[n for n in (10,20,30,35,40,50) if n<len(members)],final=True)
 h['register_roots'](s)
 ceiling=runtime_limits(s)
 stop=stop if stop is not None else threading.Event();service=None;pool_service=None;pool_log=None;listeners={};clocks={};lock=threading.Lock();delivery_lock=threading.Lock();capacity_host=None;serving=None;scripted_metrics=None;canary_barrier=make_canary_barrier(s,stop,scripted)
 phase_events={ident:phase_writer(s,ident,out/'phases',ident+'.jsonl') for ident in s['start_order']}
 for emit in phase_events.values():emit('queued')
 deadline_timer=None;job_stop_record={}
 def job_stop(cause,**evidence):
  """Job-lifetime stop with its own evidence; never caused by one case's error alone."""
  with lock:
   if not job_stop_record:
    job_stop_record.update(cause=cause,epoch=time.time(),monotonic=time.monotonic(),**evidence)
    try:save(out/'job-stop.json',dict(job_stop_record))
    except OSError as error:job_stop_record['evidence_write_error']=repr(error)
  stop.set()
 def shared_health_now():
  problems=[]
  if service is not None and service.poll() is not None:problems.append('tokenizer_service_exited')
  if pool_service is not None and pool_service.poll() is not None:problems.append('chromium_pool_service_exited')
  if capacity_host is not None:problems+=capacity_host.shared_health_problems()
  return problems
 def shared_health():
  # Re-observe before acting so a momentary telemetry gap is not an outage.
  # A dead service process is definitive; stale telemetry must persist.
  problems=shared_health_now()
  for _ in range(SHARED_HEALTH_RECHECKS):
   if not problems or any(p.endswith('_exited') or p=='metrics_poller_dead' for p in problems):break
   time.sleep(SHARED_HEALTH_RECHECK_SECONDS);problems=shared_health_now()
  return problems
 with tempfile.TemporaryDirectory(prefix='mq8-') as tmp:
  os.chmod(tmp,0o700);s=dict(s);s['tokenizer_socket']=str(Path(tmp)/'tokenizer.sock');s['sockets']={}
  if hosted_qwen_mode(s):
   s['suite_deadline_utc']=time.time()+s['suite_timeout']
  assets=[checked(s['tokenizer'])] if pooled_model_mode(s) else [Path(s['counter_assets_root'])/'mimo-v2.6-pro-73875d00/tokenizer.json',checked(s['tokenizer'])]
  manifest=Path(tmp)/'assets.json';save(manifest,[{'path':str(a),'sha256':pin(a)['sha256'],'normalization':'raw'} for a in assets])
  root=pool_source_case(s)['root']
  service=subprocess.Popen([s['python'],'-I','-B','-c',"import sys;sys.path.insert(0,sys.argv[1]);from intent_browser.tokenizer_service import main;sys.argv=sys.argv[1:];sys.argv[0]='tokenizer_service';main()",root,'--socket',s['tokenizer_socket'],'--manifest',str(manifest),'--max-clients',str(ceiling+s['prewarm_count'])],stdout=subprocess.PIPE,stderr=(out/'tokenizer-stderr.log').open('x'),text=True,env={**os.environ,'LD_LIBRARY_PATH':s['library_path']})
  try:
   if hosted_qwen_mode(s):
    deadline_timer=threading.Timer(s['suite_timeout'],stop.set);deadline_timer.daemon=True;deadline_timer.start()
   import select
   if not select.select([service.stdout],[],[],30)[0] or json.loads(service.stdout.readline()).get('ready') is not True:raise RuntimeError('Shared tokenizer host not ready')
   if s.get('shared_chromium'):
    pool_log=(out/'chromium-pool-stderr.log').open('x')
    pool_directory=(Path(tmp)/'chromium-pool').resolve()
    service_driver=checked(s['pool_service_driver'])
    if 'source_export' in s:h['verify_source_export'](s['caller_root'],s['caller_commit'],s['source_export'],{'scripts/shared_chromium_service.py':s['pool_service_driver']['sha256']})
    elif service_driver.read_bytes()!=subprocess.check_output(['git','-C',s['caller_root'],'show',s['caller_commit']+':scripts/shared_chromium_service.py']):raise ValueError('Pool service driver differs from committed source')
    checked(s['launcher'])
    if not qwen_mode(s):
     for case in queue_cases(s).values():h['recipe_check'](case)
    owner=load(out/'supervisor-start.json')
    s['chromium_descriptor']=str(pool_directory/'descriptor.json')
    pool_service=subprocess.Popen(['python3',s['launcher']['path'],'--memory-mib',str(pool_resource_options(s)[0]),'--tasks',str(pool_resource_options(s)[1]),'--receipt',str(out/'chromium-pool-bounded'),'--','timeout','--kill-after=30s',str(s['suite_timeout'])+'s',s['python'],'-I','-B',str(service_driver),'--source-root',root,'--owner-pid',str(owner['pid']),'--owner-start',owner['process_start'],'--directory',str(pool_directory),'--max-leases',str(2*(ceiling+s['prewarm_count'])),'--per-server',str(ceiling+s['prewarm_count'])],stdout=subprocess.PIPE,stderr=pool_log,text=True,env={**os.environ,'LD_LIBRARY_PATH':s['library_path']})
    if not select.select([pool_service.stdout],[],[],45)[0]:raise RuntimeError('Chromium pool service did not become ready')
    descriptor=pool_service.stdout.readline().strip()
    if descriptor!=str(pool_directory/'descriptor.json') or not Path(descriptor).is_file():raise RuntimeError('Chromium pool descriptor differs')
    s['chromium_descriptor']=descriptor
   if qwen_mode(s) and (not scripted or s.get('runtime_limits') is not None):
    modules=capacity_modules(s);_,observer_module=qwen_modules(s)
    if scripted:
     scripted_metrics=observer_module['ScriptedMetrics']()
     serving=types.SimpleNamespace(raw=scripted_metrics.raw,session='scripted-'+s['suite_id'],
      identity={'model':'scripted','serving_revision':'explicit-offline-metrics-fixture'},deadline=time.time()+s['suite_timeout'])
     save(out/'scripted-capacity-fixture.json',{'scripted':True,'provider_requests':0,'serving_readiness':False,
      'counter_parity':False,'scope':'Actual parent/client/control RPC with explicit offline policy/formatter/metrics fixtures'})
    else:_,serving=qwen_live(s)
    capacity_host=observer_module['CapacityHost'](rpc=modules['rpc'],control=modules['control'],telemetry=modules['telemetry'],source=s,output=out,case_ids=s['start_order'],cap=s['max_concurrent_episodes'],deadline=time.monotonic()+serving.deadline-time.time(),stop_event=stop,directory=tmp,qualification=serving)
    s['capacity_bindings']={ident:capacity_host.child_binding(ident) for ident in s['start_order']}
    if serving is not None:
     # Rental/allocation expiry is a job-lifetime control in private mode too.
     deadline_timer=threading.Timer(max(0,serving.deadline-time.time()),lambda:job_stop('rental_deadline',deadline_utc=serving.deadline))
     deadline_timer.daemon=True;deadline_timer.start()
    save(out/'observer-transport.json',{'socket':str(capacity_host.observer_rpc.path),'epoch':capacity_host.journal.epoch,'observer_id':capacity_host.observer.observer_id,'session_id':serving.session,'journal':str(out/'serving-telemetry.jsonl'),'maximum_batch_rows':120,'WandB_owner':'workstation controller; no credentials here'})
   for c in s['cases']:
    listener=socket.socket(socket.AF_UNIX);path=str(Path(tmp)/(c['id']+'.sock'));listener.bind(path);listener.listen(1);listener.settimeout(s['startup_timeout']);listeners[c['id']]=listener;s['sockets'][c['id']]=path
   # Capability-bearing child spec lives in the private temporary transport tree.
   runtime=Path(tmp)/'runtime-spec.json';save(runtime,s)
   save(out/'runtime-spec.redacted.json',{k:v for k,v in s.items() if k not in {'capacity_bindings','sockets','tokenizer_socket','chromium_descriptor'}})
   def one(c,admission):
    ident=c['id']
    if hosted_qwen_mode(s) and (stop.is_set() or (canary_barrier is not None and canary_barrier.failed) or time.time()>=s['suite_deadline_utc']):
     if time.time()>=s['suite_deadline_utc']:stop.set()
     raise queue['QueueCancelled']('Suite deadline/stop before case claim')
    if qwen_mode(s) and serving is not None:
     private_claim_gate(s,serving.deadline,grace,stop,job_stop,queue['QueueCancelled'])
    started=time.monotonic();process=None;connection=None;watchdog=None;connections={};stdout=None;stderr=None
    payload=None;terminal_released=False;events_finished=False
    with lock:clocks[ident]={'process_launch_monotonic':started}
    phase=phase_events[ident];phase('process_launch');stage='setup'
    try:
     events.start(s['suite_id'],ident)
     if qwen_mode(s):
      stage='readiness';check_private_case(s,c,scripted=scripted)
     stage='setup'
     stdout=(out/(ident+'-stdout.log')).open('x');stderr=(out/(ident+'-stderr.log')).open('x')
     if capacity_host is not None:capacity_host.begin_relay(ident)
     process=subprocess.Popen(['python3',s['launcher']['path'],'--memory-mib','2048','--tasks','256' if task_caps(s) else '0','--receipt',str(out/(ident+'-bounded')),'--','timeout','--kill-after=30s',str(s['suite_timeout'])+'s',s['python'],'-I','-B',s['driver']['path'],'scripted-case' if scripted else 'case',str(runtime),ident],stdout=stdout,stderr=stderr,env={**os.environ,'LD_LIBRARY_PATH':s['library_path']})
     watchdog=CaseWatchdog(process,connections,startup_seconds=s['startup_timeout'],episode_seconds=180 if scripted else s['episode_timeout'],cleanup_grace_seconds=grace,stop_event=stop,browser_step_seconds=browser_step_options(s)[0],rental_deadline=time.monotonic()+s['suite_deadline_utc']-time.time() if hosted_qwen_mode(s) else None if serving is None else time.monotonic()+serving.deadline-time.time())
     stage='readiness'
     connection,_=listeners[ident].accept();connection.settimeout(s['suite_timeout'])
     connections['connection']=connection
     # Ready receipt precedes gate; activation reply is emitted only under queue's cap.
     watched=WatchedAdmission(admission,watchdog,phase)
     if capacity_host is not None or canary_barrier is not None:
      original=watched.environment_ready
      def ready(value=None):
       phase('environment_ready')
       original(value)
       if canary_barrier is not None:canary_barrier.wait(ident)
       if capacity_host is not None:capacity_host.activate(ident,priority=s['start_order'].index(ident))
       phase('activated')
      watched.environment_ready=ready
     stage='lifecycle'
     proof=channel['serve_admission'](connection,watched,expected_run_root=out/ident/'live/runs')
     code=process.wait(timeout=60);stdout.close();stderr.close()
     if watchdog.failure is not None:raise CaseDeadline(str(watchdog.failure))
     if code!=0:raise RuntimeError('Child lifecycle exited '+str(code))
     stage='grader_or_projection'
     result=load(out/ident/'result.json');grade=load(out/ident/'grade-viewer.json')
     if result['status']!='graded_and_projected' or grade['status']!='verified':raise ValueError('Child grading/viewer unavailable')
     phase('grade_verified')
     if qwen_mode(s):
      stage='cleanup';watchdog.close();connection.close();connection=None
     task=result['result']['viewer_projection']['task_completed'];payload={'result':pin(out/ident/'result.json'),'viewer':grade,'usage':result['usage'],'task_verdict':'pass' if task is True else 'fail' if task is False else 'inconclusive'}
     if capacity_host is not None:
      def cleanup():
       return process.poll()==0 and verified_case_cleanup(s,ident,out,process)
      stage='cleanup'
      capacity_host.finish_isolated_case(ident,verify_cleanup=cleanup,record_terminal=lambda:result['status']=='graded_and_projected' and grade['status']=='verified')
     terminal_released=True
     phase('terminal_cleanup_verified')
     events.finish(s['suite_id'],ident,'succeeded',payload);events_finished=True
     if not scripted:
      with delivery_lock:flush_completions(s,events,api)
     if canary_barrier is not None:canary_barrier.complete(ident,formatter_exercised=not hosted_qwen_mode(s) or result['usage']['formatter_requests']==1)
     return {'case':ident,'state':'succeeded','payload':payload,'admission':proof}
    except BaseException as e:
     if canary_barrier is not None:canary_barrier.fail(ident)
     if watchdog is not None and watchdog.failure is not None:
      deadline_error=CaseDeadline(str(watchdog.failure));deadline_error.__cause__=e;e=deadline_error
     if qwen_mode(s) and terminal_released:
      # Capacity and cleanup were verified and released; only later diagnostic
      # output failed. Do not re-quarantine a finished lifecycle.
      failure={'stage':'post_terminal_diagnostics','type':type(e).__name__,'message':str(e),
       'quarantined':False,'events_finished':events_finished,'native_task_verdict':payload['task_verdict']}
      try:save(out/(ident+'-post-terminal-error.json'),{'case':ident,**failure})
      except BaseException:pass
      try:admission.release_without_quarantine({'post_terminal_error':failure})
      except BaseException:pass
      if not events_finished:
       try:events.finish(s['suite_id'],ident,'succeeded',{**payload,'post_terminal_error':failure})
       except BaseException:pass
      raise CaseInfrastructureError('post_terminal_diagnostics: '+str(e)) from e
     if qwen_mode(s):
      try:stage='blocked_admission' if isinstance(e,queue['AdmissionBlocked']) else case_error_stage(e,watchdog,out,ident,stage)
      except BaseException as diagnostic:e.add_note('Failure stage read unavailable: '+repr(diagnostic))
      stopped_cause=job_stop_record.get('cause') or ('external_stop' if stop.is_set() else None)
      failure={'stage':stage,'type':type(e).__name__,'message':str(e),'quarantined':True,'task_verdict':None}
      try:
       if watchdog is not None:watchdog.close()
       failure=isolate_case_error(s,ident,e,stage,out,process,connection,capacity_host,admission,
        shared_health=None if stopped_cause else shared_health)
      except BaseException as diagnostic:
       # Shared output IO may itself fail. Keep the reservation.
       # Do not silently release unknown state.
       try:admission.quarantine({'stage':stage,'evidence_write_failed':repr(diagnostic)})
       except BaseException:pass
       try:
        if capacity_host is not None:capacity_host.quarantine_case(ident,e)
       except BaseException:pass
       failure['evidence_error']=repr(diagnostic)
      if failure.get('shared_health_problems'):
       job_stop('shared_service_unhealthy',problems=failure['shared_health_problems'],observed_at_case=ident)
      if payload is not None:failure['native_task_verdict']=payload['task_verdict'];failure['graded_result']=payload['result']
      if stopped_cause:failure['job_stop']=stopped_cause
      phase('case_error',stage=stage,type=type(e).__name__,quarantined=failure['quarantined'])
      events.finish(s['suite_id'],ident,'failed',{'system_failure':failure,'task_verdict':None})
      if not scripted:
       with delivery_lock:flush_completions(s,events,api)
      if isinstance(e,queue['AdmissionBlocked']):raise e
      if stopped_cause:raise queue['QueueCancelled'](stopped_cause+' during case: '+stage+': '+str(e)) from e
      raise CaseInfrastructureError(stage+': '+str(e)) from e
     if capacity_host is not None:capacity_host.failed(ident,e,infrastructure=not isinstance(e,queue['QueueCancelled']))
     events.finish(s['suite_id'],ident,'failed',{'system_failure':{'type':type(e).__name__,'message':str(e)},'task_verdict':None})
     if not scripted:
      with delivery_lock:flush_completions(s,events,api)
     raise e
    finally:
     if not qwen_mode(s):
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
        phase('lifecycle_finished')
        with lock:clocks[ident]['lifecycle_finished_monotonic']=time.monotonic()
     else:
      final_errors=[]
      for action in (lambda:watchdog.close() if watchdog is not None else None,
                     lambda:connection.close() if connection is not None else None,
                     lambda:bounded_case_cleanup(s,process,None) if qwen_mode(s) else terminate_owned_child(process),
                     lambda:stdout.close() if stdout is not None else None,
                     lambda:stderr.close() if stderr is not None else None):
       try:action()
       except BaseException as error:final_errors.append({'type':type(error).__name__,'message':str(error)})
      phase('lifecycle_finished',secondary_cleanup_errors=final_errors)
      with lock:clocks[ident]['lifecycle_finished_monotonic']=time.monotonic()
      if final_errors:
       # A cleanup error cannot turn an already caught case failure into a job
       # cancellation. Persist it independently, retaining the primary error.
       try:save(out/(ident+'-secondary-cleanup.json'),{'case':ident,'errors':final_errors})
       except BaseException:pass
       if sys.exception() is None:raise CaseInfrastructureError('Case final cleanup failed: '+repr(final_errors))
   options={'isolate_case_errors':True} if qwen_mode(s) else {}
   if s.get('runtime_limits') is not None:
    if capacity_host is None:raise ValueError('Runtime controls require a real capacity parent')
    options.update({'max_concurrent_ceiling':ceiling,'on_queue_ready':lambda handle:capacity_host.bind_limits(handle,out)})
   result=queue['run_ordered_suite'](queue_cases(s),one,max_concurrent_episodes=s['max_concurrent_episodes'],prewarm_count=s['prewarm_count'],start_order=s['start_order'],stop_event=stop,**options)
   result['max_observed_active']=max(e['active'] for e in result['events']);result['max_observed_warming']=max(e['warming_or_ready'] for e in result['events']);result['clocks']=clocks
   if job_stop_record:result['job_stop_record']=dict(job_stop_record)
   save(out/'suite-result.json',result)
   if result['max_observed_active']>ceiling or result['max_observed_warming']>s['prewarm_count']:raise RuntimeError('Concurrency/warming bound violated')
   if pooled_model_mode(s):
    reconcile_queue_events(s,result,clocks,events,out)
    if not scripted:flush_completions(s,events,api)
   measurements=[]
   warm_ids={e['case'] for e in result['events'] if e['event']=='warmup_started'}
   for ident in s['start_order']:
    path=out/ident/'result.json'
    if not path.is_file():continue
    try:
     t=load(path)['timings'];start=clocks[ident]['process_launch_monotonic']
     measurements.append(timing_record(ident,t,start,ident in warm_ids))
    except Exception as error:
     measurements.append({'case':ident,'measurement_error':{'type':type(error).__name__,'message':str(error)},'timings_unknown':True})
   save(out/'suite-measurements.json',{'max_active':result['max_observed_active'],
    'max_warming_or_parked':result['max_observed_warming'],'cases':measurements,
    'phase_journals':[{'case':ident,'parent':pin(out/'phases'/(ident+'.jsonl')) if (out/'phases'/(ident+'.jsonl')).exists() else None,
     'parent_recording_error':phase_events[ident].failure,
     'child':pin(out/ident/'child-phases.jsonl') if (out/ident/'child-phases.jsonl').exists() else None}for ident in s['start_order']] if qwen_mode(s) else [],
    'caller_commit':s['caller_commit'],'driver':s['driver'],'configuration_sha256':config_hash(s),
    'qualification':'Observed boundary times; native grader entry is not instrumented. Missing phases remain unknown, and setup timings are not a paired causal speedup experiment.'})
   if qwen_mode(s):
    aggregate=suite_outcome_counts(result)
    save(out/'suite-outcomes.json',{'schema':'continuous-qwen-suite-outcomes-v1','counts':aggregate,
     'quarantined':[ident for ident,row in result['cases'].items() if row.get('quarantine') is not None],
     'job_stop':stop.is_set(),'job_stop_cause':job_stop_record.get('cause') or (result.get('job_stop') or {}).get('cause'),'source':s['driver'],'caller_commit':s['caller_commit'],
     'scripted':scripted,'no_failed_case_retry':True})
   if any(r['status']!='completed' for r in result['cases'].values()):raise RuntimeError('One or more case infrastructure failures')
   if not scripted:flush_completions(s,events,api)
  finally:
   stop.set()
   if deadline_timer is not None:deadline_timer.cancel();deadline_timer.join(2)
   for listener in listeners.values():listener.close()
   try:
    if capacity_host is not None:
     try:save(out/'capacity-terminal.json',{'status':capacity_host.controller.status(),**({'limits':capacity_host.controller.limits()} if s.get('runtime_limits') is not None else {}),'parent_errors':capacity_host.parent.errors,'cleanup_failures':capacity_host.parent.cleanup_failures,'finished':sorted(capacity_host.parent.finished),'quarantined':capacity_host.parent.quarantined,'stop_cause':capacity_host.parent.stop_cause})
     finally:
      try:capacity_host.close()
      finally:
       if scripted_metrics is not None:scripted_metrics.close();scripted_metrics=None
   finally:
    if scripted_metrics is not None:scripted_metrics.close()
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



def suite_outcome_counts(result):
 aggregate={'completed':0,'execution_failed':0,'blocked':0,'cancelled_by_job_stop':0,'not_started':0,'task_pass':0,'task_fail':0,'inconclusive':0,'unknown':0}
 for row in result['cases'].values():
  if row['status']=='completed':
   aggregate['completed']+=1
   verdict=row['result']['payload']['task_verdict']
   aggregate['task_pass' if verdict=='pass' else 'task_fail' if verdict=='fail' else 'inconclusive']+=1
  else:
   # A started case ended by a job stop is cancelled, not an execution failure.
   aggregate['execution_failed' if row['status']=='failed' else 'blocked' if row['status']=='blocked'
    else 'cancelled_by_job_stop' if row['status']=='cancelled' else 'not_started']+=1
   aggregate['unknown']+=1
 return aggregate


def reconcile_queue_events(s,result,clocks,events,out):
 # Bookkeeping retry only, never a repeated browser/model attempt. Failed
 # callbacks may have exited before their own Events error handler completed.
 evidence=pin(out/'suite-result.json')
 for ident,row in result['cases'].items():
  if qwen_mode(s) and row['status']=='failed':
   with events.transaction() as db:
    state=db.execute('SELECT state FROM episodes WHERE suite=? AND id=?',(s['suite_id'],ident)).fetchone()
   if state is not None and state[0] in ('pending','running'):
    if state[0]=='pending':events.start(s['suite_id'],ident)
    events.finish(s['suite_id'],ident,'failed',{'task_verdict':None,'system_failure':row['error'],'quarantine':row.get('quarantine'),'evidence':evidence})
  elif ident not in clocks:
   events.finish(s['suite_id'],ident,'not_started',{'stage':'suite_admission','reason':'Shared service/lifetime/containment failure before claim' if qwen_mode(s) else 'Canary infrastructure failure or suite stop before claim','queue_state':row['status'],'blocked_by_quarantine':row['status']=='blocked','evidence':evidence})


def finalize_unclaimed(s,events,reason):
 with events.transaction()as db:
  pending=[row[0]for row in db.execute("SELECT id FROM episodes WHERE suite=? AND state='pending'",(s['suite_id'],))]
 for ident in pending:events.finish(s['suite_id'],ident,'not_started',{'stage':'suite_admission','reason':reason,'provider_dispatches':0})

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
    if pooled_model_mode(s) and not prior_output and owner_path.is_file() and load(owner_path).get('pid')==os.getpid():
     api=runpy.run_path(str(checked(s['events_helper'])));events=api['Events'](s.get('completion_db',str(Path(s['output'])/'completion.sqlite')))
     finalize_unclaimed(s,events,'Supervisor ended before case admission')
     if mode!='scripted':flush_completions(s,events,api)
    if pooled_model_mode(s) and not prior_output and owner_path.is_file() and load(owner_path).get('pid')==os.getpid():terminal_inventory(s)
   except BaseException as inventory_error:
    if primary is None:raise
    primary.add_note('Terminal inventory also failed: '+repr(inventory_error))
 elif mode=='prepare-qwen':
  if not pooled_model_mode(s):raise ValueError('Explicit Qwen runtime mode required')
  if qwen_mode(s):validate_qwen_limits(s)
  else:hosted_runtime(s)['validate_limits'](s)
  source_guard(s)
  h=helper(s)
  for c in s['cases']:h['recipe_check'](c)
  print(json.dumps({'status':'source_prepared_NOT_runtime_ready','cases':[c['id'] for c in s['cases']],'models':0,'provider_requests':0,'caller':s['driver'],**({'admission_policy':private_admission_policy(s),'model_canary_phases':0}if qwen_mode(s) else {})}))
 else:raise ValueError('Unknown mode')
if __name__=='__main__':main()
