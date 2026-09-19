"""Read-only production catalog/UI acceptance. No task or inference dispatch.

Uses existing local invitation-signing settings without printing or saving them.
One browser session intentionally switches all sites to check filter reset and
the combined workspace; this is not a new benchmark execution.
"""
import argparse
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import time
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[3]


def run(base_url, access_env, output):
    from dotenv import dotenv_values
    from playwright.sync_api import sync_playwright, expect

    output.mkdir(parents=True, exist_ok=False)
    catalog_path = ROOT/'data/curation/expansion/hosted-review-catalog.json'
    expected = json.loads(catalog_path.read_text())
    settings = dotenv_values(access_env)
    invites = json.loads(settings['DEMO_INVITES_JSON'])
    owner = next(iter(invites))
    b64 = lambda raw: base64.urlsafe_b64encode(raw).rstrip(b'=').decode()
    body = b64(json.dumps({'id': owner, 'hash': invites[owner],
                          'expires': int(time.time()*1000)+1800000}, separators=(',', ':')).encode())
    sig = b64(hmac.new(settings['DEMO_SESSION_SECRET'].encode(), body.encode(), hashlib.sha256).digest())
    cookie = body+'.'+sig
    report = {'schema': 'hosted-review-live-acceptance-v1', 'base_url': base_url,
              'catalog_sha256': hashlib.sha256(catalog_path.read_bytes()).hexdigest(),
              'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'checks': [], 'sites': [], 'non_get_attempts': [], 'page_errors': [],
              'model_calls': 0, 'benchmark_runs': 0, 'passed': False}
    try:
        class NoRedirect(HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None
        opener = build_opener(NoRedirect())
        def fetch(headers):
            try:
                with opener.open(Request(base_url+'/api/task-catalog', headers=headers), timeout=30) as response:
                    return response.status, response.read()
            except HTTPError as response:
                return response.code, response.read()
        status, _ = fetch({})
        assert status == 401, 'Catalog must require invitation authentication'
        status, content = fetch({'Cookie': 'daylight_session='+cookie})
        assert status == 200, f'Authenticated catalog HTTP {status}'
        assert json.loads(content) == expected, 'Production catalog differs from reviewed projection'
        (output/'catalog-response.json').write_bytes(content)
        report['checks'].append('Authenticated exact catalog; unauthenticated request denied')
        os.environ['LD_LIBRARY_PATH'] = str(ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu')+':'+os.environ.get('LD_LIBRARY_PATH', '')
        expect.set_options(timeout=30000)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(viewport={'width': 1440, 'height': 1000})
            context.add_cookies([{'name': 'daylight_session', 'value': cookie,
                                 'url': base_url, 'httpOnly': True,
                                 'secure': base_url.startswith('https:'), 'sameSite': 'Strict'}])

            def route(request):
                if request.request.method not in {'GET', 'HEAD'}:
                    report['non_get_attempts'].append({'method': request.request.method,
                                                     'path': urlsplit(request.request.url).path})
                    request.abort()
                else:
                    request.continue_()
            context.route('**/*', route)
            page = context.new_page()
            page.on('pageerror', lambda error: report['page_errors'].append(str(error)))
            page.goto(base_url+'/workspace?site=tricky-shop&view=research', wait_until='domcontentloaded')
            expect(page.locator('#catalog-status')).to_contain_text('203 review objectives')
            for site in expected['sites']:
                site_id = site['id']
                tasks = [task for task in expected['tasks'] if task['site_id'] == site_id]
                page.locator(f'.site-choice[data-site="{site_id}"]').click()
                page.locator('#research-tab').click()
                expect(page.locator('#catalog-heading')).to_contain_text(str(len(tasks))+' review objectives')
                expect(page.locator('#catalog-search')).to_have_value('')
                while page.locator('#catalog-more').is_visible():
                    page.locator('#catalog-more').click()
                cards = page.locator('#catalog-cards [data-catalog-task]')
                expect(cards).to_have_count(len(tasks))
                actual = cards.evaluate_all('(rows)=>Object.fromEntries(rows.map(r=>[r.dataset.catalogTask,r.querySelector(".catalog-goal").textContent]))')
                assert actual == {task['id']: task['goal'] for task in tasks}, site_id
                selected = tasks[0]
                page.locator('#catalog-search').fill(selected['id'])
                expect(cards).to_have_count(1)
                cards.locator('button').click()
                expect(page.locator('#catalog-dialog-goal')).to_have_text(selected['goal'])
                expect(page.locator('#catalog-dialog')).to_contain_text('launch unavailable')
                if site['client_url']:
                    expect(page.locator('#catalog-dialog-browse a')).to_have_attribute('href', site['client_url'])
                page.get_by_role('button', name='Close review objective', exact=True).click()
                report['sites'].append({'id': site_id, 'exact_ids_and_goals': len(tasks),
                                        'search_and_dialog': True})
            assert not report['non_get_attempts'], 'Inspection attempted a state-changing request'
            assert not report['page_errors'], 'Browser JavaScript errors occurred'
            report['checks'].append('All 203 rendered goals, six site groups, pagination, search, dialogs and site-switch reset')
            browser.close()
        report['passed'] = True
        return report
    finally:
        (output/'report.json').write_text(json.dumps(report, indent=2)+'\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='https://browseragent.vercel.app')
    parser.add_argument('--access-env', type=Path, default=ROOT/'.local/vercel-demo/access.env')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    result = run(args.base_url.rstrip('/'), args.access_env, args.output)
    print(json.dumps({'passed': result['passed'], 'sites': result['sites'], 'report': str(args.output/'report.json')}))
