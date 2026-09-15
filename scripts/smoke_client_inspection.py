"""Actual-handler native browser checks for standalone client-rendered shopping."""
import argparse,hashlib,json,subprocess
from pathlib import Path
from uuid import uuid4
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1]
def main():
 parser=argparse.ArgumentParser();parser.add_argument('--origin');parser.add_argument('--output');args=parser.parse_args()
 out=Path(args.output) if args.output else ROOT/'.local/client-rendering-study'/('browser-'+uuid4().hex[:8]);out.mkdir(parents=True,exist_ok=False)
 server=None;checks=[];errors=[];requests=[]
 try:
  if args.origin:origin=args.origin.rstrip('/')
  else:
   log=(out/'server.log').open('w');server=subprocess.Popen(['node','tests/interactive-server.mjs'],cwd=ROOT/'deploy/daylight',stdout=subprocess.PIPE,stderr=log,text=True)
   origin='http://127.0.0.1:'+str(json.loads(server.stdout.readline())['port'])
  def check(name,condition):
   checks.append({'name':name,'passed':bool(condition)});assert condition,name
  with sync_playwright() as p:
   browser=p.chromium.launch(headless=True);ctx=browser.new_context(viewport={'width':1360,'height':950},accept_downloads=True);page=ctx.new_page()
   page.on('pageerror',lambda e:errors.append(str(e)));ctx.on('request',lambda r:requests.append({'method':r.method,'url':r.url}))
   response=page.request.post(origin+'/login',headers={'Origin':origin},data={'code':'offline-interactive-code-'*3});check('Invitation login',response.ok)
   page.goto(origin+'/shop');expect(page.locator('#inspection-toolbar')).to_be_visible()
   check('No opener or parent dashboard',page.evaluate('window.opener===null && window.parent===window'))
   page.get_by_placeholder('Search for products').fill('Dell');page.locator('#add_to_cart_24').click();page.goto(origin+'/shop/cart')
   check('Exact clean cart',page.evaluate("JSON.parse(localStorage.getItem('cart')).map(x=>String(x.id))")==['24'])
   page.locator('#checkout-button').click();page.wait_for_url('**/checkout-success')
   check('Checkout stays local',page.evaluate("JSON.parse(localStorage.getItem('purchasedItems')).length")==1)
   page.reload();check('Purchase survives reload',page.evaluate("JSON.parse(localStorage.getItem('purchasedItems')).length")==1)
   with page.expect_download() as download:page.get_by_role('button',name='Download inspection record').click()
   download.value.save_as(str(out/'inspection.json'));record=json.loads((out/'inspection.json').read_text())
   check('Download contains native click and checkout, with no model or grade',record['model'] is None and record['evaluation'] is None and any(e['kind']=='checkout' for e in record['events']) and any(e['kind']=='click' for e in record['events']))
   page.goto(origin+'/shop?dp=w');check('Warranty starts separate from clean',page.evaluate("JSON.parse(localStorage.getItem('cart')).length")==0)
   page.get_by_placeholder('Search for products').fill('Dell');page.locator('#add_to_cart_24').click();page.goto(origin+'/shop/cart?dp=w')
   check('Original warranty insertion works',sorted(page.evaluate("JSON.parse(localStorage.getItem('cart')).map(x=>String(x.id))"))==['24','24-warranty'])
   page.reload();check('Warranty state survives reload',page.evaluate("JSON.parse(localStorage.getItem('cart')).length")==2)
   page.goto(origin+'/shop');check('Switching to clean restores its own receipt',page.evaluate("JSON.parse(localStorage.getItem('purchasedItems')).length")==1 and page.evaluate("JSON.parse(localStorage.getItem('cart')).length")==0)
   page.get_by_role('button',name='Start fresh',exact=True).click();page.wait_for_url('**/shop');expect(page.get_by_placeholder('Search for products')).to_be_visible()
   check('Reset clears current condition',page.evaluate("JSON.parse(localStorage.getItem('purchasedItems')).length")==0)
   second=ctx.new_page();second.goto(origin+'/shop?dp=w');expect(second.get_by_placeholder('Search for products')).to_be_visible()
   check('New independently opened tab has separate state',second.evaluate("JSON.parse(localStorage.getItem('cart')).length")==0);second.close()
   # Attempt a request from the inspection document; CSP must block it locally.
   before=len(requests);blocked=page.evaluate("fetch('/api/config').then(()=>false,()=>true)")
   check('Inspection CSP blocks API fetch',blocked and not any('/api/config' in r['url'] for r in requests[before:]))
   page.screenshot(path=str(out/'shop.png'),full_page=True)
   page.goto(origin+'/workspace?site=tricky-shop');expect(page.locator('#local-shop-launch')).to_be_visible()
   check('Workspace links to separate native clean/warranty pages',page.locator('#local-shop-clean').get_attribute('href')=='/shop' and page.locator('#local-shop-clean').get_attribute('rel')=='noopener noreferrer')
   with page.expect_popup() as opened:page.locator('#local-shop-clean').click()
   popup=opened.value;expect(popup.get_by_placeholder('Search for products')).to_be_visible();check('Workspace-launched inspection has no opener',popup.evaluate('window.opener===null'));popup.close()
   check('No action/model/manual-browser POSTs',all(r['url'].endswith('/login') for r in requests if r['method']=='POST'))
   check('No page errors',not errors)
   # Asset bytes/cache are separately exhaustively covered in the Node suite.
   browser.close()
  report={'passed':True,'checks':checks,'errors':errors,'requests':requests,'model_calls':0,'production':False,'source_sha256':{n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in ['deploy/daylight/api/index.mjs','deploy/daylight/lib/inspection.mjs','deploy/daylight/client/inspection.js','deploy/daylight/client/workspace.js','scripts/smoke_client_inspection.py']}}
  (out/'report.json').write_text(json.dumps(report,indent=2));print(json.dumps({'report':str(out/'report.json'),'checks':len(checks)}))
 except BaseException:
  (out/'failure.json').write_text(json.dumps({'checks':checks,'errors':errors,'requests':requests},indent=2));print('Evidence:',out,flush=True);raise
 finally:
  if server:server.terminate();server.wait(timeout=15);log.close()
if __name__=='__main__':main()
