"""Model-free GWL caller/backend adoption; browser acceptance is separate."""
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import importlib.util,json,runpy,sys,tempfile,threading,time,unittest
from unittest.mock import patch
import httpx
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
CALLER=runpy.run_path(str(ROOT/'scripts/comparison_suite.py'))
PRIVATE=runpy.run_path(str(ROOT/'scripts/qwen_suite_runtime.py'))
HOSTED=runpy.run_path(str(ROOT/'scripts/openrouter_qwen_runtime.py'))
OPTIONS=runpy.run_path(str(ROOT/'environments/website_world/generation_configs.py'))
from intent_browser.backend import ChatCompletionsBackend

class CaptureOptionsTests(unittest.TestCase):
 def test_new_default_keeps_budgeted_auto_without_screens_and_async_recording(self):
  self.assertEqual(CALLER['capture_options']({}),{'observation_pipeline':'auto','trace_screenshots':False,
   'async_recording':True,'recording_capture':'pipeline'})
  self.assertEqual(CALLER['capture_options']({'observation_pipeline':'native','trace_screenshots':True,
   'async_recording':False}),{'observation_pipeline':'native','trace_screenshots':True,
   'async_recording':False,'recording_capture':'native'})
 def test_unknown_or_incompatible_options_fail_before_capture(self):
  for option in ({'observation_pipeline':'foreign'},{'observation_pipeline':False},
    {'trace_screenshots':1},{'async_recording':None},{'recording_capture':'unknown'},
    {'observation_pipeline':'auto','recording_capture':'native'}):
   with self.subTest(option=option),self.assertRaises(ValueError):CALLER['capture_options'](option)
 def test_direct_case_default_and_prospective_auto_do_not_mutate_inputs(self):
  value={'max_steps':None,'max_input_tokens':250000}
  self.assertEqual(OPTIONS['observation_runner_options'](value),{**value,'observation_pipeline':'native'})
  self.assertNotIn('observation_pipeline',value)
  auto={**value,'observation_pipeline':'auto'}
  self.assertEqual(OPTIONS['observation_runner_options'](auto),auto)
  for invalid in ('foreign',None,False,{},'native_full_only'):
   with self.subTest(invalid=invalid),self.assertRaises(ValueError):OPTIONS['observation_runner_options']({**value,'observation_pipeline':invalid})
 def test_step_hook_pairs_each_execution_without_method_replacement_or_replay(self):
  events=[];acks=[]
  admission=SimpleNamespace(step_started=lambda:acks.append('start'),step_finished=lambda:acks.append('end'))
  hook=CALLER['browser_step_context'](admission,lambda phase,**row:events.append((phase,row)),guarded=True)
  with hook(step=2,tool='click'):pass
  with self.assertRaisesRegex(ValueError,'tool'):
   with hook(step=4,tool='goto'):raise ValueError('tool error')
  self.assertEqual(acks,['start','end','start','end'])
  self.assertEqual([r[0]for r in events],['tool_started','tool_finished','tool_started','tool_error','tool_finished'])
  self.assertEqual([r[1]['execution_index']for r in events],[2,2,4,4,4])
 def test_step_ack_failure_retains_primary_and_vetoes_next_dispatch(self):
  def failed():raise RuntimeError('lost step end')
  hook=CALLER['browser_step_context'](SimpleNamespace(step_started=lambda:None,step_finished=failed),lambda *_a,**_k:None,guarded=True)
  with self.assertRaisesRegex(ValueError,'primary')as raised:
   with hook(step=0,tool='click'):raise ValueError('primary action error')
  self.assertTrue(any('lost step end'in note for note in raised.exception.__notes__))
  with self.assertRaisesRegex(RuntimeError,'lost step end'):
   with hook(step=1,tool='click'):pass

