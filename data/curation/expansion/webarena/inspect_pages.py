"""Read-only local reconnaissance. Never fetches evaluator expected answers."""
import os,json,argparse
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[4]
if (ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu').exists():os.environ['LD_LIBRARY_PATH']=str(ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu')+':'+os.environ.get('LD_LIBRARY_PATH','')
def main():
 p=argparse.ArgumentParser();p.add_argument('--site',choices=['shopping','reddit'],required=True);p.add_argument('--path',default='/');p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
 origin='http://localhost:'+('7770' if a.site=='shopping' else '9999');blocked=[]
 headers={'X-M2-Customer-Auto-Login':'emma.lopez@gmail.com:Password.123'} if a.site=='shopping' else {'X-Postmill-Auto-Login':'MarvelsGrantMan136:test1234'}
 with sync_playwright() as pw:
  b=pw.chromium.launch(headless=True);c=b.new_context(extra_http_headers=headers,service_workers='block')
  def route(r):
   if r.request.method not in ('GET','HEAD') or urlsplit(r.request.url).netloc!=urlsplit(origin).netloc:blocked.append({'method':r.request.method,'url':r.request.url});r.abort()
   else:r.continue_()
  c.route('**/*',route);page=c.new_page();page.goto(origin+a.path,timeout=120000);page.wait_for_timeout(1000)
  (a.output/'body.txt').write_text(page.locator('body').inner_text());(a.output/'page.html').write_text(page.content());(a.output/'links.json').write_text(json.dumps(page.locator('a').evaluate_all('(es)=>es.map(e=>({text:e.innerText,href:e.getAttribute("href")}))'),indent=2));(a.output/'blocked.json').write_text(json.dumps(blocked,indent=2));b.close()
 print(a.output)
if __name__=='__main__':main()
