"""Scripted browser recovery acceptance. Run under run_bounded_job.py, DISPLAY=:99."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import queue
import threading
import time
from types import SimpleNamespace

from apps.raven.backend import FRIENDLY_ERROR, Handler, Service, ThreadingHTTPServer
from apps.raven.browser_launch import demo_launch_options


class FailureService(Service):
    def __init__(self, port, output):
        super().__init__(port, demo_mode=True)
        self.output = output
        self.window = SimpleNamespace(cdp_url='scripted-fixture')

    def tabs(self):
        return []

    def stop_process(self, run):
        run.process.stopped.set()

    def start_attempt(self, run, scripted=None):
        run._events = queue.Queue()
        run.controls = queue.Queue()
        directory = self.output / run.run_id / f'attempt-{run.attempt + 1}'
        directory.mkdir(parents=True)
        run.trace = str(directory)
        stopped = threading.Event()
        run.process = SimpleNamespace(stopped=stopped, is_alive=lambda: not stopped.is_set(),
                                      exitcode=1, join=lambda **kw: None)
        events, attempt = run._events, run.attempt
        def produce():
            events.put({'type': 'step', 'index': 1, 'summary': 'Reading the sample page'})
            if stopped.wait(.4):
                return
            if 'budget' in run.payload['text']:
                events.put({'type': 'error', 'message': 'The episode ended before the agent supplied an answer.'})
                events.put({'type': 'done', 'stop_reason': 'max_total_input_tokens'})
            elif attempt == 0 or 'permanent' in run.payload['text']:
                events.put({'type': 'error', 'message': 'Worker.evaluate: private stack trace'})
                events.put({'type': 'done', 'stop_reason': 'error'})
            else:
                events.put({'type': 'final', 'markdown': 'Recovered answer.', 'sources': []})
                events.put({'type': 'done', 'stop_reason': 'agent_finished'})
            stopped.set()
        threading.Thread(target=produce, daemon=True).start()


def test_recovery_and_friendly_errors_in_both_layouts(tmp_path):
    output = Path('.local/coordination/demo-sprint/web-g-ui')
    output.mkdir(parents=True, exist_ok=True)
    results = []

    def case(layout, permanent, drop, budget=False):
        from playwright.sync_api import sync_playwright
        name = f'{layout}-{"budget-" if budget else ""}{"permanent" if permanent else "recover"}{"-sse-drop" if drop else ""}'
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        server.daemon_threads = True
        service = FailureService(server.server_port, tmp_path / name)
        server.service = service
        threading.Thread(target=server.serve_forever, daemon=True).start()
        url = f'http://127.0.0.1:{server.server_port}'
        with sync_playwright() as pw:
            browser = pw.chromium.launch(**demo_launch_options(headless=True))
            try:
                context = browser.new_context(reduced_motion='reduce')
                page = context.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(url + ('/panel.html' if layout == 'panel' else '/'))
                page.wait_for_function('window.ravenChatDemo?.ready', timeout=45000)
                if drop:
                    seen = []
                    def interrupt(route):
                        seen.append(1)
                        route.abort('failed') if len(seen) == 1 else route.continue_()
                    page.route('**/events', interrupt)
                page.locator('#message-input').fill('budget stop' if budget else 'permanent failure' if permanent else 'recover fixture')
                page.locator('#send-button').click()
                message = FRIENDLY_ERROR if permanent or budget else 'Recovered answer.'
                page.locator('.message:not(.user)').filter(has_text=message).wait_for(timeout=30000)
                page.wait_for_function('!document.querySelector("#send-button").disabled', timeout=15000)
                page.locator('.raven-steps summary').click()
                text = page.locator('body').inner_text()
                assert 'Worker.evaluate' not in text and 'private stack trace' not in text
                assert ('Taking another look…' in text) is (not budget)
                if permanent or budget:
                    assert text.count(FRIENDLY_ERROR) == 1
                assert not errors, errors
                page.screenshot(path=str(output / f'{name}.png'))
                assert all(run.attempt == (0 if budget else 1) and run.done for run in service.runs.values())
                results.append({'case': name, 'pass': True})
            finally:
                browser.close()
                for run in service.runs.values():
                    service.cancel(run)
                server.shutdown()
                server.server_close()

    # Separate browsers and traces for independent cases, bounded concurrency two.
    cases = [(layout, permanent, False) for layout in ['panel', 'fullpage'] for permanent in [False, True]]
    cases += [(layout, False, True) for layout in ['panel', 'fullpage']]
    cases += [(layout, False, False, True) for layout in ['panel', 'fullpage']]
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda args: case(*args), cases))
    (output / 'results.json').write_text(json.dumps({'metadata': {'tags': ['scripted']}, 'cases': results}, indent=2) + '\n')