class PrivateBackgroundTests(unittest.TestCase):
 def setUp(self):
  self.calls=[];self.events=[];self.block=None
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  identity={'fixture':'CPU-only'}
  def count(request):return {'input_tokens':250000,'identity':identity,'exact_complete_request':True,
   'serving_session_id':'fixture','request_sha256':PRIVATE['digest'](request)}
  self.admission=SimpleNamespace(base='http://127.0.0.1:8123/v1',identity=identity,session='fixture',
   deadline=time.time()+60,clock=time.time,readiness=lambda:None,count=count)
  outer=self
  class Raw:
   def __init__(self,*a,**kw):self.request_options=kw['request_options'];self.max_tokens=kw['max_tokens'];self.last_request=None;self.closed=False
   def complete(self,messages):
    if outer.block is not None:outer.block[0].set();outer.block[1].wait(3)
    request={'model':PRIVATE['MODEL'],'messages':deepcopy(messages),'temperature':0,'max_tokens':self.max_tokens,'stream':False,**deepcopy(self.request_options)}
    outer.calls.append((threading.get_ident(),request));self.last_request=request
    return SimpleNamespace(request=request,raw={'usage':{'prompt_tokens':250000}},text='answer')
   def configure_tools(self,options):self.request_options.update(options)
   def begin_episode(self,episode_id):pass
   def close(self):self.closed=True
  @contextmanager
  def turn(phase):
   self.events.append(('begin',phase))
   try:yield
   finally:self.events.append(('end',phase))
  self.create=lambda background:PRIVATE['QwenFactories'](backend_class=Raw,admission=self.admission,
   before_policy=lambda:None,before_formatter=lambda:None,meter=lambda *_:None,freshness_guard=lambda *_:None,
   turn=turn,background_completion=background)
 def in_thread(self,call):
  result=[]
  def run():
   try:result.append(call())
   except BaseException as error:result.append(error)
  thread=threading.Thread(target=run);thread.start();thread.join(4)
  self.assertFalse(thread.is_alive());return result[0]
 def test_explicit_background_wrapper_preserves_wire_headroom_and_permit(self):
  factory=self.create(True)
  with factory.policy_session(before_dispatch=lambda:None)as backend:
   self.assertIs(type(backend).__dict__['supports_background_completion'],True)
   result=self.in_thread(lambda:backend.complete([{'role':'user','content':'CPU test'}]))
   self.assertFalse(isinstance(result,BaseException),result)
   self.assertNotEqual(self.calls[0][0],threading.get_ident())
   self.assertEqual(self.calls[0][1]['max_tokens'],12144)
   self.assertEqual(self.events,[('begin','policy'),('end','policy')])
 def test_legacy_background_rejects_without_count_or_dispatch(self):
  with self.create(False).policy_session(before_dispatch=lambda:None)as backend:
   self.assertIsInstance(self.in_thread(lambda:backend.complete([])),RuntimeError)
  self.assertFalse(self.calls)
 def test_worker_cannot_change_tools_or_episode_identity(self):
  with self.create(True).policy_session(before_dispatch=lambda:None)as backend:
   for operation in (lambda:backend.configure_tools({'tools':[]}),lambda:backend.begin_episode('other')):
    self.assertIsInstance(self.in_thread(operation),RuntimeError)
  self.assertFalse(self.calls)
 def test_overlapping_completion_and_early_close_do_not_release_ownership(self):
  self.block=(threading.Event(),threading.Event());errors=[]
  with self.create(True).policy_session(before_dispatch=lambda:None)as backend:
   thread=threading.Thread(target=lambda:backend.complete([]));thread.start()
   try:
    self.assertTrue(self.block[0].wait(2))
    with self.assertRaisesRegex(RuntimeError,'Overlapping'):backend.complete([])
    with self.assertRaisesRegex(RuntimeError,'unverified'):backend.close()
    self.assertFalse(backend.raw.closed)
   finally:self.block[1].set();thread.join(4)
  self.assertEqual(len(self.calls),1)
 def test_background_formatter_still_uses_exact_schema_once(self):
  factory=self.create(True)
  with factory.policy_session(before_dispatch=lambda:None):pass
  directory=Path(self.tmp.name);(directory/'extraction').mkdir()
  schema={'type':'object','properties':{'x':{'type':'string'}}};(directory/'extraction/schema.json').write_text(json.dumps(schema))
  backend=factory.extraction_backend_factory(directory/'transport')
  try:
   result=self.in_thread(lambda:backend.complete([]));self.assertFalse(isinstance(result,BaseException),result)
   self.assertEqual(self.calls[-1][1]['response_format']['json_schema']['schema'],schema)
   with self.assertRaises(RuntimeError):backend.complete([])
  finally:backend.close()

