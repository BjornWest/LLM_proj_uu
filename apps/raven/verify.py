"""Finite offline integration checks. All resulting episodes carry scripted tags."""
import json
import os
from pathlib import Path
import threading
import time
from urllib.request import Request, urlopen

from apps.raven.backend import Service, Handler, ThreadingHTTPServer, target_id
from uuid import uuid4
from playwright.sync_api import sync_playwright

OUT = Path('.local/coordination/demo-sprint')


def action(name, **args):
    return {'name':name, 'arguments':json.dumps(args)}


def wait_done(run, seconds=90):
    end = time.monotonic()+seconds
    while not run.done and time.monotonic()<end:
        time.sleep(.1)
    assert run.done, 'run did not finish'
    run.process.join(10)
    assert not run.process.is_alive()
    return run.events


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    server=ThreadingHTTPServer(('127.0.0.1',18766),Handler)
    svc=Service(18766,True,Path('.local/raven-verification-profiles',uuid4().hex).resolve())
    server.service=svc
    threading.Thread(target=server.serve_forever,daemon=True).start()
    results={}
    try:
        # Independent background smoke and shared-window checks run concurrently.
        bg=svc.submit({'text':'Read the page and finish.', 'mode':'background'},[
            action('goto',url='view-source:https://example.com/'),
            action('goto',url='https://example.com/'),
            action('send_msg_to_user',text='[Example Domain](https://example.com/) is the page heading.')])
        with sync_playwright() as pw:
            browser=pw.chromium.connect_over_cdp(svc.window.cdp_url)
            context=browser.contexts[0]
            page=next(p for p in context.pages if not p.url.startswith('chrome-extension:'))
            page.goto('https://example.com/')
            page.evaluate('window.ravenPreserveState=42')
            other=context.new_page()
            other.goto('https://example.com/')
            other.evaluate('window.humanFormState=99')
            page.bring_to_front()
            sw=svc.submit({'text':'Hand over this tab then finish.', 'mode':'user_window'},[
                action('new_tab'),
                action('goto',url='https://example.com/'),
                action('tab_close'),
                action('handover_tab',tab_id='$initial',reason='Please inspect the page and return the tab.'),
                action('tab_focus',tab_id='$initial'),
                action('send_msg_to_user',text='[Example Domain](https://example.com/). Human returned the tab.')])
            end=time.monotonic()+60
            while time.monotonic()<end and not any(e['type']=='handover' and e['message'].startswith('Please inspect') for e in sw.events) and not sw.done:
                time.sleep(.1)
            assert any(e['type']=='handover' and e['message'].startswith('Please inspect') for e in sw.events), sw.events
            assert page.evaluate('window.ravenPreserveState')==42
            pending=next(e for e in sw.events if e['type']=='handover' and e['message'].startswith('Please inspect'))
            initial=pending['tab_id']
            other_id=next(tid for tid,target in sw.targets.items() if target==target_id(context,other))
            assert next(t for t in sw.controller['tabs'] if t['tab_id']==other_id)['state']=='awaiting_human'
            svc.focus(pending['tab_id'])
            assert other.evaluate('window.humanFormState')==99
            assert sw.targets[initial] != sw.targets[other_id]
            human_opened=context.new_page()
            human_opened.goto('https://example.com/')
            req=Request(f'http://127.0.0.1:18766/api/tasks/{sw.run_id}/handback',
                data=json.dumps({'tab_id':pending['tab_id'],'note':'Checked by scripted acceptance'}).encode(),
                headers={'Content-Type':'application/json'},method='POST')
            assert urlopen(req).status==200
            sw.controls.put({'action':'handback','tab_id':pending['tab_id'],'note':None})
            results['shared']=wait_done(sw)
            assert any(e['type']=='final' for e in sw.events), sw.events
            assert not any(e['type']=='error' for e in sw.events),sw.events
            transitions=[json.loads(line) for line in (Path(sw.trace)/'events.jsonl').read_text().splitlines()]
            assert any(e['event']=='human_chat_queued_for_policy' for e in transitions)
            assert len([e for e in sw.events if e['type']=='handover'])==1
            assert sum(e['type']=='step' for e in sw.events)>=6
            assert page.evaluate('window.ravenPreserveState')==42
            assert any(e['type']=='tab' and e['action']=='opened' and e['tab_id']=='tab-3' for e in sw.events)
            assert any(e['type']=='tab' and e['action']=='closed' and e['tab_id']=='tab-3' for e in sw.events)
            results['background']=wait_done(bg)
            assert any(e['type']=='final' and e['sources'] for e in bg.events), bg.events
            # SSE replays exactly, including terminal done for late subscribers.
            replay=urlopen(f'http://127.0.0.1:18766/api/tasks/{bg.run_id}/events').read().decode()
            assert [json.loads(s[6:]) for s in replay.splitlines() if s.startswith('data: ')]==bg.events
            results['sse_replay']=True
            # Human closes a handed-over tab; stale handback is friendly and the
            # agent continues in a workspace that is removed if left blank.
            sacrificial=context.new_page()
            sacrificial.goto('https://example.com/')
            sacrificial.bring_to_front()
            closed=svc.submit({'text':'Recover after a tab closes.', 'mode':'user_window'},[
                action('handover_tab',tab_id='$initial',reason='Close this tab for acceptance'),
                action('tab_focus',tab_id='$initial'),
                action('send_msg_to_user',text='The tab closed; no further browser action was needed.')])
            end=time.monotonic()+60
            while time.monotonic()<end and not any(e['type']=='handover' for e in closed.events) and not closed.done:
                time.sleep(.1)
            assert any(e['type']=='handover' for e in closed.events),closed.events
            sacrificial.close()
            results['closed_handover']=wait_done(closed)
            assert any(e['type']=='final' for e in closed.events),closed.events
            assert not any(e['type']=='error' for e in closed.events),closed.events
            page.title()  # Pump this independent CDP client's pending tab-close events.
            assert not any(p.url=='about:blank' for p in context.pages)
            page.bring_to_front()
            # Cancel while waiting for a human: no model calls, shared window survives.
            cancel=svc.submit({'text':'Wait for handover.', 'mode':'user_window'},[
                action('handover_tab',tab_id='$initial',reason='Cancellation acceptance')])
            end=time.monotonic()+60
            while time.monotonic()<end and not any(e['type']=='handover' and e['message']=='Cancellation acceptance' for e in cancel.events) and not cancel.done:
                time.sleep(.1)
            assert any(e['type']=='handover' and e['message']=='Cancellation acceptance' for e in cancel.events),cancel.events
            svc.cancel(cancel)
            assert cancel.events[-1]=={'type':'done','stop_reason':'cancelled'}
            assert not cancel.process.is_alive()
            assert page.title()
            page.goto('https://example.com/')  # Interrupted CDP route hooks no longer intercept navigation.
            results['cancel']=cancel.events
            # Exercise the actual panel's Stop and failed-submit recovery, with no API inference.
            original_submit=svc.submit
            def ui_submit(payload, scripted=None):
                if payload['text']=='Force error acceptance':
                    raise ValueError('Scripted submit failure')
                return original_submit(payload, [action('handover_tab',tab_id='$initial',reason='Panel cancellation'),action('tab_focus',tab_id='$initial'),action('send_msg_to_user',text='Returned')])
            svc.submit=ui_submit
            panel=next(p for p in context.pages if '/sidepanel.html' in p.url)
            panel.reload()  # Attach existing extension OOPIFs on this independent CDP client.
            frame=panel.frame_locator('iframe')
            frame.locator('#send-button').wait_for()
            end=time.monotonic()+60
            while not frame.locator('#send-button').is_enabled() and time.monotonic()<end:
                time.sleep(.1)
            frame.locator('#message-input').fill('Cancel UI acceptance')
            frame.locator('#send-button').click()
            end=time.monotonic()+60
            while not any(not r.done for r in svc.runs.values()) and time.monotonic()<end:
                time.sleep(.1)
            ui_run=list(svc.runs.values())[-1]
            end=time.monotonic()+60
            while not any(e['type']=='handover' for e in ui_run.events) and time.monotonic()<end:
                time.sleep(.1)
            matching=frame.locator('#tabs button[title="https://example.com/"]')
            assert matching.count()>=2
            for i in range(2):
                matching.nth(i).click()
            results['panel_duplicate_url_tabs']=True
            # Transient handback failures must retain the button for retry.
            def unavailable_handback(route):
                route.fulfill(status=503,content_type='application/json',body='{"error":"Temporary outage"}')
            context.route('**/handback',unavailable_handback)
            frame.locator('#handback').click()
            assert frame.locator('#handover').is_visible()
            assert frame.locator('#handback').is_enabled()
            assert 'Please try again' in frame.locator('#run-status').inner_text()
            context.unroute('**/handback',unavailable_handback)
            results['handback_transient_retry']=True
            frame.locator('#stop').click()
            wait_done(ui_run)
            assert ui_run.events[-1]=={'type':'done','stop_reason':'cancelled'},ui_run.events
            assert frame.locator('#send-button').is_enabled()
            results['panel_stop']=True
            frame.locator('#message-input').fill('Force error acceptance')
            frame.locator('#send-button').click()
            end=time.monotonic()+30
            while 'Scripted submit failure' not in frame.locator('#run-status').inner_text() and time.monotonic()<end:
                time.sleep(.1)
            assert frame.locator('#send-button').is_enabled()
            assert 'Scripted submit failure' in frame.locator('#run-status').inner_text()
            results['panel_error_recovery']=True
            frame.locator('#message-input').fill('Reload cancellation acceptance')
            frame.locator('#send-button').click()
            end=time.monotonic()+30
            while not any(not r.done for r in svc.runs.values()) and time.monotonic()<end:
                time.sleep(.1)
            reload_run=list(svc.runs.values())[-1]
            end=time.monotonic()+60
            while not any(e['type']=='handover' for e in reload_run.events) and time.monotonic()<end:
                time.sleep(.1)
            assert any(e['type']=='handover' for e in reload_run.events),reload_run.events
            frame.locator('#handover').wait_for(state='visible',timeout=30000)
            extra=urlopen(f'http://127.0.0.1:18766/api/tasks/{reload_run.run_id}/events')
            assert extra.readline().startswith(b'data: ')
            extra.close()
            time.sleep(5)
            assert not reload_run.done, 'Other SSE reader must not cancel the live panel'
            results['multiple_sse_preserves_panel']=True
            panel.reload()
            wait_done(reload_run)
            assert reload_run.events[-1]=={'type':'done','stop_reason':'cancelled'}
            results['panel_pagehide_cancels']=True
            frame.locator('#send-button').wait_for()
            frame.locator('#messages').evaluate('node=>node.replaceChildren()')
            frame.locator('body').evaluate('''()=>ravenChatDemo.appendMessage(
                'A recorded source: https://example.com/','Raven',{sources:[{
                id:'plain-url',url:'https://example.com/',title:'Plain URL evidence',
                evidence:'Captured example evidence',illustrative:true}]})''')
            assert frame.locator('button.raven-citation').count()==1
            frame.locator('button.raven-citation').click()
            assert frame.locator('.raven-citation-card').is_visible()
            results['panel_plain_url_citation']=True
            panel.screenshot(path=str(OUT/'web-a-shots/panel-scripted.png'))
            results['tabs']=svc.tabs()
            browser.close()
    finally:
        (OUT/'scripted-acceptance.json').write_text(json.dumps(results,indent=2))
        server.shutdown()
        svc.close()
    print('PASS: background + shared current document + handover round trip + cancel + SSE replay')


if __name__=='__main__':
    main()
