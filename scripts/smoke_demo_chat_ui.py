"""Drive the real Chat/Tasks UI against offline scripted responses; never calls a model."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from uuid import uuid4
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]

def main():
    os.environ['LD_LIBRARY_PATH'] = str(ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu') + ':' + os.environ.get('LD_LIBRARY_PATH', '')
    output = ROOT/'.local/vercel-demo'/('chat-ui-'+uuid4().hex[:8])
    output.mkdir(parents=True)
    process = subprocess.Popen(['node','tests/interactive-server.mjs'], cwd=ROOT/'deploy/daylight', stdout=subprocess.PIPE, text=True)
    origin = 'http://127.0.0.1:'+str(json.loads(process.stdout.readline())['port'])
    checks=[]
    def check(name, condition):
        assert condition, name
        checks.append(name)
        print('PASS',name,flush=True)
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True)
            page=browser.new_page(viewport={'width':1440,'height':1000})
            errors=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto(origin)
            page.get_by_label('Your invitation code').fill('offline-interactive-code-'*3)
            page.get_by_role('button',name='Open demo').click()
            page.goto(origin+'/demo')
            expect(page.locator('.read-only-tag')).to_have_text('Interactive')
            expect(page.locator('#question')).to_be_enabled()
            check('Interactive chat labels replace read-only claims',page.locator('.read-only-tag').inner_text()=='Interactive' and 'Read-only' not in page.locator('#chat-panel').inner_text())
            def data(path):
                response=page.request.get(origin+path)
                assert response.ok,response.text()
                return response.json()
            def start_at_shop():
                page.locator('[data-area=shop]').click()
                page.frame_locator('#site').get_by_role('heading',name='Ready for your next idea.').wait_for()
            def send(question):
                page.locator('#question').fill(question)
                page.locator('#send-chat').click()
                expect(page.locator('#send-chat')).to_be_disabled()
                expect(page.locator('#send-chat')).to_be_enabled(timeout=30000)
                href=page.locator('#conversation .assistant a').last.get_attribute('href')
                return data(href)
            def slow_navigation(route):
                time.sleep(.7)
                route.continue_()
            page.route('**/world/*/booking',slow_navigation)
            locks=[]
            def inspect_locks(route):
                locks.append(page.evaluate('''()=>({draftEditable:!document.getElementById('question').disabled,inputs:['run','reset','goal','send-chat'].every(id=>document.getElementById(id).disabled),
                    examples:[...document.querySelectorAll('.example,[data-question]')].every(e=>e.disabled),inert:document.getElementById('site').inert})'''))
                route.continue_()
            page.route('**/api/step',inspect_locks)
            start_at_shop()
            record=send('When are study rooms available in Ångström on Wednesday for three people for 60 minutes?')
            check('Chat uses assist and finishes through saved done receipt',record['mode']=='assist' and record['status']=='complete' and record['steps'][-1]['action']['action']=='done' and record['steps'][-1]['client_result'])
            check('Slow navigation receipt contains the newly loaded page',record['steps'][0]['client_result']['page_after']['title'].startswith('Campus Rooms'))
            controls=record['steps'][-1]['observation']['controls']
            check('Chat actually sets all requested room filters',all(next(c for c in controls if c['label']==label)['value']==value for label,value in [('Building','Ångström'),('Day','Wednesday'),('People','3'),('Duration','60')]))
            check('Availability request creates no booking or persisted state event',page.evaluate('window.demoWorld.state.bookings.length===0 && window.demoWorld.events.length===0'))
            check('Reply shown only from final recorded response',record['steps'][-1]['action']['message'] in page.locator('#conversation').inner_text())
            check('Chat permits drafting while locking conflicting controls and sending',locks and all(all(sample.values()) for sample in locks))
            check('Every response and receipt preserved without independent verdict',all(s['request'] and s['response_text'] and s['client_result'] for s in record['steps']) and record['evaluation'] is None)
            check('Original demo also puts browser tools between chat messages',page.locator('#conversation .tool-activity[data-state=applied]').count()==len(record['steps'])-1 and page.locator('#conversation .assistant .message-label').last.text_content()=='Daylight')
            (output/'availability.json').write_text(json.dumps(record,indent=2))

            # A second real chat turn explicitly requests a booking.
            start_at_shop()
            record=send('Book the first available room in Ångström on Wednesday for three people for 60 minutes.')
            check('Explicit request creates exactly one booking',page.evaluate('window.demoWorld.state.bookings.length')==1)
            check('Reservation termination labelled as runtime boundary',record['steps'][-1]['client_result']['stop_reason']=='first_accepted_reservation' and 'one-reservation limit' in page.locator('#conversation .assistant').last.inner_text())
            (output/'booking.json').write_text(json.dumps(record,indent=2))

            # Failed receipt persistence must stop without a repeated browser action.
            page.locator('#reset').click()
            start_at_shop()
            events=[]
            def reject_receipt(route):
                events.append(route.request.post_data_json)
                route.fulfill(status=503,json={'error':'Offline test: receipt could not be saved'})
            page.route('**/api/event',reject_receipt)
            record=send('When are study rooms available?')
            check('Failed receipt stops, preserving incomplete trace and avoiding retries',record['status']=='awaiting_client' and len(record['steps'])==1 and len(events)==1 and record['steps'][0]['client_result'] is None)
            check('Failure releases UI locks and does not claim success',page.locator('#reset').is_enabled() and not page.locator('#site').evaluate('(frame)=>frame.inert') and 'request stopped' in page.locator('#conversation .assistant').last.inner_text())
            page.unroute('**/api/event')

            # Replace the document during inference. It must receive an error receipt,
            # not an action on a detached snapshot or a second model request.
            page.locator('#reset').click()
            start_at_shop()
            page.unroute('**/api/step')
            def navigate_during_decision(route):
                response=route.fetch()
                page.locator('#site').evaluate("frame=>{frame.src=frame.src.replace('/shop','/preferences')}")
                page.frame_locator('#site').get_by_role('heading',name='Your account. Your rhythm.').wait_for()
                route.fulfill(response=response)
            page.route('**/api/step',navigate_during_decision)
            record=send('When are study rooms available?')
            check('Failed browser action remains visibly failed in the chat timeline',page.locator('#conversation .tool-activity[data-state=failed]').count()==1)
            check('Navigation during inference rejects stale document and saves failure receipt',record['status']=='error' and len(record['steps'])==1 and 'navigated while' in record['steps'][0]['client_result']['error'] and record['steps'][0]['client_result']['page_after'] is None)
            page.unroute('**/api/step')

            # Exercise existing task submission through the same loop.
            page.locator('#reset').click()
            page.locator('#tasks-tab').click()
            page.locator('#goal').fill('Book the first available room in Ångström on Wednesday for three people for 60 minutes.')
            page.locator('#run').click()
            expect(page.locator('#run')).to_be_disabled()
            expect(page.locator('#run')).to_be_enabled(timeout=30000)
            task=data(page.locator('#trace').get_attribute('href'))
            check('Existing Tasks path retains task mode and one-booking boundary',task['mode']=='task' and task['status']=='complete' and page.evaluate('window.demoWorld.state.bookings.length')==1)
            check('No browser JavaScript errors',not errors)
            page.screenshot(path=str(output/'desktop.png'),full_page=True)
            browser.close()
        sources=['deploy/daylight/client/dashboard.js','deploy/daylight/client/observation.js','scripts/smoke_demo_chat_ui.py','deploy/daylight/client/tool-activity.js','deploy/daylight/client/tool-activity.css']
        report={'passed':True,'checks':checks,'paid_calls':0,'policy':'Offline scripted responses; no model-reliability claim',
                'source_sha256':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in sources}}
        (output/'report.json').write_text(json.dumps(report,indent=2))
        print(json.dumps({'checks':len(checks),'report':str(output/'report.json'),'paid_calls':0}))
    finally:
        process.terminate()
        process.wait(timeout=10)

if __name__=='__main__': main()
