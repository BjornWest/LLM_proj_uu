"""CPU/mock private timeout qualification; no browser, GPU or model requests."""
from pathlib import Path
from contextlib import contextmanager
from types import SimpleNamespace
import runpy,json,sys,unittest,tempfile
import httpx
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
API=runpy.run_path(str(ROOT/'scripts/qwen_suite_runtime.py'))
HOSTED=runpy.run_path(str(ROOT/'scripts/openrouter_qwen_runtime.py'))
from intent_browser.backend import ChatCompletionsBackend

class PrivateTimeoutBoundaryTests(unittest.TestCase):
 def setUp(self):
  self.now=100.;self.deadline=5000.;self.park=0.;self.events=[];self.wires=[];self.error=None;self.meters=[]
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.directory=Path(self.tmp.name)
  self.identity={'test_fixture':'CPU/mock only'}
  def ready():
   self.events.append(('ready',self.now))
   if self.now>=self.deadline:raise TimeoutError('rental expired before dispatch')
  def count(request):
   self.events.append(('count',self.now))
   return {'input_tokens':3,'identity':self.identity,'exact_complete_request':True,'serving_session_id':'cpu-only','request_sha256':API['digest'](request)}
  self.admission=SimpleNamespace(base='http://127.0.0.1:8123/v1',deadline=self.deadline,clock=lambda:self.now,identity=self.identity,session='cpu-only',readiness=ready,count=count)
  def respond(request):
   self.wires.append(request);self.events.append(('HTTP',self.now))
   if self.error:raise self.error('mock submitted read deadline',request=request)
   return httpx.Response(200,json={'choices':[{'message':{'role':'assistant','content':'answer'},'finish_reason':'stop'}],'usage':{'prompt_tokens':3}})
  def backend(*args,**kwargs):
   raw=ChatCompletionsBackend(*args,**kwargs);raw.client.close();raw.client=httpx.Client(transport=httpx.MockTransport(respond));return raw
  @contextmanager
  def turn(phase):
   self.events.append(('wait:'+phase,self.now));self.now+=self.park
   try:yield
   finally:self.events.append(('turn_cleanup:'+phase,self.now))
  self.factory=API['QwenFactories'](backend_class=backend,admission=self.admission,before_policy=lambda:self.events.append(('policy',self.now)),before_formatter=lambda:self.events.append(('formatter',self.now)),meter=self.meters.append,freshness_guard=lambda phase:self.events.append(('fresh:'+phase,self.now)),turn=turn)
 def test_unsent_park_over_600_does_not_spend_submitted_timeout(self):
  self.park=901
  with self.factory.policy_session(before_dispatch=lambda:None)as b:b.complete([])
  self.assertEqual(len(self.wires),1);self.assertEqual(self.wires[0].extensions['timeout']['read'],600)
  self.assertEqual(next(t for label,t in self.events if label=='HTTP'),1001)
  self.assertTrue(all(t==1001 for label,t in self.events if label in ['count','policy','fresh:policy']))
 def test_rental_expiry_while_unsent_skips_count_and_generation(self):
  self.park=5000
  with self.factory.policy_session(before_dispatch=lambda:None)as b:
   with self.assertRaisesRegex(TimeoutError,'rental expired'):b.complete([])
  self.assertFalse(self.wires);self.assertFalse(any(e=='count'for e,t in self.events));self.assertTrue(self.factory.policy_finished)
 def test_submitted_buffered_read_bound_includes_server_wait_and_has_no_progress_attribution(self):
  with self.factory.policy_session(before_dispatch=lambda:None)as b:b.complete([])
  wire=self.wires[0];self.assertEqual(wire.extensions['timeout']['read'],600);self.assertFalse(json.loads(wire.content)['stream'])
  self.assertEqual(len(self.wires),1) # Nothing in this buffered wire identifies queued versus active decode.
 def test_submitted_timeout_closes_local_transport_without_completion_or_replay(self):
  self.error=httpx.ReadTimeout
  with self.factory.policy_session(before_dispatch=lambda:None)as b:
   with self.assertRaises(httpx.ReadTimeout):b.complete([])
  self.assertEqual(len(self.wires),1);self.assertTrue(b.closed_successfully);self.assertTrue(b.raw.client.is_closed)
  self.assertTrue(any(e=='turn_cleanup:policy'for e,t in self.events))
 def test_timeout_cannot_turn_failed_local_cleanup_into_success(self):
  self.error=httpx.ReadTimeout
  def failed_close():raise RuntimeError('owned transport cleanup unverified')
  with self.assertRaisesRegex(RuntimeError,'cleanup unverified'):
   with self.factory.policy_session(before_dispatch=lambda:None)as b:
    b.raw.close=failed_close;b.complete([])
  self.assertTrue(self.factory.poisoned);self.assertFalse(self.factory.policy_finished);b.raw.client.close()
 def test_rental_remaining_after_park_clips_submitted_read_deadline(self):
  self.park=4870
  with self.factory.policy_session(before_dispatch=lambda:None)as b:b.complete([])
  self.assertEqual(self.wires[0].extensions['timeout']['read'],30)
 def test_formatter_has_same_private_wait_boundary_and_remains_single_call(self):
  with self.factory.policy_session(before_dispatch=lambda:None):pass
  (self.directory/'extraction').mkdir();(self.directory/'extraction/schema.json').write_text(json.dumps({'type':'object','properties':{},'additionalProperties':False}))
  self.park=901;b=self.factory.extraction_backend_factory(self.directory/'transport')
  b.complete([]);self.assertEqual(self.wires[0].extensions['timeout']['read'],600);self.assertIn('response_format',json.loads(self.wires[0].content))
  with self.assertRaisesRegex(RuntimeError,'One formatter'):b.complete([])
  b.close()
 def test_hosted_180_does_not_change_private_constructor_boundary(self):
  API['QwenFactories'](backend_class=lambda *_:None,admission=self.admission,before_policy=lambda:None,before_formatter=lambda:None,meter=lambda _:None,freshness_guard=lambda _:None,request_timeout=600)
  with self.assertRaises(ValueError):API['QwenFactories'](backend_class=lambda *_:None,admission=self.admission,before_policy=lambda:None,before_formatter=lambda:None,meter=lambda _:None,freshness_guard=lambda _:None,request_timeout=601)
  raw=SimpleNamespace(model=HOSTED['MODEL'],base_url='https://openrouter.ai/api/v1')
  with self.assertRaises(ValueError):HOSTED['HostedQwenBackend'](raw,lambda *_:{'input_tokens':1},phase='policy',maximum=65536,deadline=1000,timeout=600,clock=lambda:1)

 def test_opt_in_submitted_read_survives_local_parking_and_uses_remaining_rental(self):
  self.factory.read_wait_policy='rental_bounded';self.park=901
  with self.factory.policy_session(before_dispatch=lambda:None)as b:b.complete([])
  limits=self.wires[0].extensions['timeout'];self.assertEqual(limits['read'],3999)
  self.assertEqual({k:limits[k]for k in ('connect','write','pool')},{'connect':30,'write':30,'pool':30})
  self.assertFalse(json.loads(self.wires[0].content)['stream'])
  event=next(row for row in self.meters if row['event']=='private_http_wait_policy')
  self.assertEqual(event['read_timeout_seconds'],3999);self.assertEqual(event['policy'],'rental_bounded')
  self.assertIn('no request-specific progress',event['scope'])
 def test_opt_in_formatter_and_short_remaining_rental_bound(self):
  self.factory.read_wait_policy='rental_bounded'
  with self.factory.policy_session(before_dispatch=lambda:None):pass
  (self.directory/'extraction').mkdir();(self.directory/'extraction/schema.json').write_text(json.dumps({'type':'object','properties':{},'additionalProperties':False}))
  self.park=4870;b=self.factory.extraction_backend_factory(self.directory/'transport');b.complete([])
  self.assertEqual(self.wires[0].extensions['timeout'],{'connect':30,'read':30,'write':30,'pool':30});b.close()
 def test_opt_in_long_formatter_reads_preserve_schema_and_one_call(self):
  self.factory.read_wait_policy='rental_bounded'
  with self.factory.policy_session(before_dispatch=lambda:None):pass
  (self.directory/'extraction').mkdir();schema={'type':'object','properties':{'x':{'type':'string'}}};(self.directory/'extraction/schema.json').write_text(json.dumps(schema))
  self.park=901;b=self.factory.extraction_backend_factory(self.directory/'transport');b.complete([])
  self.assertEqual(self.wires[0].extensions['timeout']['read'],3999);self.assertEqual(json.loads(self.wires[0].content)['response_format']['json_schema']['schema'],schema)
  with self.assertRaisesRegex(RuntimeError,'One formatter'):b.complete([])
  b.close()
 def test_opt_in_connection_and_write_bounds_respect_smaller_configured_timeout(self):
  self.factory.read_wait_policy='rental_bounded';self.factory.timeout=7
  with self.factory.policy_session(before_dispatch=lambda:None)as b:b.complete([])
  self.assertEqual(self.wires[0].extensions['timeout'],{'connect':7,'read':4900,'write':7,'pool':7})
 def test_read_policy_is_explicit_enum_and_rental_expiry_is_not_submission(self):
  for value in (None,True,180,'streaming',''):
   with self.subTest(policy=value),self.assertRaises(ValueError):
    API['QwenFactories'](backend_class=lambda *_:None,admission=self.admission,before_policy=lambda:None,before_formatter=lambda:None,meter=lambda _:None,freshness_guard=lambda _:None,read_wait_policy=value)
  self.factory.read_wait_policy='rental_bounded';self.now=self.deadline
  with self.assertRaisesRegex(TimeoutError,'Rental deadline'):self.factory.http_timeout()
  self.assertFalse(self.wires)
 def test_expiry_at_policy_guard_keeps_original_request_hooks(self):
  self.factory.read_wait_policy='rental_bounded'
  self.factory.policy_guard=lambda:setattr(self,'now',self.deadline)
  original=lambda _:None
  with self.factory.policy_session(before_dispatch=lambda:None)as b:
   b.raw.client.event_hooks['request']=[original]
   with self.assertRaisesRegex(TimeoutError,'Rental deadline'):b.complete([])
   self.assertEqual(b.raw.client.event_hooks['request'],[original])
  self.assertFalse(self.wires)
 def test_expiry_at_formatter_guard_keeps_original_request_hooks(self):
  with self.factory.policy_session(before_dispatch=lambda:None):pass
  (self.directory/'extraction').mkdir();(self.directory/'extraction/schema.json').write_text(json.dumps({'type':'object','properties':{},'additionalProperties':False}))
  self.factory.read_wait_policy='rental_bounded';self.factory.formatter_guard=lambda:setattr(self,'now',self.deadline)
  b=self.factory.extraction_backend_factory(self.directory/'transport');original=lambda _:None;b.raw.client.event_hooks['request']=[original]
  with self.assertRaisesRegex(TimeoutError,'Rental deadline'):b.complete([])
  self.assertEqual(b.raw.client.event_hooks['request'],[original]);self.assertFalse(self.wires);b.close()
 def test_meter_failure_keeps_original_request_hooks(self):
  def meter(row):
   if row['event']=='private_http_wait_policy':raise OSError('meter write failed')
  self.factory.meter=meter;original=lambda _:None
  with self.factory.policy_session(before_dispatch=lambda:None)as b:
   b.raw.client.event_hooks['request']=[original]
   with self.assertRaisesRegex(OSError,'meter write failed'):b.complete([])
   self.assertEqual(b.raw.client.event_hooks['request'],[original])
  self.assertFalse(self.wires)

