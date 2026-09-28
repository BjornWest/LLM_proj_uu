#!/usr/bin/env python3
"""Generic real-browser boundaries + one full BrowserGym policy-delivery episode.
No model/search calls, benchmark labels or external websites.
"""
import argparse
from copy import deepcopy
import hashlib
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
from threading import Thread

ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
libs=ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu'
if libs.is_dir():os.environ['LD_LIBRARY_PATH']=str(libs)+':'+os.environ.get('LD_LIBRARY_PATH','')

from playwright.sync_api import sync_playwright
from intent_browser.browser_events import BrowserEvents
from intent_browser.harness import core_feedback_profile
from intent_browser.backend import Completion
from intent_browser.actions import make_action_set
from intent_browser.runner import run_episode
from intent_browser.trace import write_json
import browsergym.core
import gymnasium as gym

PAGE='''<!doctype html><html><title>Generic feedback fixture</title>
<h1>Browser controls</h1><label>Name<input aria-label="Name"></label>
<label>Password<input aria-label="Password" type="password"></label>
<label><input type="checkbox" aria-label="Option">Option</label>
<div role="status" id="status">Ready</div>
<button onclick="toast('Unmarked notice',false)">Toast</button>
<button onclick="toast('Navigating notice',true);setTimeout(()=>location.href='/next',40)">Navigate</button>
<button onclick="setTimeout(()=>toast('Late notice',true),150)">Delayed</button>
<button onclick="document.querySelector('#status').textContent=confirm('Continue?')?'Accepted':'Dismissed'">Dialog</button>
<button onclick="window.open('/next')">Popup</button>
<button onclick="let f=document.createElement('iframe');f.src='/frame';document.body.append(f)">Frame</button>
<form><label>Required<input required aria-label="Required"></label><button>Submit</button></form>
<div hidden id="hidden"></div><script>
window.privateVerifier='PRIVATE VERIFIER SECRET';
function toast(s,aria=true){const t=document.createElement('p');if(aria)t.setAttribute('role','alert');
t.textContent=s;document.body.append(t);setTimeout(()=>t.remove(),30)}
</script></html>'''


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        content=PAGE if self.path=='/' else ('<!doctype html><button onclick="let a=document.createElement(\'p\');a.setAttribute(\'role\',\'alert\');a.textContent=\'Frame notice\';document.body.append(a)">Frame button</button>' if self.path=='/frame' else '<!doctype html><h1>Next document</h1>')
        self.send_response(200);self.send_header('Content-Type','text/html');self.end_headers();self.wfile.write(content.encode())
    def log_message(self,*args):pass


