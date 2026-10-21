#!/usr/bin/env python3
"""Local Raven API, static assets, and dedicated shared Chromium window."""
import argparse
from dataclasses import dataclass, field
import importlib.util
import json
import logging
import multiprocessing as mp
import os
from pathlib import Path
import queue
import socket
import signal
import sys
import threading
import time
from urllib.parse import urlsplit
from uuid import uuid4
from http.server import ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from apps.raven import paths
# Keep the documented python3 entry usable with the checkout's venv (see apps/raven/paths.py).
if __name__ == '__main__' and sys.prefix == sys.base_prefix and paths.PYTHON.exists():
    env = paths.child_environment(os.environ)
    env['OPENBLAS_NUM_THREADS'] = '1'
    os.execve(str(paths.PYTHON), [str(paths.PYTHON), *sys.argv], env)
from apps.raven.episode import episode_main, MODEL, OPENROUTER_MODEL
from apps.raven.browser_launch import demo_launch_options

ASSETS = ROOT / 'design/raven/outputs/raven'
APP = Path(__file__).resolve().parent
LOG = logging.getLogger('raven')
FRIENDLY_ERROR = "Sorry — I couldn't finish that. Could you try again or rephrase?"
spec = importlib.util.spec_from_file_location('raven_preview', ASSETS / 'server.py')
preview = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preview)


def target_id(context, page):
    session = context.new_cdp_session(page)
    try:
        return session.send('Target.getTargetInfo')['targetInfo']['targetId']
    finally:
        session.detach()


