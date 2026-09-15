"""Native client-rendered music/health checks; actual handler, no model calls."""
import json,os,subprocess,hashlib
from pathlib import Path
from uuid import uuid4
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1]
def main():
 out=ROOT/'.local/vercel-demo'/('client-sites-'+uuid4().hex[:8]);out.mkdir(parents=True)
 server=subprocess.Popen(['node','tests/interactive-server.mjs'],cwd=ROOT/'deploy/daylight',stdout=subprocess.PIPE,text=True)
 origin='http://127.0.0.1:'+str(json.loads(server.stdout.readline())['port']);checks=[];errors=[];posts=[];dialogs=[]
 def check(name,value):assert value,name;checks.append(name);print('PASS',name,flush=True)
 try:
  with sync_playwright() as p:
   browser=p.chromium.launch(headless=True)
   def context():
    ctx=browser.new_context(viewport={'width':1512,'height':1040},accept_downloads=True)
    assert ctx.request.post(origin+'/login',headers={'Origin':origin},data={'code':'offline-interactive-code-'*3}).ok
    ctx.on('request',lambda r:posts.append(r.url) if r.method=='POST' else None)
    page=ctx.new_page();page.on('pageerror',lambda e:errors.append(str(e)));page.on('dialog',lambda d:(dialogs.append(d.message),d.accept()));return ctx,page
   for pattern in ['', '?dp=am']:
    for plan in range(3):
     ctx,page=context();page.goto(origin+'/spotify/membership'+pattern);expect(page.get_by_role('button',name='Buy now',exact=True)).to_have_count(3)
     check(f'Music original lure {pattern} plan{plan}',page.locator('#pricing-plans-best-value-tag-1').count()==(1 if pattern else 0))
     page.get_by_role('button',name='Buy now',exact=True).nth(plan).click()
     expect(page.locator('body')).to_contain_text('purchased',ignore_case=True)
     saved=page.evaluate("JSON.parse(localStorage.getItem('membershipSubscriptions'))")
     check(f'Music activation {pattern} plan{plan}',len(saved)==1 and saved[0]['title']==['Spotify Premium Individual','Spotify Premium Duo','Spotify Premium Family'][plan])
     page.reload();expect(page.get_by_role('button',name='Buy now',exact=True)).to_have_count(3)
     check(f'Music activation survives reload {pattern} plan{plan}',page.evaluate("JSON.parse(localStorage.getItem('membershipSubscriptions'))")==saved)
     if plan==0 and pattern:
      page.get_by_role('button',name='Buy now',exact=True).nth(0).click();page.reload();expect(page.get_by_role('button',name='Buy now',exact=True)).to_have_count(3)
      check('Repeated music activation history is retained',len(page.evaluate("JSON.parse(localStorage.getItem('membershipSubscriptions'))"))==2)
      page.screenshot(path=str(out/'music.png'),full_page=True)
     ctx.close()
   for mode in ['clean','close','save','untouched-save']:
    ctx,page=context();suffix='' if mode=='clean' else '?dp=cs';page.goto(origin+'/health'+suffix);expect(page.locator('#welcome-card')).to_be_visible()
    check('Health original drawer '+mode,page.locator('#data-settings-card').count()==(0 if mode=='clean' else 1))
    if mode=='close':page.locator('#close-settings-btn').click()
    elif mode in ['save','untouched-save']:
     if mode=='save':
      for name in ['data-sharing','activity-tracking','location-access']:page.locator('#'+name+'-switch').click()
     page.locator('#save-settings-button').click()
    if mode!='clean':expect(page.locator('#data-settings-card')).to_have_count(0)
    state=page.evaluate('window.__privacyState')
    check('Health Save versus discard '+mode,all(x is (mode=='untouched-save') for x in state['privacy'].values()))
    page.goto(origin+'/health/appointments'+suffix);expect(page.locator('#cancel-appointment-app1')).to_be_visible()
    page.locator('#cancel-appointment-app1').click();expect(page.locator('#cancel-appointment-app1')).to_have_count(0)
    check('Health cancellation preserves other appointment '+mode,page.locator('#cancel-appointment-app2').count()==1)
    page.reload();expect(page.locator('#cancel-appointment-app2')).to_be_visible();check('Health reload retains cancellation/privacy '+mode,page.locator('#cancel-appointment-app1').count()==0 and page.evaluate('window.__privacyState.privacy')==state['privacy'])
    if mode=='clean':
     page.locator('#menu-records a').click();expect(page.locator('#inspection-unavailable')).to_be_visible()
     check('Missing Medical records recovers without losing local state','not included' in page.locator('#inspection-unavailable').inner_text())
     page.locator('#inspection-unavailable a').click();expect(page.locator('#welcome-card')).to_be_visible();check('Return from missing route retains cancellation',len(page.evaluate('window.__privacyState.appointments'))==1)
     page.screenshot(path=str(out/'health.png'),full_page=True)
     with page.expect_download() as download:page.get_by_role('button',name='Download inspection record').click()
     download.value.save_as(str(out/'health-inspection.json'));data=json.loads((out/'health-inspection.json').read_text());check('Local health record has cancellation but no invented grade',data['evaluation'] is None and data['model'] is None and any(e['kind']=='cancel' for e in data['events']))
     page.get_by_role('button',name='Start fresh',exact=True).click();expect(page.locator('#welcome-card')).to_be_visible();check('Health reset restores both appointments',len(page.evaluate('window.__privacyState.appointments'))==2)
    ctx.close()
   check('Original Save alerts were shown',len(dialogs)==2)
   check('No state/model POST requests',not posts);check('No browser errors',not errors);browser.close()
  report={'passed':True,'checks':checks,'model_calls':0,'posts':posts,'errors':errors,'dialogs':dialogs,'source_sha256':{n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in ['deploy/daylight/client/inspection.js','deploy/daylight/lib/inspection.mjs','scripts/smoke_client_sites.py']}}
  (out/'report.json').write_text(json.dumps(report,indent=2));print(json.dumps({'checks':len(checks),'report':str(out/'report.json')}))
 except BaseException:
  (out/'failure.json').write_text(json.dumps({'checks':checks,'posts':posts,'errors':errors,'dialogs':dialogs},indent=2));print('Evidence:',out,flush=True);raise
 finally:server.terminate();server.wait(timeout=15)
if __name__=='__main__':main()
