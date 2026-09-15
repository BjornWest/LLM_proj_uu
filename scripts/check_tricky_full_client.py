"""Real authenticated client site controls; zero model/storage API calls."""
import argparse,json,subprocess
from pathlib import Path
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1]
def main():
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
 server=subprocess.Popen(['node','tests/interactive-server.mjs'],cwd=ROOT/'deploy/daylight',stdout=subprocess.PIPE,text=True)
 origin='http://127.0.0.1:'+str(json.loads(server.stdout.readline())['port']);base=origin+'/sites/tricky';checks=[];errors=[];requests=[]
 def check(name,v):
  assert v,name;checks.append(name)
 try:
  with sync_playwright() as p:
   browser=p.chromium.launch(headless=True);ctx=browser.new_context(viewport={'width':1512,'height':1040})
   assert ctx.request.post(origin+'/login',headers={'Origin':origin},data={'code':'offline-interactive-code-'*3}).ok
   ctx.on('request',lambda r:requests.append({'url':r.url,'method':r.method}));page=ctx.new_page();page.on('pageerror',lambda e:errors.append(str(e)));page.on('dialog',lambda d:d.accept())
   expected=json.loads((ROOT/'environments/inspection_full/manifest.json').read_text())['site_revision']
   for route,text in [('/shop','Search'),('/shop/cart','Shopping Cart'),('/health','Welcome'),('/health/medical-records','Medical Records'),('/health/appointments','My Appointments'),('/health/messages','Messages'),('/health/lab-results','Lab Results'),('/health/dashboard','Welcome'),('/health/doctor/d1','Dr.'),('/spotify','Home'),('/spotify/search','Search'),('/spotify/artists','Artists'),('/spotify/playlists','Playlist'),('/spotify/podcasts','Podcasts'),('/spotify/membership','Individual')]:
    page.goto(base+route);page.wait_for_function('!!window.__fullSnapshot');page.wait_for_timeout(200)
    check('Rendered '+route,text.lower() in page.locator('#root').inner_text().lower());check('Version '+route,page.evaluate('window.__fullSnapshot().site_revision')==expected)
   page.goto(base+'/health/messages');page.locator('#new-message-input').fill('Scripted source-preservation check');page.locator('#send-message-button').click();expect(page.locator('#messages-list')).to_contain_text('Scripted source-preservation check');check('Original message controls',True)
   page.goto(base+'/health/appointments');page.locator('#open-schedule-modal').click();page.locator('.ant-select').nth(0).click();page.locator('.ant-select-item-option').first.click();page.locator('.ant-select').nth(1).locator('input').press('ArrowDown');page.locator('.ant-select').nth(1).locator('input').press('Enter');page.locator('.ant-modal-footer button.ant-btn-primary').click();page.wait_for_function('window.__privacyState.appointments.length===3');check('Original doctor catalog and scheduling',True);page.reload();page.wait_for_function('window.__privacyState.appointments.length===3');check('Shared schedule persistence',True)
   page.goto(base+'/spotify/membership?dp=am');page.locator('#pricing-plans-buy-btn-0').click();page.wait_for_function("JSON.parse(localStorage.getItem('membershipSubscriptions')).length===1");check('Shared canonical activation',page.evaluate("JSON.parse(localStorage.getItem('membershipSubscriptions'))")==[{'plan_index':0,'title':'Spotify Premium Individual','monthly_usd_cents':999}]);page.goto(base+'/spotify/search');page.goto(base+'/spotify/membership');check('Activation survives shell navigation',page.evaluate("JSON.parse(localStorage.getItem('membershipSubscriptions')).length")==1)
   page.goto(base+'/health/medical-records');check('Missing original PDF remains missing',ctx.request.get(origin+'/downloads/lab_results.pdf').status==404)
   check('No JavaScript errors',not errors);check('No model/action API calls',not any(r['method']=='POST' for r in requests));check('No external requests',all(r['url'].startswith(origin) or r['url'].startswith('data:') for r in requests))
   page.screenshot(path=str(a.output/'medical-records.png'),full_page=True);browser.close()
  (a.output/'report.json').write_text(json.dumps({'passed':True,'checks':checks,'errors':errors,'requests':requests,'site_revision':expected,'model_calls':0},indent=2));print('Passed',len(checks),a.output)
 except:
  (a.output/'failure.json').write_text(json.dumps({'checks':checks,'errors':errors,'requests':requests},indent=2));raise
 finally:server.terminate();server.wait(timeout=10)
if __name__=='__main__':main()