def main(output):
    output.mkdir(parents=True,exist_ok=False)
    source_paths=[*sorted((ROOT/'intent_browser').glob('*.py')),Path(__file__).resolve()]
    sources={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths}
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    origin=f'http://127.0.0.1:{server.server_port}'
    reports=[]
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True)
            def case(name,fn):
                context=browser.new_context();page=context.new_page();page.goto(origin)
                events=BrowserEvents();events.start(context);events.drain()
                try:
                    evidence=fn(page,events)
                    reports.append({'case':name,'passed':True,'evidence':evidence})
                finally: events.close();context.close()
            def toast(page,c):
                page.get_by_role('button',name='Toast',exact=True).click();page.wait_for_timeout(80)
                result=c.drain();assert 'Unmarked notice' in json.dumps(result)
                assert 'Unmarked notice' not in page.locator('body').inner_text()
                return result
            case('unmarked_transient',toast)
            def navigation(page,c):
                page.get_by_role('button',name='Navigate',exact=True).click();page.wait_for_url('**/next')
                result=c.drain();assert 'Navigating notice' in json.dumps(result)
                assert any(e['kind']=='navigation' for e in result['events'])
                return result
            case('announcement_survives_document_navigation',navigation)
            def late(page,c):
                page.get_by_role('button',name='Delayed',exact=True).click()
                first=c.drain();assert 'Late notice' not in json.dumps(first)
                page.wait_for_timeout(220);result=c.drain()
                assert 'Late notice' in json.dumps(result)
                assert all(e['window']=='between_actions' for e in result['events'])
                return result
            case('late_event_between_decisions',late)
            def form(page,c):
                page.get_by_label('Name',exact=True).fill('Bjorn')
                page.get_by_label('Option',exact=True).check()
                page.get_by_role('button',name='Submit',exact=True).click()
                result=c.drain();kinds={e['kind'] for e in result['events']}
                assert {'input','change','invalid','focus'}<=kinds
                assert any(e.get('checked') is True for e in result['events'])
                return result
            case('form_control_and_validation_events',form)
            def submit(page,c):
                page.get_by_label('Required',exact=True).fill('Public value')
                page.get_by_role('button',name='Submit',exact=True).click()
                result=c.drain();assert any(e['kind']=='submit' for e in result['events'])
                return result
            case('submit_attempt_survives_navigation',submit)
            def hidden(page,c):
                page.get_by_label('Password',exact=True).fill('PRIVATE PASSWORD SECRET')
                page.evaluate("document.querySelector('#hidden').innerHTML='<p role=alert>PRIVATE HIDDEN SECRET</p>'")
                result=c.drain();assert 'PRIVATE' not in json.dumps(result)
                return result
            case('hidden_and_password_excluded',hidden)
            def frames(page,c):
                page.get_by_role('button',name='Frame',exact=True).click()
                page.frame_locator('iframe').get_by_role('button',name='Frame button').click()
                result=c.drain();assert 'Frame notice' in json.dumps(result)
                assert len({e['frame'] for e in result['events'] if e['frame']})>=2
                return result
            case('new_frame_observed',frames)
            def cross_frame(page,c):
                # A second origin, still our own local server. No third-party calls.
                page.evaluate('(url)=>{const f=document.createElement("iframe");f.src=url;document.body.append(f)}',
                              origin.replace('127.0.0.1','localhost')+'/frame')
                page.frame_locator('iframe').get_by_role('button',name='Frame button').click()
                page.locator('iframe').evaluate('(el)=>el.remove()')
                result=c.drain();assert 'Frame notice' in json.dumps(result)
                assert any(e['kind']=='frame_detached' for e in result['events'])
                return result
            case('cross_origin_frame_events_survive_detach',cross_frame)
            def popup(page,c):
                with page.expect_popup() as opened:page.get_by_role('button',name='Popup',exact=True).click()
                child=opened.value;child.wait_for_load_state();child.close()
                result=c.drain();kinds={e['kind'] for e in result['events']}
                assert {'page_opened','page_closed'}<=kinds
                return result
            case('popup_lifecycle',popup)
            def dialog(page,c):
                page.get_by_role('button',name='Dialog',exact=True).click()
                assert page.locator('#status').inner_text()=='Dismissed'
                result=c.drain();assert any(e['kind']=='dialog_opened' for e in result['events'])
                return result
            case('dialog_observer_keeps_auto_dismiss',dialog)
            def overflow(page,c):
                page.evaluate("for(let i=0;i<300;i++){const p=document.createElement('p');p.setAttribute('role','alert');p.textContent='Notice '+i;document.body.append(p)}")
                # Overflow is pushed asynchronously, not forced by drain.
                page.wait_for_timeout(350)
                result=c.drain();assert len(result['events'])<=64
                assert result['omitted']>0 or any(e['kind']=='capture_gap' for e in result['events'])
                assert not c.drain()['events']
                return result
            case('bounded_overflow_and_no_duplicate_drain',overflow)
            def cleanup(page,c):
                c.close();page.get_by_role('button',name='Toast',exact=True).click();page.wait_for_timeout(80)
                assert not c.events
                return {'no_new_events':True}
            case('cleanup_detaches_observers',cleanup)
            def isolated(page,c):
                assert not c.drain()['events']
                other=browser.new_context();op=other.new_page();op.goto(origin)
                op.get_by_role('button',name='Toast',exact=True).click();op.wait_for_timeout(80)
                assert not c.drain()['events'];other.close()
                return {'other_context_not_observed':True}
            case('browser_context_isolation',isolated)
            browser.close()

        holder={}
        def factory(video):
            env=gym.make('browsergym/openended',task_kwargs={'start_url':origin,'goal':'Inspect controls'},
                         headless=True,action_mapping=make_action_set().to_python_code)
            holder['env']=env;return env
        class Backend:
            calls=0
            def complete(self,messages):
                self.calls+=1
                if self.calls==1:
                    page=holder['env'].unwrapped.page
                    bid=page.get_by_role('button',name='Toast',exact=True).get_attribute('bid')
                    assert f'[{bid}]' in messages[-1]['content'];code=f'click({bid!r})'
                else:
                    assert 'Unmarked notice' in json.dumps(messages)
                    assert 'Unmarked notice' not in messages[-1]['content']
                    code="send_msg_to_user('Done')"
                return Completion(code,{'source':'scripted'},{'messages':deepcopy(messages)})
        trace,summary=run_episode(factory,Backend(),{'driver':'scripted','network_model_calls':0},
                                 output/'runs',max_steps=2,harness_profile=core_feedback_profile(),debug_timings=True)
        assert summary['error'] is None,summary['error']
        rows=[json.loads(s) for s in (trace/'steps.jsonl').read_text().splitlines()]
        deliveries=[json.loads(s) for s in (trace/'policy-delivery.jsonl').read_text().splitlines()]
        assert len(deliveries)==2
        assert any(i['kind']=='browser_feedback' and i['confirmed'] for i in deliveries[1]['items'])
        for row,delivery in zip(rows,deliveries):
            for item in delivery['items']:
                content=json.loads((trace/item['artifact']).read_text())
                span=item['message_span'];text=row['model_request']['messages'][span['message_index']]['content'][span['start']:span['end']]
                assert text==content['text']
                assert hashlib.sha256(text.encode()).hexdigest()==item['sha256']
            assert 'PRIVATE' not in json.dumps(row['messages'])
        assert rows[1]['messages'][:len(rows[0]['messages'])]==rows[0]['messages']
        reports.append({'case':'browsergym_delivery_integration','passed':True,'trace':str(trace)})
    finally:server.shutdown();server.server_close();thread.join()
    assert sources=={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths}
    report={'passed':True,'cases':reports,'model_calls':0,'source_sha256':sources,
            'scope':'Scripted browser diagnostics, not model performance or benchmark certification'}
    write_json(output/'report.json',report)
    print(json.dumps({'passed':True,'cases':len(reports),'report':str(output/'report.json')}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    main(parser.parse_args().output)
