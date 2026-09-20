"""Actual saved worker failure through real authenticated API and shared viewer."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from uuid import uuid4
from playwright.sync_api import sync_playwright, expect
ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--episode', required=True, type=Path)
args = parser.parse_args()
os.environ['LD_LIBRARY_PATH'] = str(ROOT / '.local/system-libs/usr/lib/x86_64-linux-gnu') + ':' + os.environ.get('LD_LIBRARY_PATH', '')
out = ROOT / '.local/vercel-demo' / ('worker-replay-' + uuid4().hex[:8]); out.mkdir(parents=True)
env = dict(os.environ, REPLAY_EPISODE=str(args.episode.resolve()))
process = subprocess.Popen(['node', 'tests/worker-replay-server.mjs'], cwd=ROOT/'deploy/daylight', stdout=subprocess.PIPE, text=True, env=env)
info = json.loads(process.stdout.readline()); origin = 'http://127.0.0.1:' + str(info['port']); checks = []
def check(name, condition):
    assert condition, name
    checks.append(name)
    print('PASS', name, flush=True)
try:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={'width': 1512, 'height': 1040}); errors = []; writes = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('request', lambda r: writes.append(r.url) if r.method == 'POST' and not r.url.endswith('/login') else None)
        page.goto(origin + '/workspace/replays')
        page.get_by_label('Your invitation code').fill('local-replay-code-'*3)
        page.get_by_role('button', name='Open demo').click()
        page.goto(origin + '/workspace/replays?run=h:' + info['id'])
        frame = page.frame_locator('#shared-trace-viewer')
        expect(frame.locator('#chat .bubble')).not_to_have_count(0)
        check('Finished worker history opens shared viewer', 'source=harness' in page.locator('#shared-trace-viewer').get_attribute('src'))
        expect(page.locator('#run-viewer')).to_be_hidden()
        check('Old finished replay frame is hidden', True)
        data = page.request.get(origin + '/api/harness/jobs/' + info['id'] + '/session').json()
        source = [json.loads(line) for line in (args.episode/'steps.jsonl').read_text().splitlines()]
        responses = [json.loads(m['text']) for m in data['messages'] if m['title'] == 'Raw model response']
        check('Every raw response equals retained source', responses == [s['model_response'] for s in source])
        final = responses[-1]['choices'][0]
        check('Malformed final tool-call response remains visible', final['finish_reason'] == 'tool_calls' and 'tool_calls' not in final['message'])
        check('Final reasoning retained', bool(final['message'].get('reasoning')))
        expect(frame.locator('.browser-recorded-outcome')).to_contain_text('native tool call')
        check('Original ZIP link is available', frame.get_by_role('link', name='Download unchanged original trace ZIP').get_attribute('href').endswith('/trace'))
        frame.get_by_role('button', name='Tools only', exact=True).click()
        expect(frame.locator('.trace-tool-event')).to_have_count(4)
        check('Four actual tool actions, no invented fifth', True)
        frame.get_by_role('button', name='Replay', exact=True).click()
        image = frame.locator('.browser-replay-stage img')
        expect(image).to_be_visible(); expect(image).to_have_js_property('complete', True)
        check('Authorized saved image renders', image.evaluate('e=>e.naturalWidth') > 0)
        frame.get_by_role('button', name='Next →', exact=True).click()
        expect(frame.locator('.browser-replay [role=status]')).to_contain_text('Step 1')
        check('Shared step replay navigates', True)
        page.screenshot(path=str(out/'replay.png'))
        page.goto(origin + '/harness?activity=replay&embed=1#' + info['id'])
        page.wait_for_url('**/trace-viewer?**')
        check('Legacy replay deep link redirects to shared viewer', 'source=harness' in page.url)
        check('No model or browser-agent actions requested', not writes)
        check('No JavaScript errors', not errors)
        browser.close()
    sources = ['deploy/daylight/client/workspace.js','deploy/daylight/client/harness.js','deploy/daylight/client/trace-browser.js','deploy/daylight/lib/worker-replay.mjs','scripts/project_worker_trace.py']
    (out/'report.json').write_text(json.dumps({'checks':checks,'passed':True,'model_calls':0,'source_sha256':{s:hashlib.sha256((ROOT/s).read_bytes()).hexdigest() for s in sources}},indent=2)+'\n')
    print(out/'report.json')
finally:
    process.terminate(); process.wait(timeout=15)
