"""CPU-only continuous queue and real controller/RPC; no model or browser."""
from pathlib import Path
from types import SimpleNamespace
import json,os,runpy,tempfile,threading,time,unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
CALLER=runpy.run_path(str(ROOT/'scripts/comparison_suite.py'))
QUEUE=runpy.run_path(str(ROOT/'scripts/episode_queue.py'))
OBS=runpy.run_path(str(ROOT/'tests/test_qwen_suite_observer.py'))

class ContinuousQueueTests(unittest.TestCase):
 def test_long_first_case_does_not_gate_parallel_start_or_refill(self):
  stop=threading.Event();long=threading.Event();started={i:threading.Event() for i in range(6)}
  lock=threading.Lock();active=peak=0;observed=[];answers=[]
  spec={'runtime_mode':'qwen-private-v1'}
  self.assertIsNone(CALLER['make_canary_barrier'](spec,stop,False))
  def one(ident,admission):
   nonlocal active,peak
   admission.environment_ready()
   with lock:active+=1;peak=max(peak,active);observed.append((ident,active,time.monotonic()))
   started[ident].set()
   try:
    if ident==0:
     if not long.wait(4):raise TimeoutError('CPU test release missing')
    else:time.sleep(.04)
    return {'task_completed':ident!=1} # Negative native grade is still a completion.
   finally:
    with lock:
     observed.append((ident,'finished',time.monotonic()));active-=1
  thread=threading.Thread(target=lambda:answers.append(QUEUE['run_ordered_suite'](
   {str(i):i for i in range(6)},one,max_concurrent_episodes=3,prewarm_count=1,stop_event=stop)))
  thread.start()
  try:
   self.assertTrue(started[0].wait(2));self.assertTrue(started[2].wait(2))
   self.assertTrue(started[5].wait(2));self.assertTrue(thread.is_alive())
   self.assertFalse(long.is_set());self.assertEqual(peak,3)
  finally:long.set();thread.join(4)
  self.assertFalse(thread.is_alive());self.assertEqual(len(answers),1)
  result=answers[0];self.assertFalse(result['cancelled']);self.assertEqual(len(result['cases']),6)
  self.assertTrue(all(r['status']=='completed' for r in result['cases'].values()))
  self.assertFalse(result['cases']['1']['result']['task_completed'])
  self.assertEqual(max(e['active'] for e in result['events']),3)
  self.assertEqual(len([r for r in observed if r[1]!='finished']),6)
  if os.environ.get('QWEN_CONTINUOUS_PROBE_OUTPUT'):
   p=Path(os.environ['QWEN_CONTINUOUS_PROBE_OUTPUT']);p.parent.mkdir(parents=True,exist_ok=True)
   with p.open('x')as f:json.dump({'schema':'continuous-admission-CPU-probe-v1','scripted':True,'model_requests':0,'browser_runs':0,'target':3,'measured_peak_active':peak,'long_first_case':0,'long_case_still_active_at_last_case_start':True,'normal_negative_case':1,'observed_boundaries':observed,'queue':result},f,indent=2)

 def test_empty_canary_configuration_really_has_no_private_gate(self):
  for options in ({},{'canary_task_ids':[]},{'canary_enabled':False}):
   with self.subTest(options=options):self.assertIsNone(CALLER['make_canary_barrier'](
    {'runtime_mode':'qwen-private-v1',**options},threading.Event(),False))
  hosted={'runtime_mode':'qwen-openrouter-v1','canary_task_ids':['a','b','c','d']}
  self.assertIsNotNone(CALLER['make_canary_barrier'](hosted,threading.Event(),False))

 def test_case_cleanup_requires_native_ack_and_owned_launcher_proof(self):
  with tempfile.TemporaryDirectory() as tmp:
   out=Path(tmp);(out/'a').mkdir();(out/'a-bounded').mkdir()
   spec={'launcher':{'sha256':'owned'}};process=SimpleNamespace(poll=lambda:1)
   marker={'status':'passed','case':'a','wrapper_finalizers_returned':True,'pool_lease_released':True,
    'capacity_channel_closed':True,'capacity_infrastructure_error':None}
   guardian={'cleanup_verified':True,'source_sha256':'owned'}
   (out/'a/cleanup.json').write_text(json.dumps(marker));(out/'a-bounded/result.json').write_text(json.dumps(guardian))
   self.assertTrue(CALLER['verified_case_cleanup'](spec,'a',out,process))
   for key,value in [('capacity_channel_closed',False),('capacity_infrastructure_error',{'unknown':True}),('pool_lease_released',False),('case','foreign')]:
    (out/'a/cleanup.json').write_text(json.dumps({**marker,key:value}))
    self.assertFalse(CALLER['verified_case_cleanup'](spec,'a',out,process))
   (out/'a/cleanup.json').write_text(json.dumps(marker))
   (out/'a-bounded/result.json').write_text(json.dumps({**guardian,'source_sha256':'foreign'}))
   self.assertFalse(CALLER['verified_case_cleanup'](spec,'a',out,process))

 def test_phase_fingerprints_and_failure_boundaries_are_saved_without_grades(self):
  with tempfile.TemporaryDirectory() as tmp:
   s={'runtime_mode':'qwen-private-v1','caller_commit':'tip','driver':{'sha256':'source'}}
   emit=CALLER['phase_writer'](s,'a',tmp,'parent.jsonl')
   for phase in ['queued','environment_ready','activated','tool_started','tool_finished','case_error','lifecycle_finished']:emit(phase)
   rows=[json.loads(x) for x in (Path(tmp)/'parent.jsonl').read_text().splitlines()]
   self.assertEqual(len(rows),7);self.assertTrue(all(r['configuration_sha256']==CALLER['config_hash'](s) for r in rows))
   self.assertTrue(all(r['caller_commit']=='tip' and r['driver_sha256']=='source' for r in rows))
   self.assertEqual(sorted(r['monotonic'] for r in rows),[r['monotonic'] for r in rows])
   self.assertTrue(all('task_verdict' not in r for r in rows))

 def test_tool_timestamps_do_not_add_a_deadline_or_replay_failed_actions(self):
  rows=[];calls=[]
  def original(value):
   calls.append(value)
   if value=='fail':raise ValueError('CPU tool error')
   return value
  env=SimpleNamespace(step=original)
  CALLER['record_browser_steps'](env,lambda phase,**data:rows.append((phase,data)))
  self.assertEqual(env.step('ok'),'ok')
  with self.assertRaises(ValueError):env.step('fail')
  self.assertEqual(calls,['ok','fail'])
  self.assertEqual([r[0] for r in rows],['tool_started','tool_finished','tool_started','tool_error','tool_finished'])
  self.assertEqual([r[1]['sequence'] for r in rows],[1,1,2,2,2])

 def test_phase_io_failure_is_explicit_and_does_not_prevent_cleanup(self):
  with tempfile.TemporaryDirectory() as tmp:
   s={'runtime_mode':'qwen-private-v1','caller_commit':'tip','driver':{'sha256':'source'}}
   emit=CALLER['phase_writer'](s,'a',tmp,'parent.jsonl')
   import io
   with patch.object(Path,'open',side_effect=OSError('CPU simulated disk failure')),patch('sys.stderr',io.StringIO()):
    emit('cleanup_started')
   self.assertEqual(emit.failure['phase'],'cleanup_started')
   emit('cleanup_finished')
   self.assertTrue((Path(tmp)/'parent.jsonl').exists())
   self.assertIsNotNone(emit.failure)

