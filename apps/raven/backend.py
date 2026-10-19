#!/usr/bin/env python3
"""Local Raven API, static assets, and dedicated shared Chromium window."""
import argparse
from dataclasses import dataclass, field
import importlib.util
import json
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
SHARED = Path('/home/bjorn/code/LLM_proj_uu')
# Keep the documented python3 entry usable with this workstation's shared venv.
if __name__ == '__main__' and sys.prefix == sys.base_prefix and (SHARED / '.venv/bin/python').exists():
    env = dict(os.environ)
    env['OPENBLAS_NUM_THREADS'] = '1'
    env['PYTHONPATH'] = os.pathsep.join([str(ROOT), '/home/bjorn/code/cau-merge-20261016', env.get('PYTHONPATH', '')])
    libs = str(SHARED / '.local/system-libs/usr/lib/x86_64-linux-gnu')
    env['LD_LIBRARY_PATH'] = libs + os.pathsep + env.get('LD_LIBRARY_PATH', '')
    os.execve(str(SHARED / '.venv/bin/python'), [str(SHARED / '.venv/bin/python'), *sys.argv], env)
sys.path.insert(0, str(ROOT))
from apps.raven.episode import episode_main, MODEL

ASSETS = ROOT / 'design/raven/outputs/raven'
APP = Path(__file__).resolve().parent
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
    def __init__(self, port, profile_dir=None):
        self.port = port
        self.profile_dir = profile_dir
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
                self.context = pw.chromium.launch_persistent_context(
                    str(self.profile_dir or ROOT / '.local/raven-demo-profile'), headless=False, channel='chromium',
                    no_viewport=True, env={**os.environ, 'DISPLAY': os.getenv('DISPLAY', ':0')},
                    args=[f'--load-extension={extension}', f'--disable-extensions-except={extension}',
                          f'--remote-debugging-port={debug_port}', '--remote-debugging-address=127.0.0.1',
                          '--window-size=1440,1000', '--hide-crash-restore-bubble'],
                    ignore_default_args=['--disable-extensions'],
                    accept_downloads=False, service_workers='allow')
                page = self.context.pages[0] if self.context.pages else self.context.new_page()
                page.goto('https://example.com/')
                worker = self.context.service_workers[0] if self.context.service_workers else self.context.wait_for_event('serviceworker')
                worker.evaluate("port => chrome.sidePanel.setOptions({path:'sidepanel.html?port='+port})", self.port)
                extension_origin = worker.url.rsplit('/', 1)[0]
                welcome = next((p for p in self.context.pages if p.url.endswith('/welcome.html')), None)
                if welcome is None:
                    welcome = self.context.new_page()
                    welcome.goto(extension_origin + '/welcome.html')
                welcome.locator('#open').click()
                welcome.close()
                page.bring_to_front()
                self.cdp_url = f'http://127.0.0.1:{debug_port}'
                self.ready.set()
                while True:
                    try:
                        action, data, response = self.commands.get(timeout=0.1)
                    except queue.Empty:
                        self.context.pages[0].wait_for_timeout(50) if self.context.pages else None
                        continue
                    try:
                        if action == 'close':
                            self.context.close()
                            response.put(True)
                            break
                        if action == 'tabs':
                            from apps.raven.shared_browser import active_target
                            active = active_target(self.context)
                            rows = []
                            for p in self.context.pages:
                                if p.url.startswith('chrome-extension:'):
                                    continue
                                tid = target_id(self.context, p)
                                rows.append(dict(tab_id=tid, url=p.url,
                                    title=p.title(), owner='human', active=tid == active))
                            response.put(rows)
                        elif action == 'focus':
                            for p in self.context.pages:
                                if target_id(self.context, p) == data:
                                    p.bring_to_front()
                                    response.put(True)
                                    break
                            else:
                                raise ValueError('Tab no longer exists')
                    except Exception as exc:
                        response.put(exc)
        except Exception as exc:
            self.error = str(exc)
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
    tabs: list = field(default_factory=list)
    targets: dict = field(default_factory=dict)
    controller: dict = field(default_factory=dict)
    process: object = None
    controls: object = None
    trace: str = ''

    def emit(self, event):
        with self.condition:
            if self.done:
                return
            self.events.append(event)
            if event['type'] == 'done':
                self.done = True
            self.condition.notify_all()


