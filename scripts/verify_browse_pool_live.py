"""Native saved mutations through the real lease proxy, then full reset/new visitor.

Only backend-owned disposable clones. No model calls, shared app changes or
Playwright HAR/trace headers (which would contain ephemeral lease credentials).
"""
import argparse,json,os,time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4
import httpx
from playwright.sync_api import sync_playwright
from data.curation.manual_sites.rehearse import state
ROOT=Path(__file__).resolve().parents[1]

def run(site,output,token):
 output.mkdir(parents=True,exist_ok=False);origin='http://172.23.129.52:8896';lease=None;checks=[]
 def check(name,value):assert value,name;checks.append(name)
 def rpc(op,value={}):
  r=httpx.post(origin+'/_control/'+op,json=value,headers={'Authorization':'Bearer '+token},timeout=10);r.raise_for_status();return r.json()
 def ready():
  for _ in range(180):
   if next(x for x in rpc('status')['sites'] if x['site_id']=='webarena-'+site)['status']=='ready':return
   time.sleep(1)
  raise RuntimeError('Pool did not become ready')
 ready();initial=state(site);lease=rpc('acquire',{'site_id':'webarena-'+site,'session_id':str(uuid4())})
 try:
  other=httpx.post(origin+'/_control/acquire',json={'site_id':'webarena-'+site,'session_id':str(uuid4())},headers={'Authorization':'Bearer '+token});check('Occupied site rejects another visitor',other.status_code==429)
  with sync_playwright() as pw:
   browser=pw.chromium.launch();context=browser.new_context(service_workers='block',extra_http_headers={'X-Daylight-Lease':lease['lease_token']})
   context.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin+'/') else r.abort())
   page=context.new_page();page.set_default_timeout(30000)
   if site=='shopping':
    page.goto(origin+'/customer/account/',timeout=60000);page.goto(origin+'/elmwood-inn-fine-teas-orange-vanilla-caffeine-free-fruit-infusion-16-ounce-pouch.html',timeout=60000)
    page.locator('.product-info-main a[data-action="add-to-wishlist"]').click();page.wait_for_url('**/wishlist/**',timeout=60000);page.locator('.products-grid.wishlist').wait_for(state='visible')
   else:
    page.goto(origin,timeout=60000);page.get_by_role('button',name='MarvelsGrantMan136').click();page.get_by_role('link',name='Profile',exact=True).click();page.get_by_role('link',name='Edit biography',exact=True).click()
    page.locator('textarea').fill('Exclusive browsing lease test; reset before next visitor.');page.get_by_role('button',name='Save',exact=True).click();page.get_by_text('The biography was updated.',exact=True).wait_for()
   page.screenshot(path=str(output/'changed.png'));changed=state(site);check('Native proxy action saves a real database change',changed!=initial)
   old=lease;rpc('release',lease);lease=None
   check('Revoked browser GET blocked immediately',context.request.get(origin+'/').status==410)
   check('Revoked browser POST blocked before dispatch',context.request.post(origin+'/').status==410)
   ready();restored=state(site);check('Full clone reset restores saved baseline',restored==initial)
   lease=rpc('acquire',{'site_id':'webarena-'+site,'session_id':str(uuid4())});check('New visitor gets a distinct credential',lease['lease_token']!=old['lease_token'])
   fresh=browser.new_context(service_workers='block',extra_http_headers={'X-Daylight-Lease':lease['lease_token']});p=fresh.new_page();response=p.goto(origin,timeout=60000);check('New visitor can browse restored application',response.status==200)
   check('Old browser remains revoked after new lease',context.request.get(origin+'/').status==410)
   browser.close()
  report={'passed':True,'site':site,'checks':checks,'initial':initial,'changed':changed,'restored':restored,'model_calls':0,'scope':'Native Playwright through actual proxy plus independent clone DB reads; no model or grade'}
  (output/'report.json').write_text(json.dumps(report,indent=2));return {'site':site,'checks':len(checks),'passed':True}
 finally:
  if lease:rpc('release',lease)

def main():
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
 os.environ['LD_LIBRARY_PATH']=str(ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu');token=(ROOT/'.local/browse-pool/token').read_text()
 with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda site:run(site,a.output/site,token),['shopping','forum']))
 (a.output/'report.json').write_text(json.dumps({'passed':True,'cases':results,'model_calls':0},indent=2));print(results)
if __name__=='__main__':main()