class CleanFailureTests(OBS['ObserverTests']):
 # Reuse the actual local metrics server/controller/Unix-RPC fixture. Inherited
 # regression tests also ensure the one-host policy/formatter lease still works.
 def test_clean_technical_failure_releases_only_its_case_and_allows_refill(self):
  a=self.client('a');b=self.client('b');self.host.activate('a',priority=0);self.host.activate('b',priority=1)
  with a.turn('policy'):pass
  a.close();self.host.finish_failed_case('a',verify_cleanup=lambda:True,record_terminal=lambda:True)
  self.assertFalse(self.stop.is_set());self.assertEqual(self.host.parent.stop_cause,None)
  c=self.client('c');self.host.activate('c',priority=2)
  with b.turn('policy'):pass
  with c.turn('policy'):pass
  for ident,client in [('b',b),('c',c)]:
   client.close();self.host.finish(ident,verify_cleanup=lambda:True,record_terminal=lambda:True)
  self.assertEqual(self.host.parent.finished,{'a','b','c'})

 def test_actual_caller_failure_boundary_retains_error_and_shared_parent(self):
  a=self.client('a');self.host.activate('a',priority=0)
  with a.turn('policy'):pass
  a.close();out=self.directory/'caller';(out/'a').mkdir(parents=True);(out/'a-bounded').mkdir()
  marker={'status':'passed','case':'a','wrapper_finalizers_returned':True,'pool_lease_released':True,
   'capacity_channel_closed':True,'capacity_infrastructure_error':None}
  (out/'a/cleanup.json').write_text(json.dumps(marker))
  (out/'a-bounded/result.json').write_text(json.dumps({'cleanup_verified':True,'source_sha256':'owned'}))
  spec={'runtime_mode':'qwen-private-v1','caller_commit':'tip','driver':{'sha256':'driver'},
   'launcher':{'sha256':'owned'},'rental_deadline_utc':time.time()+20}
  process=SimpleNamespace(poll=lambda:1);services=[SimpleNamespace(poll=lambda:None)]*2
  class Admission:
   def quarantine(self,evidence):self.evidence=evidence
   def recover_quarantine(self,verify_cleanup):return verify_cleanup() is True
  receipt=CALLER['isolate_case_error'](spec,'a',ValueError('case formatter error'),'formatter',out,
   process,None,self.host,Admission())
  self.assertFalse(receipt['quarantined'])
  self.assertFalse(self.stop.is_set());self.assertTrue(self.host.controller.status()['episodes']['a']['done'])
  receipt=json.loads((out/'a-case-failure.json').read_text());self.assertIsNone(receipt['task_verdict'])
  b=self.client('b');self.host.activate('b',priority=1)
  with b.turn('policy'):pass
  b.close();self.host.finish('b',verify_cleanup=lambda:True,record_terminal=lambda:True)

 def test_stale_telemetry_rejects_case_isolation_without_releasing_cap(self):
  a=self.client('a');self.host.activate('a',priority=0);a.close()
  status=self.host.controller.status()
  with patch.object(self.host.controller,'status',return_value={**status,'telemetry_fresh':False}):
   with self.assertRaisesRegex(RuntimeError,'unverified'):
    self.host.finish_failed_case('a',verify_cleanup=lambda:True,record_terminal=lambda:True)
  self.assertFalse(self.host.controller.status()['episodes']['a']['done'])
  self.host.finish('a',verify_cleanup=lambda:True,record_terminal=lambda:True)

 def test_failed_case_with_sent_request_never_gets_early_credit(self):
  a=self.client('a');self.host.activate('a',priority=0)
  with a.turn('policy'):
   with self.assertRaisesRegex(RuntimeError,'unverified'):
    self.host.finish_failed_case('a',verify_cleanup=lambda:True,record_terminal=lambda:True)
   row=self.host.controller.status()['episodes']['a']
   self.assertIsNotNone(row['request_id']);self.assertFalse(row['done'])
  a.close();self.host.finish('a',verify_cleanup=lambda:True,record_terminal=lambda:True)

 def test_unverified_failed_cleanup_stops_cohort_and_retains_ownership(self):
  a=self.client('a');self.host.activate('a',priority=0);a.close()
  with self.assertRaises(self.mods['rpc'].CapacityChannelError):
   self.host.finish_failed_case('a',verify_cleanup=lambda:False,record_terminal=lambda:True)
  self.assertTrue(self.stop.is_set());self.assertFalse(self.host.controller.status()['episodes']['a']['done'])