class Service:
    def __init__(self, port, user_window=False, profile_dir=None):
        self.port = port
        self.runs = {}
        self.lock = threading.RLock()
        self.window = UserWindow(port, profile_dir) if user_window else None
        self.context = mp.get_context('spawn')

    def submit(self, payload, scripted=None):
        with self.lock:
            if payload['mode'] == 'user_window':
                if not self.window:
                    raise ValueError('Start the backend with --user-window')
                if any(not r.done and r.payload['mode'] == 'user_window' for r in self.runs.values()):
                    raise ValueError('The shared window already has an active task')
            run = Run(uuid4().hex, payload)
            self.runs[run.run_id] = run
            run.emit({'type': 'status', 'state': 'starting'})
            events, run.controls = self.context.Queue(), self.context.Queue()
            run.process = self.context.Process(target=episode_main, args=(payload,
                str(ROOT / '.local/raven-runs' / run.run_id), events, run.controls,
                self.window.cdp_url if payload['mode'] == 'user_window' else None, scripted))
            run.process.start()
            threading.Thread(target=self.collect, args=(run, events), daemon=True).start()
            return run

    def collect(self, run, events):
        while True:
            try:
                event = events.get(timeout=0.2)
            except queue.Empty:
                if not run.process.is_alive():
                    break
                continue
            if '_tabs' in event:
                run.tabs = event['_tabs']
            elif '_targets' in event:
                run.targets = event['_targets']
            elif '_controller' in event:
                run.controller = event['_controller']
            elif '_trace' in event:
                run.trace = event['_trace']
            else:
                run.emit(event)
        run.process.join()
        if not run.done:
            run.emit({'type': 'error', 'message': f'Episode process exited ({run.process.exitcode})'})
            run.emit({'type': 'done', 'stop_reason': 'error'})

    def cancel(self, run):
        with run.condition:
            if not run.done:
                run.cancelled = True
                try:
                    os.killpg(run.process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    run.process.terminate()
                run.process.join(timeout=4)
                if run.process.is_alive():
                    run.process.kill()
                    run.process.join(timeout=2)
                run.emit({'type': 'done', 'stop_reason': 'cancelled'})
        return {'cancelled': True}

    def tabs(self):
        if not self.window:
            return []
        rows = self.window.call('tabs')
        runs = [r for r in self.runs.values() if r.payload['mode'] == 'user_window']
        if not runs:
            return rows
        run = runs[-1]
        reverse = {target: tid for tid, target in run.targets.items()}
        ownership = {t['tab_id']: t['owner'] for t in run.tabs}
        states = {t['tab_id']: t['state'] for t in run.controller.get('tabs', [])}
        for row in rows:
            row['tab_id'] = reverse.get(row['tab_id'], row['tab_id'])
            tid = row['tab_id']
            if run.done:
                row['owner'] = 'human'
            else:
                row['owner'] = ('agent' if states[tid] == 'agent_controlled' else 'human') if tid in states else ownership.get(tid, 'human')
        return rows

    def focus(self, tab_id):
        if not self.window:
            raise ValueError('No shared window')
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
            return self.json(dict(ok=True, model=MODEL, modes=['background', 'user_window']))
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
            cursor = 0
            try:
                while True:
                    with run.condition:
                        if cursor == len(run.events) and not run.done:
                            run.condition.wait(10)
                        pending = run.events[cursor:]
                        cursor = len(run.events)
                        done = run.done
                    for event in pending:
                        self.wfile.write(('data: ' + json.dumps(event, ensure_ascii=False) + '\n\n').encode())
                    if not pending and not done:
                        self.wfile.write(b': keepalive\n\n')
                    self.wfile.flush()
                    if done:
                        break
            except (BrokenPipeError, ConnectionResetError):
                pass
            self.close_connection = True
            return
        return super().do_GET()

    def do_POST(self):
        if not self.allowed_client():
            self.send_error(403, 'Local origin required')
            return
        service = self.server.service
        parts = urlsplit(self.path).path.strip('/').split('/')
        try:
            data = json.loads(self.rfile.read(int(self.headers.get('Content-Length', '0'))) or '{}')
            if parts == ['api', 'tasks']:
                if not isinstance(data.get('text'), str) or not data['text'].strip() or data.get('mode') not in ('background', 'user_window'):
                    raise ValueError('Expected text and mode background or user_window')
                run = service.submit(data)
                return self.json({'run_id': run.run_id})
            if len(parts) == 4 and parts[:2] == ['api', 'tasks']:
                run = service.runs.get(parts[2])
                if not run:
                    return self.json({'error': 'Unknown run'}, 404)
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
    parser.add_argument('--user-window', action='store_true')
    args = parser.parse_args()
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    server.daemon_threads = True
    server.service = Service(args.port, args.user_window)
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
