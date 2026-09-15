"""Actual-handler interruption checks with gated offline inference; zero paid calls."""
import asyncio,hashlib,json,os,subprocess
from pathlib import Path
from uuid import uuid4
from playwright.async_api import async_playwright,expect
ROOT=Path(__file__).resolve().parents[1]

async def main():
    os.environ['LD_LIBRARY_PATH']=str(ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu')+':'+os.environ.get('LD_LIBRARY_PATH','')
    out=ROOT/'.local/vercel-demo'/('chat-interrupt-'+uuid4().hex[:8]);out.mkdir(parents=True)
    server=subprocess.Popen(['node','tests/interrupt-server.mjs'],cwd=ROOT/'deploy/daylight',stdout=subprocess.PIPE,text=True)
    origin='http://127.0.0.1:'+str(json.loads(server.stdout.readline())['port']);checks=[]
    def check(name,value):
        assert value,name
        checks.append(name);print('PASS',name,flush=True)
    async def eventually(operation):
        for _ in range(300):
            result=await operation()
            if result:return result
            await asyncio.sleep(.025)
        raise AssertionError('Timed out waiting for controlled browser state')
    try:
      async with async_playwright() as p:
        browser=await p.chromium.launch();context=await browser.new_context(viewport={'width':1512,'height':1040});page=await context.new_page();errors=[];starts=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.on('request',lambda r:starts.append(r.post_data_json) if r.method=='POST' and r.url.endswith('/api/start') else None)
        await page.goto(origin);await page.get_by_label('Your invitation code').fill('offline-interactive-code-'*3);await page.get_by_role('button',name='Open demo').click()
        async def get(path):return await (await page.request.get(origin+path)).json()
        async def read(id):return await get('/api/traces/'+id)
        for name,path,frame_selector,send in [('workspace','/workspace','#site-frames iframe','#send-question'),('original','/demo','#site','#send-chat')]:
            async def open_page():
                await page.goto(origin+path);await expect(page.locator('#question')).to_be_enabled()
                await page.frame_locator(frame_selector).get_by_role('heading',name='Reserve a study room').wait_for()
            question=page.locator('#question');button=page.locator(send)
            await open_page();before=len(starts)
            await question.fill('Wait for old inference');await question.press('Enter')
            async def pending():return (await get('/__test/state'))['pending']
            old=(await eventually(pending))[0]
            await expect(button).to_be_enabled();await expect(button).to_have_attribute('aria-label','Interrupt and send message')
            await question.fill('Actually, just answer without changing filters');await question.press('Enter')
            await expect(page.locator('#conversation')).to_contain_text('Fresh answer for: Actually, just answer without changing filters')
            await expect(button).to_have_attribute('data-running','false')
            state=await get('/__test/state');new=state['calls'][-1]['id'];trace=await read(new)
            check(name+' new message interrupts without waiting for old inference',old in state['pending'] and trace['status']=='complete' and len(starts)==before+2)
            check(name+' new turn records exact goal, interrupted context and predecessor',trace['continuation_of']==old and trace['goal']==starts[-1]['goal'] and any(m.get('content')=='Wait for old inference' for m in trace['steps'][0]['request']['messages']))
            check(name+' interrupt retains the same conversation session',trace['conversation_id']==(await read(old))['conversation_id'])
            check(name+' old request is durably interrupted before its response exists',(await read(old))['status']=='interrupted' and (await read(old))['steps'][0]['response'] is None)
            await page.request.post(origin+'/__test/release')
            async def late():
                row=await read(old)
                return row if row['steps'][0]['response'] else None
            saved=await eventually(late)
            check(name+' late response and cost retained without executing stale action',saved['status']=='interrupted' and saved['steps'][0]['usage']['cost']==.0001 and saved['steps'][0]['client_result'] is None and await page.frame_locator(frame_selector).locator('#room-people').input_value()=='1')
            check(name+' late response cannot overwrite new answer or reactivate UI',await button.get_attribute('data-running')=='false' and await page.locator('#conversation .run-interruption').count()==1 and len(starts)==before+2)
            await page.screenshot(path=str(out/(name+'-interrupted.png')),full_page=True)
            review=await page.context.new_page();before_review=len(starts)
            await review.goto(origin+'/workspace/replays?run=d:'+old)
            await expect(review.locator('#trace-conversation .user')).to_have_count(2)
            check(name+' saved interrupted turns open as one read-only conversation',len(starts)==before_review and '2 recorded turns' in await review.locator('#browser-record-summary').inner_text())
            check(name+' saved late action is labelled interrupted without receipt','interrupted output' in await review.locator('#trace-conversation .assistant .transcript-label').first.inner_text() and 'No execution receipt' in await review.locator('#trace-conversation .tool .transcript-label').inner_text())
            await review.close()


            # Hold a real iframe navigation already triggered by the old action.
            await open_page();await page.frame_locator(frame_selector).get_by_role('link',name='Shop',exact=True).click()
            await page.frame_locator(frame_selector).get_by_role('heading',name='Ready for your next idea.').wait_for()
            entered=asyncio.Event();release=asyncio.Event()
            async def navigation(route):
                entered.set();await release.wait();await route.continue_()
            await page.route('**/world/*/booking',navigation);before=len(starts)
            await question.fill('Navigate to Study rooms');await question.press('Enter');await asyncio.wait_for(entered.wait(),10)
            state=await get('/__test/state');old=state['calls'][-1]['id']
            await question.fill('Describe this new page only');await button.click()
            async def interrupted():return (await read(old))['status']=='interrupted'
            await eventually(interrupted)
            check(name+' redirected turn waits for already executing navigation',len(starts)==before+1 and await button.is_disabled())
            await question.fill('Keep this unsent draft');await page.locator('#ask-form' if name=='workspace' else '#chat-form').evaluate("f=>f.dispatchEvent(new Event('submit',{cancelable:true}))")
            release.set();await expect(page.locator('#conversation')).to_contain_text('Fresh answer for: Describe this new page only');await expect(button).to_have_attribute('data-running','false')
            await page.unroute('**/world/*/booking',navigation)
            state=await get('/__test/state');new=state['calls'][-1]['id'];prior=await read(old);following=await read(new)
            check(name+' interruption preserves navigation receipt and refreshes next observation',len(prior['steps'])==1 and prior['status']=='interrupted' and prior['steps'][0]['client_result']['page_after']['title'].startswith('Campus Rooms') and following['steps'][0]['observation']['title'].startswith('Campus Rooms'))
            check(name+' duplicate submit during handover is ignored and later draft survives',len(starts)==before+2 and await question.input_value()=='Keep this unsent draft')

            # Start response not yet available: do not leak an orphan active trace.
            await open_page();entered=asyncio.Event();release=asyncio.Event();first=True
            async def starting(route):
                nonlocal first
                if first:first=False;entered.set();await release.wait()
                await route.continue_()
            await page.route('**/api/start',starting);before=len(starts)
            await question.fill('Old startup');await question.press('Enter');await asyncio.wait_for(entered.wait(),10)
            await question.fill('Replacement during startup');await question.press('Enter');release.set()
            await expect(page.locator('#conversation')).to_contain_text('Fresh answer for: Replacement during startup');await expect(button).to_have_attribute('data-running','false')
            await page.unroute('**/api/start',starting)
            following=await read((await get('/__test/state'))['calls'][-1]['id']);prior=await read(following['continuation_of'])
            check(name+' interruption during start creates no old inference or orphan run',prior['status']=='interrupted' and prior['steps']==[] and len(starts)==before+2)

            # Preserve a receipt already being sent before proceeding to the new turn.
            await open_page();entered=asyncio.Event();release=asyncio.Event();first=True
            async def saving(route):
                nonlocal first
                if first:first=False;entered.set();await release.wait()
                await route.continue_()
            await page.route('**/api/event',saving);before=len(starts)
            await question.fill('Original answer awaiting receipt');await question.press('Enter');await asyncio.wait_for(entered.wait(),10)
            old=(await get('/__test/state'))['calls'][-1]['id']
            await question.fill('Replacement while saving');await question.press('Enter');await eventually(interrupted)
            check(name+' redirect waits for in-progress receipt saving',len(starts)==before+1)
            release.set();await expect(page.locator('#conversation')).to_contain_text('Fresh answer for: Replacement while saving');await expect(button).to_have_attribute('data-running','false')
            await page.unroute('**/api/event',saving);prior=await read(old)
            check(name+' interrupted done receipt retained without showing superseded answer',prior['status']=='interrupted' and prior['steps'][0]['client_result'] is not None and 'Fresh answer for: Original answer awaiting receipt' not in await page.locator('#conversation').inner_text())

            await open_page();before=len(starts)
            await question.fill('Wait for first interrupted run');await question.press('Enter');first_id=(await eventually(pending))[0]
            await question.fill('Wait for second interrupted run');await question.press('Enter')
            async def two_pending():
                ids=(await get('/__test/state'))['pending'];return ids if len(ids)==2 else None
            second_id=(await eventually(two_pending))[-1]
            await question.fill('Final redirection');await question.press('Enter');await expect(page.locator('#conversation')).to_contain_text('Fresh answer for: Final redirection');await expect(button).to_have_attribute('data-running','false')
            following=await read((await get('/__test/state'))['calls'][-1]['id'])
            check(name+' repeated interruptions keep the latest turn and ordered user context',len(starts)==before+3 and following['continuation_of']==second_id and [m['content'] for m in following['steps'][0]['request']['messages'] if m['content'].startswith('Wait for')]==['Wait for first interrupted run','Wait for second interrupted run'])
            await page.request.post(origin+'/__test/release')
            async def both_late():return all(row['steps'][0]['response'] for row in [await read(first_id),await read(second_id)])
            await eventually(both_late)
            check(name+' multiple late responses cannot apply filters',await page.frame_locator(frame_selector).locator('#room-people').input_value()=='1' and all(row['status']=='interrupted' for row in [await read(first_id),await read(second_id)]))

            # A cancellation storage failure stops locally without silently launching.
            await open_page();before=len(starts)
            await question.fill('Wait for cancellation failure');await question.press('Enter');old=(await eventually(pending))[0]
            async def fail_cancel(route):await route.fulfill(status=503,content_type='application/json',body=json.dumps({'error':'Offline cancellation storage failure'}))
            await page.route('**/api/interrupt',fail_cancel)
            await question.fill('This replacement must not start');await button.click();await expect(page.locator('#conversation .run-interruption')).to_contain_text('new message was not started')
            await expect(button).to_have_attribute('data-running','false')
            check(name+' failed cancellation does not retry or launch replacement',len(starts)==before+1)
            await page.request.post(origin+'/__test/release');await eventually(late)
            check(name+' even after cancellation write failure late action stays unexecuted',await page.frame_locator(frame_selector).locator('#room-people').input_value()=='1' and len(starts)==before+1)
            await page.unroute('**/api/interrupt',fail_cancel)
        check('No browser JavaScript errors',not errors);await browser.close()
      sources=['workspace.js','dashboard.js','tool-activity.js','tool-activity.css']
      (out/'report.json').write_text(json.dumps({'passed':True,'checks':checks,'paid_calls':0,'transport':'Controlled offline responses through actual handler','source_sha256':{name:hashlib.sha256((ROOT/'deploy/daylight/client'/name).read_bytes()).hexdigest() for name in sources}},indent=2))
      print(json.dumps({'checks':len(checks),'report':str(out/'report.json'),'paid_calls':0}))
    finally:server.terminate();server.wait(timeout=10)
if __name__=='__main__':asyncio.run(main())