class IsolatedCaseTests(unittest.TestCase):
 def spec(self):return {'runtime_mode':'qwen-private-v1','caller_commit':'tip','driver':{'sha256':'CPU-fixture'},'rental_deadline_utc':time.time()+30}

 def test_each_injected_stage_is_saved_and_the_queue_keeps_running(self):
  stages=['timeout','tool','setup','readiness','formatter','grader','projection'];proofs=[]
  for stage in stages:
   with self.subTest(stage=stage),tempfile.TemporaryDirectory() as tmp:
    stop=threading.Event();counts={};lock=threading.Lock();later=threading.Event()
    def one(ident,admission):
     with lock:counts[ident]=counts.get(ident,0)+1
     admission.environment_ready()
     if ident=='bad':
      error=TimeoutError('CPU injected timeout') if stage=='timeout' else ValueError('CPU injected '+stage)
      failure=CALLER['isolate_case_error'](self.spec(),ident,error,stage,Path(tmp),None,None,None,admission)
      self.assertFalse(failure['quarantined'])
      raise CALLER['CaseInfrastructureError'](stage)
     if ident=='long':self.assertTrue(later.wait(2))
     else:later.set()
     return {'task_completed':False}
    result=QUEUE['run_ordered_suite']({x:x for x in ['bad','long','next','last']},one,
     max_concurrent_episodes=2,prewarm_count=0,stop_event=stop,isolate_case_errors=True)
    self.assertFalse(stop.is_set());self.assertFalse(result['cancelled'])
    self.assertEqual(result['cases']['bad']['status'],'failed')
    self.assertTrue(all(result['cases'][x]['status']=='completed' for x in ['long','next','last']))
    self.assertEqual(counts,{x:1 for x in ['bad','long','next','last']})
    receipt=json.loads((Path(tmp)/'bad-case-failure.json').read_text())
    self.assertEqual(receipt['stage'],stage);self.assertIsNone(receipt['task_verdict'])
    self.assertEqual(max(e['active'] for e in result['events']),2)
    proofs.append({'injected_stage':stage,'failure':receipt,'queue':result,'attempt_counts':counts,'root_stop':stop.is_set()})
  if os.environ.get('QWEN_CASE_FAILURE_PROBE_OUTPUT'):
   with Path(os.environ['QWEN_CASE_FAILURE_PROBE_OUTPUT']).open('x') as stream:
    json.dump({'schema':'continuous-qwen-case-isolation-CPU-proof-v2','scripted':True,'model_requests':0,'browser_runs':0,'cases':proofs},stream,indent=2)

 def test_quarantine_retains_a_slot_until_proof_and_does_not_replay(self):
  stop=threading.Event();failed=threading.Event();next_started=threading.Event();recover=threading.Event()
  admissions={};counts={};answers=[]
  def one(ident,admission):
   admissions[ident]=admission;counts[ident]=counts.get(ident,0)+1;admission.environment_ready()
   if ident=='bad':
    admission.quarantine({'native_cleanup':'unacknowledged'});failed.set()
    raise RuntimeError('CPU cleanup failure')
   if ident=='long':
    self.assertTrue(failed.wait(2));self.assertTrue(next_started.wait(2));self.assertTrue(recover.wait(2))
   elif ident=='next':next_started.set()
   return ident
  thread=threading.Thread(target=lambda:answers.append(QUEUE['run_ordered_suite'](
   {x:x for x in ['bad','long','next','last']},one,max_concurrent_episodes=3,prewarm_count=0,
   stop_event=stop,isolate_case_errors=True)))
  thread.start()
  try:
   self.assertTrue(next_started.wait(2));self.assertFalse(stop.is_set())
   self.assertFalse(admissions['bad'].recover_quarantine(lambda:False))
   self.assertTrue(admissions['bad'].recover_quarantine(lambda:True));recover.set()
  finally:recover.set();thread.join(4)
  self.assertFalse(thread.is_alive());result=answers[0]
  self.assertFalse(result['cancelled']);self.assertEqual(counts,{x:1 for x in ['bad','long','next','last']})
  self.assertEqual(max(e['active'] for e in result['events']),3)
  self.assertTrue(any(e['quarantined']==1 for e in result['events']))
  self.assertIsNone(result['cases']['bad']['quarantine'])

 def test_all_slots_quarantined_returns_blocked_without_cancellation_or_hang(self):
  stop=threading.Event();calls=[]
  def one(ident,admission):
   calls.append(ident);admission.environment_ready()
   admission.quarantine({'cleanup':'unknown'});raise RuntimeError('CPU cleanup failure')
  result=QUEUE['run_ordered_suite']({x:x for x in ['a','b','c','d']},one,
   max_concurrent_episodes=2,prewarm_count=0,stop_event=stop,isolate_case_errors=True)
  self.assertFalse(stop.is_set());self.assertEqual(calls,['a','b'])
  self.assertEqual([r['status'] for r in result['cases'].values()],['failed','failed','blocked','blocked'])
  self.assertEqual(max(e['active'] for e in result['events']),2)

 def test_unanticipated_baseexception_is_quarantined_without_job_stop(self):
  stop=threading.Event();calls=[]
  def one(ident,admission):
   calls.append(ident);admission.environment_ready()
   if ident=='bad':raise SystemExit('CPU injected case exit')
   return ident
  result=QUEUE['run_ordered_suite']({x:x for x in ['bad','next','last']},one,
   max_concurrent_episodes=2,prewarm_count=0,stop_event=stop,isolate_case_errors=True)
  self.assertFalse(stop.is_set());self.assertEqual(set(calls),{'bad','next','last'})
  self.assertIsNotNone(result['cases']['bad']['quarantine'])
  self.assertEqual(result['cases']['last']['status'],'completed')

 def test_default_prewarm_drains_when_all_active_slots_are_quarantined(self):
  stop=threading.Event();warm=threading.Event();result=[];calls=[]
  def one(ident,admission):
   calls.append(ident)
   if ident=='bad':
    admission.environment_ready();self.assertTrue(warm.wait(2))
    admission.quarantine({'native_cleanup':'unacknowledged'});raise RuntimeError('CPU cleanup error')
   warm.set();admission.environment_ready();raise AssertionError('Warm case must never activate')
  thread=threading.Thread(target=lambda:result.append(QUEUE['run_ordered_suite'](
   {x:x for x in ['bad','warm','next']},one,max_concurrent_episodes=1,prewarm_count=1,
   stop_event=stop,isolate_case_errors=True)))
  thread.start();thread.join(3)
  try:self.assertFalse(thread.is_alive())
  finally:
   if thread.is_alive():stop.set();thread.join(3)
  self.assertFalse(stop.is_set());self.assertEqual(calls,['bad','warm'])
  self.assertEqual([r['status'] for r in result[0]['cases'].values()],['failed','blocked','blocked'])
  self.assertIsNotNone(result[0]['cases']['warm']['quarantine']) # setup resources need native proof
  self.assertEqual(max(e['active'] for e in result[0]['events']),1)
  self.assertEqual(max(e['warming_or_ready'] for e in result[0]['events']),1)

 def test_blocked_warm_native_channel_receives_case_cancel_and_can_cleanup(self):
  import socket
  channel=runpy.run_path(str(ROOT/'scripts/episode_queue_channel.py'))
  class NativeCancelled(RuntimeError):pass
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);stop=threading.Event();warm=threading.Event();child_outcomes=[]
   def one(ident,admission):
    if ident=='bad':
     admission.environment_ready();self.assertTrue(warm.wait(2))
     admission.quarantine({'cleanup':'unknown'});raise RuntimeError('CPU injected failure')
    parent,child=socket.socketpair();child.settimeout(3);parent.settimeout(3)
    def native():
     try:
      gate=channel['ChildAdmission'](child,ident,NativeCancelled)
      gate.environment_admission(SimpleNamespace(episode_id='CPU-scripted-ready',directory=root/'episode',ready_monotonic=time.monotonic()))
      child_outcomes.append('UNEXPECTED activation')
     except NativeCancelled:child_outcomes.append('cancelled_before_dispatch')
     finally:child.close()
    thread=threading.Thread(target=native);thread.start();warm.set()
    try:channel['serve_admission'](parent,admission,expected_run_root=root)
    except QUEUE['AdmissionBlocked']:
     thread.join(3);self.assertFalse(thread.is_alive())
     self.assertEqual(child_outcomes,['cancelled_before_dispatch'])
     admission.quarantine({'CPU_native_channel':'cancel acknowledged'})
     self.assertTrue(admission.recover_quarantine(lambda:thread.is_alive() is False))
     raise
    finally:parent.close();thread.join(3)
   result=QUEUE['run_ordered_suite']({'bad':'bad','warm':'warm','next':'next'},one,
    max_concurrent_episodes=1,prewarm_count=1,stop_event=stop,isolate_case_errors=True)
   self.assertFalse(stop.is_set());self.assertEqual(result['cases']['warm']['status'],'blocked')
   self.assertIsNone(result['cases']['warm']['quarantine'])
   self.assertEqual(result['cases']['next']['status'],'blocked')
   self.assertEqual(child_outcomes,['cancelled_before_dispatch'])

 def test_thread_constructor_failure_does_not_stop_other_cases(self):
  original=QUEUE['_Queue'].start.__globals__['Thread']
  def factory(*args,**kw):
   if kw['name']=='episode-bad':raise RuntimeError('CPU constructor failure')
   return original(*args,**kw)
  def one(ident,admission):admission.environment_ready();return ident
  stop=threading.Event()
  with patch.dict(QUEUE['_Queue'].start.__globals__,{'Thread':factory}):
   result=QUEUE['run_ordered_suite']({'bad':'bad','next':'next'},one,max_concurrent_episodes=1,
    prewarm_count=0,stop_event=stop,isolate_case_errors=True)
  self.assertFalse(stop.is_set());self.assertEqual(result['cases']['bad']['status'],'failed')
  self.assertIsNone(result['cases']['bad']['quarantine']);self.assertEqual(result['cases']['next']['status'],'completed')

 def test_warm_failure_cannot_be_reactivated_by_recovery_before_return(self):
  stop=threading.Event();started=threading.Event();answers=[];release=threading.Event()
  def one(ident,admission):
   if ident=='warm':
    admission.quarantine({'setup':'failed before ready'})
    self.assertTrue(admission.recover_quarantine(lambda:True))
    started.set();raise RuntimeError('CPU warm setup failure')
   admission.environment_ready();self.assertTrue(started.wait(2));release.set();return ident
  result=QUEUE['run_ordered_suite']({'active':'active','warm':'warm','last':'last'},one,
   max_concurrent_episodes=1,prewarm_count=1,stop_event=stop,isolate_case_errors=True)
  self.assertFalse(stop.is_set());self.assertEqual(result['cases']['last']['status'],'completed')
  self.assertFalse(any(e['event']=='environment_activated' and e['case']=='warm' for e in result['events']))
  self.assertIsNone(result['cases']['warm']['quarantine'])

 def test_thread_creation_failure_is_per_case_and_later_cases_still_start(self):
  original=QUEUE['_Queue'].start.__globals__['Thread'];attempts=[]
  def thread(*args,**kw):
   ident=kw['name'];attempts.append(ident)
   if ident=='episode-bad':return SimpleNamespace(start=lambda:(_ for _ in ()).throw(RuntimeError('CPU thread limit')))
   return original(*args,**kw)
  def one(ident,admission):admission.environment_ready();return ident
  stop=threading.Event()
  with patch.dict(QUEUE['_Queue'].start.__globals__,{'Thread':thread}):
   result=QUEUE['run_ordered_suite']({'bad':'bad','next':'next'},one,
    max_concurrent_episodes=1,prewarm_count=0,stop_event=stop,isolate_case_errors=True)
  self.assertFalse(stop.is_set());self.assertEqual(result['cases']['bad']['status'],'failed')
  self.assertEqual(result['cases']['next']['status'],'completed');self.assertIsNone(result['cases']['bad']['quarantine'])
  self.assertEqual(attempts,['episode-bad','episode-next'])

 def test_scripted_job_failure_has_no_authority_over_separate_model_fixture(self):
  model_stop=threading.Event();script_stop=threading.Event();release=threading.Event();answers=[]
  def model(ident,admission):admission.environment_ready();release.wait(2);return ident
  thread=threading.Thread(target=lambda:answers.append(QUEUE['run_ordered_suite'](
   {'model':'model'},model,max_concurrent_episodes=1,prewarm_count=0,stop_event=model_stop,isolate_case_errors=True)))
  thread.start()
  def scripted(ident,admission):admission.environment_ready();raise SystemExit('scripted CPU failure')
  control=QUEUE['run_ordered_suite']({'control':'control'},scripted,max_concurrent_episodes=1,
   prewarm_count=0,stop_event=script_stop,isolate_case_errors=True)
  self.assertFalse(model_stop.is_set());self.assertFalse(script_stop.is_set());release.set();thread.join(3)
  self.assertEqual(control['cases']['control']['status'],'failed')
  self.assertEqual(answers[0]['cases']['model']['status'],'completed')

 def test_cleanup_error_is_retained_and_never_claimed_recovered(self):
  with tempfile.TemporaryDirectory() as tmp:
   class Admission:
    def quarantine(self,evidence):self.evidence=evidence
    def recover_quarantine(self,proof):raise AssertionError('Must not recover')
   proc=SimpleNamespace(poll=lambda:None,wait=lambda **kw:(_ for _ in ()).throw(SystemExit('cleanup error')))
   result=CALLER['isolate_case_error'](self.spec(),'bad',ValueError('tool error'),'tool',Path(tmp),proc,None,None,Admission())
   self.assertTrue(result['quarantined'])
   proof=json.loads((Path(tmp)/'bad-case-isolation.json').read_text())
   self.assertEqual(proof['secondary_errors'][0]['stage'],'process_containment')
   self.assertFalse(proof['cleanup_verified'])

 def test_readiness_failure_is_local_and_does_not_validate_other_cases(self):
  spec={**self.spec(),'ready':{'path':'CPU-fixture'}};case={'id':'bad'}
  with patch.dict(CALLER['check_private_case'].__globals__,{'source_guard':lambda *a:None,
   'helper':lambda *_:{'recipe_check':lambda c:None},'checked':lambda *_:'unused',
   'load':lambda *_:{'driver':spec['driver'],'cases':[]}}):
   with self.assertRaisesRegex(ValueError,'missing'):CALLER['check_private_case'](spec,case)
   CALLER['check_private_case'](spec,case,scripted=True) # no dependency on another job outcome

