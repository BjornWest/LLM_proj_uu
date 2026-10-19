#!/usr/bin/env python3
"""No-model presentation smoke: live service read checks + isolated mock UI runs.

Run through scripts/run_bounded_job.py, on DISPLAY=:99. No live tasks are submitted.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import threading
from pathlib import Path
from urllib.request import urlopen

from apps.raven.backend import Handler, Run, ThreadingHTTPServer
from apps.raven.browser_launch import demo_launch_options


class MockService:
    """Same served app and API handler; explicit scripted response, no episode/model."""
    demo_mode = True
    model = 'offline-scripted-mock'
    options = {'metadata': {'tags': ['scripted']}}
    window = None

    def __init__(self):
        self.runs = {}

    def tabs(self):
        return []

    def submit(self, payload):
        run = Run(str(len(self.runs)), payload)
        self.runs[run.run_id] = run
        def produce():
            run.emit({'type': 'step', 'index': 1, 'summary': 'Checking the sample page'})
            run.emit({'type': 'final', 'markdown': '**Smoke check complete.** Scripted fixture; no live research.', 'sources': []})
            run.emit({'type': 'done', 'stop_reason': 'agent_finished'})
        threading.Thread(target=produce, daemon=True).start()
        return run

    def cancel(self, run):
        run.emit({'type': 'done', 'stop_reason': 'cancelled'})
        return {'cancelled': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:8770')
    parser.add_argument('--windows-browser', action='store_true', help='Also check the live native Windows extension worker')
    parser.add_argument('--output', type=Path, default=Path('.local/coordination/demo-sprint/web-g-smoke'))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    results = []

    def check(name, operation):
        try:
            operation()
            results.append({'check': name, 'pass': True})
            print('PASS ' + name, flush=True)
        except Exception as exc:
            results.append({'check': name, 'pass': False, 'error': str(exc)})
            print('FAIL ' + name + ': ' + str(exc), flush=True)

    def health():
        with urlopen(args.url.rstrip('/') + '/api/health', timeout=10) as response:
            assert json.load(response)['ok'], 'backend is unhealthy'
    check('backend health (no model)', health)

    if args.windows_browser:
        def worker():
            with urlopen(args.url.rstrip('/') + '/api/worker-health', timeout=20) as response:
                state = json.load(response)
            assert state.get('ok') and state.get('windows_browser'), state
        check('Windows extension worker reachable', worker)

    from playwright.sync_api import sync_playwright
    # The live service and the isolated mock run together; the mock cannot call a model.
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    server.service = MockService()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    fixture = f'http://127.0.0.1:{server.server_port}'
    try:
        def surface(name, path):
            with sync_playwright() as pw:
                browser = pw.chromium.launch(**demo_launch_options(headless=True))
                try:
                    def load(name=name, path=path):
                        context = browser.new_context(reduced_motion='reduce')
                        try:
                            page = context.new_page()
                            response = page.goto(args.url.rstrip('/') + path)
                            assert response.ok, f'HTTP {response.status}'
                            page.wait_for_function('window.ravenChatDemo?.ready', timeout=45000)
                            assert page.locator('#message-input').is_visible()
                            page.screenshot(path=str(args.output / f'{name}-live.png'))
                        finally:
                            context.close()
                    check(name + ' loads', load)
    
                    def mock_run(name=name, path=path):
                        context = browser.new_context(reduced_motion='reduce')
                        errors = []
                        try:
                            page = context.new_page()
                            page.on('pageerror', lambda error: errors.append(str(error)))
                            page.goto(fixture + path)
                            page.wait_for_function('window.ravenChatDemo?.ready', timeout=45000)
                            page.locator('#message-input').fill('Run the no-model smoke fixture.')
                            page.locator('#send-button').click()
                            page.get_by_text('Smoke check complete.', exact=False).wait_for(timeout=30000)
                            page.wait_for_function('!document.querySelector("#send-button").disabled', timeout=15000)
                            assert not errors, errors
                            assert not page.locator('#raven-status').is_visible(), 'debug status is visible'
                            page.screenshot(path=str(args.output / f'{name}-mock.png'))
                        finally:
                            context.close()
                    check(name + ' mock run end to end (scripted, no model)', mock_run)
                finally:
                    browser.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda case: surface(*case), [('panel', '/panel.html'), ('full-page', '/')]))
    except Exception as exc:
        check('browser available', lambda: (_ for _ in ()).throw(exc))
    finally:
        server.shutdown()
        server.server_close()
    (args.output / 'results.json').write_text(json.dumps({'metadata': {'tags': ['scripted']}, 'checks': results}, indent=2) + '\n')
    return 0 if all(item['pass'] for item in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