class UserWindow:
    """All persistent Playwright objects belong to one service thread."""
    def __init__(self, port, profile_dir=None, windows_browser=False):
        self.port = port
        self.profile_dir = profile_dir
        self.windows_browser = windows_browser
        self.windows_chrome = None
        self.commands = queue.Queue()
        self.ready = threading.Event()
        self.error = None
        self.cdp_url = None
        self.thread = threading.Thread(target=self.loop, daemon=True)
        self.thread.start()
        self.ready.wait(45)
        if self.error:
            raise RuntimeError(self.error)
        if not self.cdp_url:
            raise RuntimeError('Shared Chromium did not start')

    def loop(self):
        from playwright.sync_api import sync_playwright
        try:
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                debug_port = sock.getsockname()[1]
            with sync_playwright() as pw:
                extension = APP / 'extension'
                if self.windows_browser:
                    from apps.raven.windows_browser import launch_browser
                    self.windows_chrome = launch_browser(
                        ROOT / '.local/raven-windows' / str(self.port), extension, self.port, self.profile_dir)
                    self.browser = pw.chromium.connect_over_cdp(self.windows_chrome.endpoint, timeout=30000)
                    self.context = self.browser.contexts[0]
                else:
                    self.context = pw.chromium.launch_persistent_context(**demo_launch_options(
                        user_data_dir=str(self.profile_dir or ROOT / '.local/raven-demo-profile'), headless=False, channel='chromium',
                        no_viewport=True,
                        args=[f'--load-extension={extension}', f'--disable-extensions-except={extension}',
                              f'--remote-debugging-port={debug_port}', '--remote-debugging-address=127.0.0.1',
                              '--window-size=1440,1000', '--hide-crash-restore-bubble'],
                        ignore_default_args=['--disable-extensions'],
                        accept_downloads=False, service_workers='allow'))
                page = self.context.pages[0] if self.context.pages else self.context.new_page()
                page.goto('https://example.com/')
                from apps.raven.shared_browser import raven_worker
                worker = raven_worker(self.context)
                # Native Windows CfT can expose the worker before its extension APIs are bound.
                for attempt in range(40):
                    if worker.evaluate("() => !!(globalThis.chrome && chrome.sidePanel)"):
                        break
                    time.sleep(0.25)
                    worker = raven_worker(self.context)
                worker.evaluate("port => chrome.sidePanel.setOptions({path:'sidepanel.html?port='+port})", self.port)
                extension_origin = worker.url.rsplit('/', 1)[0]
                welcome = next((p for p in self.context.pages if p.url.endswith('/welcome.html')), None)
                if welcome is None:
                    welcome = self.context.new_page()
                    welcome.goto(extension_origin + '/welcome.html')
                welcome.locator('#open').click()
                welcome.close()
                page.bring_to_front()
                if not self.windows_browser:
                    self.browser = pw.chromium.connect_over_cdp(f'http://127.0.0.1:{debug_port}')
                # Create the separate agent window during startup, before the
                # user's window is presented. WSL can focus newly mapped windows
                # even when Target.createTarget requests background:true.
                session = self.browser.new_browser_cdp_session()
                before = set(session.send('Target.getBrowserContexts')['browserContextIds'])
                background = self.browser.new_context(accept_downloads=False, service_workers='block', no_viewport=True)
                after = set(session.send('Target.getBrowserContexts')['browserContextIds'])
                context_id = (after - before).pop()
                self.background_target = session.send('Target.createTarget', dict(url='about:blank',
                    browserContextId=context_id, newWindow=True, background=True))['targetId']
                page.wait_for_timeout(300)
                window_id = session.send('Browser.getWindowForTarget', {'targetId':self.background_target})['windowId']
                session.send('Browser.setWindowBounds', {'windowId':window_id, 'bounds':{'windowState':'minimized'}})
                session.detach()
                self.background_contexts = [background]
                page.bring_to_front()
                self.cdp_url = self.windows_chrome.endpoint if self.windows_browser else f'http://127.0.0.1:{debug_port}'
                self.ready.set()
                while True:
                    try:
                        action, data, response = self.commands.get(timeout=0.1)
                    except queue.Empty:
                        self.context.pages[0].wait_for_timeout(50) if self.context.pages else None
                        continue
                    try:
                        if action == 'worker-health':
                            from apps.raven.shared_browser import raven_worker
                            worker = raven_worker(self.context)
                            response.put({'ok': bool(worker.evaluate("() => !!(globalThis.chrome && chrome.sidePanel && chrome.tabs)")),
                                          'windows_browser': self.windows_browser})
                        elif action == 'close':
                            for context in self.background_contexts:
                                context.close()
                            if self.windows_browser:
                                self.browser.new_browser_cdp_session().send('Browser.close')
                            self.browser.close()
                            if not self.windows_browser:
                                self.context.close()
                            else:
                                self.windows_chrome.close()
                            response.put(True)
                            break
                        if action == 'background':
                            pages = self.background_contexts[0].pages
                            if not pages:
                                raise ValueError('Agent window was closed; restart the demo service')
                            response.put(target_id(pages[0].context, pages[0]))
                        elif action == 'tabs':
                            from apps.raven.shared_browser import active_target
                            active = active_target(self.context)
                            rows = []
                            for p in [p for c in [self.context, *self.background_contexts] for p in c.pages]:
                                if p.is_closed() or p.url.startswith('chrome-extension:'):
                                    continue
                                try:
                                    tid = target_id(p.context, p)
                                    rows.append(dict(tab_id=tid, url=p.url,
                                        title=p.title(), owner='human', active=tid == active))
                                except Exception:
                                    if not p.is_closed():
                                        raise
                            response.put(rows)
                        elif action == 'focus':
                            for p in [p for c in [self.context, *self.background_contexts] for p in c.pages]:
                                if target_id(p.context, p) == data:
                                    session = p.context.new_cdp_session(p)
                                    wid = session.send('Browser.getWindowForTarget')['windowId']
                                    session.send('Browser.setWindowBounds', {'windowId':wid,'bounds':{'windowState':'normal'}})
                                    session.detach()
                                    p.bring_to_front()
                                    response.put(True)
                                    break
                            else:
                                raise ValueError('Tab no longer exists')
                    except Exception as exc:
                        response.put(exc)
        except Exception as exc:
            self.error = str(exc)
        finally:
            if self.windows_chrome is not None:
                self.windows_chrome.close()
            self.ready.set()

    def call(self, action, data=None):
        response = queue.Queue()
        self.commands.put((action, data, response))
        result = response.get(timeout=15)
        if isinstance(result, Exception):
            raise result
        return result


@dataclass
class Run:
    run_id: str
    payload: dict
    events: list = field(default_factory=list)
    condition: threading.Condition = field(default_factory=threading.Condition)
    done: bool = False
    cancelled: bool = False
    subscribers: int = 0
    tabs: list = field(default_factory=list)
    targets: dict = field(default_factory=dict)
    controller: dict = field(default_factory=dict)
    process: object = None
    controls: object = None
    trace: str = ''
    attempt: int = 0
    retry_cursor: int = 0
    retry_requested: threading.Event = field(default_factory=threading.Event)

    def emit(self, event):
        with self.condition:
            if self.done:
                return
            self.events.append(event)
            if event['type'] == 'done':
                self.done = True
            self.condition.notify_all()