class ContinuousEventsTests(unittest.TestCase):
 def test_summary_separates_task_verdicts_execution_errors_and_blocked(self):
  rows={}
  for key,verdict in [('pass','pass'),('fail','fail'),('inconclusive','inconclusive')]:
   rows[key]={'status':'completed','result':{'payload':{'task_verdict':verdict}}}
  for key in ('failed','blocked','not_started'):rows[key]={'status':key}
  self.assertEqual(CALLER['suite_outcome_counts']({'cases':rows}),{'completed':3,'execution_failed':1,
   'blocked':1,'not_started':1,'task_pass':1,'task_fail':1,'inconclusive':1,'unknown':3})

 @unittest.skipUnless(os.environ.get('EPISODE_EVENTS_SOURCE'),'Pinned external Events fixture not supplied')
 def test_actual_events_finalize_failed_pending_and_blocked_rows_without_retry(self):
  from hashlib import sha256
  path=Path(os.environ['EPISODE_EVENTS_SOURCE'])
  self.assertEqual(sha256(path.read_bytes()).hexdigest(),'16a2bdd7f53dfef4135b464d062b32116af549c935c9645e9f052c1241ee476a')
  Events=runpy.run_path(str(path))['Events']
  with tempfile.TemporaryDirectory() as tmp:
   out=Path(tmp);events=Events(out/'completion.sqlite');events.register('CPU-scripted',['good','bad','thread-failure','blocked'])
   events.subscribe('final','CPU-scripted','cpu-fixture-no-delivery',final=True)
   events.start('CPU-scripted','good');events.finish('CPU-scripted','good','succeeded',{'task_verdict':'fail','scripted':True})
   events.start('CPU-scripted','bad')
   result={'cases':{'good':{'status':'completed'},'bad':{'status':'failed','error':{'stage':'grader'},'quarantine':None},
    'thread-failure':{'status':'failed','error':{'stage':'thread_start'},'quarantine':None},'blocked':{'status':'blocked'}}}
   (out/'suite-result.json').write_text(json.dumps(result))
   CALLER['reconcile_queue_events']({'runtime_mode':'qwen-private-v1','suite_id':'CPU-scripted'},result,{'good':{},'bad':{}},events,out)
   with events.transaction() as db:
    rows={r['id']:(r['state'],json.loads(r['payload'])) for r in db.execute('SELECT * FROM episodes')}
   self.assertEqual([rows[x][0] for x in ['good','bad','thread-failure','blocked']],['succeeded','failed','failed','not_started'])
   self.assertIsNone(rows['bad'][1]['task_verdict']);self.assertIsNone(rows['thread-failure'][1]['task_verdict'])
   self.assertTrue(rows['blocked'][1]['blocked_by_quarantine'])
   self.assertEqual(len(events.notices()),1)
   with self.assertRaises(ValueError):events.start('CPU-scripted','bad') # no browser/model retry authority

