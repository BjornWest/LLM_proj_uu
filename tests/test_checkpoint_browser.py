"""Real Chromium history/state boundaries; local HTTP, no model calls."""
from copy import deepcopy
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from threading import Thread
from types import SimpleNamespace
import time
import unittest

from playwright.sync_api import sync_playwright
from intent_browser.checkpoint_browser import capture_browser,restore_browser,digest
from intent_browser.checkpoint_history import track,capture

class BrowserCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.requests=[];requests=self.requests
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):self.respond()
            def do_POST(self):self.respond()
            def respond(self):
                body=self.rfile.read(int(self.headers.get('content-length','0')))
                requests.append((self.command,self.path,body))
                html='''<!doctype html><html><head><title>PAGE</title></head><body>
                <a href="/b">Next</a><form method="POST" action="/committed"><input name="value" value="a b"><button>Commit</button></form>
                <label><input type="checkbox">Consent</label><select><option>EUR</option><option>USD</option></select>
                <div id="panel" style="height:50px;overflow:auto"><div style="height:1000px">Scroll content</div></div>
                <script>window.storedAtLoad=localStorage.getItem('test');</script></body></html>'''.replace('PAGE',self.path)
                data=(('#panel{height:50px;overflow:auto}' if self.path=='/style.css' else html)).encode();self.send_response(200);self.send_header('content-type','text/css' if self.path=='/style.css' else 'text/html');self.send_header('cache-control','no-store');self.send_header('content-length',str(len(data)));self.end_headers();self.wfile.write(data)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.thread=Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.origin=f'http://127.0.0.1:{self.server.server_port}'
        self.pw=sync_playwright().start();self.browser=self.pw.chromium.launch(headless=True)
        self.context=self.browser.new_context(service_workers='block');track(self.context)
        self.page=self.context.new_page();self.page.goto(self.origin+'/a')
    def tearDown(self):
        self.browser.close();self.pw.stop();self.server.shutdown();self.server.server_close();self.thread.join()
    def env(self,page):return SimpleNamespace(unwrapped=SimpleNamespace(page=page,last_action='fill("7", "draft")',last_action_error='previous diagnostic',start_time=time.time()-123))
    def clone(self,state):
        ctx=self.browser.new_context(service_workers='block');track(ctx);page=ctx.new_page();env=self.env(page);restore_browser(env,state);return env.unwrapped,ctx
    def test_get_history_storage_scroll_and_last_action(self):
        self.page.goto(self.origin+'/b')
        self.page.evaluate('''() => {localStorage.setItem('test','inherited');sessionStorage.setItem('session','saved');document.querySelector('select').value='USD';document.querySelector('input[type=checkbox]').checked=true;document.querySelector('#panel').scrollTop=120;document.querySelector('input').focus();}''')
        state=capture_browser(self.env(self.page));before=len(self.requests)
        restored,ctx=self.clone(state);page=restored.page
        self.assertEqual(len(self.requests),before,'hydration must not issue navigation HTTP')
        self.assertEqual(restored.last_action_error,'previous diagnostic');self.assertAlmostEqual(time.time()-restored.start_time,123,delta=2)
        self.assertEqual(page.locator('select').input_value(),'USD');self.assertTrue(page.locator('input[type=checkbox]').is_checked())
        self.assertIsNone(page.locator('input[type=checkbox]').get_attribute('value'))
        self.assertEqual(page.locator('#panel').evaluate('(e)=>e.scrollTop'),120)
        self.assertEqual(page.evaluate('window.storedAtLoad'),'inherited')
        page.go_back(wait_until='load');self.assertEqual(page.url,self.origin+'/a');self.assertEqual(self.requests[-1][:2],('GET','/a'))
        page.go_forward(wait_until='load');self.assertEqual(page.url,self.origin+'/b');self.assertEqual(self.requests[-1][:2],('GET','/b'))
        page.evaluate("localStorage.setItem('test','updated')");page.reload(wait_until='load')
        self.assertEqual(page.evaluate('window.storedAtLoad'),'updated','removed preload must not overwrite later storage')
        ctx.close()
    def test_unchanged_stylesheet_not_removed_and_refetched_during_restore(self):
        self.page.evaluate("""() => new Promise(resolve=>{const link=document.createElement('link');link.rel='stylesheet';link.href='/style.css';link.onload=resolve;document.head.append(link);})""")
        self.page.locator('#panel').evaluate("e=>{e.removeAttribute('style');e.scrollTop=120}")
        state=capture_browser(self.env(self.page));before=len(self.requests);restored,ctx=self.clone(state)
        self.assertEqual(self.requests[before:],[('GET','/style.css',b'')],'only initial hydration asset load, no attribute-triggered refetch')
        self.assertEqual(restored.page.locator('#panel').evaluate('(e)=>e.scrollTop'),120);ctx.close()

    def test_unsupported_indexeddb_rejected(self):
        self.page.evaluate("""()=>new Promise((resolve,reject)=>{const request=indexedDB.open('private-state');request.onsuccess=()=>{request.result.close();resolve()};request.onerror=reject})""")
        with self.assertRaisesRegex(Exception,'IndexedDB'):capture_browser(self.env(self.page))
    def test_unsupported_frames_and_contenteditable_selection_rejected(self):
        self.page.evaluate("()=>{const frame=document.createElement('iframe');document.body.append(frame)}")
        with self.assertRaisesRegex(Exception,'Frames'):capture_browser(self.env(self.page))
        self.page.evaluate("()=>{document.querySelector('iframe').remove();const edit=document.createElement('div');edit.contentEditable='true';edit.textContent='draft';document.body.append(edit);edit.focus()}")
        with self.assertRaisesRegex(Exception,'Contenteditable'):capture_browser(self.env(self.page))

    def test_history_api_same_url_not_mistaken_for_a_full_document(self):
        self.page.evaluate("history.pushState({draft:'unsaved'}, '', location.href)")
        with self.assertRaisesRegex(ValueError,'History API'):capture_browser(self.env(self.page))

    def test_forward_get_stack_preserved(self):
        self.page.goto(self.origin+'/b');self.page.go_back(wait_until='load')
        state=capture_browser(self.env(self.page));before=len(self.requests);restored,ctx=self.clone(state)
        self.assertEqual(len(self.requests),before);self.assertEqual(capture(restored.page),state['pages'][0]['history'])
        restored.page.go_forward(wait_until='load');self.assertEqual(restored.page.url,self.origin+'/b');ctx.close()
    def test_post_result_restored_without_mutation_and_reload_is_real_post(self):
        with self.page.expect_navigation(wait_until='load'):self.page.locator('button').click()
        state=capture_browser(self.env(self.page));before=len(self.requests);restored,ctx=self.clone(state)
        self.assertEqual(len(self.requests),before);self.assertEqual(restored.page.url,self.origin+'/committed')
        restored.page.reload(wait_until='load');self.assertEqual(self.requests[-1],('POST','/committed',b'value=a+b'));self.assertEqual(len(self.requests),before+1);ctx.close()
    def test_forward_post_boundary_rejected_without_world_request(self):
        with self.page.expect_navigation(wait_until='load'):self.page.locator('button').click()
        self.page.go_back(wait_until='load');state=capture_browser(self.env(self.page));before=len(self.requests)
        with self.assertRaisesRegex(ValueError,'Forward history'):self.clone(state)
        self.assertEqual(len(self.requests),before)
    def test_multi_tab_current_pages_isolated(self):
        second=self.context.new_page();second.goto(self.origin+'/a');second.set_viewport_size({'width':900,'height':650})
        second.evaluate("sessionStorage.setItem('tab','second')");self.page.evaluate("sessionStorage.setItem('tab','first')")
        state=capture_browser(self.env(second));before=len(self.requests);restored,ctx=self.clone(state)
        self.assertEqual(len(self.requests),before);self.assertEqual(restored.page.url,second.url)
        self.assertEqual([p.evaluate("sessionStorage.getItem('tab')") for p in ctx.pages],['first','second'])
        self.assertEqual(restored.page.viewport_size,{'width':900,'height':650});ctx.close()

if __name__=='__main__':unittest.main()