class Service:
    def __init__(self, port, user_window=False, profile_dir=None, model_backend='sol', reasoning_effort='medium', service_tier='priority', windows_browser=False, demo_mode=False):
        self.port = port
        self.demo_mode = demo_mode
        self.runs = {}
        self.lock = threading.RLock()
        self.window = UserWindow(port, profile_dir, windows_browser) if user_window or windows_browser else None
        self.context = mp.get_context('spawn')
        self.options = dict(model_backend=model_backend, reasoning_effort=reasoning_effort, service_tier=service_tier)
        self.model = OPENROUTER_MODEL if model_backend == 'openrouter' else MODEL

    def submit(self, payload, scripted=None):
        with self.lock:
            payload = dict(payload)
            if payload['mode'] == 'background_window':
                if not self.window:
                    raise ValueError('Start the backend with --user-window')
                if any(not r.done and r.payload['mode'] == 'background_window' for r in self.runs.values()):
                    raise ValueError('The background window already has an active task')
                payload['_background_target'] = self.window.call('background')
            if payload['mode'] == 'user_window':
                if not self.window:
                    raise ValueError('Start the backend with --user-window')
                if any(not r.done and r.payload['mode'] == 'user_window' for r in self.runs.values()):
                    raise ValueError('The shared window already has an active task')
            run = Run(uuid4().hex, payload)
            self.runs[run.run_id] = run
            run.emit({'type': 'status', 'state': 'starting'})
            self.start_attempt(run, scripted)
            threading.Thread(target=self.collect, args=(run, run._events, scripted), daemon=True).start()
            return run

    def start_attempt(self, run, scripted=None):
        run._events, run.controls = self.context.Queue(), self.context.Queue()
        output = ROOT / '.local/raven-runs' / run.run_id / f'attempt-{run.attempt + 1}'
        output.mkdir(parents=True, exist_ok=True)
        run.trace = str(output)
        run.process = self.context.Process(target=episode_main, args=(dict(run.payload),
            str(output), run._events, run.controls,
            self.window.cdp_url if run.payload['mode'] in ('user_window', 'background_window') else None,
            list(scripted) if scripted is not None else None, self.options))
        run.process.start()

    @staticmethod
    def stop_process(run):
        if run.process.is_alive():
            try:
                os.killpg(run.process.pid, signal.SIGTERM)
            except ProcessLookupError:
                run.process.terminate()
            run.process.join(timeout=4)
            if run.process.is_alive():
                run.process.kill()
        run.process.join(timeout=2)

    def retry(self, run, after_event_id=None):
        with run.condition:
            if after_event_id is not None and after_event_id < run.retry_cursor:
                return {'ok': True}
            if not run.done:
                LOG.warning('Run %s stream recovery requested (attempt %s)', run.run_id, run.attempt + 1)
                run.retry_requested.set()
        return {'ok': True}

    def collect(self, run, events, scripted=None):
        demo = getattr(self, 'demo_mode', False)
        while True:
            failure = None
            terminal = None
            answered = False
            journal = Path(run.trace) / 'service-events.jsonl' if run.trace else None
            while True:
                if run.retry_requested.is_set():
                    failure = 'SSE connection dropped'
                    break
                try:
                    event = events.get(timeout=0.2)
                except queue.Empty:
                    if not run.process.is_alive():
                        break
                    continue
                if journal:
                    with journal.open('a') as stream:
                        stream.write(json.dumps(event, ensure_ascii=False) + '\n')
                if '_tabs' in event:
                    run.tabs = event['_tabs']
                elif '_targets' in event:
                    run.targets = event['_targets']
                elif '_controller' in event:
                    run.controller = event['_controller']
                elif '_trace' in event:
                    run.trace = event['_trace']
                else:
                    if event['type'] == 'error':
                        LOG.error('Run %s attempt %s: %s', run.run_id, run.attempt + 1, event['message'])
                        failure = event['message']
                        if demo:
                            continue
                    if event['type'] == 'done' and demo:
                        terminal = event
                        break
                    if event['type'] == 'final':
                        answered = True
                    if event['type'] == 'handover' and run.payload['mode'] == 'background_window':
                        try:
                            self.focus(run.run_id + ':' + event['tab_id'])
                        except Exception:
                            LOG.exception('Could not focus handover tab')
                            event = {**event, 'message': event['message'] +
                                ' Please open the tab yourself; Raven could not bring it to the front.'}
                    run.emit(event)
            if demo and terminal and terminal['stop_reason'] == 'error':
                failure = failure or 'Episode failed without an error message'
            if not terminal and not run.done:
                failure = failure or f'Episode process exited ({run.process.exitcode})'
            if failure:
                LOG.error('Run %s attempt %s failed: %s', run.run_id, run.attempt + 1, failure)
                if journal:
                    with journal.open('a') as stream:
                        stream.write(json.dumps({'service_error': failure}) + '\n')
            retryable = failure and (terminal is None or terminal['stop_reason'] == 'error')
            if demo and retryable and not answered:
                with run.condition:
                    self.stop_process(run)
                    if run.done or run.cancelled:
                        return
                    run.retry_requested.clear()
                    if run.attempt == 0:
                        run.attempt += 1
                        # Reattach to the last live document rather than the user's newly focused tab.
                        active = next((t['tab_id'] for t in run.tabs if t.get('active')), None)
                        target = run.targets.get(active) if active else None
                        if target:
                            run.payload['_background_target'] = target
                        run.controller = {}
                        run.emit({'type': 'step', 'summary': 'Taking another look…', 'index': 0})
                        run.retry_cursor = len(run.events)
                        self.start_attempt(run, scripted)
                        events = run._events
                        continue
                    run.emit({'type': 'error', 'message': FRIENDLY_ERROR})
                    run.emit({'type': 'done', 'stop_reason': 'error'})
                    return
            run.process.join(timeout=4)
            if demo and terminal:
                run.emit(terminal)
            elif not run.done:
                run.emit({'type': 'error', 'message': FRIENDLY_ERROR if demo else failure})
                run.emit({'type': 'done', 'stop_reason': 'error'})
            return

    def cancel(self, run):
        with run.condition:
            if not run.done:
                run.cancelled = True
                self.stop_process(run)
                run.emit({'type': 'done', 'stop_reason': 'cancelled'})
        return {'cancelled': True}

    def tabs(self):
        if not self.window:
            return []
        rows = self.window.call('tabs')
        runs = [r for r in self.runs.values() if r.payload['mode'] in ('user_window', 'background_window')]
        for row in rows:
            for run in reversed(runs):
                tid = next((tid for tid, target in run.targets.items() if target == row['tab_id']), None)
                if tid:
                    row['tab_id'] = run.run_id + ':' + tid
                    row['owner'] = next((t['owner'] for t in run.tabs if t['tab_id'] == tid), 'human')
                    break
        return rows

    def focus(self, tab_id):
        if not self.window:
            raise ValueError('No shared window')
        if ':' in tab_id:
            run_id, tab_id = tab_id.split(':', 1)
            run = self.runs[run_id]
            self.window.call('focus', run.targets[tab_id])
            return
        for run in reversed(list(self.runs.values())):
            if tab_id in run.targets:
                tab_id = run.targets[tab_id]
                break
        self.window.call('focus', tab_id)

    def close(self):
        for run in list(self.runs.values()):
            self.cancel(run)
        if self.window:
            self.window.call('close')


