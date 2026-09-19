"""Synthetic proxy/cookie/HAR check including private httpx reads; no sites/model."""
import argparse
import base64
import json
import os
from pathlib import Path
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from playwright.sync_api import sync_playwright
from .bindings import ROOT, digest
from .private_http import get_page


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    secret = 'synthetic-secret-not-a-real-credential'
    auth = 'Basic ' + base64.b64encode(('job:' + secret).encode()).decode()
    seen = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            authenticated = self.headers.get('Proxy-Authorization') == auth
            seen.append({'url': self.path, 'authenticated': authenticated,
                         'fixture_cookie': 'fixture_session=one' in self.headers.get('Cookie', '')})
            if not authenticated:
                self.send_response(407)
                self.send_header('Proxy-Authenticate', 'Basic realm="Worker"')
                self.end_headers()
                return
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.send_header('Set-Cookie', 'fixture_session=one; Path=/')
            self.end_headers()
            self.wfile.write(b'<html><body>Local proxy test</body></html>')
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    os.environ['LD_LIBRARY_PATH'] = str(ROOT / '.local/system-libs/usr/lib/x86_64-linux-gnu') + ':' + os.getenv('LD_LIBRARY_PATH', '')
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            proxy = {'server': f'http://127.0.0.1:{server.server_port}', 'username': 'job', 'password': secret}
            context = browser.new_context(proxy=proxy, record_har_path=str(args.output / 'browser.har'), record_har_content='embed')
            page = context.new_page()
            # Actual adapter ordering: bootstrap API GET, browser, private final API GET.
            first = get_page(browser_context=context, origin='http://worker-environment.test', path='/account', headers={}, proxy=proxy)
            assert first.status == 200
            page.goto('http://worker-environment.test/task')
            last = get_page(browser_context=context, origin='http://worker-environment.test', path='/final', headers={}, proxy=proxy)
            assert last.status == 200
            context.close()
            browser.close()
        raw = (args.output / 'browser.har').read_bytes()
        assert secret.encode() not in raw and auth.encode() not in raw
        entries = json.loads(raw)['log']['entries']
        assert all(h['name'].lower() != 'proxy-authorization' for e in entries for h in e['request']['headers'])
        for suffix in ('/account', '/task', '/final'):
            matched = [r for r in seen if r['url'].endswith(suffix) and r['authenticated']]
            assert matched, suffix
            if suffix != '/account':
                assert matched[-1]['fixture_cookie'], suffix
        report = {'passed': True, 'requests': seen, 'har_sha256': digest(args.output / 'browser.har'),
            'proxy_secret_absent': True, 'private_httpx_proxy_used': True, 'server_cookie_shared': True,
            'scope': 'Synthetic proxy/session/recording compatibility, not real clone isolation or task acceptance',
            'source_sha256': digest(__file__), 'model_calls': 0}
        (args.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(report))
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
