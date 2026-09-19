"""Independent offline transport/amendment review. Never touch live download state."""
import ast,contextlib,hashlib,io,json,tempfile,threading,unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
import requests
from requests.adapters import BaseAdapter
from data.curation.expansion import download_ranges_v3 as v3,download_ranges_v4 as v4
from data.curation.expansion.download_assets import validate_plan
from data.curation.expansion.range_http_pool import RangeSessions
ROOT=Path(__file__).resolve().parents[5]
HERE=Path(__file__).parent
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
class Tests(unittest.TestCase):
 def test_v4_validation_exact_fail_closed_cases(self):
  asset={'bytes':100,'source_bytes':1000,'etag':'pin'}
  def response():
   r=requests.Response();r.status_code=206;r.headers.update({'Content-Range':'bytes 20-99/1000','Content-Length':'80','ETag':'pin'});return r
  v4.validate_range(response(),asset,20,99)
  for key,val in [('Content-Range','bytes 20-99/100'),('Content-Range','bytes 0-99/1000'),('Content-Length','79'),('ETag','other'),('Content-Encoding','gzip')]:
   r=response();r.headers[key]=val
   with self.assertRaises(ValueError):v4.validate_range(r,asset,20,99)
  r=response();r.status_code=200
  with self.assertRaises(ValueError):v4.validate_range(r,asset,20,99)
 def test_thread_local_and_close_after_workers(self):
  made=[];closed=[];lock=threading.Lock();barrier=threading.Barrier(3)
  class Client:
   adapters={}
   def close(self):closed.append(id(self))
  def factory():
   with lock:c=Client();made.append(c);return c
  with RangeSessions(factory)as pool,ThreadPoolExecutor(max_workers=3)as workers:
   def work():
    first=pool.client();barrier.wait();assert pool.client()is first;return id(first)
   ids=list(workers.map(lambda _:work(),range(3)));self.assertEqual(len(set(ids)),3);self.assertEqual(closed,[])
  self.assertEqual(set(closed),set(ids))
 def test_cookie_clear_does_not_strip_explicit_fields(self):
  with RangeSessions()as pool:
   client=pool.client();client.cookies.set('from_previous','secret');calls=[]
   def fake(url,**kw):calls.append((url,kw,list(client.cookies)));client.cookies.set('from_this','temporary');return object()
   with patch.object(client,'get',fake):
    for i in range(2):pool.get('https://offline.test/blob',headers={'Range':'bytes=2-3','If-Range':'pin','Accept-Encoding':'identity'},stream=True,timeout=(30,120))
   self.assertEqual(len(calls),2)
   for _,kwargs,cookies in calls:self.assertEqual(cookies,[]);self.assertEqual(kwargs,{'headers':{'Range':'bytes=2-3','If-Range':'pin','Accept-Encoding':'identity'},'stream':True,'timeout':(30,120)})
 def test_terminal_get_failure_never_automatically_retried(self):
  with RangeSessions()as pool:
   with patch.object(pool.client(),'get',side_effect=requests.ConnectionError('mock DNS'))as get:
    with self.assertRaises(requests.ConnectionError):pool.get('https://offline.test/blob')
    self.assertEqual(get.call_count,1)
 def test_real_session_redirect_retains_cookie_only_inside_call(self):
  # Exercise requests' actual redirect/cookie handling with a wholly in-memory adapter.
  import http.client
  from types import SimpleNamespace
  class Adapter(BaseAdapter):
   max_retries=SimpleNamespace(total=0)
   def __init__(self):self.calls=[]
   def send(self,request,**kwargs):
    self.calls.append(request);r=requests.Response();r.request=request;r.url=request.url;r._content=b'ok';r._content_consumed=True;r.status_code=302 if request.url.endswith('/start') else 200
    headers=http.client.HTTPMessage()
    if r.status_code==302:r.headers['Location']='/end';headers.add_header('Set-Cookie','within=1; Path=/')
    r.raw=SimpleNamespace(_original_response=SimpleNamespace(msg=headers));return r
   def close(self):pass
  adapter=Adapter()
  def factory():
   s=requests.Session();s.trust_env=False;s.mount('https://',adapter);return s
  with RangeSessions(factory)as pool:
   r=pool.get('https://offline.test/start');self.assertEqual(r.status_code,200)
   pool.get('https://offline.test/end')
  self.assertNotIn('Cookie',adapter.calls[0].headers);self.assertEqual(adapter.calls[1].headers.get('Cookie'),'within=1');self.assertNotIn('Cookie',adapter.calls[2].headers)
 def test_byte_cap_plan_rejection_before_io(self):
  with tempfile.TemporaryDirectory()as d:
   p=Path(d)/'plan.json';p.write_text(json.dumps({'limit_bytes':4,'assets':[{'filename':'x','url':'https://offline.test/x','bytes':5,'etag':'pin'}]}));dest=Path(d)/'absent'
   with patch.object(RangeSessions,'get',side_effect=AssertionError('no HTTP'))as get:
    with self.assertRaisesRegex(ValueError,'exceeds'):v4.run(p,dest,1)
    get.assert_not_called();self.assertFalse(dest.exists())
 def test_resume_validates_unchanged_manifest_before_transport(self):
  with tempfile.TemporaryDirectory()as d:
   root=Path(d);p=root/'plan.json';plan={'limit_bytes':5,'assets':[{'filename':'x','url':'https://offline.test/x','bytes':5,'etag':'pin'}]};p.write_text(json.dumps(plan));dest=root/'out';dest.mkdir();(dest/'ranges-ledger.json').write_text(json.dumps({'chunk_bytes':v4.CHUNK,'plan_sha256':'wrong'}))
   with patch.object(RangeSessions,'get',side_effect=AssertionError('no HTTP'))as get:
    with self.assertRaisesRegex(ValueError,'manifest'):v4.run(p,dest,1)
    get.assert_not_called()
