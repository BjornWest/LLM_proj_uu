"""Read-only deployed workspace checks; never enqueue a job or call a model."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import httpx
from playwright.sync_api import sync_playwright, expect
ROOT=Path(__file__).resolve().parents[1]
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--origin',default='https://browseragent.vercel.app')
    parser.add_argument('--assets',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    expect.set_options(timeout=20000)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    invitation=json.loads((ROOT/'.local/vercel-demo/invitation-codes.json').read_text())['bjorn']
    code=invitation if isinstance(invitation,str) else invitation['code'];checks=[]
    def check(name,value):
        assert value,name
        checks.append(name);print('PASS',name,flush=True)
    with httpx.Client(base_url=args.origin,headers={'Origin':args.origin},trust_env=False,timeout=45) as client:
        check('Anonymous workspace requires invitation',client.get('/workspace').status_code==303)
        check('Invitation accepted',client.post('/login',data={'code':code}).status_code==303)
        paths={'workspace.html':'/','workspace.js':'/assets/workspace.js','workspace.css':'/assets/workspace.css','tool-activity.js':'/assets/tool-activity.js','tool-activity.css':'/assets/tool-activity.css','harness.html':'/harness','harness.js':'/assets/harness.js','harness.css':'/assets/harness.css','index.html':'/demo','dashboard.js':'/assets/dashboard.js','observation.js':'/assets/observation.js'}
        hashes={}
        for name,path in paths.items():
            response=client.get(path);check('Exact committed asset '+name,response.status_code==200 and response.content==(args.assets/name).read_bytes())
            hashes[name]=hashlib.sha256(response.content).hexdigest()
        config=client.get('/api/harness/config').json();before=client.get('/api/harness/jobs').json()['jobs']
        check('Fifteen reviewed tasks available on live worker',len(config['tasks'])==15 and all(t['available'] for t in config['tasks']) and config['worker']['mode']=='live' and config['worker']['online'])
        check('All tasks have explicit server site metadata',all(t.get('site_id') and t.get('collection') for t in config['tasks']))
        check('Generated goals remain null',all(t['goal'] is None for t in config['tasks'] if t.get('goal_mode')=='resolve_after_session_prepare'))
        agent_config=client.get('/api/config').json()
        check('Original browser agent configured',agent_config['live_available'])
        check('Chat interruption API advertised',agent_config['capabilities'].get('interrupt')=='/api/interrupt')
        os.environ['LD_LIBRARY_PATH']=str(ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu')+':'+os.environ.get('LD_LIBRARY_PATH','')
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True);context=browser.new_context(viewport={'width':1512,'height':1040})
            context.add_cookies([{'name':c.name,'value':c.value,'url':args.origin,'httpOnly':True,'sameSite':'Lax'} for c in client.cookies.jar])
            page=context.new_page();errors=[];writes=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.on('request',lambda r:writes.append({'method':r.method,'path':r.url.split(args.origin)[-1]}) if r.method not in ['GET','HEAD','OPTIONS'] else None)
            page.goto(args.origin);expect(page.locator('#question')).to_be_enabled();expect(page.locator('#site-count')).to_have_text('6')
            page.frame_locator('#site-frames iframe').get_by_role('heading',name='Reserve a study room').wait_for()
            page.screenshot(path=str(args.output/'explore.png'),full_page=True)
            page.locator('#question').fill('Unsent draft');page.locator('#enter-fullscreen').click();expect(page.locator('#exit-fullscreen')).to_be_visible();check('Full screen hides navigation and preserves the sidebar',page.locator('.app-header').is_hidden() and page.locator('#agent-sidebar').is_visible())
            page.screenshot(path=str(args.output/'full-screen.png'),full_page=True)
            page.frame_locator('#site-frames iframe').locator('#room-people').press('Escape');expect(page.locator('#exit-fullscreen')).to_be_hidden();check('Escape from the website exits full screen without losing draft',page.locator('#question').input_value()=='Unsent draft')
            page.locator('#question').fill('');page.locator('#question').press('Shift+Enter');check('Shift Enter inserts a newline without sending',page.locator('#question').input_value()=='\n');page.locator('#question').press('Enter');page.locator('#question').fill('')
            page.locator('#research-tab').click();page.locator('#task-cards button').first.click();expect(page.locator('#try-task')).to_be_enabled()
            check('Campus task shows exact trusted goal',page.locator('#dialog-goal').inner_text()==next(t['goal'] for t in config['tasks'] if t['id']=='rooms'))
            page.locator('.dialog-close').click();page.locator('.site-choice[data-site=chaos]').click();page.locator('#remote-tasks').click();expect(page.locator('#task-cards button')).to_have_count(7)
            page.locator('#task-cards button').first.click();expect(page.locator('#dialog-goal')).to_have_text('Resolved when the session starts');page.locator('.dialog-close').click()
            check('Chaos task review preserves pending objective without starting',True)
            page.locator('.site-choice[data-site=tricky-shop]').click();page.locator('#remote-tasks').click();expect(page.locator('#task-cards .condition')).to_have_count(2)
            check('Clean and injected task conditions visible',{'clean','injected'}==set(page.locator('#task-cards .condition').all_text_contents()))
            page.locator('#all-replays-link').click();expect(page.locator('#global-view')).to_be_visible();page.locator('#global-count').filter(has_text='conversations & runs').wait_for()
            page.screenshot(path=str(args.output/'library.png'),full_page=True)
            completed=next((j for j in before if j.get('steps') and j['status'] in ['finished','error','interrupted']),None)
            if completed:
                page.goto(args.origin+'/workspace/replays?run=h:'+completed['id']);viewer=page.frame_locator('#run-viewer');expect(viewer.locator('#run-detail')).to_be_visible()
                expect(viewer.locator('#follow-live')).to_be_hidden();check('Historical replay uses embedded recorded-evidence renderer',viewer.locator('#submit-run').is_disabled())
                page.screenshot(path=str(args.output/'replay.png'),full_page=True)
            check('No browser script errors',not errors);check('Browsing issued zero writes',not writes)
            browser.close()
        check('No new jobs created',[j['id'] for j in before]==[j['id'] for j in client.get('/api/harness/jobs').json()['jobs']])
        (args.output/'report.json').write_text(json.dumps({'passed':True,'origin':args.origin,'checks':checks,'asset_sha256':hashes,'paid_calls':0,'new_agent_jobs':0},indent=2))
        print(json.dumps({'checks':len(checks),'report':str(args.output/'report.json'),'paid_calls':0}))
if __name__=='__main__':main()