class IsolatedRPCFailureTests(OBS['ObserverTests']):
 def test_bad_cleanup_retains_only_case_and_verified_recovery_clears_it(self):
  a=self.client('a');b=self.client('b');self.host.activate('a',priority=0);self.host.activate('b',priority=1)
  a.close()
  with self.assertRaises(self.mods['rpc'].CapacityChannelError):
   self.host.finish_isolated_case('a',verify_cleanup=lambda:False,record_terminal=lambda:True)
  self.assertFalse(self.stop.is_set());self.assertIn('a',self.host.parent.quarantined)
  self.assertFalse(self.host.controller.status()['episodes']['a']['done'])
  with b.turn('policy'):pass
  self.host.finish_isolated_case('a',verify_cleanup=lambda:True,record_terminal=lambda:True)
  self.assertNotIn('a',self.host.parent.quarantined)
  self.assertTrue(self.host.controller.status()['episodes']['a']['done'])
  c=self.client('c');self.host.activate('c',priority=2)
  with c.turn('policy'):pass
  for ident,client in [('b',b),('c',c)]:client.close();self.host.finish(ident,verify_cleanup=lambda:True,record_terminal=lambda:True)

 def test_quarantine_preserves_sent_request_without_credit_or_global_stop(self):
  a=self.client('a');self.host.activate('a',priority=0)
  entered=threading.Event();release=threading.Event();errors=[]
  def turn():
   try:
    with a.turn('policy'):entered.set();release.wait(3)
   except BaseException as exc:errors.append(exc)
  thread=threading.Thread(target=turn);thread.start()
  try:
   self.assertTrue(entered.wait(2));before=self.host.controller.status()['episodes']['a']['request_id']
   self.assertIsNotNone(before);self.host.quarantine_case('a',RuntimeError('uncertain HTTP'))
   self.assertFalse(self.stop.is_set())
   self.assertEqual(self.host.controller.status()['episodes']['a']['request_id'],before)
   self.assertFalse(self.host.controller.status()['episodes']['a']['done'])
  finally:release.set();thread.join(4);a.close()
  # Only a trusted final callback proving the exact HTTP drain can clear it.
  self.host.finish_isolated_case('a',verify_cleanup=lambda:True,record_terminal=lambda:True)
  self.assertTrue(self.host.controller.status()['episodes']['a']['done'])

if __name__=='__main__':unittest.main()
