"""Real UI / service / BrowserGym with fake model responses. Never spends money."""
import os,json,subprocess,hashlib,zipfile,io,time,gzip
from pathlib import Path
from uuid import uuid4
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1]
out=ROOT/'.local/shared-browser'/('acceptance-'+uuid4().hex[:8]);out.mkdir(parents=True)
env={**os.environ,'SHARED_TEST_OUTPUT':str(out/'service'),'PLAYWRIGHT_BROWSERS_PATH':str(Path.home()/'.cache/ms-playwright'),'LD_LIBRARY_PATH':str(ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu')}
os.environ['LD_LIBRARY_PATH']=env['LD_LIBRARY_PATH']
log=(out/'server.log').open('w');server=subprocess.Popen(['node','tests/shared-browser-server.mjs'],cwd=ROOT/'deploy/daylight',env=env,stdout=subprocess.PIPE,stderr=log,text=True)
checks=[];errors=[]
def check(name,value):
 assert value,name
 checks.append(name);print('PASS',name,flush=True)
try:
 origin='http://127.0.0.1:'+str(json.loads(server.stdout.readline())['port'])
 with sync_playwright() as pw:
  browser=pw.chromium.launch();page=browser.new_page(viewport={'width':1500,'height':1100});page.set_default_timeout(45000);expect.set_options(timeout=45000)
  page.on('pageerror',lambda e:errors.append(str(e)))
  page.goto(origin);page.get_by_label('Your invitation code').fill('offline-shared-browser-code-'*3);page.get_by_role('button',name='Open demo').click()
  page.locator('.site-choice[data-site=tricky-music]').click();page.locator('#manual-task').select_option('tricky-p11-clean');page.locator('#manual-open').click();expect(page.locator('#manual-surface')).to_have_attribute('aria-disabled','false')
  def session():return page.request.get(origin+'/api/manual/sessions').json()['sessions'][0]
  initial=session();sid=initial['id'];check('Opened real browser with Ask enabled',page.locator('#remote-send').is_enabled())
  def ask(goal):
   page.locator('#remote-question').fill(goal);page.locator('#remote-send').click()
  def settled(turns):
   for _ in range(100):
    s=session()
    if len(s.get('asks',[]))>=turns and s['controller']=='human':return s
    page.wait_for_timeout(200)
   raise AssertionError('Ask did not finish')
  ask('What is visible?');first=settled(1);check('Answer leaves exact session/browser and actions intact',first['id']==sid and first['action_count']==0 and first['asks'][0]['status']=='complete')
  expect(page.locator('#remote-conversation')).to_contain_text('same browser')
  page.reload();expect(page.locator('#remote-conversation')).to_contain_text('same browser');check('Conversation survives browser reload without new session',session()['id']==sid)
  # Human navigation on this exact native browser, then agent follow-up.
  raw=json.loads(gzip.decompress(max((out/'service').rglob('*.json.gz'),key=lambda p:p.stat().st_mtime).read_bytes()))
  home=next(n for n in raw['axtree_object']['nodes'] if n.get('name',{}).get('value')=='Navigate to Home' and n.get('role',{}).get('value')=='link')
  bbox=raw['extra_element_properties'][home['browsergym_id']]['bbox'];native=page.locator('#manual-frame').bounding_box();s=session();tx=(bbox[0]+bbox[2]/2)*native['width']/s['frame']['width'];ty=(bbox[1]+bbox[3]/2)*native['height']/s['frame']['height']
  page.locator('#manual-frame').click(position={'x':tx,'y':ty});expect(page.locator('#manual-surface')).to_have_attribute('aria-disabled','false');check('Human navigated within same browser',session()['action_count']==1)
  ask('Show subscriptions and explain the options without buying');second=settled(2);check('Agent navigates from human-selected page without reset',second['id']==sid and second['action_count']==2 and second['asks'][-1]['status']=='complete')
  ask('Slow answer please');expect(page.locator('#remote-stop')).to_be_enabled();page.locator('#remote-stop').click();stopped=settled(3);check('Late model response discarded after Stop',stopped['asks'][-1]['status']=='interrupted' and stopped['action_count']==2)
  expect(page.locator('#manual-surface')).to_have_attribute('aria-disabled','false')
  ask('Malformed answer please');bad=settled(4);check('Invalid output retained without executing or closing browser',bad['asks'][-1]['status']=='error' and bad['status']=='ready' and bad['action_count']==2)
  ask('What is visible now?');final=settled(5);check('Follow-up succeeds after interruption and parse failure',final['asks'][-1]['status']=='complete' and final['id']==sid)
  page.locator('#manual-close').click();expect(page.locator('#manual-status')).to_contain_text('finished');closed=session()
  data=page.request.get(origin+'/api/manual/sessions/'+sid+'/trace').body();(out/'trace.zip').write_bytes(data)
  with zipfile.ZipFile(io.BytesIO(data)) as z:
   episode=json.loads(z.read(next(n for n in z.namelist() if n.endswith('/episode.json'))));steps=[json.loads(line) for line in z.read(next(n for n in z.namelist() if n.endswith('/steps.jsonl'))).decode().splitlines()]
   asks=[json.loads(z.read(n)) for n in z.namelist() if '/ask-' in n and n.endswith('.json')]
   check('Complete archive includes all five asks and both actor types',len(asks)==5 and {s['actor'] for s in steps}=={'agent','scripted_validation'})
   check('Agent action has exact delivered messages/request/raw response',all(s['messages'] and s['model_request'] and s['model_response'] for s in steps if s['actor']=='agent'))
   check('Arbitrary asks remain ungraded with separate reference result',episode['evaluation'] is None and closed['evaluation'] is None and closed['reference_evaluation'] is not None)
   check('Archive reports model attempts and mixed session honestly',episode['driver']=='shared-browser' and episode['model_attempt_count']>=5)
   check('No auth credentials saved in archive',all(b'fake-never-sent-externally' not in z.read(n) for n in z.namelist()))
  check('No browser JavaScript errors',not errors);page.screenshot(path=str(out/'workspace.png'),full_page=True);browser.close()
 report={'passed':True,'checks':checks,'model_calls':0,'paid_calls':0,'mock_model_requests':len((out/'service/requests.jsonl').read_text().splitlines()),'trace_sha256':hashlib.sha256(data).hexdigest()};(out/'report.json').write_text(json.dumps(report,indent=2));print(out/'report.json')
finally:
 server.terminate()
 try:server.wait(timeout=10)
 except subprocess.TimeoutExpired:server.kill()
 log.close()
