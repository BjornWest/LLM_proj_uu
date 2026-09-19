import json,tempfile,threading,time,unittest
from pathlib import Path
from uuid import uuid4
from scripts.browse_pool_server import Pool
class PoolTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.resets=[];self.gate=threading.Event();self.gate.set();self.now=0
  config={'browser_origin':'http://fixture:8896','sites':[{'site_id':s,'image_id':'sha256:test','upstream_origin':'http://127.0.0.1:1','reset_argv':['never']} for s in ['webarena-shopping','webarena-forum']]}
  def reset(slot):self.gate.wait(2);self.resets.append(slot['config']['site_id'])
  self.pool=Pool(config,self.temp.name,resetter=reset,clock=lambda:self.now)
  self.pool.initialize();self.wait_ready('webarena-shopping');self.wait_ready('webarena-forum')
 def tearDown(self):self.gate.set();self.pool.close();self.temp.cleanup()
 def wait_ready(self,site):
  for _ in range(200):
   if self.pool.slots[site]['status']=='ready':return
   time.sleep(.005)
  self.fail('Reset did not finish')
 def acquire(self,site='webarena-shopping'):return self.pool.control('acquire',{'site_id':site,'session_id':str(uuid4())})
 def test_exclusive_independent_slots(self):
  code,a=self.acquire();self.assertEqual(code,200);self.assertEqual(self.acquire()[0],429)
  code,b=self.acquire('webarena-forum');self.assertEqual(code,200);self.assertNotEqual(a['lease_token'],b['lease_token'])
  self.assertEqual(self.pool.enter(a['lease_token'])['config']['site_id'],'webarena-shopping')
 def test_revoke_before_drain_and_reset(self):
  _,a=self.acquire();token=a['lease_token'];slot=self.pool.enter(token);self.gate.clear()
  self.pool.control('release',{'lease_token':token});self.assertIsNone(self.pool.enter(token));self.assertEqual(self.acquire()[0],429)
  self.assertEqual(len(self.resets),2);self.pool.leave(slot);self.gate.set();self.wait_ready('webarena-shopping')
  _,b=self.acquire();self.assertNotEqual(token,b['lease_token']);self.pool.control('release',{'lease_token':token})
  self.assertEqual(self.pool.slots['webarena-shopping']['token'],b['lease_token'])
 def test_expiry_and_reset_failure_fail_closed(self):
  _,a=self.acquire();self.now=1201
  def broken(slot):raise RuntimeError('No reset')
  self.pool.resetter=broken;self.pool.expire()
  for _ in range(100):
   if self.pool.slots['webarena-shopping']['status']=='error':break
   time.sleep(.005)
  self.assertIsNone(self.pool.enter(a['lease_token']));self.assertEqual(self.acquire()[0],503)
 def test_no_reset_inputs_or_token_leak_in_status_and_events(self):
  _,a=self.acquire();result=self.pool.control('status',{})[1]
  self.assertNotIn(a['lease_token'],json.dumps(result));self.assertNotIn(a['lease_token'],Path(self.temp.name,'events.jsonl').read_text())
  self.assertEqual(self.pool.control('reset',{'command':'bad'})[0],404)

class ProxyTests(unittest.TestCase):
 def test_authenticated_proxy_forwards_once_and_revokes_access(self):
  from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
  from http.client import HTTPConnection
  from scripts.browse_pool_server import handler
  received=[]
  class Upstream(BaseHTTPRequestHandler):
   def log_message(self,*args):pass
   def do_POST(self):
    received.append({'body':self.rfile.read(int(self.headers['Content-Length'])), 'headers':dict(self.headers)})
    self.send_response(200);self.send_header('Content-Length','2');self.end_headers();self.wfile.write(b'ok')
  upstream=ThreadingHTTPServer(('127.0.0.1',0),Upstream);threading.Thread(target=upstream.serve_forever,daemon=True).start()
  with tempfile.TemporaryDirectory() as root:
   config={'browser_origin':'http://fixture','sites':[{'site_id':s,'image_id':'test','account_headers':{'X-Test-Account':'fixture'},'upstream_origin':f'http://127.0.0.1:{upstream.server_port}'} for s in ['webarena-shopping','webarena-forum']]}
   pool=Pool(config,root,resetter=lambda s:None)
   for slot in pool.slots.values():slot['status']='ready'
   server=ThreadingHTTPServer(('127.0.0.1',0),handler(pool,'secret'));threading.Thread(target=server.serve_forever,daemon=True).start()
   def call(path,body,headers):
    c=HTTPConnection('127.0.0.1',server.server_port);c.request('POST',path,body,headers);r=c.getresponse();result=(r.status,r.read());c.close();return result
   try:
    self.assertEqual(call('/_control/acquire','{}',{})[0],401)
    code,lease=pool.control('acquire',{'site_id':'webarena-shopping','session_id':str(uuid4())});self.assertEqual(code,200)
    headers={'X-Daylight-Lease':lease['lease_token'],'Authorization':'secret-not-forwarded'}
    self.assertEqual(call('/change','one',headers),(200,b'ok'));self.assertEqual(len(received),1)
    self.assertEqual(received[0]['headers']['X-Test-Account'],'fixture');self.assertNotIn('X-Daylight-Lease',received[0]['headers']);self.assertNotIn('Authorization',received[0]['headers'])
    pool.control('release',lease)
    self.assertEqual(call('/change','two',headers)[0],410);self.assertEqual(len(received),1)
   finally:server.shutdown();server.server_close();pool.close();upstream.shutdown();upstream.server_close()

class RedirectTests(unittest.TestCase):
 def test_only_unambiguous_canonical_redirects_allowed(self):
  from scripts.browse_pool_server import allowed_redirect
  origin='http://127.0.0.1:8896'
  for location in ['/account','../news','?page=2',origin+'/next']:
   self.assertTrue(allowed_redirect(location,origin,'/folder/page'),location)
  for location in ['https://example.org/','//example.org','http://127.0.0.1:80/','http://user@127.0.0.1:8896/','/\\example.org','http:\\example.org','\n//example.org','///outside.invalid/path','http:////outside.invalid/path','']:
   self.assertFalse(allowed_redirect(location,origin,'/folder/page'),location)

if __name__=='__main__':unittest.main()