class Handler(preview.Handler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ASSETS), **kwargs)

    def translate_path(self, path):
        name = urlsplit(path).path
        if name in ('/panel.html', '/panel.js', '/panel-controller.js'):
            return str(APP / name[1:])
        if name == '/':
            return str(ASSETS / 'chat-fullpage-v42.html')
        return super().translate_path(path)

    def json(self, data, status=200):
        if 'error' in data:
            LOG.error('HTTP %s %s: %s', status, self.path, data['error'])
            if self.server.service.demo_mode:
                data = {**data, 'error': FRIENDLY_ERROR}
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self.allowed_client():
            self.send_error(403, 'Local origin required')
            return
        path = urlsplit(self.path).path
        service = self.server.service
        if path == '/api/health':
            return self.json(dict(ok=True, model=service.model, demo_mode=service.demo_mode, **service.options,
                modes=['background', 'user_window', 'background_window'] if service.window else ['background']))
        if path == '/api/worker-health':
            try:
                return self.json(service.window.call('worker-health') if service.window else {'ok': False},
                                 200 if service.window else 503)
            except Exception as exc:
                LOG.exception('Worker health check failed')
                return self.json({'error': str(exc)}, 503)
        if path == '/api/tabs':
            try:
                return self.json({'tabs': service.tabs()})
            except Exception as exc:
                return self.json({'error': str(exc)}, 503)
        parts = path.strip('/').split('/')
        if len(parts) == 4 and parts[:2] == ['api', 'tasks'] and parts[3] == 'events':
            run = service.runs.get(parts[2])
            if not run:
                return self.json({'error': 'Unknown run'}, 404)
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('X-Accel-Buffering', 'no')
            self.end_headers()
            cursor = min(int(self.headers.get('Last-Event-ID') or 0), len(run.events))
            with run.condition:
                run.subscribers += 1
            try:
                while True:
                    with run.condition:
                        if cursor == len(run.events) and not run.done:
                            run.condition.wait(2)
                        pending = run.events[cursor:]
                        cursor = len(run.events)
                        done = run.done
                    for ordinal, event in enumerate(pending, cursor - len(pending) + 1):
                        self.wfile.write(('id: ' + str(ordinal) + '\ndata: ' + json.dumps(event, ensure_ascii=False) + '\n\n').encode())
                    if not pending and not done:
                        self.wfile.write(b': keepalive\n\n')
                    self.wfile.flush()
                    if done:
                        break
            except (BrokenPipeError, ConnectionResetError):
                LOG.exception('Run %s SSE disconnected', run.run_id)
                # Only the client knows the last received event ID. Its automatic
                # /retry request owns stream recovery; the write cursor can include
                # buffered events the client never received.
            finally:
                with run.condition:
                    run.subscribers -= 1
                    if not service.demo_mode and run.subscribers == 0 and not run.done and run.payload['mode'] in ('user_window', 'background_window'):
                        # Extension iframe teardown can drop unload fetch/beacon.
                        # Its last SSE connection is the remaining lifecycle signal.
                        service.cancel(run)
            self.close_connection = True
            return
        return super().do_GET()

    def do_POST(self):
        if not self.allowed_client():
            self.send_error(403, 'Local origin required')
            return
        service = self.server.service
        from urllib.parse import unquote
        parts = [unquote(p) for p in urlsplit(self.path).path.strip('/').split('/')]
        try:
            data = json.loads(self.rfile.read(int(self.headers.get('Content-Length', '0'))) or '{}')
            if parts == ['api', 'tasks']:
                if not isinstance(data.get('text'), str) or not data['text'].strip() or data.get('mode') not in ('background', 'user_window', 'background_window'):
                    raise ValueError('Expected text and mode background, user_window or background_window')
                run = service.submit(data)
                return self.json({'run_id': run.run_id})
            if len(parts) == 4 and parts[:2] == ['api', 'tasks']:
                run = service.runs.get(parts[2])
                if not run:
                    return self.json({'error': 'Unknown run'}, 404)
                if parts[3] == 'retry' and service.demo_mode:
                    return self.json(service.retry(run, int(data.get('after_event_id', 0))))
                if parts[3] == 'cancel':
                    return self.json(service.cancel(run))
                if parts[3] == 'handback':
                    tabs = run.controller.get('tabs', [])
                    tab = next((t for t in tabs if t['tab_id'] == data.get('tab_id')), None)
                    if run.done or not tab or tab['state'] not in ('awaiting_human', 'human_active'):
                        raise ValueError('No pending handover for that tab')
                    run.controls.put({'action': 'handback', 'tab_id': data['tab_id'], 'note': data.get('note')})
                    return self.json({'ok': True})
            if len(parts) == 4 and parts[:2] == ['api', 'tabs'] and parts[3] == 'focus':
                service.focus(parts[2])
                return self.json({'ok': True})
            return self.json({'error': 'Unknown endpoint'}, 404)
        except (ValueError, KeyError, TypeError) as exc:
            return self.json({'error': str(exc)}, 400)
        except Exception as exc:
            return self.json({'error': str(exc)}, 500)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8766)
    parser.add_argument('--demo-mode', action=argparse.BooleanOptionalAction, default=False,
                        help='Retry infrastructure failures once and show friendly errors')
    parser.add_argument('--user-window', action='store_true')
    parser.add_argument('--windows-browser', action='store_true', help='Use native Windows Chrome for Testing for panel modes (implies --user-window)')
    parser.add_argument('--profile-dir', type=Path, help='Dedicated profile; Windows path when using --windows-browser')
    parser.add_argument('--model-backend', choices=['sol', 'openrouter'], default='sol')
    parser.add_argument('--reasoning-effort', choices=['low', 'medium', 'high', 'xhigh'], default='medium')
    parser.add_argument('--service-tier', choices=['priority', 'default'], default='priority')
    args = parser.parse_args()
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    server.daemon_threads = True
    server.service = Service(args.port, args.user_window, args.profile_dir,
        args.model_backend, args.reasoning_effort, args.service_tier, args.windows_browser, args.demo_mode)
    print(f'Raven: http://localhost:{args.port}/panel.html', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.service.close()
        server.server_close()


if __name__ == '__main__':
    main()
