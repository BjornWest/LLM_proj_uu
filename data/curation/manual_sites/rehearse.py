"""Native browser write followed by whole-container reset, no inference.

Provisioning-only transport maps the canonical proxy origin to one clone. It
does not exercise production authentication, leases, proxy revocation or UI.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
from urllib.parse import urlsplit

from .clones import CANONICAL, ROOT, SITES, command, inspect, upstream

# Public benchmark fixture identities, not deployed access credentials.
HEADERS = {
    'shopping': {'X-M2-Customer-Auto-Login': 'emma.lopez@gmail.com:Password.123'},
    'forum': {'X-Postmill-Auto-Login': 'MarvelsGrantMan136:test1234'},
}


def state(site):
    inspect(site)
    name = SITES[site]['name']
    if site == 'forum':
        sql = "SELECT json_build_object('username',username,'biography',biography) FROM users WHERE username='MarvelsGrantMan136'"
        return json.loads(command('docker', 'exec', '--user', 'postgres', name, 'psql', '-v', 'ON_ERROR_STOP=1', '-d', 'postmill', '-Atc', sql))
    # Credentials stay inside the container, never exported in artifacts.
    php = '$e=require "/var/www/magento2/app/etc/env.php";$c=$e["db"]["connection"]["default"];$p=new PDO("mysql:host=".$c["host"].";dbname=".$c["dbname"],$c["username"],$c["password"],[PDO::ATTR_ERRMODE=>PDO::ERRMODE_EXCEPTION]);echo json_encode($p->query($argv[1])->fetchAll(PDO::FETCH_ASSOC));'
    sql = "SELECT w.wishlist_id,w.customer_id,i.wishlist_item_id,i.product_id,i.qty,i.description FROM customer_entity c JOIN wishlist w ON w.customer_id=c.entity_id LEFT JOIN wishlist_item i ON i.wishlist_id=w.wishlist_id WHERE c.email='emma.lopez@gmail.com' ORDER BY i.wishlist_item_id"
    return json.loads(command('docker', 'exec', name, 'php', '-r', php, sql))


def native_write(site, output):
    from playwright.sync_api import sync_playwright
    events = []; errors = []; blocked = []
    class Forward(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def forward(self):
            parts = urlsplit(self.path)
            if parts.scheme != 'http' or parts.netloc != urlsplit(CANONICAL).netloc:
                blocked.append({'method': self.command, 'url': self.path})
                self.send_error(403); return
            suffix = parts.path + ('?' + parts.query if parts.query else '')
            headers = {k: v for k, v in self.headers.items() if k.lower() not in ('proxy-connection', 'connection', 'host')}
            headers.update(HEADERS[site]); headers['Host'] = urlsplit(CANONICAL).netloc
            body = self.rfile.read(int(self.headers.get('Content-Length', '0'))) or None
            conn = http.client.HTTPConnection('127.0.0.1', SITES[site]['port'], timeout=120)
            try:
                conn.request(self.command, suffix, body=body, headers=headers)
                response = conn.getresponse(); payload = response.read()
                events.append({'method': self.command, 'canonical_url': self.path, 'upstream_path': suffix, 'status': response.status})
                self.send_response(response.status)
                for k, v in response.getheaders():
                    if k.lower() not in ('transfer-encoding', 'connection', 'content-length'):
                        self.send_header(k, v)
                self.send_header('Content-Length', str(len(payload))); self.end_headers()
                if self.command != 'HEAD': self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError) as error:
                events.append({'method': self.command, 'canonical_url': self.path, 'client_disconnected': type(error).__name__})
            finally:
                conn.close()
        do_GET = do_HEAD = do_POST = forward
    server = ThreadingHTTPServer(('127.0.0.1', 0), Forward)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, proxy={'server': f'http://127.0.0.1:{server.server_port}'})
        context = browser.new_context(service_workers='block')
        context.tracing.start(screenshots=True, snapshots=True, sources=False)
        page = context.new_page(); page.set_default_timeout(30000)
        page.on('pageerror', lambda e: errors.append(str(e)))
        def snap(label):
            page.screenshot(path=str(output / (label + '.png')), full_page=True)
            (output / (label + '.txt')).write_text(page.locator('body').inner_text())
        try:
            if site == 'shopping':
                page.goto(CANONICAL + '/customer/account/', wait_until='load', timeout=120000)
                snap('account')
                page.goto(CANONICAL + '/elmwood-inn-fine-teas-orange-vanilla-caffeine-free-fruit-infusion-16-ounce-pouch.html', wait_until='load', timeout=120000)
                snap('before')
                page.locator('.product-info-main a[data-action="add-to-wishlist"]').click()
                page.wait_for_url('**/wishlist/**', timeout=120000)
                page.locator('.products-grid.wishlist').wait_for(state='visible')
                snap('after')
            else:
                page.goto(CANONICAL + '/', wait_until='load', timeout=120000)
                page.get_by_role('button', name='MarvelsGrantMan136').click()
                page.get_by_role('link', name='Profile', exact=True).click()
                page.get_by_role('link', name='Edit biography', exact=True).click()
                snap('before')
                page.locator('textarea').fill('Disposable manual-session reset rehearsal; remove on whole-container reset.')
                page.get_by_role('button', name='Save', exact=True).click()
                page.get_by_text('The biography was updated.', exact=True).wait_for()
                page.get_by_role('link', name='/u/MarvelsGrantMan136', exact=True).click()
                page.get_by_role('complementary').get_by_text('Disposable manual-session reset rehearsal; remove on whole-container reset.', exact=True).wait_for()
                snap('after')
        finally:
            context.tracing.stop(path=str(output / 'browser-trace.zip'))
            (output / 'browser.json').write_text(json.dumps({'transport': 'temporary loopback HTTP forwarder for canonical-origin native browsing; not deployed lease proxy', 'requests': events, 'page_errors': errors, 'blocked_requests': blocked, 'final_url': page.url}, indent=2) + '\n')
            browser.close(); server.shutdown(); server.server_close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site', choices=SITES, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); args.output.mkdir(parents=True, exist_ok=False)
    lib = ROOT / '.local/system-libs/usr/lib/x86_64-linux-gnu'
    os.environ['LD_LIBRARY_PATH'] = str(lib) + ':' + os.environ.get('LD_LIBRARY_PATH', '')
    before = inspect(args.site); initial = state(args.site)
    sources = [Path(__file__), Path(__file__).with_name('clones.py')]
    source_hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    (args.output / 'sources').mkdir()
    for source in sources:
        (args.output / 'sources' / source.name).write_bytes(source.read_bytes())
    report = {'schema': 'manual-site-reset-rehearsal-v1', 'site': args.site, 'before': before,
              'initial_state': initial, 'model_calls': 0, 'production_verified': False,
              'limitations': ['Single native saved mutation, not exhaustive database verification.', 'Provisioning transport only; lease revocation and deployment require independent backend acceptance.']}
    (args.output / 'initial.json').write_text(json.dumps(report, indent=2) + '\n')
    try:
        if args.site == 'shopping' and any(row['wishlist_item_id'] is not None for row in initial):
            raise ValueError('Rehearsal requires a freshly recreated empty wishlist baseline')
        if args.site == 'forum' and 'Disposable manual-session reset rehearsal' in (initial['biography'] or ''):
            raise ValueError('Prior rehearsal mutation remains; recreate before repeating')
        native_write(args.site, args.output)
        changed = state(args.site); report['changed_state'] = changed
        if changed == initial:
            raise AssertionError('Native browser write did not change state')
        # Sequential by design: mutation must precede reset on this one owned clone.
        result = subprocess.run([sys.executable, '-m', 'data.curation.manual_sites.clones', 'reset', '--site', args.site,
                                 '--expected-id', before['Id'], '--output', str(args.output / 'reset')], cwd=ROOT, capture_output=True, text=True)
        (args.output / 'reset.stdout').write_text(result.stdout); (args.output / 'reset.stderr').write_text(result.stderr)
        result.check_returncode()
        report['after'] = inspect(args.site); report['restored_state'] = state(args.site)
        report['passed'] = report['after']['Id'] != before['Id'] and report['restored_state'] == initial
        if not report['passed']:
            raise AssertionError('Recreated container baseline mismatch')
    except Exception as e:
        report.update(passed=False, error=f'{type(e).__name__}: {e}'); raise
    finally:
        report['source_sha256'] = source_hashes
        report['artifacts_sha256'] = {str(p.relative_to(args.output)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(args.output.rglob('*')) if p.is_file() and p != args.output / 'report.json'}
        (args.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps({'site': args.site, 'passed': report['passed'], 'report': str(args.output / 'report.json')}))


if __name__ == '__main__':
    main()
