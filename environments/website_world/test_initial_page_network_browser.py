"""Real LocalOriginBridge dual interception: held, completed and canceled work."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from time import monotonic
import base64

import pytest
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

from .local_origins import OriginMap, LocalOriginBridge, InitialPageNetwork


@pytest.mark.parametrize('finish', ['complete', 'held', 'cancel', 'complete-redirect', 'cancel-post'])
def test_dual_interception_real_network_quietness(finish):
    events = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_GET(self):
            events.append(self.path)
            if self.path == '/redirect':
                self.send_response(302);self.send_header('Location','/final');self.end_headers();return
            mode = 'setTimeout(()=>console.log("release-held"),1100);' if finish.startswith('complete') else (
                'setTimeout(()=>controller.abort(),750);' if finish.startswith('cancel') else '')
            method = ',method:"POST",body:"x"' if finish == 'cancel-post' else ''
            html = ('<html><body><main>ready</main><script>'
                    'const controller=new AbortController();'
                    'addEventListener("load",()=>{fetch("/held",{signal:controller.signal' + method + '}).catch(()=>{});'
                    + mode + '});</script></body></html>').encode()
            self.send_response(200); self.send_header('Content-Type', 'text/html'); self.end_headers(); self.wfile.write(html)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    Thread(target=server.serve_forever, daemon=True).start()
    identity = OriginMap([{'site_id':'shop','name':'shop','kind':'retailer',
                          'origin':f'http://localhost:{server.server_port}'}],world_id='network-quietness')
    bridge = LocalOriginBridge(identity)
    held = []
    original = bridge._forward_paused
    def forward(session, event, request):
        if request.url == 'https://shop.test/held':
            held.append((session, event, request))
            return  # Deliberately hold a real intercepted request, never replay it.
        return original(session, event, request)
    bridge._forward_paused = forward
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                context = browser.new_context(service_workers='block')
                page = context.new_page()
                requests = []
                page.on('request', lambda request:requests.append(request))
                def console(message):
                    if message.text == 'release-held':
                        session, event, request = held[0]
                        bridge._send_cdp(session,'Fetch.fulfillRequest',{
                            'requestId':event['requestId'],'responseCode':200,
                            'body':base64.b64encode(b'complete').decode()},request)
                page.on('console', console)
                with InitialPageNetwork(page) as tracker:
                    bridge.attach(context)
                    page.goto('https://shop.test/redirect' if finish=='complete-redirect' else 'https://shop.test/', timeout=5000)
                    # Reproduce the rejected oracle: Playwright sees zero traffic.
                    page.wait_for_load_state('networkidle', timeout=2000)
                    assert held and not requests
                    started = monotonic()
                    if finish == 'held':
                        with pytest.raises(PlaywrightTimeoutError):
                            tracker.wait(timeout_ms=850, quiet_ms=100)
                        assert tracker.record['status'] == 'failed'
                        assert tracker.record['pending_requests'] == 1
                    else:
                        result = tracker.wait(timeout_ms=2000, quiet_ms=100)
                        assert result['status'] == 'passed' and result['pending_requests'] == 0
                        assert monotonic() - started >= (.5 if finish.startswith('complete') else .2)
                        if finish == 'complete-redirect':
                            assert result['redirect_hops'] >= 1
                        if finish.startswith('cancel'):
                            assert result['failed_requests'] >= 1
                        if finish=='cancel-post':
                            assert result['failed_mutations'] == 1
                            assert result['failed_mutation_backend_effects']=='unknown'
                    assert events == (['/redirect','/final'] if finish=='complete-redirect' else ['/'])  # Held GET never forwarded to backend.
            finally:
                browser.close()
    finally:
        bridge.close();server.shutdown();server.server_close()
