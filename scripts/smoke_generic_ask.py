"""Actual invited UI and BrowserGym; scripted model transport, zero paid calls."""
import argparse,gzip,hashlib,io,json,os,subprocess,zipfile
from pathlib import Path
from playwright.sync_api import sync_playwright,expect
from smoke_generic_browsing_live import TARGETS
ROOT=Path(__file__).resolve().parents[1]
def main():
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--webarena',action='store_true');a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
 env={**os.environ,'SHARED_TEST_OUTPUT':str(a.output.resolve()/'service'),'SHARED_TEST_BROWSE':'1','PLAYWRIGHT_BROWSERS_PATH':str(Path.home()/'.cache/ms-playwright'),'LD_LIBRARY_PATH':str(ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu')}
 if a.webarena:
  for line in (ROOT/'.local/browse-pool/control.env').read_text().splitlines():
   if '=' in line and not line.startswith('#'):
    k,v=line.split('=',1);env[k]=v.strip().strip('\"\'')
 os.environ['LD_LIBRARY_PATH']=env['LD_LIBRARY_PATH'];log=(a.output/'server.log').open('w');server=subprocess.Popen(['node','tests/shared-browser-server.mjs'],cwd=ROOT/'deploy/daylight',env=env,stdout=subprocess.PIPE,stderr=log,text=True)
 checks=[];cases=[]
 def check(name,value):
  assert value,name
  checks.append(name)
 try:
  origin='http://127.0.0.1:'+str(json.loads(server.stdout.readline())['port'])
  with sync_playwright() as pw:
   browser=pw.chromium.launch();page=browser.new_page(viewport={'width':1500,'height':1100});page.set_default_timeout(40000);expect.set_options(timeout=40000);errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
   page.goto(origin);page.get_by_label('Your invitation code').fill('offline-shared-browser-code-'*3);page.get_by_role('button',name='Open demo').click()
   def row():return page.request.get(origin+'/api/manual/sessions').json()['sessions'][0]
   def settled(n):
    for _ in range(160):
     r=row()
     if len(r.get('asks',[]))>=n and r['controller']=='human':return r
     page.wait_for_timeout(200)
    raise AssertionError('Ask did not settle')
   def ask(goal):page.locator('#remote-question').fill(goal);page.locator('#remote-send').click()
   for site,label in TARGETS.items():
    if site.startswith('webarena-')!=a.webarena:continue
    page.locator(f'.site-choice[data-site="{site}"]').click();expect(page.locator('#manual-task')).to_have_value('browse.'+site);page.locator('#manual-open').click();expect(page.locator('#remote-send')).to_be_enabled();initial=row();sid=initial['id']
    check(site+' advertises Ask without reference goal',initial['ask_enabled'] and initial['browse_only'] and initial['reference_goal'] is None)
    page.locator('#manual-key').select_option('Tab') if page.locator('#manual-key').count() else None
    # Native manual action before Ask must remain in the same trace.
    page.locator('#manual-scroll-down').click();expect(page.locator('#manual-surface')).to_have_attribute('aria-disabled','false');before=row();check(site+' human action before Ask',before['action_count']==1)
    ask('Test click: '+label);done=settled(1)
    check(site+' agent clicked once and answered in same browser',done['id']==sid and done['asks'][0]['status']=='complete' and done['action_count']==2 and not done['last_error'])
    check(site+' controller and ungraded outcome preserved',done['controller']=='human' and done['evaluation'] is None and done['reference_evaluation'] is None)
    expect(page.locator('#remote-conversation')).to_contain_text('same browser')
    if site in ('tricky-music','webarena-forum'):
     ask('Slow answer please');expect(page.locator('#remote-stop')).to_be_enabled();page.locator('#remote-stop').click();stopped=settled(2);check(site+' interruption never dispatches late action',stopped['asks'][-1]['status']=='interrupted' and stopped['action_count']==2)
     ask('Malformed answer please');bad=settled(3);check(site+' parse error retains session without replay',bad['asks'][-1]['status']=='error' and bad['status']=='ready' and bad['action_count']==2)
     ask('What is visible now?');again=settled(4);check(site+' followup after stop/error',again['asks'][-1]['status']=='complete' and again['id']==sid)
    page.locator('#manual-reload').click();expect(page.locator('#manual-surface')).to_have_attribute('aria-disabled','false');check(site+' human resumes after agent',row()['action_count']==3)
    page.locator('#manual-close').click();expect(page.locator('#manual-status')).to_contain_text('finished');closed=row();check(site+' closes without fabricated grading',closed['trace_ready'] and closed['reference_evaluation'] is None and closed['evaluation'] is None)
    response=page.request.get(origin+'/api/manual/sessions/'+sid+'/trace');assert response.ok;raw=response.body();(a.output/(site+'.zip')).write_bytes(raw)
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
     ep=json.loads(z.read(next(n for n in z.namelist() if n.endswith('/episode.json'))));steps=[json.loads(line) for line in z.read(next(n for n in z.namelist() if n.endswith('/steps.jsonl'))).decode().splitlines()]
     check(site+' trace records mixed actors and all requests',ep['driver']=='shared-browser' and ep['model_attempt_count']>=2 and {s['actor'] for s in steps}=={'agent','scripted_validation'} and all(s['messages'] and s['model_request'] and s['model_response'] for s in steps if s['actor']=='agent'))
     check(site+' no reference grade or launch credentials exported',ep['evaluation'] is None and not any('browser-launch' in n for n in z.namelist()) and all(b'fake-never-sent-externally' not in z.read(n) for n in z.namelist()))
    cases.append({'site_id':site,'session_id':sid,'action_count':closed['action_count'],'asks':closed['asks'],'zip_sha256':hashlib.sha256(raw).hexdigest()})
   check('No UI errors',not errors);browser.close()
  sources=['scripts/manual_environment.py','scripts/shared_browser_policy.py','deploy/daylight/lib/manual.mjs','deploy/daylight/client/workspace.js','deploy/daylight/tests/shared-browser-server.mjs']
  (a.output/'report.json').write_text(json.dumps({'passed':True,'checks':checks,'cases':cases,'paid_calls':0,'real_model_calls':0,'mock_requests':len((a.output/'service/requests.jsonl').read_text().splitlines()),'source_sha256':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in sources}},indent=2));print(json.dumps({'passed':True,'checks':len(checks),'report':str(a.output/'report.json')}))
 finally:server.terminate();server.wait(timeout=15);log.close()
if __name__=='__main__':main()
