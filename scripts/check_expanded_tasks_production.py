"""Read-only live catalog/launch-dialog check. Never creates a job or model call."""
import argparse
import hashlib
import json
import os
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--origin', default='https://browseragent.vercel.app')
    p.add_argument('--assets', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args(); args.output.mkdir(parents=True, exist_ok=False)
    os.environ['LD_LIBRARY_PATH'] = str(ROOT / '.local/system-libs/usr/lib/x86_64-linux-gnu') + ':' + os.getenv('LD_LIBRARY_PATH', '')
    expected = json.loads((ROOT / 'config/expanded_team_tasks.json').read_text())['tasks']
    value = json.loads((ROOT / '.local/vercel-demo/invitation-codes.json').read_text())['bjorn']
    code = value if isinstance(value, str) else value['code']
    checks, writes, errors = [], [], []
    def check(name, passed):
        assert passed, name
        checks.append(name)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        context = browser.new_context(viewport={'width': 1440, 'height': 1000})
        check('Anonymous config denied', context.request.get(args.origin + '/api/harness/config').status == 401)
        response = context.request.post(args.origin + '/login', form={'code': code}, headers={'Origin': args.origin}, max_redirects=0)
        check('Invitation login', response.status == 303)
        config = context.request.get(args.origin + '/api/harness/config').json()
        actual = {row['id']: row for row in config['tasks'] if row.get('expanded')}
        check('Exactly 203 expanded entries', len(actual) == len(expected) == 203)
        check('Live worker online', config['worker']['online'] and config['worker']['mode'] == 'live')
        check('Every exact reviewed goal/revision/site available', all(actual[row['id']]['available'] is True and all(actual[row['id']][k] == row[k] for k in ('goal', 'revision', 'site_id')) for row in expected))
        for name in ('workspace.js', 'workspace.html', 'workspace.css'):
            url = '/' if name.endswith('.html') else '/assets/' + name
            response = context.request.get(args.origin + url)
            check('Exact committed asset ' + name, response.status == 200 and response.body() == (args.assets / name).read_bytes())
        page = context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))
        def readonly(route):
            if route.request.method not in ('GET', 'HEAD'):
                writes.append(route.request.url); route.abort()
            else: route.continue_()
        page.route('**/api/**', readonly)
        for site in sorted({row['site_id'] for row in expected}):
            rows = [row for row in expected if row['site_id'] == site]
            row = rows[0]
            page.goto(args.origin + '/workspace?site=' + site + '&view=research')
            expect(page.locator('#catalog-readiness')).to_have_text(f'{len(rows)} of {len(rows)} available to the agent', timeout=30000)
            page.locator('#catalog-search').fill(row['id'])
            page.locator('#catalog-cards button').first.click()
            expect(page.locator('#catalog-launch')).to_be_visible()
            page.locator('#catalog-launch').click()  # Opens review only; never clicks Try task.
            expect(page.locator('#dialog-goal')).to_have_text(row['goal'])
            expect(page.locator('#try-task')).to_be_enabled()
            check(site + ' exposes exact ready task dialog', row['revision'] in page.locator('#dialog-task-facts').inner_text())
        page.screenshot(path=str(args.output / 'launch-dialog.png'))
        check('No browser errors', not errors)
        check('No API writes, jobs or model calls', not writes)
        browser.close()
    report = {'passed': True, 'checks': checks, 'model_calls': 0, 'api_writes_after_login': writes,
              'origin': args.origin, 'tasks': len(actual), 'scope': 'Read-only production config, exact assets, six launch dialogs; no live inference',
              'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (args.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'passed': True, 'checks': len(checks), 'tasks': len(actual)}))


if __name__ == '__main__': main()
