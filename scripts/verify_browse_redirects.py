"""Real Chromium redirect containment at lease proxy; local synthetic HTTP only."""
import argparse,json,os,tempfile,threading,hashlib
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4
from playwright.sync_api import sync_playwright
from scripts.browse_pool_server import Pool,handler
ROOT=Path(__file__).resolve().parents[1]
def main():
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
 os.environ['LD_LIBRARY_PATH']=str(ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu');foreign=[];upstream=[]
 class Trap(BaseHTTPRequestHandler):
  def log_message(self,*args):pass
  def do_GET(self):foreign.append(self.path);self.send_response(200);self.end_headers()
 trap=ThreadingHTTPServer(('127.0.0.1',0),Trap);threading.Thread(target=trap.serve_forever,daemon=True).start()
 class Source(BaseHTTPRequestHandler):
  def log_message(self,*args):pass
  def do_GET(self):
   upstream.append({'path':self.path,'lease_header_present':bool(self.headers.get('X-Daylight-Lease'))})
   if self.path in ('/unsafe','/protocol-relative','/triple-slash','/scheme-slashes','/safe'):
    target='/ok' if self.path=='/safe' else ('http:' if self.path=='/unsafe' else '')+f'//127.0.0.1:{trap.server_port}/leak'
    if self.path=='/triple-slash':target=f'///127.0.0.1:{trap.server_port}/leak'
    if self.path=='/scheme-slashes':target=f'http:////127.0.0.1:{trap.server_port}/leak'
    self.send_response(302);self.send_header('Location',target);self.send_header('Content-Length','0');self.end_headers()
   else:self.send_response(200);self.send_header('Content-Length','2');self.end_headers();self.wfile.write(b'ok')
 source=ThreadingHTTPServer(('127.0.0.1',0),Source);threading.Thread(target=source.serve_forever,daemon=True).start()
 with tempfile.TemporaryDirectory() as state:
  config={'browser_origin':'pending','sites':[{'site_id':s,'image_id':'synthetic','upstream_origin':f'http://127.0.0.1:{source.server_port}'} for s in ('webarena-shopping','webarena-forum')]};pool=Pool(config,state,resetter=lambda s:None)
  for slot in pool.slots.values():slot['status']='ready'
  proxy=ThreadingHTTPServer(('127.0.0.1',0),handler(pool,'private-admin'));origin=f'http://127.0.0.1:{proxy.server_port}';config['browser_origin']=origin;threading.Thread(target=proxy.serve_forever,daemon=True).start()
  _,lease=pool.control('acquire',{'site_id':'webarena-shopping','session_id':str(uuid4())});rows=[]
  try:
   with sync_playwright() as pw:
    browser=pw.chromium.launch();context=browser.new_context(extra_http_headers={'X-Daylight-Lease':lease['lease_token']});page=context.new_page()
    for route,expected in [('/safe',200),('/unsafe',502),('/protocol-relative',502),('/triple-slash',502),('/scheme-slashes',502)]:
     response=page.goto(origin+route);assert response.status==expected;(rows.append({'path':route,'status':response.status,'final_url':page.url}))
    assert not foreign and not any(r['lease_header_present'] for r in upstream);browser.close()
   report={'passed':True,'cases':rows,'foreign_requests':foreign,'upstream':upstream,'source_sha256':hashlib.sha256((ROOT/'scripts/browse_pool_server.py').read_bytes()).hexdigest(),'model_calls':0,'scope':'Chromium with global lease header, no Playwright request guard; proxy alone blocks foreign redirect'}
   (a.output/'report.json').write_text(json.dumps(report,indent=2));print('Chromium redirect containment: 5 cases passed')
  finally:proxy.shutdown();proxy.server_close();pool.close();source.shutdown();source.server_close();trap.shutdown();trap.server_close()
if __name__=='__main__':main()