class CallerReadPolicyTests(unittest.TestCase):
 def setUp(self):
  import importlib.util
  spec=importlib.util.spec_from_file_location('_private_read_policy_caller',ROOT/'scripts/comparison_suite.py');self.caller=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.caller)
 def test_explicit_policy_is_private_only_and_binds_configuration(self):
  self.assertEqual(self.caller.private_read_wait_policy({'runtime_mode':'qwen-private-v1'}),'bounded_request')
  private={'runtime_mode':'qwen-private-v1','private_read_wait_policy':'rental_bounded'}
  self.assertEqual(self.caller.private_read_wait_policy(private),'rental_bounded')
  for mode in ('qwen-openrouter-v1','other',None):
   with self.subTest(mode=mode),self.assertRaises(ValueError):self.caller.check_release({**private,'runtime_mode':mode})
  self.assertNotEqual(self.caller.config_hash(private),self.caller.config_hash({**private,'private_read_wait_policy':'bounded_request'}))
 def test_canaries_are_four_distinct_front_of_queue_members(self):
  from unittest.mock import patch
  ids=['A01','A03','A04','H09']
  value={'runtime_mode':'qwen-private-v1','max_steps':None,'episode_timeout':None,'max_input_tokens':250000,'server_context_tokens':262144,'max_tokens':16384,'request_timeout':600,'startup_timeout':900,'shared_tokenizer':True,'shared_chromium':True,'max_concurrent_episodes':4,'canary_task_ids':ids,'start_order':['qwen-'+i for i in ids],'cases':[{'policy_model':API['MODEL'],'max_input_tokens':250000,'id':'qwen-'+i,'task_id':i,'recipe_manifest':{}}for i in ids],'qwen_sources':{},'private_read_wait_policy':'rental_bounded'}
  with patch.object(self.caller,'checked',return_value=ROOT):self.caller.validate_qwen_limits(value)
  for canaries in (['A01']*4,ids[:3],['A01','A03','A04','absent'],ids[:3]+[None],list(reversed(ids))):
   with self.subTest(canaries=canaries),patch.object(self.caller,'checked',side_effect=AssertionError('before target imports')),self.assertRaises(ValueError):self.caller.validate_qwen_limits({**value,'canary_task_ids':canaries})
  legacy=['B02','B14','H03','H05'];cases=[{'policy_model':API['MODEL'],'max_input_tokens':250000,'id':'qwen-'+i,'task_id':i,'recipe_manifest':{}}for i in legacy]
  with patch.object(self.caller,'checked',return_value=ROOT):self.caller.validate_qwen_limits({**value,'private_read_wait_policy':'bounded_request','canary_task_ids':legacy,'start_order':['qwen-'+i for i in legacy],'cases':cases})

if __name__=='__main__':unittest.main()
