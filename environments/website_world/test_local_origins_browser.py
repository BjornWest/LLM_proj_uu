"""Actual Chromium checks for local forwarding and browser-owned storage."""
from contextlib import ExitStack
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
import json
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import sync_playwright, Error as PlaywrightError
from environments.website_world.local_origins import OriginMap, LocalOriginBridge


def test_local_redirects_fetch_cookies_and_context_isolation():
    events = []
    origins = {}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass

        def do_GET(self):
            events.append({'port': self.server.server_port, 'path': self.path,
                           'cookie': self.headers.get('Cookie', '')})
            path = urlsplit(self.path).path
            self.send_response(302 if path in ('/redirect', '/outside', '/relative') else 200)
            if path == '/redirect': self.send_header('Location', origins['b'] + '/echo?x=a%2Bb#part')
            if path == '/relative': self.send_header('Location', '/echo?relative=1#part')
            if path == '/outside': self.send_header('Location', 'http://outside.invalid/')
            if path == '/cookies':
                self.send_header('Set-Cookie', 'host=a; Path=/; HttpOnly')
                self.send_header('Set-Cookie', 'domain=a; Domain=localhost; Path=/')
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(('<a href="' + origins.get('b', '') + '/echo">Other site</a>'
                '<p>' + self.headers.get('Cookie', '') + '</p>').encode())

        def do_POST(self):
            body = self.rfile.read(int(self.headers['Content-Length']))
            events.append({'port': self.server.server_port, 'path': self.path, 'body': body.decode(),
                           'origin': self.headers.get('Origin'), 'referer': self.headers.get('Referer')})
            self.send_response(200); self.send_header('Content-Type', 'application/json'); self.end_headers()
            self.wfile.write(json.dumps({'url': origins['b'] + '/echo', 'body': json.loads(body)}).encode())

    with ExitStack() as stack:
        for key in ('a', 'b'):
            server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
            thread = Thread(target=server.serve_forever, daemon=True); thread.start()
            stack.callback(server.server_close); stack.callback(server.shutdown)
            origins[key] = f'http://localhost:{server.server_port}'
        rows = [{'site_id': k, 'name': k, 'kind': 'retailer', 'origin': v} for k, v in origins.items()]
        identity = OriginMap(rows, world_id='fixture')
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            c1 = browser.new_context(service_workers='block'); c2 = browser.new_context(service_workers='block')
            p1 = c1.new_page(); p2 = c2.new_page()
            bridge1 = LocalOriginBridge(identity); bridge1.attach(c1)
            bridge2 = LocalOriginBridge(identity); bridge2.attach(c2)
            stack.callback(bridge1.close); stack.callback(bridge2.close)
            p1.goto('https://a.test/cookies')
            assert {c['name'] for c in c1.cookies()} == {'host', 'domain'}
            assert all(c['domain'] in ('a.test', '.a.test') for c in c1.cookies())
            assert c2.cookies() == []
            p1.evaluate("localStorage.setItem('selection','42')")
            p1.goto('https://a.test/echo'); assert 'host=a' in p1.locator('p').inner_text()
            p1.get_by_role('link', name='Other site').click()
            assert p1.url == 'https://b.test/echo' and p1.locator('p').inner_text() == ''
            assert p1.evaluate("localStorage.getItem('selection')") is None
            p2.goto('https://a.test/echo'); assert p2.locator('p').inner_text() == ''
            assert p2.evaluate("localStorage.getItem('selection')") is None
            p1.goto('https://a.test/echo')
            assert p1.evaluate("localStorage.getItem('selection')") == '42'
            result = p1.evaluate("""async()=>await (await fetch('/api/quote',{
                method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({size:'42'})})).json()""")
            assert result == {'url': 'https://b.test/echo', 'body': {'size': '42'}}
            posted = next(e for e in events if 'body' in e)
            assert posted['origin'] == origins['a'] and posted['referer'].startswith(origins['a'])
            p1.goto('https://a.test/redirect')
            assert p1.url == 'https://b.test/echo?x=a%2Bb#part'
            p1.goto('https://a.test/relative')
            assert p1.url == 'https://a.test/echo?relative=1#part'
            assert p1.evaluate("async()=>{const r=await fetch('/outside');return [r.status,await r.text()]}") == [502, 'Off-world redirect rejected']
            before = len(events)
            assert p1.evaluate("async()=>{try{await fetch('http://outside.invalid/');return false}catch{return true}}")
            assert len(events) == before
            assert all(not e['cookie'] for e in events if e['port'] == urlsplit(origins['b']).port and 'cookie' in e)
            assert 'localhost:' not in p1.content()
            c1.close(); c2.close()
            assert bridge1.closed and bridge2.closed
            browser.close()


@pytest.mark.parametrize('method', ['GET', 'POST'])
def test_expired_ack_inside_real_cdp_callback_does_not_poison_following_navigation(method):
    """Consume an ID, then deliver its late ack inside the same real callback.

    Chromium produces the real expired-ID error. Explicitly use the pinned
    Playwright dispatch error sink for a leaked callback error: greenlet timing
    can otherwise print it through asyncio without storing Connection._error.
    The HTTP request (including the mutation) is forwarded once.
    """
    forwarded=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            forwarded.append(('GET',self.path))
            body=b'<html><title>healthy</title><body>ok</body></html>'
            self.send_response(200);self.send_header('Content-Type','text/html');self.end_headers();self.wfile.write(body)
        def do_POST(self):
            forwarded.append(('POST',self.path))
            self.send_response(200);self.end_headers();self.wfile.write(b'committed')
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    identity=OriginMap([dict(site_id='a',name='a',kind='retailer',
                            origin=f'http://localhost:{server.server_port}')],world_id='expired-ack')
    bridge=LocalOriginBridge(identity)
    original=bridge._paused
    def paused(session,event):
        original(session,event)
        if event['request']['url']=='https://a.test/abandon':
            request=SimpleNamespace(url=event['request']['url'],method=event['request']['method'],
                _phase_request_id=event['requestId'],_phase_network_id=event.get('networkId'))
            try:
                bridge._send_cdp(session,'Fetch.fulfillRequest',{
                    'requestId':event['requestId'],'responseCode':200,'body':''},request)
            except PlaywrightError as error:
                # Model dispatch -> _on_event_listener_error from Playwright
                # 1.44. This test-only access must never appear in the bridge.
                session._impl_obj._connection._on_event_listener_error(error)
    bridge._paused=paused
    try:
        with sync_playwright()as pw:
            browser=pw.chromium.launch()
            try:
                context=browser.new_context(service_workers='block');page=context.new_page();bridge.attach(context)
                page.goto('https://a.test/start')
                if method=='GET':page.goto('https://a.test/abandon')
                else:assert page.evaluate("async()=>await(await fetch('/abandon',{method:'POST',body:'one mutation'})).text()")=='committed'
                page.goto('https://a.test/after',timeout=3000)
                assert page.title()=='healthy'
                assert forwarded.count((method,'/abandon'))==1
                assert bridge.expired_interception_ack_count==1
                assert bridge.expired_interception_acknowledgements[0]['backend_effects']=='unknown'
                assert bridge.expired_interception_acknowledgements[0]['replayed'] is False
                context.close()
            finally:browser.close()
    finally:
        bridge.close();server.shutdown();server.server_close();thread.join(3)
