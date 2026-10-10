"""One source-isolated B06 with automatic grading and no episode-duration alarm.

The actual provider lifetime, per-request and startup watchdogs remain finite.
Serving/proof/parser admission is fail-closed; this module never allocates a GPU.
"""
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from urllib.request import urlopen
import argparse, ast, importlib, inspect, json, math, os, runpy, sys, importlib.abc, importlib.machinery, signal, time, threading
sys.dont_write_bytecode=True

def read(p): return json.loads(Path(p).read_bytes())
def pin(p):
 p=Path(p).resolve();return {'path':str(p),'sha256':sha256(p.read_bytes()).hexdigest()}
def checked(row):
 p=Path(row['path']).resolve()
 if pin(p)!=row:raise ValueError('Pinned input changed: '+str(p))
 return p
def save(p,v):
 with Path(p).open('x') as f:json.dump(v,f,indent=2,ensure_ascii=False);f.write('\n')
def isolate(spec):
 binding=read(checked(spec['isolation_binding']));root=Path(binding['root']).resolve()
 helper=runpy.run_path(str(checked(binding['viewer_bootstrap'])))
 manifest=read(checked(binding['manifest']));assets=read(checked(binding['external_assets']));external=Path(assets['source_root']).resolve()
 for folder,pins in ((root,manifest['source_sha256']),(external,{n:v['sha256'] for n,v in assets['files'].items()})):
  helper['require_import_closure'](folder,pins)
  for name,h in pins.items():checked({'path':str(folder/name),'sha256':h})
 excluded={root,external,Path('/home/bjorn/code/LLM_proj_uu'),Path(binding['original_external_root'])}
 sys.path[:]=[str(root),str(external)]+[s for s in sys.path if Path(s or '.').resolve() not in excluded]
 sys.dont_write_bytecode=True
 os.environ['HARNESS_AX_TOKENIZER']=str(checked(binding['tokenizer']));os.environ['LD_LIBRARY_PATH']=binding['library_path']
 return binding,root,external,helper

class EmergencyStop:
    """Record a terminal infrastructure failure and exit without Playwright cleanup.

    Raising inside its sync greenlet can destroy the dispatcher. Signals and
    browser-watchdog expiry therefore stop from a separate thread instead.
    The bounded launcher kills descendants; Training stops remote serving.
    """
    def __init__(self, record):
        self.record = record
        self.lock = threading.Lock()
        self.request = threading.Event()
        self.reason = None
        # Allocate emergency workers BEFORE browser startup. A saturated thread
        # cap during a stall must not make a signal handler raise into Playwright.
        def stop():
            self.request.wait()
            try:
                self.record(self.reason)
            finally:
                os._exit(124)
        def fallback():
            self.request.wait()
            time.sleep(5)
            os._exit(124)
        for target in (stop, fallback):
            threading.Thread(target=target, daemon=True).start()

    def __call__(self, reason):
        if not self.lock.acquire(blocking=False):
            return
        self.reason = reason
        self.request.set()


