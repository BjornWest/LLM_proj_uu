"""Real workspace/API/BrowserGym browsing of complete sites; no model calls.

Test selectors come from saved AX boxes, never from hidden expected task answers.
Requires backend-owned WebArena pool when --webarena is selected.
"""
import argparse,gzip,hashlib,json,os,subprocess,zipfile,io
from pathlib import Path
from uuid import uuid4
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1]
TARGETS={'tricky-shop':'Add Oral-B Precision Clean Toothbrush to cart','tricky-health':'Medical Records','tricky-news':'Read more about Crypto Market Surges Amid Regulatory Shifts','tricky-music':'Navigate to Artists','webarena-shopping':'My Account','webarena-forum':'Forums'}

def main():
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--webarena',action='store_true');p.add_argument('--origin',help='Explicit deployed origin; uses local bjorn invitation');p.add_argument('--container');a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
 if a.container:os.environ['MANUAL_TEST_CONTAINER']=a.container
 env={**os.environ,'MANUAL_TEST_OUTPUT':str(a.output.resolve()/'service'),'MANUAL_TEST_BROWSE':'1','MANUAL_TEST_PACKAGE':str(ROOT/'.local/environment-packages/portable-full-v2'),'PLAYWRIGHT_BROWSERS_PATH':str(Path.home()/'.cache/ms-playwright'),'LD_LIBRARY_PATH':str(ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu')}
 os.environ['LD_LIBRARY_PATH']=env['LD_LIBRARY_PATH'];log=(a.output/'server.log').open('w')
 server=None if a.origin else subprocess.Popen(['node','tests/manual-server.mjs'],cwd=ROOT/'deploy/daylight',env=env,stdout=subprocess.PIPE,stderr=log,text=True)
 checks=[];cases=[]
 def check(label,ok):
  assert ok,label
  checks.append(label)
 try:
  origin=a.origin.rstrip('/') if a.origin else 'http://127.0.0.1:'+str(json.loads(server.stdout.readline())['port'])
  invitation=json.loads((ROOT/'.local/vercel-demo/invitation-codes.json').read_text())['bjorn'] if a.origin else 'offline-interactive-code-'*3
  code=invitation if isinstance(invitation,str) else invitation['code']
  with sync_playwright() as pw:
   browser=pw.chromium.launch();page=browser.new_page(viewport={'width':1500,'height':1100});expect.set_options(timeout=35000);page.set_default_timeout(35000)
   errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
   page.goto(origin);page.get_by_label('Your invitation code').fill(code);page.get_by_role('button',name='Open demo').click();expect(page.locator('#site-count')).to_have_text('9')
   def get(url):
    r=page.request.get(origin+url);assert r.ok,(url,r.status,r.text()[:100]);return r.json()
   def row():return get('/api/manual/sessions')['sessions'][0]
   def obs(session):
    if os.environ.get('MANUAL_TEST_CONTAINER'):
     code="from pathlib import Path;import sys;root=Path('/manual')/sys.argv[1];p=max(root.rglob('observation-*.json.gz'),key=lambda p:p.stat().st_mtime_ns);sys.stdout.buffer.write(p.read_bytes())"
     return json.loads(gzip.decompress(subprocess.check_output(['docker','exec',os.environ['MANUAL_TEST_CONTAINER'],'python','-c',code,session['id']])))
    file=max((a.output/'service/sessions'/session['id']).rglob('observation-*.json.gz'),key=lambda p:p.stat().st_mtime_ns)
    return json.loads(gzip.decompress(file.read_bytes()))
   for site,label in TARGETS.items():
    if site.startswith('webarena-')!=a.webarena:continue
    page.locator(f'.site-choice[data-site="{site}"]').click()
    expect(page.locator('#manual-task')).to_have_value('browse.'+site)
    page.locator('#manual-open').click();expect(page.locator('#manual-surface')).to_have_attribute('aria-disabled','false');before=row()
    check(site+' opens complete ungraded browse session',before['browse_only'] and before['ask_enabled'] is False and before['reference_goal'] is None and before['evaluation'] is None)
    check(site+' Ask is disabled',page.locator('#remote-send').is_disabled())
    observation=obs(before);nodes=observation['axtree_object']['nodes'];target=next(n for n in nodes if n.get('name',{}).get('value')==label and n.get('browsergym_id'))
    box=observation['extra_element_properties'][target['browsergym_id']]['bbox'];x,y,w,h=box
    for _ in range(4):
     if 0<y+h/2<before['frame']['height']:break
     page.locator('#manual-scroll-down').click();expect(page.locator('#manual-surface')).to_have_attribute('aria-disabled','false');before=row();observation=obs(before)
     target=next(n for n in observation['axtree_object']['nodes'] if n.get('name',{}).get('value')==label and n.get('browsergym_id'));box=observation['extra_element_properties'][target['browsergym_id']]['bbox'];x,y,w,h=box
    image=page.locator('#manual-frame');visible=image.bounding_box()
    assert 0<x+w/2<before['frame']['width'] and 0<y+h/2<before['frame']['height'],(site,box)
    image.click(position={'x':(x+w/2)*visible['width']/before['frame']['width'],'y':(y+h/2)*visible['height']/before['frame']['height']})
    expect(page.locator('#manual-surface')).to_have_attribute('aria-disabled','false');clicked=row()
    check(site+' native click executes once without errors',clicked['action_count']==before['action_count']+1 and not clicked['last_error'])
    for action in ['back','forward','reload']:
     page.locator('#manual-'+action).click();expect(page.locator('#manual-surface')).to_have_attribute('aria-disabled','false');check(site+' '+action+' works',not row()['last_error'])
    page.locator('#manual-scroll-down').click();expect(page.locator('#manual-surface')).to_have_attribute('aria-disabled','false')
    page.locator('#manual-close').click();expect(page.locator('#manual-status')).to_contain_text('finished');closed=row()
    check(site+' closes with trace and no grade',closed['trace_ready'] and closed['evaluation'] is None and closed['reference_evaluation'] is None)
    if not a.origin:
     other=pw.request.new_context(base_url=origin,extra_http_headers={'Origin':origin})
     login=other.post('/login',form={'code':'offline-other-code-'*3});assert login.ok
     check(site+' owner isolation protects state/frame/trace',all(other.get(url).status==404 for url in ['/api/manual/sessions/'+closed['id'],closed['frame']['url'],'/api/manual/sessions/'+closed['id']+'/trace']))
     other.dispose()
    raw=page.request.get(origin+'/api/manual/sessions/'+closed['id']+'/trace');assert raw.ok;archive=raw.body();(a.output/(site+'.zip')).write_bytes(archive)
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
     names=z.namelist();check(site+' original ZIP contains no lease launch config',not any('browser-launch' in n for n in names));ep=json.loads(z.read(next(n for n in names if n.endswith('/episode.json'))));check(site+' zero model calls',ep['model_attempt_count']==0)
    cases.append({'site_id':site,'session':closed,'zip_sha256':hashlib.sha256(archive).hexdigest()})
   check('No browser script errors',not errors);browser.close()
  (a.output/'report.json').write_text(json.dumps({'passed':True,'checks':checks,'cases':cases,'model_calls':0,'origin':origin,'scope':'Actual workspace/API/BrowserGym and exclusive pool when selected','container':os.environ.get('MANUAL_TEST_CONTAINER')},indent=2));print(json.dumps({'passed':True,'checks':len(checks),'report':str(a.output/'report.json')}))
 finally:
  if server:server.terminate();server.wait(timeout=15)
  log.close()
if __name__=='__main__':main()
