"""Actual production workspace + API handler with offline transport. No paid calls."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
from uuid import uuid4
from playwright.sync_api import sync_playwright, expect
ROOT=Path(__file__).resolve().parents[1]
def main():
    os.environ['LD_LIBRARY_PATH']=str(ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu')+':'+os.environ.get('LD_LIBRARY_PATH','')
    output=ROOT/'.local/vercel-demo'/('workspace-'+uuid4().hex[:8]);output.mkdir(parents=True)
    process=subprocess.Popen(['node','tests/workspace-server.mjs'],cwd=ROOT/'deploy/daylight',stdout=subprocess.PIPE,text=True)
    origin='http://127.0.0.1:'+str(json.loads(process.stdout.readline())['port']);checks=[]
    def check(name,value):
        assert value,name
        checks.append(name);print('PASS',name,flush=True)
    try:
      with sync_playwright() as p:
        browser=p.chromium.launch(headless=True);page=browser.new_page(viewport={'width':1512,'height':1040});errors=[];writes=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.on('request',lambda r:writes.append((r.url,r.post_data_json)) if r.method=='POST' and '/api/' in r.url else None)
        page.goto(origin);page.get_by_label('Your invitation code').fill('offline-interactive-code-'*3);page.get_by_role('button',name='Open demo').click()
        expect(page.locator('#question')).to_be_enabled();expect(page.locator('#site-count')).to_have_text('10')
        check('Authenticated root opens workspace with catalog sites',page.locator('#site-name').inner_text()=='Campus')
        check('No sample bookshop or sample runs in production','Fieldnotes' not in page.locator('body').inner_text())
        frame=page.frame_locator('#site-frames iframe');frame.get_by_role('link',name='Shop',exact=True).click();frame.get_by_role('heading',name='Ready for your next idea.').wait_for()
        check('Manual Campus navigation works before asking',True)
        locks=[];running_tools=[];saving_tools=[]
        def navigation(route):
            running_tools.append(page.locator('#conversation .tool-activity[data-state=running]').count()==1);route.continue_()
        page.route('**/world/*/booking',navigation)
        def receipts(route):
            if route.request.post_data_json['result']['description']!='Agent supplied an answer':
                saving_tools.append(page.locator('#conversation .tool-activity[data-state=saving]').count()==1)
            route.continue_()
        page.route('**/api/event',receipts)
        def capture(route):
            if page.locator('#conversation .tool-activity').count()==5:
                page.locator('#conversation').evaluate('log=>{log.scrollTop=0}')
            locks.append(page.evaluate("()=>document.querySelector('#site-frames iframe').inert && !document.querySelector('#question').disabled && !document.querySelector('#send-question').disabled && [...document.querySelectorAll('.site-choice')].every(b=>b.disabled)"));route.continue_()
        page.route('**/api/step',capture)
        page.locator('#question').fill('When are rooms available for three people in Ångström on Wednesday for 60 minutes?');page.locator('#send-question').click();expect(page.locator('#send-question')).to_have_attribute('data-running','true');expect(page.locator('#send-question')).to_have_attribute('data-running','false',timeout=30000)
        record=page.request.get(origin+page.locator('#conversation .record-link').last.get_attribute('href')).json()
        check('Ask uses real assist API and explicit site/activity metadata',record['mode']=='assist' and record['interaction_kind']=='ask' and record['site_id']=='campus')
        check('Ask navigation/filter actions and done receipts are all stored',record['status']=='complete' and record['steps'][0]['client_result']['page_after']['title'].startswith('Campus Rooms') and all(s['request'] and s['response_text'] and s['client_result'] for s in record['steps']))
        check('Informational Ask makes no booking and claims no independent grade',page.evaluate('window.demoWorld.state.bookings.length')==0 and record['evaluation'] is None)
        check('Conflicting manual controls remain locked throughout Ask',locks and all(locks))
        check('Reading earlier tool activity preserves chat scroll position on reply',page.locator('#conversation').evaluate('log=>log.scrollTop')<2)
        tools=page.locator('#conversation .tool-activity');check('Tool events appear inside chat between user and final reply',tools.count()==len(record['steps'])-1 and page.locator('#conversation').evaluate("log=>log.firstElementChild.classList.contains('user') && log.lastElementChild.classList.contains('assistant')"))
        check('Tool status distinguishes navigation, receipt persistence and applied action',running_tools and all(running_tools) and saving_tools and all(saving_tools) and page.locator('#conversation .tool-activity[data-state=applied]').count()==tools.count())
        tools.first.locator('summary').click();check('Expanded tool details retain exact pre-action target and action',json.loads(tools.first.locator('pre').text_content())==record['steps'][0]['action'] and 'Campus Supply' in tools.first.locator('.tool-activity-context').inner_text())
        check('Display tool entries stay out of model conversation messages',all(all(m['role'] in ['user','assistant'] for m in body.get('conversation',[])) for url,body in writes if url.endswith('/api/step')))
        page.unroute('**/world/*/booking');page.unroute('**/api/event');page.screenshot(path=str(output/'explore.png'),full_page=True)
        page.locator('#research-tab').click()
        expect(page.locator('#replay-rows tr[data-kind=ask]')).to_have_count(1)
        check('Per-site history includes actual Ask and excludes historical unknown sites',page.locator('#replay-rows tr[data-kind=unknown]').count()==0)
        page.locator('#task-cards [data-task=rooms]').click();goal=page.locator('#dialog-goal').inner_text();page.locator('#try-task').click()
        expect(page.locator('#review-view')).to_be_visible();viewer=page.frame_locator('#run-viewer');expect(viewer.locator('#run-summary')).to_have_text(goal)
        starts=[body for url,body in writes if url.endswith('/api/harness/jobs')]
        check('Try this task posts exact trusted goal once to actual broker',len(starts)==1 and starts[0]=={'task':'rooms','interaction_kind':'task','required_execution_mode':'live','goal':goal})
        check('Queued live run opens embedded existing renderer',viewer.locator('body').evaluate("b=>b.classList.contains('embedded')") and viewer.locator('#submit-run').is_disabled() and viewer.locator('.sidebar').is_hidden())
        page.screenshot(path=str(output/'queued.png'),full_page=True)
        page.locator('.site-choice[data-site=chaos]').click();expect(page.locator('#remote-explore')).to_be_visible();page.locator('#remote-tasks').click();page.locator('#task-cards button').first.click()
        expect(page.locator('#dialog-goal')).to_have_text('Resolved when the session starts');page.locator('#try-task').click();expect(page.locator('#review-view')).to_be_visible()
        starts=[body for url,body in writes if url.endswith('/api/harness/jobs')]
        check('Generated Chaos goal omitted, task revision and explicit activity sent',len(starts)==2 and 'goal' not in starts[-1] and starts[-1]['task_revision'] and starts[-1]['interaction_kind']=='task')
        expect(page.frame_locator('#run-viewer').locator('#run-summary')).to_have_text('Resolved when the session starts')
        check('Pending trusted goal remains pending in live review',True)
        page.locator('#all-replays-link').click();expect(page.locator('#global-view')).to_be_visible();unknown=page.locator('#global-rows tr[data-kind=unknown]');expect(unknown).to_have_count(1)
        check('Current registry never fills missing historical site, collection, condition or task name',unknown.get_attribute('data-site')=='unknown' and 'Collection not recorded' in unknown.inner_text() and 'Task ID: tricky-p07-injected' in unknown.inner_text() and 'injected' not in unknown.locator('.run-meta').inner_text())
        page.locator('#global-kind').select_option('ask');expect(page.locator('#global-rows tr')).to_have_count(1)
        page.locator('#global-rows .run-title').click();expect(page.locator('#browser-trace-json')).to_contain_text(record['id'])
        check('Global Ask filter opens preserved original JSON read-only',json.loads(page.locator('#browser-trace-json').text_content())==record)
        page.locator('#back-to-research').click();page.locator('#clear-filters').click();page.locator('#global-grade').select_option('unknown');expect(page.locator('#global-rows tr')).to_have_count(2)
        count=len(writes);page.locator('#global-rows .run-title').first.click();viewer=page.frame_locator('#run-viewer');expect(viewer.locator('#step-position')).to_have_text('1 / 2');viewer.locator('#next-step').click();expect(viewer.locator('#step-position')).to_have_text('2 / 2')
        check('Replay retains distinct identical action strings with no model/job writes',len(writes)==count and viewer.locator('#observation-title').inner_text().startswith('Step 2'))
        check('BrowserGym conversation retains both identical recorded actions without inventing model dialogue',page.locator('#trace-conversation .assistant .transcript-text').all_text_contents()==['click(126)','click(126)'] and 'Full model messages are not published' in page.locator('#browser-record-summary').inner_text())
        check('Null safe-success is Unknown despite other outcome flags',page.locator('#review-grade').inner_text()=='Unknown')
        page.screenshot(path=str(output/'replay.png'),full_page=True)
        page.locator('#all-replays-link').click();page.locator('#clear-filters').click();page.locator('#global-site').select_option('chaos');expect(page.locator('#global-rows tr')).to_have_count(1)
        check('Global site filter is independent from activity and grade',True)
        page.set_viewport_size({'width':390,'height':844});page.screenshot(path=str(output/'mobile.png'),full_page=True)
        check('Mobile layout has no document overflow',page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
        page.set_viewport_size({'width':1512,'height':1040});page.goto(origin+'/workspace?site=campus&view=research');page.locator('#task-cards button').first.wait_for()
        def rehearsal(route):
            response=route.fetch();value=response.json();value['worker']['mode']='rehearsal';route.fulfill(response=response,json=value)
        page.route('**/api/harness/config',rehearsal);page.reload();page.locator('#task-cards button').first.click();expect(page.locator('#try-task')).to_be_disabled();check('Rehearsal worker cannot silently satisfy real-agent launch',page.locator('#try-task').inner_text()=='Live worker required')
        page.unroute('**/api/harness/config');page.goto(origin+'/workspace')
        expect(page.locator('#question')).to_be_enabled()
        def failed_receipt(route):route.fulfill(status=503,json={'error':'Offline receipt failure'})
        page.route('**/api/event',failed_receipt);before=len(writes);page.locator('#question').fill('Find rooms');page.locator('#send-question').click();expect(page.locator('#send-question')).to_have_attribute('data-running','false',timeout=30000);expect(page.locator('#conversation')).to_contain_text('request stopped')
        check('Unsaved receipt is visibly distinct from an applied tool action',page.locator('#conversation .tool-activity[data-state=unrecorded]').count()==1 and page.locator('#conversation .tool-activity[data-state=applied]').count()==0)
        check('Failed receipt stops without automatic retry and releases controls',len([1 for url,_ in writes[before:] if url.endswith('/api/event')])==1 and not page.locator('#site-frames iframe').evaluate('f=>f.inert'))
        page.unroute('**/api/event')
        pages=[]
        def paginated(route):
            second='cursor=' in route.request.url;pages.append(second)
            item={'id':str(uuid4()),'interaction_kind':'ask','site_id':'campus','collection':'demo','goal':'Older request' if second else 'Newer request','status':'complete','created_at':'2026-01-01T00:00:00Z' if second else '2026-02-01T00:00:00Z','evaluation':None}
            route.fulfill(json={'traces':[item],'has_more':not second,'cursor':None if second else 'opaque-next'})
        page.route('**/api/traces?*',paginated);page.goto(origin+'/workspace/replays');page.locator('#global-kind').select_option('ask');expect(page.locator('#global-rows tr')).to_have_count(1)
        check('Global history loads one page and labels partial filters',pages==[False] and 'loaded history only' in page.locator('#global-history-status').inner_text())
        page.locator('#global-history-more').click();expect(page.locator('#global-rows tr')).to_have_count(2)
        check('Explicit Load more follows opaque pagination and sorts recorded timestamps',pages==[False,True] and 'Newer request' in page.locator('#global-rows tr').first.inner_text())
        page.unroute('**/api/traces?*');page.goto(origin+'/workspace?site=campus&view=research');page.locator('#task-cards button').first.click()
        rejected=[]
        def reject_task(route):rejected.append(route.request.post_data_json);route.fulfill(status=503,json={'error':'Offline broker unavailable'})
        page.route('**/api/harness/jobs',reject_task);page.locator('#try-task').click();expect(page.locator('#task-launch-status')).to_contain_text('No automatic retry')
        check('Failed launch stays visible without retry or fabricated run',len(rejected)==1 and page.locator('#task-dialog').is_visible() and page.locator('#try-task').is_enabled())
        page.unroute('**/api/harness/jobs');page.goto(origin+'/workspace');expect(page.locator('#question')).to_be_enabled()
        page.route('**/api/start',lambda route:route.fulfill(status=401,json={'error':'Session expired'}))
        page.locator('#question').fill('Find rooms');page.locator('#send-question').click();expect(page.locator('#workspace-notice')).to_contain_text('session expired');expect(page.locator('#send-question')).to_be_disabled()
        check('Expired invitation disables further model submissions',page.locator('#question').is_disabled())
        check('No browser JavaScript errors',not errors)
        browser.close()
      report={'passed':True,'checks':checks,'paid_calls':0,'policy':'Real production handler with offline model transport; no reliability claim','sources':{str(f.relative_to(ROOT)):hashlib.sha256(f.read_bytes()).hexdigest() for f in [ROOT/'deploy/daylight/client'/n for n in ['workspace.js','workspace.html','workspace.css','harness.js','harness.css','tool-activity.js','tool-activity.css']]}}
      (output/'report.json').write_text(json.dumps(report,indent=2));print(json.dumps({'checks':len(checks),'report':str(output/'report.json'),'paid_calls':0}))
    finally:process.terminate();process.wait(timeout=10)
if __name__=='__main__':main()