class Watchdogs:
    """No aggregate episode budget. Expiry comes only from the provider platform."""
    def __init__(self, live, *, startup_seconds=180, request_seconds=600,
                 utc=time.time, mono=time.monotonic, emergency_stop=None):
        self.utc, self.mono = utc, mono
        self.emergency_stop = emergency_stop
        for value in (startup_seconds, request_seconds):
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ValueError('Positive finite operation watchdog required')
        self.startup_seconds, self.request_seconds = startup_seconds, request_seconds
        lifetime = live['platform_lifetime']
        if lifetime.get('mode') != 'episode-owned' or lifetime.get('expiry_kind') != 'provider-platform-maximum':
            raise ValueError('Actual platform lifetime required; no episode cutoff')
        started, expires, maximum = [lifetime[k] for k in ('started_at_utc', 'expires_at_utc', 'provider_max_seconds')]
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in (started, expires, maximum)):
            raise ValueError('Finite platform lifetime required')
        if maximum != 86400 or not started <= utc() < expires or abs(expires - started - maximum) > 1:
            raise ValueError('Lifetime must equal actual provider maximum')
        if live['gpu_deadline_utc'] != expires:
            raise ValueError('Legacy deadline alias must be actual platform expiry')
        self.expires = expires
        self.deadline_monotonic = mono() + expires - utc()

    def remaining(self):
        n = min(self.expires - self.utc(), self.deadline_monotonic - self.mono())
        if n <= 0:
            raise TimeoutError('Actual provider platform lifetime expired')
        return n

    def timeout(self, limit=None):
        return min(self.request_seconds if limit is None else limit, self.remaining())

    @contextmanager
    def operation(self, name, seconds, *, browser=False):
        """Bound a stalled synchronous operation; always disarm its own alarm."""
        if browser:
            if self.emergency_stop is None:
                raise ValueError('Browser watchdog requires durable emergency stop')
            active = threading.Event()
            active.set()
            fired = threading.Event()
            def browser_expired():
                if active.is_set():
                    fired.set()
                    self.emergency_stop(name + ' watchdog expired')
            timer = threading.Timer(self.timeout(seconds), browser_expired)
            timer.daemon = True
            timer.start()
            try:
                yield
                self.remaining()
                if fired.is_set():
                    # Only a synthetic stop callback can return normally.
                    raise TimeoutError(name + ' watchdog expired')
            finally:
                active.clear()
                timer.cancel()
            return
        if signal.getitimer(signal.ITIMER_REAL)[0] != 0:
            raise RuntimeError('Overlapping wall-clock watchdog is not allowed')
        previous = signal.getsignal(signal.SIGALRM)
        fired = False
        def expired(signum, frame):
            nonlocal fired
            fired = True
            raise TimeoutError(name + ' watchdog expired')
        signal.signal(signal.SIGALRM, expired)
        signal.setitimer(signal.ITIMER_REAL, self.timeout(seconds))
        try:
            yield
            self.remaining()
            if fired:
                raise TimeoutError(name + ' watchdog expired')
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous)


def verify_parser(spec, live):
    receipt = read(checked(live['parser_patch_receipt']))
    binding = spec['parser_patch_binding']
    if set(binding) != {'original_source_sha256', 'patched_source_sha256', 'patch_sha256'}:
        raise ValueError('Exact reviewed parser binding required')
    for key, value in binding.items():
        if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
            raise ValueError('Exact parser SHA256 required')
        if receipt.get(key) != value:
            raise ValueError('Installed parser patch differs')
    if receipt.get('passed') is not True or receipt.get('serving_session_id') != live['serving_session_id']:
        raise ValueError('Actual installed parser regression/session evidence missing')
    regression = read(checked(receipt['regression_receipt']))
    if regression.get('passed') is not True or regression.get('patched_source_sha256') != binding['patched_source_sha256']:
        raise ValueError('Actual patched parser regressions did not pass')
    if regression.get('serving_session_id') != live['serving_session_id']:
        raise ValueError('Parser regression session differs')
    server = read(checked(live['deployment_receipt']))['qualification']
    count = read(checked(live['complete_wire_count_parity_proof']))
    if server.get('parser_patch_sha256') != binding['patch_sha256'] or count.get('parser_patch_sha256') != binding['patch_sha256']:
        raise ValueError('Serving/count fingerprint omits reviewed parser patch')
    return receipt


