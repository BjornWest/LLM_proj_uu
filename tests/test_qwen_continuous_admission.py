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
  self.assertEqual([r[0] for r in rows],['tool_started','tool_finished']*2)
  self.assertEqual([r[1]['sequence'] for r in rows],[1,1,2,2])

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
  with patch.dict(CALLER['finish_case_failure'].__globals__,source_guard=lambda s:None):
   self.assertTrue(CALLER['finish_case_failure'](spec,'a',ValueError('case formatter error'),out,
    process,self.host,services,self.stop))
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

if __name__=='__main__':unittest.main()
