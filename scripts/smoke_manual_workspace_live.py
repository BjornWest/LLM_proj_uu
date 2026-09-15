"""Actual workspace/API/BrowserGym manual integration; isolated scripted validation."""
import hashlib,io,json,os,subprocess,zipfile
from pathlib import Path
from uuid import uuid4
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1]

def main():
    expect.set_options(timeout=45000)
    out=ROOT/'.local/vercel-demo'/('manual-workspace-live-'+uuid4().hex[:8]);out.mkdir(parents=True)
    env={**os.environ,'PLAYWRIGHT_BROWSERS_PATH':str(Path.home()/'.cache/ms-playwright'),
         'LD_LIBRARY_PATH':str(ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu')+':'+os.environ.get('LD_LIBRARY_PATH',''),
         'MANUAL_TEST_OUTPUT':str(out/'service')}
    os.environ['LD_LIBRARY_PATH']=env['LD_LIBRARY_PATH']
    log=(out/'server.log').open('w');server=subprocess.Popen(['node','tests/manual-server.mjs'],cwd=ROOT/'deploy/daylight',env=env,stdout=subprocess.PIPE,stderr=log,text=True)
    checks=[];errors=[];requests=[];archives={};page=None
    def check(name,value):assert value,name;checks.append(name);print('PASS',name,flush=True)
    try:
      start=json.loads(server.stdout.readline());origin='http://127.0.0.1:'+str(start['port'])
      with sync_playwright() as p:
        browser=p.chromium.launch();page=browser.new_page(viewport={'width':1512,'height':1040});page.set_default_timeout(45000)
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.on('request',lambda r:requests.append({'method':r.method,'path':r.url.removeprefix(origin),'body':r.post_data_json if r.method=='POST' else None}))
        def get(path):
            response=page.request.get(origin+path);assert response.ok,(path,response.status,response.text()[:200]);return response.json()
        def session():return get('/api/manual/sessions')['sessions'][0]
        def settled():expect(page.locator('#manual-surface')).to_have_attribute('aria-disabled','false')
        page.goto(origin);page.get_by_label('Your invitation code').fill('offline-interactive-code-'*3);page.get_by_role('button',name='Open demo').click();expect(page.locator('#site-count')).to_have_text('6')
        settings=get('/api/manual/config');check('Actual manual service advertises fourteen configured external variants',settings['enabled'] and sum(len(s['tasks']) for s in settings['sites'])==14)
        page.locator('.site-choice[data-site=tricky-music]').click();page.locator('#manual-task').select_option('tricky-p11-clean');page.locator('#manual-open').click();settled();before=session()
        check('P11 clean opens real BrowserGym with exact setup and no model grade',before['task']=='tricky-p11-clean' and before['runtime']=='BrowserGym' and before['interaction_kind']=='manual' and before['evaluation'] is None and before['action_count']==0)
        initial=page.request.get(origin+before['frame']['url']);(out/'p11-before.png').write_bytes(initial.body())
        frame=page.locator('#manual-frame');box=frame.bounding_box();frame.click(position={'x':350*box['width']/before['frame']['width'],'y':339*box['height']/before['frame']['height']});settled();after=session()
        check('Scaled workspace click reaches the real P11 Buy control exactly once',after['action_count']==1 and after['last_action']['type']=='click' and abs(after['last_action']['x']-350)<=1 and abs(after['last_action']['y']-339)<=1)
        current=page.request.get(origin+after['frame']['url']);(out/'p11-after.png').write_bytes(current.body())
        check('Action returns a new authenticated browser frame',after['frame']['id']!=before['frame']['id'] and hashlib.sha256(initial.body()).digest()!=hashlib.sha256(current.body()).digest())
        count=len([r for r in requests if r['method']=='POST']);page.reload();settled();check('Reload recovers same real session without capture or repeated Buy',session()['id']==before['id'] and session()['action_count']==1 and len([r for r in requests if r['method']=='POST'])==count)
        page.locator('#manual-close').click();expect(page.locator('#manual-status')).to_contain_text('finished');closed=session()
        check('Closing preserves null user-goal evaluation and separate reference diagnostic',closed['evaluation'] is None and closed['trace_ready'] and closed['reference_evaluation'] is not None and closed['reference_evaluation']['injection_exposed'] is None and closed['reference_evaluation']['injection_avoided'] is None)
        page.locator('#research-tab').click();page.locator('#replay-kind').select_option('manual');expect(page.locator('#replay-rows tr')).to_have_count(1);page.locator('#replay-rows .replay-action').click();expect(page.locator('#manual-review')).to_be_visible()
        check('Workspace review labels manual execution Not graded with diagnostic-only reference',page.locator('#review-grade').inner_text()=='Not graded' and 'Manual exploration' in page.locator('#review-kind').text_content() and 'diagnostic only' in page.locator('#manual-review summary').text_content())
        download=page.request.get(origin+page.locator('#manual-trace-download').get_attribute('href'));assert download.ok;raw=download.body();(out/'p11-original.zip').write_bytes(raw)
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            assert z.testzip() is None
            name=next(n for n in z.namelist() if n.endswith('/episode.json'))
            episode=json.loads(z.read(name))
            check('Original ZIP records one real browser action and scripted validation, not model inference',episode['driver']=='scripted_validation' and episode['model'] is None and episode['evaluation'] is None and episode['browser_step_count']==1)
            (out/'p11-episode.json').write_text(json.dumps(episode,indent=2))
        archives[closed['id']]=hashlib.sha256(raw).hexdigest()
        page.screenshot(path=str(out/'p11-review.png'),full_page=True)
        other=p.request.new_context();login=other.post(origin+'/login',headers={'Origin':origin},data={'code':'offline-other-code-'*3});assert login.ok
        check('A different invitation cannot read the session frame or original ZIP',other.get(origin+'/api/manual/sessions/'+closed['id']).status==404 and other.get(origin+closed['frame']['url']).status==404 and other.get(origin+'/api/manual/sessions/'+closed['id']+'/trace').status==404);other.dispose()
        page.locator('.site-choice[data-site=tricky-shop]').click();page.locator('#manual-task').select_option('tricky-p07-clean');page.locator('#manual-open').click();settled();shop=session()
        check('A distinct site starts a new isolated browser after explicit close',shop['id']!=closed['id'] and shop['site_id']=='tricky-shop' and shop['action_count']==0 and shop['reference_goal']!=closed['reference_goal'])
        page.locator('#manual-scroll-down').click();settled();page.locator('#manual-key').select_option('Tab');page.locator('#manual-press').click();settled();shop=session()
        check('Shop accepts native scroll and keyboard actions through the workspace',shop['action_count']==2 and shop['last_action']=={'type':'press','key':'Tab'})
        page.locator('#manual-refresh').click();settled();refreshed=session();check('Explicit image refresh captures without another browser action',refreshed['action_count']==2 and refreshed['frame']['id']!=shop['frame']['id'])
        (out/'p07-frame.png').write_bytes(page.request.get(origin+refreshed['frame']['url']).body());page.screenshot(path=str(out/'p07-workspace.png'),full_page=True)
        page.locator('#manual-close').click();expect(page.locator('#manual-status')).to_contain_text('finished');page.locator('#all-replays-link').click();page.locator('#global-kind').select_option('manual');expect(page.locator('#global-rows tr')).to_have_count(2)
        check('Global history keeps both real manual sessions separate and ungraded',page.locator('#global-rows .grade').all_text_contents()==['Not graded','Not graded'])
        check('Manual workspace issued no model or agent-job requests',not any(r['method']=='POST' and r['path'] in ['/api/start','/api/step','/api/harness/jobs'] for r in requests))
        check('No browser JavaScript errors',not errors);browser.close()
      (out/'report.json').write_text(json.dumps({'passed':True,'checks':checks,'paid_calls':0,'model_calls':0,'execution':'Actual isolated BrowserGym package + manual driver + API + workspace; scripted validation only','archives_sha256':archives,'source_sha256':{name:hashlib.sha256((ROOT/'deploy/daylight/client'/name).read_bytes()).hexdigest() for name in ['workspace.html','workspace.css','workspace.js']}},indent=2))
      print(json.dumps({'checks':len(checks),'report':str(out/'report.json'),'paid_calls':0}))
    except BaseException:
      (out/'failure.json').write_text(json.dumps({'checks':checks,'errors':errors,'requests':requests},indent=2))
      if page:
        try:page.screenshot(path=str(out/'failure.png'),full_page=True)
        except Exception:pass
      print('Failure evidence:',out,flush=True);raise
    finally:server.terminate();server.wait(timeout=15);log.close()
if __name__=='__main__':main()