def verify_projection(live):
    proof = read(checked(live['complete_wire_count_parity_proof']))
    relay = checked(live['relay_source'])
    source = relay.read_text()
    functions = [n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name == 'tokenize_payload']
    if len(functions) != 1:
        raise ValueError('Unique relay projection required')
    projection = dict(counter_source_sha256='3b89ffe833520c9ec94cf290e30d3aa127241c1ed904754e73c3d4141ea9f29b',
        counter_wire_function_sha256='f21b9f8becf3a8713ad3bcf59d610cc59f97406a5d17b6396013191dd5ad2de3',
        tokenize_projection_source_sha256=live['relay_source']['sha256'],
        tokenize_projection_function_sha256=sha256(ast.get_source_segment(source,functions[0]).encode()).hexdigest(),
        relay_source_sha256=live['relay_source']['sha256'])
    value = sha256(json.dumps(projection,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()
    if proof.get('runtime_projection') != projection or proof.get('counter_projection_sha256') != value:
        raise ValueError('Ordered counter composite fingerprint differs')
    if proof.get('counter_projection_digest_format') != 'sha256-compact-sorted-utf8-json-of-runtime-projection-v1':
        raise ValueError('Reviewed implementation fingerprint formula required')
    if read(checked(live['deployment_receipt']))['qualification'].get('counter_projection_sha256') != value:
        raise ValueError('Actual serving counter fingerprint differs')
    return value


def build_runtime(spec, live, watchdogs):
    verify_parser(spec, live)
    verify_projection(live)
    source = checked(spec['ordered_counter_source'])
    if sha256(source.read_bytes()).hexdigest() != '3b89ffe833520c9ec94cf290e30d3aa127241c1ed904754e73c3d4141ea9f29b':
        raise ValueError('Released db706d65 ordered counter required')
    api = runpy.run_path(str(source))
    # Use the existing ordered counter unchanged. Its finite deadline is the
    # provider's actual platform maximum, never a custom episode budget.
    return api['build'](live=live, deadline_monotonic=watchdogs.deadline_monotonic)


def episode(spec_path,live_path,output,watchdogs):
 def remaining():return watchdogs.remaining()
 spec=read(spec_path)
 if spec['case']!='B06':raise ValueError('One B06 only')
 live=read(live_path)
 if spec.get('schema') != 'modal-full-B06-v1':raise ValueError('Full episode contract required')
 with watchdogs.operation('execution startup',watchdogs.startup_seconds):
  checked(spec['factory_source']);checked(spec['original_runtime_source']);checked(spec['original_runtime_spec'])
  dependency_inventory=read(checked(spec['venv_dependency_inventory']))
  if Path(sys.executable).resolve()!=Path(dependency_inventory['interpreter']).resolve():raise ValueError('Pinned interpreter differs')
  dependency_files={row['path']:row for row in dependency_inventory['files']}
  for row in dependency_files.values():checked(row)
  selected_roots=set()
  for path in dependency_files:
   parts=Path(path).parts
   if 'site-packages' in parts:
    name=parts[parts.index('site-packages')+1]
    if not name.endswith('.dist-info'):selected_roots.add(name.split('.')[0])
  class DependencyOrigins(importlib.abc.MetaPathFinder):
   def find_spec(self,fullname,path=None,target=None):
    if fullname.split('.')[0] not in selected_roots:return None
    found=importlib.machinery.PathFinder.find_spec(fullname,path)
    if found and found.origin and found.origin not in {'built-in','frozen'}:
     origin=str(Path(found.origin).resolve())
     if origin not in dependency_files:raise ValueError('Unpinned selected dependency origin '+origin)
     checked(dependency_files[origin])
    return found
  for name,module in list(sys.modules.items()):
   if name.split('.')[0] in selected_roots:
    origin=str(Path(module.__file__).resolve())
    if origin not in dependency_files:raise ValueError('Selected dependency already loaded from foreign origin')
    checked(dependency_files[origin])
  sys.meta_path.insert(0,DependencyOrigins())
  binding,root,external,helper=isolate(spec)
  if spec.get('reviewed_commit')!=binding['commit']:raise ValueError('Runtime spec/reviewed release commit differs')
  checked(spec['review_report'])
  with urlopen(binding['viewer_url']+'/api/sessions',timeout=25) as response:
   if response.status != 200:raise ValueError('Trace viewer unavailable before dispatch')
   json.load(response)
  recipe=checked(spec['recipe_manifest']).parent
  for n,h in read(recipe/'manifest.json')['files'].items():checked({'path':str(recipe/n),'sha256':h})
  module=importlib.import_module(spec['caller']['module']);call=getattr(module,spec['caller']['symbol'])
  if pin(inspect.getsourcefile(call))!=spec['caller']['source']:raise ValueError('Released caller source differs')
 events=[];holder={};factory_events=[]
 from intent_browser.backend import ChatCompletionsBackend
 from intent_browser.runner import run_episode
 from scripts.trace_grades import read_grade
 def guard():
  remaining();checked(spec['isolation_binding']);checked(spec['recipe_manifest']);checked(spec['caller']['source']);helper['require_module_origins'](root,external)
  public=read(output/'runtime-binding/task.public.json')
  if public['user_message']!=spec['expected_user_message'] or public['memories']!=spec['public_memories']:raise ValueError('Bound public prose/memories differ')
 factory_module=runpy.run_path(str(checked(spec['factory_source'])))
 PrivateFactories=factory_module['PrivateFactories']
 with watchdogs.operation('counter admission', watchdogs.startup_seconds):
  runtime=build_runtime(spec,live,watchdogs)
 if set(runtime)!={'complete_request_counter','runner_input_counter','readiness','expected_identity','base_url','api_key'}:raise ValueError('Protocol runtime contract differs')
 expected_identity=runtime['expected_identity']
 def backend_class(*args,**kwargs):
  kwargs['timeout']=watchdogs.timeout()
  backend=ChatCompletionsBackend(*args,**kwargs)
  original=backend.complete
  def complete(messages):
   backend.client.timeout=watchdogs.timeout()
   with watchdogs.operation('model request', watchdogs.request_seconds):
    return original(messages)
  backend.complete=complete;return backend
 def extraction_guard():remaining();guard()
 factories=PrivateFactories(backend_class=backend_class,base_url=runtime['base_url'],model=expected_identity['model'],api_key=runtime['api_key'],server_context=131072,isl=100000,complete_request_counter=runtime['complete_request_counter'],expected_identity=expected_identity,readiness=runtime['readiness'],extraction_before_dispatch=extraction_guard,meter=factory_events.append,timeout=watchdogs.timeout())
 @contextmanager
 def session(*,before_dispatch):
  def admission():
   remaining();before_dispatch()
  try:
   with factories.policy_session(before_dispatch=admission) as backend:yield backend
  finally:
   if factories.policy_finished:events.append('policy_closed')
 def runner(factory,backend,metadata,**options):
  if options['automatic_grading'].phase!='external':raise ValueError('External automatic grader required')
  if spec.get('hidden_interaction') and (not callable(options.get('clarification_callback')) or not options.get('clarification_audit_id')):raise ValueError('Actual hidden reply callback/audit binding absent')
  def make_env(video=None):
   with watchdogs.operation('browser startup', watchdogs.startup_seconds,browser=True):
    env=factory(video)
   original_reset=env.reset
   def reset(*args,**kwargs):
    with watchdogs.operation('browser setup',watchdogs.startup_seconds,browser=True):
     return original_reset(*args,**kwargs)
   env.reset=reset
   for method in ('step','close'):
    original_method=getattr(env,method)
    def bounded(*args,_method=method,_original=original_method,**kwargs):
     with watchdogs.operation('browser '+_method,watchdogs.startup_seconds,browser=True):
      return _original(*args,**kwargs)
    setattr(env,method,bounded)
   holder['actual_browser']=True;return env
  return run_episode(make_env,backend,metadata,**options)
 def project(*,trace,grade):
  derived=read_grade(trace)
  if derived['binding_status']!='verified' or derived['structured_claims_correct'] is not grade['structured_claims_correct']:raise ValueError('Native/sidecar verdict differs')
  ident=sha256(('browsergym:'+Path(trace).name).encode()).hexdigest()[:20]
  base=binding['viewer_url']
  with urlopen(base+'/api/sessions',timeout=min(25,remaining())) as r:r.read()
  with urlopen(base+'/api/sessions/'+ident,timeout=min(25,remaining())) as r:detail=json.load(r)
  if detail['derived_evaluation']!=derived:raise ValueError('Actual HTTP projection differs from bound grade')
  canonical=read(Path(trace)/'evaluation.json')
  if canonical['task_completed'] is not grade['structured_claims_correct']:raise ValueError('Canonical automatic verdict differs')
  proof={'status':'verified','url':base+'/#'+ident,'derived_grade':pin(Path(trace)/'derived-answer-grade.json'),'canonical_grade':pin(Path(trace)/'evaluation.json')}
  save(output/'HTTP-proof.json',proof);return proof
 output=Path(output).resolve();output.parent.mkdir(parents=True,exist_ok=True)
 # The released caller's positional/keyword contract is supplied, not inferred.
 args=[str(recipe),str(output)]
 def formatter_factory(*args):
  remaining();return factories.extraction_backend_factory(*args)
 kwargs={**spec['caller'].get('kwargs',{}),'policy_session':session,'metadata':{'model':expected_identity['model'],'driver':'modal-real-model','tags':['model','modal-full-episode',spec['case']],'training_eligible':False},'runner_options':{'max_steps':None,'max_input_tokens':100000,'retry_policy':None,'input_counter':runtime['runner_input_counter'],'trace_screenshots':False},'viewer_projection':project,'quota_guard':guard,'extraction_backend_factory':formatter_factory,'runner':runner}
 inspect.signature(call).bind(*args,**kwargs)
 try:
  result=call(*args,**kwargs)
  save(output.parent/(output.name+'-driver-result.json'),{'result':result,'actual_browser':holder.get('actual_browser',False),'spec':pin(spec_path),'live':pin(live_path),'factory_events':factory_events})
  if result['status']!='graded_and_projected':raise ValueError('Runtime failed: '+str(result.get('reason')))
  if result['policy_summary']['max_steps'] is not None or result['policy_summary']['max_input_tokens']!=100000:raise ValueError('Actual runner limits differ')
  if not holder.get('actual_browser'):raise ValueError('No actual browser startup observed')
  save(output/'factory-live-proof.json',{'identity':expected_identity,'events':factory_events,'qualification':'Actual admitted requests/responses; tokens from released full-wire server counter. No synthetic counts/answers.'})
  return {'trace':result['trace'],'task_verdict':result['native_grade']['structured_claims_correct'],'native_grade':result['native_grade'],'canonical':pin(Path(result['trace'])/'evaluation.json'),'HTTP_proof':pin(output/'HTTP-proof.json'),'factory_live_proof':pin(output/'factory-live-proof.json'),'qualification':'Real model B06 and attached extractor; broad effects unknown'}
 except BaseException:
  raise


def preflight(spec, live):
 if spec.get('schema') != 'modal-full-B06-v1' or spec.get('case') != 'B06':
  raise ValueError('One B06 full-episode contract required')
 if live.get('dispatch_authorized') is not True:
  raise ValueError('Explicit fresh dispatch authorization required')
 if any(k in spec for k in ('maximum_episode_seconds','episode_deadline_utc','policy_grading_reserve_seconds')):
  raise ValueError('Arbitrary episode-duration budget is forbidden')
 if spec.get('watchdogs') != {'startup_seconds':180,'request_seconds':600}:
  raise ValueError('Reviewed startup/request watchdogs must be 180/600 seconds')
 serving=read(checked(live['serving_binding']))
 deployment=read(checked(live['deployment_receipt']))
 if deployment.get('platform_lifetime') != live['platform_lifetime']:
  raise ValueError('Actual deployment/platform lifetime differs')
 identity=deployment['qualification']['identity']
 # source_commit in serving identity denotes unchanged95 task lineage. The
 # execution root is separately bound to the argument-recovery descendant.
 if serving['first_case']['commit'] != '95e9ac988ea515f7194cbdc82ae327e248fc94fa' or identity != live['identity']:
  raise ValueError('Accepted B06 serving/task lineage differs')
 if identity.get('source_commit') != serving['first_case']['commit']:
  raise ValueError('Task lineage identity differs')
 if live.get('server_context') != 131072 or live.get('isl') != 100000:
  raise ValueError('B06 ISL/context differs')
 verify_parser(spec,live)
 return Watchdogs(live,startup_seconds=spec['watchdogs']['startup_seconds'],request_seconds=spec['watchdogs']['request_seconds'])


def verify_terminal(result):
    verdict = result['task_verdict']
    if verdict is not None and type(verdict) is not bool:
        raise ValueError('Native task verdict must be boolean or explicitly inconclusive')
    canonical = read(checked(result['canonical']))
    proof = read(checked(result['HTTP_proof']))
    if result['native_grade']['structured_claims_correct'] is not verdict or canonical['task_completed'] is not verdict:
        raise ValueError('Terminal native/canonical grade differs')
    if canonical.get('technical_error'):
        raise ValueError('Automatic grading has a technical error')
    if verdict is None and not canonical.get('limitations'):
        raise ValueError('Explicit inconclusive reason required')
    if proof.get('status') != 'verified' or not proof.get('url'):
        raise ValueError('Terminal HTTP grade projection missing')
    if proof.get('canonical_grade') != result['canonical']:
        raise ValueError('HTTP/canonical grade binding differs')
    derived = read(checked(proof['derived_grade']))
    if derived.get('binding_status') != 'verified':
        raise ValueError('Published grade binding is unverified')
    if derived['structured_claims_correct'] is not verdict:
        raise ValueError('Terminal published derived grade differs')
    return verdict


def run_inner(spec_path,spec_sha256,live_path,live_sha256,output,emergency_stop=None):
 checked({'path':str(spec_path.resolve()),'sha256':spec_sha256})
 checked({'path':str(live_path.resolve()),'sha256':live_sha256})
 spec=read(spec_path);live=read(live_path)
 pilot=live.get('pilot_id')
 if not isinstance(pilot,str) or not pilot.strip():raise ValueError('Unique live pilot_id required')
 # Shared location independent of output name; exclusive pilot claim never reset.
 claims=Path(spec['claims_directory']).resolve();claims.mkdir(parents=True,exist_ok=True)
 claim=claims/(sha256(pilot.encode()).hexdigest()+'.json')
 save(claim,{'pilot_id':pilot,'case':'B06','spec':pin(spec_path),'live':pin(live_path),'output':str(output.resolve())})
 event_api=runpy.run_path(str(checked(spec['events_helper'])))
 database=claim.with_suffix('.sqlite')
 if database.exists():raise FileExistsError(database)
 registry=event_api['Events'](database);suite=pilot;episode_id='B06'
 registry.register(suite,[episode_id])
 registry.subscribe('Evaluation-B06',suite,'codex:01a117cc-c706-7100-916c-0f72d0d48e68',episode=episode_id,final=False)
 registry.subscribe('Evaluation-pilot',suite,'codex:01a117cc-c706-7100-916c-0f72d0d48e68',final=True)
 registry.start(suite,episode_id)
 failure_path=claim.with_name(claim.stem+'-failure.json')
 def record_emergency(reason):
  row=registry.snapshot()['episodes'][0]
  if row['state']!='running':
   note=claim.with_name(claim.stem+'-terminal-interruption.json')
   if not note.exists():save(note,{'reason':reason,'episode_state':row['state'],'task_verdict':row['payload'].get('task_verdict'),'retained_evidence':row['payload']})
   return
  failure={'pilot_id':pilot,'infrastructure_failure':'EmergencyStop','reason':reason,'task_verdict':None,'spec':pin(spec_path),'live':pin(live_path)}
  if not failure_path.exists():save(failure_path,failure)
  if registry.snapshot()['episodes'][0]['state']=='running':registry.finish(suite,episode_id,'failed',failure)
 if emergency_stop is None:emergency_stop=EmergencyStop(record_emergency)
 else:emergency_stop.record=record_emergency
 try:
  watchdogs=preflight(spec,live)
  watchdogs.emergency_stop=emergency_stop
  if output.exists():raise FileExistsError(output)
  result=episode(spec_path,live_path,output,watchdogs)
  verify_terminal(result)
  registry.finish(suite,episode_id,'succeeded',result)
  signal.setitimer(signal.ITIMER_REAL,0)
  notification_pending=False
  try:event_api['flush'](registry)
  except Exception as error:
   notification_pending=True
   save(claim.with_name(claim.stem+'-notification-error.json'),{'error':str(error),'task_verdict':result['task_verdict'],'outbox_retained':True})
  save(claim.with_name(claim.stem+'-completion.json'),{'snapshot':registry.snapshot(),'notices':registry.notices(),'evidence':result,'recipient':'codex:01a117cc-c706-7100-916c-0f72d0d48e68','qualification':'Actual Events.flush attempts; accepted delivery is not read acknowledgment'})
  print(json.dumps({'status':'model_episode_graded_and_projected','pilot_id':pilot,'task_verdict':result['task_verdict'],'notification_pending':notification_pending}))
 except BaseException as primary:
  signal.setitimer(signal.ITIMER_REAL,0)
  failure={'pilot_id':pilot,'infrastructure_failure':type(primary).__name__,'reason':str(primary),'task_verdict':None,'spec':pin(spec_path),'live':pin(live_path)}
  save(failure_path,failure)
  if registry.snapshot()['episodes'][0]['state']=='running':registry.finish(suite,episode_id,'failed',failure)
  event_api['flush'](registry)
  raise
 finally:
  signal.setitimer(signal.ITIMER_REAL,0)

def run(*args):
 signals=(signal.SIGALRM,signal.SIGTERM,signal.SIGINT)
 previous={sig:signal.getsignal(sig) for sig in signals}
 old_timer=signal.getitimer(signal.ITIMER_REAL)
 if old_timer[0]>0:raise RuntimeError('An outer episode alarm is not allowed')
 output=args[4]
 def record_startup(reason):
  output.parent.mkdir(parents=True,exist_ok=True)
  path=output.parent/(output.name+'-startup-or-terminal-failure.json')
  if not path.exists():save(path,{'error_type':'EmergencyStop','reason':reason,'task_verdict':None})
 emergency_stop=EmergencyStop(record_startup)
 def interrupted(signum,frame):emergency_stop('Caller interrupted by signal '+str(signum))
 signal.signal(signal.SIGTERM,interrupted);signal.signal(signal.SIGINT,interrupted)
 try:return run_inner(*args,emergency_stop=emergency_stop)
 finally:
  signal.setitimer(signal.ITIMER_REAL,0)
  for sig,handler in previous.items():signal.signal(sig,handler)

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--spec',type=Path,required=True);p.add_argument('--spec-sha256',required=True);p.add_argument('--live',type=Path,required=True);p.add_argument('--live-sha256',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 try:run(a.spec,a.spec_sha256,a.live,a.live_sha256,a.output)
 except BaseException as primary:
  # Includes failures before the pinned Events helper can be loaded; never
  # overwrite a prior attempt or require invalidated source pins to log error.
  a.output.parent.mkdir(parents=True,exist_ok=True)
  path=a.output.parent/(a.output.name+'-startup-or-terminal-failure.json')
  if not path.exists():save(path,{'error_type':type(primary).__name__,'reason':str(primary),'spec_path':str(a.spec),'live_path':str(a.live),'task_verdict':None})
  raise
