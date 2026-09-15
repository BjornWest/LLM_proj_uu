"""Manual workspace UI contract checks with mocked remote sessions, no model calls."""
import json,os,subprocess,hashlib
from pathlib import Path
from uuid import uuid4
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1]
def main():
    os.environ['LD_LIBRARY_PATH']=str(ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu')+':'+os.environ.get('LD_LIBRARY_PATH','')
    out=ROOT/'.local/vercel-demo'/('manual-workspace-'+uuid4().hex[:8]);out.mkdir(parents=True)
    server=subprocess.Popen(['node','tests/workspace-server.mjs'],cwd=ROOT/'deploy/daylight',stdout=subprocess.PIPE,text=True)
    origin='http://127.0.0.1:'+str(json.loads(server.stdout.readline())['port']);checks=[]
    def check(name,value):assert value,name;checks.append(name);print('PASS',name,flush=True)
    try:
      with sync_playwright() as p:
        browser=p.chromium.launch();canvas=browser.new_page(viewport={'width':1000,'height':800});canvas.set_content('<body style="background:#e9eff5;font:24px system-ui;padding:60px"><h1>Offline remote frame fixture</h1><p>UI controls test only; no dataset browser is running.</p><input placeholder="Example field"><button>Example control</button></body>');png=canvas.screenshot();canvas.close()
        page=browser.new_page(viewport={'width':1512,'height':1040});errors=[];requests=[];sessions=[];fault=False;image_fault=False;serial=0;locks=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.on('request',lambda r:requests.append((r.method,r.url.removeprefix(origin),r.post_data_json if r.method=='POST' else None)))
        tasks=[{'id':'tricky-p11-clean','title':'Music membership','condition':'clean'},{'id':'tricky-p11-injected','title':'Music membership','condition':'injected'}]
        settings={'enabled':True,'sites':[{'site_id':'tricky-music','tasks':tasks,'default_task':tasks[0]['id']},{'site_id':'tricky-shop','tasks':[{'id':'tricky-p07-clean','title':'Shop','condition':'clean'}],'default_task':'tricky-p07-clean'}],'limits':{'max_sessions':2,'idle_seconds':300,'max_seconds':900,'max_actions':100}}
        settings['sites'].append({'site_id':'tricky-health','tasks':[{'id':'tricky-p10-clean','title':'Health account','condition':'clean'}],'default_task':'tricky-p10-clean'})
        def frame(session):
            nonlocal serial
            serial+=1;session['frame']={'id':str(serial),'width':1000,'height':800,'url':f'/api/manual/sessions/{session["id"]}/frame/{serial}','page_url':'http://remote-fixture.local/music'}
        def remote(route):
            nonlocal fault,image_fault
            url=route.request.url.removeprefix(origin);body=route.request.post_data_json if route.request.method=='POST' else None
            def reply(value,status=200):route.fulfill(status=status,content_type='application/json',body=json.dumps(value))
            if url=='/api/manual/config':return reply(settings)
            if url=='/api/manual/sessions' and body is None:return reply({'sessions':sessions})
            if '/frame/' in url:return route.fulfill(status=404 if image_fault else 200,content_type='image/png',body=b'' if image_fault else png)
            if url=='/api/manual/sessions':
                session={'id':str(uuid4()),'task':body['task'],'task_name':'Music membership','condition':'injected' if body['task'].endswith('injected') else 'clean','site_id':'tricky-music','collection':'trickyarena','interaction_kind':'manual','runtime':'BrowserGym','status':'ready','created_at':'2026-09-15T15:00:00Z','action_count':0,'reference_goal':'Find the recorded music membership setting','evaluation':None,'reference_evaluation':None,'trace_ready':False}
                frame(session);sessions.insert(0,session);return reply(session)
            session=next(s for s in sessions if s['id']==url.split('/')[4])
            if body is None:return reply(session)
            if url.endswith('/action'):
                locks.append(page.locator('#manual-surface').get_attribute('aria-disabled')=='true' and page.locator('#manual-close').is_disabled() and page.locator('#manual-send-text').is_disabled())
                page.locator('#manual-surface').dispatch_event('click',{'clientX':20,'clientY':20})
                if fault:fault=False;return reply({'error':'Stale frame rejected'},409)
                assert body['frame_id']==session['frame']['id'];session['last_action']=body['action'];session['action_count']+=1;frame(session)
            elif url.endswith('/observe'):frame(session)
            elif url.endswith('/close'):session.update(status='finished',trace_ready=True,reference_evaluation={'safe_success':True,'diagnostic':'fixture only'})
            return reply(session)
        page.route('**/api/manual/**',remote)
        page.goto(origin);page.get_by_label('Your invitation code').fill('offline-interactive-code-'*3);page.get_by_role('button',name='Open demo').click();expect(page.locator('#site-count')).to_have_text('6')
        page.locator('.site-choice[data-site=tricky-music]').click();expect(page.locator('#manual-open')).to_be_enabled()
        check('External exploration is explicitly human controlled and separate from Ask',page.locator('#ask-form').is_hidden() and 'no model is running' in page.locator('#remote-explore').inner_text() and 'fresh browser' in page.locator('.manual-agent-note').inner_text())
        check('Setup selector distinguishes clean and injected conditions',page.locator('#manual-task option').all_text_contents()==['Music membership · clean','Music membership · injected'])
        page.locator('#manual-task').select_option('tricky-p11-injected');page.locator('#manual-open').click();expect(page.locator('#manual-surface')).to_have_attribute('aria-disabled','false')
        check('Opening sends only exact selected task and uses authenticated frame route',[r[2] for r in requests if r[0]=='POST' and r[1]=='/api/manual/sessions']==[{'task':'tricky-p11-injected'}] and page.locator('#manual-frame').get_attribute('src').startswith('/api/manual/sessions/'))
        def actions():return [r[2] for r in requests if r[0]=='POST' and r[1].endswith('/action')]
        box=page.locator('#manual-frame').bounding_box();page.locator('#manual-frame').click(position={'x':box['width']*.25,'y':box['height']*.5});expect(page.locator('#manual-surface')).to_have_attribute('aria-disabled','false')
        check('Image click scales to remote frame dimensions within one pixel',actions()[-1]['action']['type']=='click' and abs(actions()[-1]['action']['x']-250)<=1 and abs(actions()[-1]['action']['y']-400)<=1)
        page.locator('#manual-surface').focus();page.locator('#manual-surface').press('ArrowDown');expect(page.locator('#manual-surface')).to_have_attribute('aria-disabled','false');check('Focused image sends a native select navigation key',actions()[-1]['action']=={'type':'press','key':'ArrowDown'})
        count=len(actions());page.locator('#manual-surface').press('Shift+Tab');check('Shift Tab exits remote keyboard controls without another action',len(actions())==count and page.locator('#manual-surface').evaluate('e=>document.activeElement!==e'))
        page.locator('#manual-text').fill('New message');page.locator('#manual-text').press('ArrowLeft');check('Keyboard elsewhere never drives remote page',len(actions())==count)
        page.locator('#manual-send-text').click();expect(page.locator('#manual-surface')).to_have_attribute('aria-disabled','false');check('Send text transmits exact typed string',actions()[-1]['action']=={'type':'type','text':'New message'})
        page.locator('#manual-scroll-down').click();expect(page.locator('#manual-surface')).to_have_attribute('aria-disabled','false');check('Scroll is one explicit bounded command',actions()[-1]['action']=={'type':'scroll','dx':0,'dy':500})
        check('Commands lock conflicting controls and use unique IDs with latest frame',all(locks) and len({r['request_id'] for r in actions()})==len(actions()) and len({r['frame_id'] for r in actions()})==len(actions()))
        page.locator('.site-choice[data-site=tricky-shop]').click();check('Another site cannot silently replace the current owner session',page.locator('#manual-open').is_disabled() and page.locator('#manual-other').is_visible())
        page.locator('#manual-other').click();expect(page.locator('#site-name')).to_have_text('Music membership')
        before=len([r for r in requests if r[0]=='POST']);page.reload();expect(page.locator('#manual-surface')).to_have_attribute('aria-disabled','false');check('Reload reconnects using metadata without new session or capture',len([r for r in requests if r[0]=='POST'])==before and page.locator('#manual-task').input_value()=='tricky-p11-injected')
        fault=True;before=len(actions());page.locator('#manual-scroll-up').click();expect(page.locator('#manual-error')).to_contain_text('Stale frame rejected');check('Uncertain command is not retried and blocks further actions',len(actions())==before+1 and page.locator('#manual-send-text').is_disabled())
        before=len([r for r in requests if r[0]=='POST']);page.locator('#manual-check').click();expect(page.locator('#manual-surface')).to_have_attribute('aria-disabled','false');check('Explicit recovery reads metadata without replaying command',len([r for r in requests if r[0]=='POST'])==before)
        image_fault=True;page.locator('#manual-refresh').click();expect(page.locator('#manual-error')).to_contain_text('image could not be loaded');check('Missing image cannot accept blind clicks',page.locator('#manual-surface').get_attribute('aria-disabled')=='true')
        image_fault=False;page.locator('#manual-refresh').click();expect(page.locator('#manual-surface')).to_have_attribute('aria-disabled','false')
        page.set_viewport_size({'width':390,'height':844});check('Remote controls fit mobile width',page.evaluate('document.documentElement.scrollWidth<=innerWidth'));page.screenshot(path=str(out/'mobile.png'),full_page=True);page.set_viewport_size({'width':1512,'height':1040})
        page.locator('#manual-close').click();expect(page.locator('#manual-status')).to_contain_text('finished');check('Closing leaves last frame read-only and enables a new isolated session',page.locator('#manual-open').is_enabled() and page.locator('#manual-surface').get_attribute('aria-disabled')=='true')
        page.locator('#research-tab').click();page.locator('#replay-kind').select_option('manual');expect(page.locator('#replay-rows tr')).to_have_count(1);check('Site history marks human session Manual and Not graded',page.locator('#replay-rows .run-kind').inner_text()=='Manual' and page.locator('#replay-rows .grade').inner_text()=='Not graded')
        page.locator('#all-replays-link').click();page.locator('#global-kind').select_option('manual');expect(page.locator('#global-rows tr')).to_have_count(1);before=len([r for r in requests if r[0]=='POST']);page.locator('#global-rows .replay-action').click();expect(page.locator('#manual-review')).to_be_visible()
        check('Read-only manual review separates reference diagnostics from agent grade',page.locator('#review-grade').inner_text()=='Not graded' and page.locator('#manual-trace-download').get_attribute('href').endswith('/trace') and 'true' in page.locator('#manual-reference-evaluation').text_content() and len([r for r in requests if r[0]=='POST'])==before)
        # Exact user-reported shape: a closed music image plus another live health session.
        page.locator('.site-choice[data-site=tricky-music]').click()
        expect(page.locator('#manual-frame-status')).to_contain_text('Saved screenshot')
        check('Closed music screenshot is explicitly read-only without a busy cursor',page.locator('#manual-surface').get_attribute('data-state')=='closed' and page.locator('#manual-surface').evaluate('e=>getComputedStyle(e).cursor')=='default')
        health={**sessions[0],'id':str(uuid4()),'site_id':'tricky-health','task':'tricky-p10-clean','task_name':'Health account','status':'ready','created_at':'2026-09-15T16:00:00Z','trace_ready':False,'reference_evaluation':None}
        frame(health);sessions.insert(0,health)
        before=len([r for r in requests if r[0]=='POST']);before_observe=len([r for r in requests if r[1].endswith('/observe')]);page.locator('#manual-check').click()
        expect(page.locator('#manual-close-other')).to_be_enabled()
        check('Status refresh visibly confirms its purpose without browser actions', 'Status checked at' in page.locator('#manual-checked').inner_text() and 'does not refresh the screenshot' in page.locator('#manual-checked').inner_text() and len([r for r in requests if r[0]=='POST'])==before and len([r for r in requests if r[1].endswith('/observe')])==before_observe)
        check('Blocked music launch identifies the active health session',page.locator('#manual-open').is_disabled() and page.locator('#manual-close').is_disabled() and 'Health account' in page.locator('#manual-status').inner_text() and 'Health account' in page.locator('#manual-close-other').inner_text())
        prior_closes=len([r for r in requests if r[0]=='POST' and r[1].endswith('/close')])
        page.locator('#manual-close-other').click();expect(page.locator('#manual-open')).to_be_enabled()
        closes=[r for r in requests if r[0]=='POST' and r[1].endswith('/close')]
        check('Explicit close-other targets health exactly once and releases the music slot',closes[-1][1]=='/api/manual/sessions/'+health['id']+'/close' and len(closes)==prior_closes+1 and health['status']=='finished')
        failed={**health,'id':str(uuid4()),'status':'error','created_at':'2026-09-15T17:00:00Z','error':'ValueError: Browser left supported health routes','last_error':'','trace_ready':True}
        frame(failed);sessions.insert(0,failed)
        page.locator('.site-choice[data-site=tricky-health]').click();page.locator('#manual-check').click();expect(page.locator('#manual-error')).to_contain_text('Medical records and profiles are not included')
        check('Unsupported health link explains fixture boundary and recovery',page.locator('#manual-open').is_enabled() and 'Appointments' in page.locator('#manual-scope').inner_text() and 'Open a new session' in page.locator('#manual-error').inner_text())
        check('Raw route error remains available without changing the saved verdict',page.locator('#manual-error-raw').text_content()==failed['error'] and failed['status']=='error' and page.locator('#manual-frame-status').inner_text().startswith('Saved screenshot'))
        page.screenshot(path=str(out/'health-boundary.png'),full_page=True)
        check('Manual exploration issued no inference or worker job writes',not any(r[0]=='POST' and r[1] in ['/api/start','/api/step','/api/harness/jobs'] for r in requests))
        check('No browser JavaScript errors',not errors);browser.close()
      (out/'report.json').write_text(json.dumps({'passed':True,'checks':checks,'paid_calls':0,'evidence':'Mock manual API and screenshot; validates frontend contract, not BrowserGym execution','source_sha256':{name:hashlib.sha256((ROOT/'deploy/daylight/client'/name).read_bytes()).hexdigest() for name in ['workspace.html','workspace.css','workspace.js']}},indent=2));print(json.dumps({'checks':len(checks),'report':str(out/'report.json')}))
    finally:server.terminate();server.wait(timeout=10)
if __name__=='__main__':main()
