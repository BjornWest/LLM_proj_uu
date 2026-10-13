"""Real local sockets/controller/metrics; no browser, GPU or model generation."""
from pathlib import Path
from types import SimpleNamespace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from hashlib import sha256
import json,runpy,socket,tempfile,threading,time,unittest

ROOT=Path(__file__).resolve().parents[1]
CALLER=runpy.run_path(str(ROOT/'scripts/comparison_suite.py'))
API=runpy.run_path(str(ROOT/'scripts/qwen_suite_observer.py'))

def pin(path):return {'path':str(path),'sha256':sha256(path.read_bytes()).hexdigest()}

def modules():
 import importlib.util,sys,types
 name='_qwen_test_control_'+str(time.monotonic_ns());package=types.ModuleType(name);package.__path__=[];sys.modules[name]=package
 result={}
 for key,relative in [('control','capacity_control'),('telemetry','serving_telemetry')]:
  path=ROOT/'training/browser_training'/f'{relative}.py';spec=importlib.util.spec_from_file_location(name+'.'+relative,path)
  m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m);result[key]=m
 result['rpc']=SimpleNamespace(**runpy.run_path(str(ROOT/'scripts/episode_capacity_rpc.py')))
 return result


class ObserverTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(prefix='qo-');self.addCleanup(self.tmp.cleanup);self.directory=Path(self.tmp.name)
  self.stop=threading.Event();self.mods=modules();outer=self;self.scrapes=0
  class Handler(BaseHTTPRequestHandler):
   def do_GET(self):
    outer.scrapes+=1;n=outer.scrapes;label='{model_name="test-model",engine="0"}'
    pairs=[('vllm:num_requests_waiting',0),('vllm:num_requests_running',0),('vllm:kv_cache_usage_perc',.1),('vllm:num_preemptions_total',0),('vllm:generation_tokens_total',n*10)]
    body='\n'.join(f'{key}{label} {value}' for key,value in pairs)+'\n'
    for reason in ['capacity','deferred']:body+=f'vllm:num_requests_waiting_by_reason{{model_name="test-model",engine="0",reason="{reason}"}} 0\n'
    raw=body.encode();self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
   def log_message(self,*args):pass
  self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
  self.addCleanup(self.server.server_close);self.addCleanup(self.server.shutdown)
  self.qual=SimpleNamespace(session='test-session',identity={'model':'test-model','serving_revision':'test-revision'},raw=f'http://127.0.0.1:{self.server.server_port}')
  self.host=API['CapacityHost'](rpc=self.mods['rpc'],control=self.mods['control'],telemetry=self.mods['telemetry'],source={},output=self.directory,
   case_ids=['a','b','c'],cap=2,deadline=time.monotonic()+20,stop_event=self.stop,directory=self.directory,qualification=self.qual)
  self.addCleanup(self.cleanup_host)
  until=time.monotonic()+3
  while self.host.poller.status()['snapshot'] is None and time.monotonic()<until:time.sleep(.01)
  self.assertIsNotNone(self.host.poller.status()['snapshot'])
  self.clients=[]

 def cleanup_host(self):
  self.stop.set()
  for client in getattr(self,'clients',[]):client.close()
  self.host.close()

 def client(self,ident):
  self.host.begin_relay(ident)
  c=API['connect_client'](self.mods['rpc'],self.host.child_binding(ident),deadline=time.monotonic()+10)
  self.clients.append(c);return c

 def rpc_read(self,frame):
  with socket.socket(socket.AF_UNIX) as s:
   s.settimeout(3);s.connect(str(self.host.observer_rpc.path));s.sendall((json.dumps(frame)+'\n').encode())
   raw=b''
   while not raw.endswith(b'\n'):raw+=s.recv(65536)
   return json.loads(raw)

 def test_shared_parent_cap_policy_formatter_and_refill(self):
  a=self.client('a');b=self.client('b');self.host.activate('a',priority=0);self.host.activate('b',priority=1)
  with self.assertRaises(ValueError):self.host.activate('c',priority=2)
  with a.turn('policy'):pass
  with b.turn('policy'):pass
  with a.turn('formatter'):pass
  a.close();self.host.finish('a',verify_cleanup=lambda:True,record_terminal=lambda:True)
  c=self.client('c');self.host.activate('c',priority=2)
  with c.turn('policy'):pass
  for ident,client in [('b',b),('c',c)]:
   client.close();self.host.finish(ident,verify_cleanup=lambda:True,record_terminal=lambda:True)
  status=self.host.controller.status();self.assertTrue(all(v['done'] for v in status['episodes'].values()))
  self.assertEqual(self.host.parent.finished,{'a','b','c'});self.assertFalse(self.stop.is_set())

 def test_formatter_release_survives_other_case_cohort_abort(self):
  client=self.client('a');self.host.activate('a',priority=0);self.host.activate('b',priority=1)
  entered=threading.Event();response=threading.Event();cleaned=threading.Event();errors=[]
  def complete():
   try:
    with client.turn('formatter'):
     entered.set();response.wait(4);cleaned.set()
   except BaseException as error:errors.append(error)
   finally:client.close()
  worker=threading.Thread(target=complete);worker.start()
  try:
   self.assertTrue(entered.wait(2))
   self.host.failed('b',RuntimeError('native grading failed'),infrastructure=True)
   row=self.host.controller.status()['episodes']['a']
   self.assertEqual(row['request_id'],'a:formatter:1');self.assertTrue(row['dispatch_retired'])
   self.assertFalse(row['done']);self.assertEqual(self.host.parent.finished,set())
   response.set();worker.join(3);self.assertFalse(worker.is_alive());self.assertTrue(cleaned.is_set())
   self.assertEqual(errors,[]);self.assertIsNone(client.infrastructure_error)
   self.host.finish('a',verify_cleanup=lambda:cleaned.is_set()and not worker.is_alive()and client.infrastructure_error is None,record_terminal=lambda:True)
   self.assertTrue(self.host.controller.status()['episodes']['a']['done'])
   self.assertEqual(self.host.parent.finished,{'a'});self.assertTrue(self.stop.is_set())
   self.assertEqual(self.host.parent.stop_cause['case'],'b')
  finally:response.set();worker.join(4)

 def test_real_child_http_formatter_drains_after_cohort_abort(self):
  import subprocess,sys
  entered=threading.Event();release=threading.Event()
  class Handler(BaseHTTPRequestHandler):
   def do_GET(self):
    entered.set();release.wait(4);body=b'cpu-only formatter answer'
    self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
   def log_message(self,*args):pass
  server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  self.host.begin_relay('a');self.host.activate('a',priority=0);self.host.activate('b',priority=1)
  code="""import json,runpy,sys,time,types
from urllib.request import urlopen
cfg=json.load(sys.stdin);rpc=types.SimpleNamespace(**runpy.run_path(cfg['rpc']));api=runpy.run_path(cfg['observer'])
client=api['connect_client'](rpc,cfg['binding'],deadline=time.monotonic()+10)
try:
 with client.turn('formatter'):
  with urlopen(cfg['url'],timeout=5)as response:body=response.read()
 print(json.dumps({'http_drained':body==b'cpu-only formatter answer','infrastructure_error':client.infrastructure_error}))
finally:client.close()
"""
  child=subprocess.Popen([sys.executable,'-I','-B','-c',code],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
  cfg={'rpc':str(ROOT/'scripts/episode_capacity_rpc.py'),'observer':str(ROOT/'scripts/qwen_suite_observer.py'),'binding':self.host.child_binding('a'),'url':f'http://127.0.0.1:{server.server_port}/completion'}
  child.stdin.write(json.dumps(cfg));child.stdin.close();child.stdin=None
  try:
   self.assertTrue(entered.wait(3));self.host.failed('b',RuntimeError('other native grader failed'),infrastructure=True)
   row=self.host.controller.status()['episodes']['a'];self.assertEqual(row['request_id'],'a:formatter:1');self.assertFalse(row['done'])
   self.assertIsNone(child.poll());release.set();out,err=child.communicate(timeout=8)
   self.assertEqual(child.returncode,0,err);evidence=json.loads(out);self.assertTrue(evidence['http_drained']);self.assertIsNone(evidence['infrastructure_error'])
   self.host.finish('a',verify_cleanup=lambda:child.poll()==0 and evidence['http_drained']and evidence['infrastructure_error']is None,record_terminal=lambda:True)
   row=self.host.controller.status()['episodes']['a'];self.assertIsNone(row['request_id']);self.assertTrue(row['done']);self.assertEqual(self.host.parent.cleanup_failures,{})
  finally:
   release.set()
   if child.poll()is None:child.kill();child.wait(3)
   server.shutdown();server.server_close();thread.join(3)

 def test_expired_abort_drain_retains_request_and_refuses_clean_finish(self):
  self.host.cleanup_grace=0.05
  client=self.client('a');self.host.activate('a',priority=0);self.host.activate('b',priority=1)
  permit=client._exchange({'type':'acquire','phase':'formatter','sequence':1})
  self.host.failed('b',RuntimeError('grader failure'),infrastructure=True)
  thread,_=self.host.relays['a'];thread.join(2);self.assertFalse(thread.is_alive())
  row=self.host.controller.status()['episodes']['a'];self.assertEqual(row['request_id'],permit['request_id']);self.assertFalse(row['done'])
  until=time.monotonic()+2
  while 'a'not in self.host.parent.ended and time.monotonic()<until:time.sleep(.005)
  self.assertEqual(self.host.parent.errors['a']['message'],'Capacity cleanup channel ended with an in-flight request')
  client.close()
  with self.assertRaises(self.mods['rpc'].CapacityChannelError):
   self.host.finish('a',verify_cleanup=lambda:False,record_terminal=lambda:True)
  self.assertEqual(self.host.controller.status()['episodes']['a']['request_id'],permit['request_id'])
  self.assertNotIn('a',self.host.parent.finished)

 def test_direct_stop_relay_cannot_grant_another_request(self):
  client=self.client('a');self.host.activate('a',priority=0)
  with client.turn('policy'):pass
  self.stop.set()
  with self.assertRaises(self.mods['rpc'].CapacityParentError)as caught:
   with client.turn('formatter'):self.fail('Post-stop generation permitted')
  self.assertEqual(caught.exception.parent_error_type,'CapacitySuiteStopped')
  self.assertIsNone(self.host.controller.status()['episodes']['a']['request_id'])

 def test_failed_cleanup_retains_cap_and_stops_refill(self):
  client=self.client('a');self.host.activate('a',priority=0)
  with client.turn('policy'):pass
  client.close()
  with self.assertRaises(self.mods['rpc'].CapacityChannelError):self.host.finish('a',verify_cleanup=lambda:False,record_terminal=lambda:True)
  self.assertTrue(self.stop.is_set());self.assertNotIn('a',self.host.parent.finished)
  self.assertFalse(self.host.controller.status()['episodes']['a']['done'])

 def test_observer_private_read_epoch_bounds_and_journal(self):
  first=self.rpc_read({'op':'read','after':0,'limit':120})
  self.assertEqual(first['status'],'ok');v=first['value'];self.assertEqual(v['session_id'],'test-session')
  self.assertLessEqual(len(v['rows']),120)
  self.assertEqual(self.rpc_read({'op':'read','after':0,'limit':121})['status'],'error')
  self.assertEqual(self.rpc_read({'op':'write'})['status'],'error')
  self.assertEqual(self.rpc_read({'op':'read','after':1,'observer_id':v['observer_id'],'epoch':'wrong'})['status'],'error')
  self.host.journal.drain();lines=(self.directory/'serving-telemetry.jsonl').read_text().splitlines();self.assertTrue(lines)
  self.assertEqual(json.loads(lines[-1])['epoch'],self.host.journal.epoch)

 def test_partial_observer_disconnect_does_not_spin_or_kill_service(self):
  with socket.socket(socket.AF_UNIX) as s:s.connect(str(self.host.observer_rpc.path));s.sendall(b'{');s.shutdown(socket.SHUT_WR)
  time.sleep(.05);self.assertEqual(self.rpc_read({'op':'read'})['status'],'ok')

 def test_warm_eof_is_retirement_not_early_completion(self):
  c=self.client('c');c.close()
  until=time.monotonic()+2
  while 'c' not in self.host.parent.ended and time.monotonic()<until:time.sleep(.01)
  self.assertIn('c',self.host.parent.ended);self.assertNotIn('c',self.host.parent.finished)
  self.assertNotIn('c',self.host.controller.status()['episodes'])

class ConstructionFailureTests(unittest.TestCase):
 def test_partial_socketpair_failure_closes_previously_allocated_pair(self):
  from unittest.mock import patch
  original=socket.socketpair;allocated=[]
  def pair():
   if allocated:raise OSError('injected descriptor exhaustion')
   value=original();allocated.extend(value);return value
  with tempfile.TemporaryDirectory(prefix='qo-init-') as tmp,patch.object(API['socket'],'socketpair',side_effect=pair):
   with self.assertRaisesRegex(OSError,'descriptor exhaustion'):
    API['CapacityHost'](rpc=SimpleNamespace(),control=SimpleNamespace(),telemetry=SimpleNamespace(),source={},output=tmp,
       case_ids=['a','b'],cap=2,deadline=time.monotonic()+5,stop_event=threading.Event(),directory=tmp,qualification=SimpleNamespace())
  self.assertEqual([s.fileno() for s in allocated],[-1,-1])

if __name__=='__main__':unittest.main()
