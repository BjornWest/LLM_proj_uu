import hashlib,json,tempfile,threading,unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import requests
from data.curation.expansion.range_http_pool import RangeSessions
from data.curation.expansion import download_ranges_v4 as download

class Sessions(unittest.TestCase):
 def test_reuse_same_worker_and_close(self):
  made=[]
  def factory():
   s=requests.Session();made.append(s);return s
  with RangeSessions(factory)as pool:
   self.assertIs(pool.client(),pool.client())
   self.assertEqual(len(made),1)
  with self.assertRaises(RuntimeError):pool.client()
 def test_workers_do_not_share_session(self):
  barrier=threading.Barrier(2)
  with RangeSessions()as pool,ThreadPoolExecutor(max_workers=2)as workers:
   def acquire():
    s=pool.client();barrier.wait();return s
   a=workers.submit(acquire);b=workers.submit(acquire)
   self.assertIsNot(a.result(),b.result())
 def test_retry_adapter_rejected(self):
  def factory():
   s=requests.Session();s.mount('https://',requests.adapters.HTTPAdapter(max_retries=2));return s
  with RangeSessions(factory)as pool:
   with self.assertRaisesRegex(ValueError,'retries'):pool.client()
 def test_cookies_cleared_but_request_fields_unchanged(self):
  with RangeSessions()as pool:
   client=pool.client();client.cookies.set('previous','not_sent')
   with patch.object(client,'get',return_value='response')as get:
    self.assertEqual(pool.get('https://example.test/file',headers={'Range':'bytes=0-2'},stream=True),'response')
    get.assert_called_once_with('https://example.test/file',headers={'Range':'bytes=0-2'},stream=True)
    self.assertEqual(len(client.cookies),0)
 def test_partial_failure_resume_and_complete_hash(self):
  with tempfile.TemporaryDirectory()as tmp:
   root=Path(tmp);plan=root/'plan.json';data=b'abcde';asset={'filename':'file','bytes':5,'url':'https://example.test/file','etag':'pin','expected_sha256':hashlib.sha256(data).hexdigest()}
   plan.write_text(json.dumps({'limit_bytes':5,'assets':[asset]}));dest=root/'download';calls=[];failed=[False]
   class Response:
    status_code=206
    def __init__(self,start,end):self.start,self.end=start,end;self.headers={'Content-Range':f'bytes {start}-{end}/5','Content-Length':str(end-start+1),'ETag':'pin'}
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def iter_content(self,*args):
     if not failed[0]:
      failed[0]=True;yield data[:2];raise requests.ConnectionError('offline interruption')
     yield data[self.start:self.end+1]
   def get(self,url,**kwargs):
    r=kwargs['headers']['Range'];calls.append(r);start,end=map(int,r.removeprefix('bytes=').split('-'));return Response(start,end)
   with patch.object(requests.Session,'get',get),patch.object(download,'CHUNK',4):
    with self.assertRaises(requests.ConnectionError):download.run(plan,dest,workers=1)
    self.assertEqual(calls,['bytes=0-3'])
    self.assertEqual((dest/'file.ranges/0').read_bytes(),b'ab')
    download.run(plan,dest,workers=1)
    self.assertEqual(calls,['bytes=0-3','bytes=2-3','bytes=4-4'])
    self.assertEqual((dest/'file').read_bytes(),data)
    ledger=json.loads((dest/'ranges-ledger.json').read_text());self.assertEqual(ledger['reserved_bytes'],5)
    download.run(plan,dest,workers=1)
    self.assertEqual(len(calls),3)
    (dest/'file').write_bytes(b'xxxxx')
    with self.assertRaisesRegex(ValueError,'changed'):download.run(plan,dest,workers=1)
    self.assertEqual(len(calls),3)
if __name__=='__main__':unittest.main()
