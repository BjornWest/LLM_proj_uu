"""Offline browser regression: blocked history/registry cannot block Campus."""
import hashlib,json,os,subprocess,re
from pathlib import Path
from uuid import uuid4
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1]
def main():
 os.environ['LD_LIBRARY_PATH']=str(ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu')+':'+os.environ.get('LD_LIBRARY_PATH','')
 output=ROOT/'.local/vercel-demo'/('history-loading-'+uuid4().hex[:8]);output.mkdir(parents=True)
 process=subprocess.Popen(['node','tests/workspace-server.mjs'],cwd=ROOT/'deploy/daylight',stdout=subprocess.PIPE,text=True)
 origin='http://127.0.0.1:'+str(json.loads(process.stdout.readline())['port']);checks=[]
 def check(name,condition):
  assert condition,name
  checks.append(name);print('PASS',name,flush=True)
 try:
  with sync_playwright() as p:
   browser=p.chromium.launch(headless=True);page=browser.new_page();errors=[];requests=[];held=[]
   page.on('pageerror',lambda e:errors.append(str(e)))
   page.on('request',lambda r:requests.append(r.url))
   page.goto(origin+'/login');page.get_by_label('Your invitation code').fill('offline-interactive-code-'*3)
   for suffix in ['/api/config','/api/harness/config','/api/manual/config','/api/manual/sessions']:
    page.route('**'+suffix,lambda route:held.append(route))
   page.get_by_role('button',name='Open demo').click()
   frame=page.frame_locator('#site-frames iframe');frame.get_by_role('heading',name='Reserve a study room').wait_for()
   check('Campus renders while model/registry/manual APIs remain held',len(held)>=3)
   frame.get_by_role('link',name='Shop',exact=True).click();frame.get_by_role('heading',name='Ready for your next idea.').wait_for()
   check('Manual page navigation works before backend readiness',True)
   check('Explore sends no trace listing or job-history requests',not any('/api/traces' in u or '/api/harness/jobs' in u for u in requests))
   for route in held:route.continue_()
   page.unroute_all(behavior='wait');expect(page.locator('#site-count')).to_have_text('6');expect(page.locator('#question')).to_be_enabled()
   check('Readiness enables Ask without replacing the manually navigated page','/shop' in page.locator('#site-frames iframe').evaluate('f=>f.contentWindow.location.pathname'))
   pages=[];pending=[];first_id=str(uuid4());second_id=str(uuid4())
   def history(route):pages.append(route.request.url);pending.append(route)
   page.route(re.compile(r'.*/api/traces\?.*'),history);page.locator('#all-replays-link').click();expect(page.locator('#global-history-status')).to_contain_text('Loading history')
   page.locator('.site-choice[data-site=campus]').click();frame.get_by_role('heading',name='Ready for your next idea.').wait_for()
   check('Blocked history can be left without blocking interactive site',len(pending)==1)
   item=lambda id,goal:{'id':id,'goal':goal,'status':'complete','created_at':'2026-01-01T00:00:00Z','site_id':'campus','collection':'demo','interaction_kind':'ask','runtime':'test','evaluation':None}
   pending.pop(0).fulfill(json={'traces':[item(first_id,'First page')],'has_more':True,'cursor':'opaque-next'})
   page.locator('#all-replays-link').click();page.locator('#global-kind').select_option('ask');expect(page.locator('#global-rows tr')).to_have_count(1)
   check('One page only; revisiting history does not fetch all pages',len(pages)==1)
   expect(page.locator('#global-history-status')).to_contain_text('loaded history only')
   page.locator('#global-history-more').click();expect(page.locator('#global-history-more')).to_be_disabled()
   check('Next page uses exact opaque cursor',len(pending)==1 and 'cursor=opaque-next' in pages[-1])
   pending.pop(0).fulfill(status=503,json={'error':'Offline page failure'});expect(page.locator('#global-history-status')).to_contain_text('Offline page failure')
   expect(page.locator('#global-rows tr')).to_have_count(1);check('Page failure preserves loaded history without automatic retry',len(pages)==2)
   page.locator('#global-history-more').click();expect(page.locator('#global-history-more')).to_be_disabled()
   pending.pop(0).fulfill(json={'traces':[item(second_id,'Second page')],'has_more':False,'cursor':None})
   expect(page.locator('#global-rows tr')).to_have_count(2);expect(page.locator('#global-history-more')).to_be_hidden()
   check('Explicit retry appends one page without duplicates',len(pages)==3)
   # A deep link outside the loaded page is fetched directly, without scanning history.
   third_id=str(uuid4());raw={**item(third_id,'Direct link'),'steps':[],'owner':'tester','mode':'assist'}
   page.route('**/api/traces/'+third_id,lambda r:r.fulfill(json=raw))
   page.unroute(re.compile(r'.*/api/traces\?.*'));lists=[]
   def empty_history(r):lists.append(r.request.url);r.fulfill(json={'traces':[],'has_more':False,'cursor':None})
   page.route(re.compile(r'.*/api/traces\?.*'),empty_history);page.goto(origin+'/workspace/replays?run=d:'+third_id)
   expect(page.locator('#review-title')).to_have_text('Direct link');expect(page.locator('#browser-trace-json')).to_contain_text(third_id)
   check('Deep link opens a trace outside loaded pages without scanning',len(lists)==1)
   check('No browser script errors',not errors)
   page.screenshot(path=str(output/'deep-link.png'));browser.close()
  (output/'report.json').write_text(json.dumps({'passed':True,'checks':checks,'paid_calls':0,'sources':{n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in ['deploy/daylight/client/workspace.js','deploy/daylight/client/workspace.html','scripts/check_history_loading.py']}},indent=2))
  print(str(output/'report.json'))
 finally:process.terminate();process.wait(timeout=10)
if __name__=='__main__':main()
