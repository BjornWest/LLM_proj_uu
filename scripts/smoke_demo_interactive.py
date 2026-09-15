"""Exercise deployed-demo assist API with real navigation/selects and scripted model responses."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
from uuid import uuid4

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def main():
    os.environ['LD_LIBRARY_PATH'] = str(ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu') + ':' + os.environ.get('LD_LIBRARY_PATH', '')
    output = ROOT/'.local/vercel-demo'/('interactive-'+uuid4().hex[:8])
    output.mkdir(parents=True)
    process = subprocess.Popen(['node', 'tests/interactive-server.mjs'], cwd=ROOT/'deploy/daylight', stdout=subprocess.PIPE, text=True)
    origin = 'http://127.0.0.1:'+str(json.loads(process.stdout.readline())['port'])
    checks = []

    def check(name, passed):
        checks.append({'check': name, 'passed': bool(passed)})
        assert passed, name

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(origin)
            page.get_by_label('Your invitation code').fill('offline-interactive-code-'*3)
            page.get_by_role('button', name='Open demo').click()
            page.wait_for_selector('#site')

            def api(path, data=None):
                response = (page.request.post(origin+path, data=data, headers={'Origin': origin})
                            if data is not None else page.request.get(origin+path))
                assert response.ok, (response.status, response.text())
                return response.json()

            records = []
            for goal in ['When are study rooms available in Ångström on Wednesday for three people for 60 minutes?',
                         'Book the first available room in Ångström on Wednesday for three people for 60 minutes.']:
                page.locator('[data-area="shop"]').click()
                page.frame_locator('#site').get_by_role('heading', name='Ready for your next idea.').wait_for()
                id = api('/api/start', {'mode': 'assist', 'goal': goal})['id']
                for _ in range(12):
                    observation = page.evaluate('''async()=>{
                      const {snapshot}=await import('/assets/observation.js');
                      window.testCaptured=snapshot(document.querySelector('#site').contentDocument);
                      return window.testCaptured.observation;
                    }''')
                    decision = api('/api/step', {'id': id, 'observation': observation})
                    check('valid logged decision', not decision['error'])
                    action = decision['action']
                    target = next((c for c in observation['controls'] if c['id'] == action.get('id')), None)
                    page.evaluate('''async action=>{
                      const {execute}=await import('/assets/observation.js');
                      execute(action,window.testCaptured,document.querySelector('#site').contentDocument);
                    }''', action)
                    if target and target['tag'] == 'a':
                        page.frame_locator('#site').get_by_role('heading', name='Reserve a study room').wait_for()
                    after = page.evaluate('''async()=>({
                      page_after:(await import('/assets/observation.js')).snapshot(document.querySelector('#site').contentDocument).observation,
                      state_after:window.demoWorld.state,events:window.demoWorld.events
                    })''')
                    status = api('/api/event', {'id': id, 'result': {**after, 'description': action['action']+' '+(target or {}).get('label', '')}})['status']
                    if status != 'ready':
                        check('completed', status == 'complete')
                        break
                record = api('/api/traces/'+id)
                (output/(id+'.json')).write_text(json.dumps(record, ensure_ascii=False, indent=2))
                check('navigation executed', record['steps'][0]['client_result']['page_after']['title'].startswith('Campus Rooms'))
                final_controls = record['steps'][-1]['observation']['controls']
                for label, value in [('Building', 'Ångström'), ('Day', 'Wednesday'), ('People', '3'), ('Duration', '60')]:
                    check('filter '+label, next(c for c in final_controls if c['label'] == label)['value'] == value)
                bookings = page.evaluate('window.demoWorld.state.bookings')
                if goal.startswith('When'):
                    check('availability question made no booking', not bookings)
                    check('availability question no persisted effects', page.evaluate('window.demoWorld.events.length') == 0)
                else:
                    check('single requested booking', len(bookings) == 1 and bookings[0]['people'] == 3 and bookings[0]['duration'] == 60 and bookings[0]['building'] == 'Ångström')
                check('every exchange and receipt saved', all(s['request'] and s['response_text'] and s['client_result'] for s in record['steps']))
                check('client evidence not promoted', record['evaluation'] is None and not record['training_eligible'])
                records.append({'id': id, 'steps': len(record['steps']), 'goal': goal})
            check('history contains both turns', len(api('/api/traces')['traces']) == 2)
            check('no browser errors', not errors)
            browser.close()
        sources = ['deploy/daylight/lib/agent.mjs', 'deploy/daylight/lib/store.mjs', 'deploy/daylight/api/index.mjs',
                   'deploy/daylight/client/observation.js', 'deploy/daylight/tests/interactive-server.mjs', 'scripts/smoke_demo_interactive.py']
        report = {'passed': True, 'paid_calls': 0, 'policy': 'scripted test responses, not model performance', 'checks': checks, 'records': records,
                  'source_sha256': {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in sources}}
        (output/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(json.dumps({'report': str(output.relative_to(ROOT)/'report.json'), 'checks': len(checks), 'paid_calls': 0}))
    finally:
        process.terminate()
        process.wait(timeout=10)


if __name__ == '__main__':
    main()