def main():
 amendment_path=ROOT/'.local/curation-expansion/infrastructure/download-v4-amendment.json';amendment=json.loads(amendment_path.read_text())
 for path,pin in amendment['source_sha256'].items():assert sha(ROOT/path)==pin,path
 planpath=ROOT/amendment['same_plan'];assert sha(planpath)==amendment['plan_sha256'];plan=json.loads(planpath.read_text());reserved=validate_plan(plan);assert reserved==amendment['reserved_bytes']==198568153001 and plan['limit_bytes']==200000000000
 paths={name:ROOT/'data/curation/expansion'/('download_ranges_'+name+'.py')for name in ('v3','v4')};texts={k:p.read_text()for k,p in paths.items()}
 same={}
 for name in ('validate_range','file_sha','verify_completed'):
  nodes={v:next(n for n in ast.parse(s).body if isinstance(n,ast.FunctionDef)and n.name==name)for v,s in texts.items()};same[name]=ast.dump(nodes['v3'],include_attributes=False)==ast.dump(nodes['v4'],include_attributes=False);assert same[name]
 normalized=texts['v4'].replace('Version4 reuses one no-retry HTTP session per worker to reduce DNS churn.\n','').replace('from data.curation.expansion.range_http_pool import RangeSessions','import requests').replace(", 'transport_helper_sha256':file_sha(Path(__file__).with_name('range_http_pool.py'))",'').replace('with sessions.get(', 'with requests.get(').replace('with RangeSessions() as sessions, ThreadPoolExecutor(max_workers=workers) as pool:','with ThreadPoolExecutor(max_workers=workers) as pool:')
 assert normalized==texts['v3'],'Unexpected v4 delta'
 stream=io.StringIO();suite=unittest.TestSuite()
 suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(Tests))
 for module in ('data.curation.expansion.test_download_ranges_v4','data.curation.expansion.test_download_ranges_v3','data.curation.expansion.test_download_ranges_v2'):suite.addTests(unittest.defaultTestLoader.loadTestsFromName(module))
 # Final outbound tripwire: supplied test doubles bypass requests networking.
 with contextlib.redirect_stdout(stream),patch('socket.create_connection',side_effect=AssertionError('Network forbidden in audit')):
  result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
 assert result.wasSuccessful(),stream.getvalue()
 report={'schema':'independent-download-v4-review-v1','coordination_id':'DOWNLOAD-V4-REVIEW-01','status':'accepted_transport_amendment','amendment_sha256':sha(amendment_path),'source_pins_match':True,'v4_delta_exactly_limited_to':['Docstring/import','Per-worker RangeSessions transport','Pool/helper SHA logged in implementations','Session context closes only after executor drains'],'unchanged_functions':same,'range_and_resume_logic_byte_identical_after_transport_normalization':True,'tests_run':result.testsRun,'new_independent_tests':7,'upstream_tests':14,'test_log':stream.getvalue(),'reserved_bytes':reserved,'limit_bytes':plan['limit_bytes'],'remaining_plan_allowance_bytes':plan['limit_bytes']-reserved,'findings':[],'semantics':['One requests Session per executor worker and per asset, never shared across concurrent workers.','Adapters with nonzero automatic retry total rejected; range failure propagates with no same-call retry. Already in-flight bounded workers may finish before shutdown, as in v3.','Cookies cleared before each range; cookies within a single redirect chain preserved as with requests.get. Explicit request range/ETag/identity headers and timeout unchanged.','Completed chunks and archives keep prior hashes; partial prefix restart requests suffix only; whole-file expected identity and exact original source total retained.','Plan cap is planned asset-body reservation plus existing reservations; not measured TCP/TLS/redirect traffic or crash-loss retransmission. Existing v3 accounting meaning unchanged.'],'limits':['No live network or connection reuse/DNS improvement measured.','Live ledger/process/download files were not opened, modified, restarted or stopped. Ledger-before SHA is retained amendment assertion, not independently reconstructed.','This checks transport delta and offline guards, not completed archive identity or overall site readiness.'],'source_sha256':{**amendment['source_sha256'],str(Path(__file__).relative_to(ROOT)):sha(__file__)},'network_calls':0,'browser_calls':0,'model_calls':0}
 out=Path(__file__).with_suffix('.json')
 with out.open('x')as f:json.dump(report,f,indent=2);f.write('\n')
 print(json.dumps({k:report[k]for k in ('status','tests_run','reserved_bytes','findings')}))
if __name__=='__main__':main()
