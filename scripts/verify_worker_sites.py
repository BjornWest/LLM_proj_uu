"""Zero-model real browser/private-read acceptance on a dedicated worker lease.

Does not use manual clones or shared benchmark sites. Closing the lease performs
the normal full reset; never requests caller-selected SQL or container mutation.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from intent_browser.worker_sites import WorkerSites
from data.curation.worker_integration.bindings import load_registry, contract_for
from data.curation.worker_integration.private_http import get_page


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--task', required=True, choices=['webarena:407', 'webarena:467', 'webarena:630'])
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--service', default='http://127.0.0.1:8897')
    p.add_argument('--token-file', type=Path, default=ROOT / '.local/worker-sites/token')
    p.add_argument('--registry', type=Path, default=ROOT / '.local/curation-expansion/worker-registry-v2.json')
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=False)
    os.environ['LD_LIBRARY_PATH'] = str(ROOT / '.local/system-libs/usr/lib/x86_64-linux-gnu') + ':' + os.getenv('LD_LIBRARY_PATH', '')
    from playwright.sync_api import sync_playwright
    row = next(r for r in load_registry(a.registry)['tasks'] if r['id'] == a.task)
    contract = contract_for(ROOT, row)
    token = a.token_file.read_text().strip()
    service = WorkerSites(a.service, token)
    lease = service.acquire(a.task, row['revision'], str(uuid4()))
    report = {'task_id': a.task, 'revision': row['revision'], 'model_calls': 0, 'checks': {},
              'source_sha256': {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in
                   [Path(__file__), ROOT / 'scripts/worker_site_service.py', ROOT / 'scripts/worker_site_state.py',
                    ROOT / 'scripts/worker_site_clones.py', ROOT / 'intent_browser/worker_sites.py',
                    ROOT / 'data/curation/worker_integration/private_http.py']}}
    checks = report['checks']
    try:
        identity = lease.attest(); report['identity'] = identity
        checks['dedicated_identity'] = bool(identity['container_id'] and identity['reset_report_sha256'])
        if row['family'] == 'webarena.wishlist':
            state = lease.state_read('shopping.wishlist_state', {})
            checks['fresh_wishlist'] = state['items'] == [] and state['options'] == []
            checks['fixture_owner'] = state['owner']['email'] == 'emma.lopez@gmail.com'
            path = '/customer/account/'
        elif row['family'] == 'webarena.votes':
            state = lease.state_read('forum.vote_state', {'target_id': contract['grader_input']['target_id']})
            checks['neutral_vote'] = state['vote'] == [] and len(state['target']) == 1
            checks['both_newest_orders'] = bool(state['ui_newest'] and state['timestamp_newest'])
            path = '/user/MarvelsGrantMan136'
        else:
            state = lease.state_read('forum.submission_ids', {})
            checks['full_baseline'] = len(state) > 100 and all(type(i) is int for i in state)
            checks['no_new_posts'] = lease.state_read('forum.posts_since', {'baseline_ids': state}) == []
            path = '/user/MarvelsGrantMan136'
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            context = browser.new_context(proxy=lease.browser_proxy, record_har_path=str(a.output / 'browser.har'), record_har_content='embed')
            try:
                first = get_page(browser_context=context, origin=lease.origin, path=path, headers={}, proxy=lease.browser_proxy)
                checks['private_read'] = first.status == 200
                before_cookies = context.cookies(lease.origin)
                checks['server_cookies_received'] = bool(before_cookies)
                page = context.new_page(); response = page.goto(lease.origin + path, timeout=60000)
                checks['browser_site'] = response.status == 200
                (a.output / 'page-title.json').write_text(json.dumps({'title': page.title(), 'url': page.url}))
                last = get_page(browser_context=context, origin=lease.origin, path=path, headers={}, proxy=lease.browser_proxy)
                checks['private_final_read'] = last.status == 200
                response = page.goto('http://outside.invalid/worker-isolation-check', timeout=15000)
                checks['foreign_browser_blocked'] = response.status == 403
                checks['same_identity_after_reads'] = lease.attest() == identity
            finally:
                context.close(); browser.close()
        raw = (a.output / 'browser.har').read_bytes()
        proxy = lease.browser_proxy
        basic = base64.b64encode((proxy['username'] + ':' + proxy['password']).encode())
        checks['no_control_or_lease_secret_in_har'] = all(s not in raw for s in [token.encode(), proxy['password'].encode(), basic])
        entries = json.loads(raw)['log']['entries']
        checks['no_proxy_headers_in_har'] = all(h['name'].lower() not in ('proxy-authorization', 'x-daylight-lease') for e in entries for h in e['request']['headers'])
        report['har_sha256'] = hashlib.sha256(raw).hexdigest()
        checks['unchanged_sources'] = all(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == sha for name, sha in report['source_sha256'].items())
        report['passed'] = all(checks.values())
    finally:
        try: lease.close()
        finally:
            service.close()
            (a.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'task': a.task, 'checks': checks, 'passed': report['passed']}))
    if not report['passed']: raise SystemExit(1)


if __name__ == '__main__': main()
