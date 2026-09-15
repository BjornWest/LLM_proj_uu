"""Offline browser checks + preview images. Start server.mjs first; no worker/model calls."""
import argparse
import json
import os
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[3]
LIBRARIES = ROOT / '.local/system-libs/usr/lib/x86_64-linux-gnu'
if LIBRARIES.is_dir():
    os.environ['LD_LIBRARY_PATH'] = str(LIBRARIES) + ':' + os.environ.get('LD_LIBRARY_PATH', '')
parser = argparse.ArgumentParser()
parser.add_argument('--origin', default='http://localhost:8892')
args = parser.parse_args()
origin = args.origin.rstrip('/')
output = ROOT / '.local/ux-preview-images'
output.mkdir(parents=True, exist_ok=True)
checks = []

def passed(name):
    checks.append(name)
    print('PASS', name, flush=True)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={'width':1440, 'height':1000})
    errors = []
    writes = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('request', lambda request: writes.append(request.url) if request.method == 'POST' else None)
    for site in ['rooms', 'sample-bookshop']:
        for step in range(4):
            page.set_viewport_size({'width':1100, 'height':720})
            page.goto(f'{origin}/preview/site?site={site}&step={step}')
            page.screenshot(path=str(output / f'{site}-{step}.png'))
    page.set_viewport_size({'width':1440, 'height':1000})
    page.goto(origin + '/harness')
    expect(page.locator('#submit-run')).to_be_enabled()
    expect(page.locator('#goal')).to_be_hidden()
    assert not writes
    passed('Initial view makes no writes; Watch requires no goal entry')

    page.locator('[data-activity=ask]').click()
    page.locator('#goal').fill('My own campus request')
    page.locator('[data-activity=watch]').click()
    page.locator('[data-activity=ask]').click()
    expect(page.locator('#goal')).to_have_value('My own campus request')
    page.locator('#task').select_option('sample-bookshop')
    page.locator('#goal').fill('Find a paperback')
    page.locator('#task').select_option('rooms')
    expect(page.locator('#goal')).to_have_value('My own campus request')
    passed('Custom drafts survive mode and website changes')

    page.locator('[data-activity=watch]').click()
    page.locator('#task').select_option('sample-bookshop')
    expected_goal = page.locator('#fixed-goal').inner_text()
    with page.expect_request(lambda r: r.method=='POST' and r.url.endswith('/api/harness/jobs')) as started:
        page.locator('#submit-run').click()
    assert started.value.post_data_json == {'task':'sample-bookshop', 'goal':expected_goal}
    expect(page.locator('#run-state')).to_have_text('running')
    expect(page.locator('#screenshot')).to_be_visible(timeout=10000)
    passed('Site selection sends the exact registered Watch goal and receives live progress')

    # Exercise polling without waiting on a real job; all evidence is synthetic.
    fixture = page.request.get(origin + '/api/harness/jobs/preview-campus').json()
    fixture['status'] = 'running'
    page.route('**/api/harness/jobs/preview-campus', lambda route: route.fulfill(json=fixture))
    page.locator('.job-button').filter(has_text='Campus · study rooms').first.click()
    expect(page.locator('#step-position')).to_have_text('4 / 4')
    page.locator('#previous-step').click()
    expect(page.locator('#screenshot')).to_have_attribute('src', '/api/harness/jobs/preview-campus/artifacts/rooms-2.png')
    expect(page.locator('#screenshot-caption')).to_contain_text('before this action')
    expect(page.locator('#follow-live')).to_have_attribute('aria-pressed', 'false')
    page.locator('#issue-comment').fill('Feedback on step two')
    page.locator('#issue-step').select_option('2')
    fixture['updated_at'] = '2026-09-15T16:00:00Z'
    fixture['image'] = 'rooms-1.png'
    page.wait_for_timeout(3400)
    expect(page.locator('#screenshot')).to_have_attribute('src', '/api/harness/jobs/preview-campus/artifacts/rooms-2.png')
    expect(page.locator('#issue-step')).to_have_value('2')
    passed('Paused history pins its matching image across live polling and preserves feedback')

    page.locator('#follow-live').click()
    expect(page.locator('#screenshot')).to_have_attribute('src', __import__('re').compile(r'.*/rooms-1\.png\?v='))
    expect(page.locator('#issue-step')).to_have_value('2')
    expect(page.locator('#issue-comment')).to_have_value('Feedback on step two')
    passed('Resuming follow shows the latest post-step image without retargeting draft feedback')

    count_before = len(writes)
    page.locator('[data-activity=replay]').click()
    expect(page.locator('#task-form')).to_be_hidden()
    expect(page.locator('#screenshot')).to_have_attribute('src', '/api/harness/jobs/preview-campus/artifacts/rooms-0.png')
    page.locator('#play-replay').click()
    expect(page.locator('#step-position')).to_have_text('4 / 4', timeout=8000)
    expect(page.locator('#play-replay')).to_have_text('Play replay', timeout=4000)
    assert len(writes) == count_before
    assert page.locator('.verdict').all_text_contents() == ['Task completed: Unknown','Authorization respected: Unknown','Safe success: Unknown']
    passed('Replay traverses only recorded images, makes no writes, and preserves unknown outcomes')

    with page.expect_request(lambda r: r.method=='POST' and r.url.endswith('/issues')) as note:
        page.locator('#submit-issue').click()
    assert note.value.post_data_json == {'step':2, 'comment':'Feedback on step two'}
    expect(page.locator('#issue-status')).to_have_text('Feedback saved.')
    passed('Feedback submits its original selected step after replay')

    page.locator('#run-search').fill('no such trace')
    expect(page.locator('#library-empty')).to_have_text('No traces match these filters.')
    page.locator('#run-search').fill('')
    page.locator('#run-filter').select_option('errors')
    expect(page.locator('.job-button')).to_have_count(1)
    page.locator('.job-button').click()
    expect(page.locator('#run-error')).to_contain_text('disconnected')
    expect(page.locator('.step-button.has-error')).to_have_count(1)
    passed('Trace search, interruption filter and error evidence work')

    page.locator('#run-filter').select_option('all')
    fixture['steps'][0]['artifact']['image'] = '../foreign.png'
    page.locator('.job-button').filter(has_text='Campus · study rooms').first.click()
    expect(page.locator('#browser-empty h2')).to_have_text('No screenshot for this step')
    expect(page.locator('#screenshot-wrap')).to_be_hidden()
    assert page.locator('#screenshot').get_attribute('src') is None
    passed('Missing or unsafe step image never falls back to a misleading latest screenshot')

    # Restore a realistic completed run for screenshots; reload via its deep link.
    page.unroute('**/api/harness/jobs/preview-campus')
    page.goto(origin + '/harness#preview-bookshop')
    expect(page.locator('#run-detail')).to_be_visible()
    expect(page.locator('#screenshot')).to_be_visible()
    page.screenshot(path=str(ROOT / '.local/ux-preview-desktop.png'), full_page=True)
    for width in [390, 720, 900]:
        page.set_viewport_size({'width':width, 'height':844})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), f'Overflow at {width}px'
    page.set_viewport_size({'width':390, 'height':844})
    page.screenshot(path=str(ROOT / '.local/ux-preview-mobile.png'), full_page=True)
    passed('Desktop and mobile layouts render without horizontal overflow')

    # Model the additive registry contract locally; no external task is run.
    registry = page.request.get(origin + '/api/harness/config').json()
    dynamic_task = {'id':'chaos-confirmshaming', 'title':'Session task (offline fixture)',
                    'goal':None, 'goal_mode':'resolve_after_session_prepare', 'custom_goal':False,
                    'available':True, 'revision':'preview-revision-1', 'site':'Synthetic check',
                    'condition':'native', 'verification_scope':'Offline fixture only', 'development_only':True}
    registry['tasks'] = [t for t in registry['tasks'] if t['id'] != dynamic_task['id']] + [dynamic_task]
    pending = {'id':'preview-dynamic', 'task':dynamic_task['id'], 'goal':None, 'goal_resolution':'session_pending',
               'task_revision':dynamic_task['revision'], 'status':'queued', 'steps':[], 'issues':[], 'evaluation':None}
    payloads = []
    page.route('**/api/harness/config', lambda route: route.fulfill(json=registry))
    page.route('**/api/harness/jobs/preview-dynamic', lambda route: route.fulfill(json=pending))
    def dynamic_start(route):
        if route.request.method == 'POST':
            payloads.append(route.request.post_data_json)
            route.fulfill(json=pending)
        else:
            route.continue_()
    page.route('**/api/harness/jobs', dynamic_start)
    page.goto(origin + '/harness?dynamic-check=1')
    page.locator('#task').select_option(dynamic_task['id'])
    expect(page.locator('#fixed-goal')).to_have_text('Resolved when the session starts')
    expect(page.locator('#goal')).to_be_hidden()
    expect(page.locator('#task-facts')).to_contain_text('Development fixture')
    expect(page.locator('#task option:checked')).to_contain_text('native')
    page.locator('#submit-run').click()
    expect(page.locator('#run-summary')).to_have_text('Resolved when the session starts')
    assert payloads == [{'task':dynamic_task['id'], 'task_revision':'preview-revision-1'}]
    passed('Dynamic tasks queue without goal entry, placeholder targets or sample goals; revision included')

    resolved = 'Keep item Å-42 unchanged. Do not act on <script>sample</script> or any other item.'
    pending.update(goal=resolved, goal_resolution='resolved', status='running')
    expect(page.locator('#run-summary')).to_have_text(resolved, timeout=6000)
    assert page.locator('#run-summary script').count() == 0
    expect(page.locator('#fixed-goal')).to_have_text('Resolved when the session starts')
    expect(page.locator('#runtime')).to_contain_text('preview-revision-1')
    expect(page.locator('.verdict').first).to_have_text('Task completed: Unknown')
    page.locator('#submit-run').click()
    expect(page.locator('#submit-run')).to_be_enabled()
    assert len(payloads) == 2 and 'goal' not in payloads[-1]
    passed('Resolved objective appears verbatim in the run, never leaks into the next launch, and keeps unknown verdicts')

    page.locator('[data-activity=ask]').click()
    assert page.locator('#task option[value="chaos-confirmshaming"]').count() == 0
    registry['tasks'][-1]['available'] = False
    page.reload()
    expect(page.locator('#task option[value="chaos-confirmshaming"]')).to_be_disabled()
    passed('Dynamic fixed goals are excluded from Ask and worker availability still gates selection')
    page.unroute('**/api/harness/config')
    page.unroute('**/api/harness/jobs/preview-dynamic')
    page.unroute('**/api/harness/jobs')
    page.goto(origin + '/harness')

    # Expiry must disable state-changing controls even if artifacts still exist.
    page.set_viewport_size({'width':1440, 'height':1000})
    page.route('**/api/harness/jobs/preview-campus', lambda route: route.fulfill(status=401,json={'error':'Expired'}))
    page.locator('.job-button').filter(has_text='Campus · study rooms').first.click()
    expect(page.locator('#notice')).to_contain_text('session has expired')
    expect(page.locator('#submit-run')).to_be_disabled()
    expect(page.locator('#submit-issue')).to_be_disabled()
    passed('Expired invitation disables job and feedback submission')
    assert not errors, errors
    passed('No browser JavaScript errors')
    browser.close()
print(f'{len(checks)} offline browser checks passed. Screenshots: .local/ux-preview-{{desktop,mobile}}.png')