class HostedBackgroundTests(unittest.TestCase):
 def setUp(self):self.raws=[];self.addCleanup(lambda:[r.client.close() for r in self.raws])
 def make(self,response,timeout=180):
  raw=ChatCompletionsBackend('https://openrouter.ai/api/v1',HOSTED['MODEL'],supports_images=True,request_options={'provider':{'only':['akashml']}})
  raw.client.close();raw.client=httpx.Client(transport=httpx.MockTransport(response));self.raws.append(raw)
  backend=HOSTED['BackgroundHostedQwenBackend'](raw,lambda *_:{'input_tokens':1},phase='policy',maximum=16384,
   deadline=time.time()+20,timeout=timeout)
  return backend
 def test_background_completion_changes_no_process_alarm_or_request(self):
  import signal
  before=signal.getsignal(signal.SIGALRM);timer=signal.getitimer(signal.ITIMER_REAL);seen=[];out=[]
  def response(req):seen.append(json.loads(req.content));return httpx.Response(200,json={'choices':[{'message':{'content':'ok'}}],'usage':{}})
  backend=self.make(response)
  thread=threading.Thread(target=lambda:out.append(backend.complete([{'role':'user','content':'hi'}])))
  thread.start();thread.join(3)
  self.assertFalse(thread.is_alive());self.assertEqual(len(out),1);self.assertEqual(len(seen),1)
  self.assertEqual(seen[0]['provider'],{'only':['akashml']})
  self.assertIs(signal.getsignal(signal.SIGALRM),before);self.assertEqual(signal.getitimer(signal.ITIMER_REAL),timer)
  self.assertIs(type(backend).__dict__['supports_background_completion'],True);backend.close()
 def test_total_timeout_poisons_and_retains_unstopped_http_until_verified_close(self):
  entered=threading.Event();release=threading.Event();calls=[]
  def response(req):
   calls.append(req);entered.set();release.wait(6)
   return httpx.Response(200,json={'choices':[{'message':{'content':'late'}}],'usage':{}})
  backend=self.make(response);backend.timeout=.03 # Short controlled CPU deadline, not a production option.
  start=time.monotonic()
  try:
   with self.assertRaises(HOSTED['HostedRequestDeadline']):backend.complete([])
   self.assertLess(time.monotonic()-start,2.5);self.assertTrue(backend.poisoned)
   with self.assertRaisesRegex(RuntimeError,'unverified'):backend.close()
   with self.assertRaisesRegex(RuntimeError,'no retry'):backend.complete([])
  finally:release.set();backend.request_thread.join(3)
  self.assertEqual(len(calls),1);self.assertIsNotNone(backend.interrupted_completion);backend.close()
 def test_deadline_consumed_by_admission_does_not_dispatch(self):
  calls=[]
  backend=self.make(lambda req:calls.append(req))
  backend.meter=lambda row:setattr(backend,'deadline',time.time()-1)
  with self.assertRaisesRegex(TimeoutError,'no dispatch'):backend.complete([])
  self.assertFalse(calls);backend.close()
 def test_tools_and_session_configuration_stay_on_owner(self):
  backend=self.make(lambda req:None);errors=[]
  def worker():
   for operation in (lambda:backend.configure_tools({'tools':[]}),lambda:backend.begin_episode('other'),
     lambda:setattr(backend,'request_options',{})):
    try:operation()
    except BaseException as error:errors.append(error)
  thread=threading.Thread(target=worker);thread.start();thread.join(3)
  self.assertEqual(len(errors),3);self.assertTrue(all(isinstance(error,RuntimeError)for error in errors));backend.close()

if __name__=='__main__':unittest.main()
