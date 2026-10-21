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

    def new_background_window(self, page, keep_others=False):
        """(Re)create the minimized agent window used by "Work in background window"
        (keep_others: an additional window for a flock helper; returns its context)."""
        session = self.browser.new_browser_cdp_session()
        before = set(session.send('Target.getBrowserContexts')['browserContextIds'])
        background = self.browser.new_context(accept_downloads=False, service_workers='block', no_viewport=True)
        after = set(session.send('Target.getBrowserContexts')['browserContextIds'])
        context_id = (after - before).pop()
        create = dict(url='about:blank', browserContextId=context_id, newWindow=True, background=True)
        try:
            # Born minimized and off-screen (newer Chrome), so Windows shows no opening animation.
            self.background_target = session.send('Target.createTarget', dict(create, windowState='minimized',
                left=-32000, top=-32000, width=1440, height=1000))['targetId']
        except Exception:
            self.background_target = session.send('Target.createTarget', create)['targetId']
        page.wait_for_timeout(300)
        window_id = session.send('Browser.getWindowForTarget', {'targetId':self.background_target})['windowId']
        # Keep the agent's window out of sight: park it off-screen, then minimize. WSL/Windows
        # can still map and focus a newly created window; off-screen it never covers the user's.
        session.send('Browser.setWindowBounds', {'windowId':window_id, 'bounds':{'windowState':'normal',
            'left':-32000, 'top':-32000, 'width':1440, 'height':1000}})
        session.send('Browser.setWindowBounds', {'windowId':window_id, 'bounds':{'windowState':'minimized'}})
        session.detach()
        if keep_others:
            self.helper_contexts[self.background_target] = background
            return background
        for old in self.background_contexts:
            try:
                old.close()
            except Exception:
                pass
        self.background_contexts = [background]

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
                self.background_contexts = []
                self.helper_contexts = {}
                self.new_background_window(page)
                blank = ('about:blank', 'chrome://newtab/', 'chrome://new-tab-page/')
                page.wait_for_timeout(1500)  # the side panel/welcome flow can still open a default tab
                for extra in [p for p in self.context.pages if p is not page and p.url in blank]:
                    extra.close()
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
                            pages = self.background_contexts[0].pages if self.background_contexts else []
                            if not pages:
                                # The user closed the agent window: make a new minimized one.
                                self.new_background_window(self.context.pages[0])
                                pages = self.background_contexts[0].pages
                            response.put(target_id(pages[0].context, pages[0]))
                        elif action == 'helper_window':
                            self.new_background_window(self.context.pages[0], keep_others=True)
                            response.put(self.background_target)
                        elif action == 'helper_tab':
                            tab = self.context.new_page()
                            response.put(target_id(self.context, tab))
                        elif action == 'close_helper_window':
                            helper = self.helper_contexts.pop(data, None)
                            if helper is not None:
                                helper.close()
                            response.put(True)
                        elif action == 'tabs':
                            from apps.raven.shared_browser import active_target
                            active = active_target(self.context)
                            rows = []
                            for c in [self.context, *self.background_contexts, *self.helper_contexts.values()]:
                              for p in c.pages:
                                # The agent window's idle placeholder is not a page anyone visited.
                                if p.is_closed() or p.url.startswith('chrome-extension:') or (
                                        c is not self.context and p.url == 'about:blank'):
                                    continue
                                try:
                                    tid = target_id(p.context, p)
                                    rows.append(dict(tab_id=tid, url=p.url, title=p.title(),
                                        owner='human' if c is self.context else 'agent', active=tid == active))
                                except Exception:
                                    if not p.is_closed():
                                        raise
                            response.put(rows)
                        elif action == 'focus':
                            for p in [p for c in [self.context, *self.background_contexts, *self.helper_contexts.values()] for p in c.pages]:
                                if target_id(p.context, p) == data:
                                    session = p.context.new_cdp_session(p)
                                    wid = session.send('Browser.getWindowForTarget')['windowId']
                                    bounds = session.send('Browser.getWindowBounds', {'windowId':wid})['bounds']
                                    # Only un-minimize / bring the parked agent window on-screen; never
                                    # touch a normal, maximized or fullscreen window of the user.
                                    if bounds.get('windowState') == 'minimized':
                                        session.send('Browser.setWindowBounds', {'windowId':wid,'bounds':{'windowState':'normal'}})
                                        bounds = session.send('Browser.getWindowBounds', {'windowId':wid})['bounds']
                                    if bounds.get('windowState') == 'normal' and (bounds.get('left', 0) < -5000 or bounds.get('top', 0) < -5000):
                                        session.send('Browser.setWindowBounds', {'windowId':wid,'bounds':{'left':80,'top':60}})
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


BACKENDS = ('sol', 'openrouter', 'selfhosted')


class ModelRegistry:
    """Presets from models.json, reloaded when the file changes; CLI picks the default."""
    def __init__(self, path, cli_preset=None, defaults=None):
        self.path, self.cli_preset, self.defaults = Path(path), cli_preset, defaults or {}
        self.mtime, self.data, self.override = object(), {}, None
        self.lock = threading.Lock()
        self.probes = {}
        if cli_preset:
            match = next((p for p in self.presets() if p['id'] != 'cli' and p['backend'] == cli_preset['backend']
                          and p['model'] == cli_preset['model']
                          and p.get('base_url') == cli_preset.get('base_url')), None)
            self.override = match['id'] if match else cli_preset['id']
            if match:
                self.cli_preset = None

    def presets(self):
        with self.lock:
            try:
                mtime = self.path.stat().st_mtime
            except FileNotFoundError:
                mtime = None
            if mtime != self.mtime:
                self.mtime = mtime
                try:
                    data = json.loads(self.path.read_text()) if mtime else {}
                    for preset in data.get('presets', []):
                        if not preset.get('id') or preset.get('backend') not in BACKENDS or not preset.get('model'):
                            raise ValueError(f'Invalid preset {preset!r}')
                        if preset['backend'] == 'selfhosted' and not preset.get('base_url'):
                            raise ValueError(f"Self-hosted preset {preset['id']} needs base_url")
                    self.data = data
                    LOG.info('Loaded %d model presets from %s', len(data.get('presets', [])), self.path)
                except Exception:
                    LOG.exception('Ignoring invalid %s; keeping previous presets', self.path)
            presets = [dict(p) for p in self.data.get('presets', [])]
        if self.cli_preset and all(p['id'] != self.cli_preset['id'] for p in presets):
            presets.append(dict(self.cli_preset))
        for preset in presets:
            preset.setdefault('label', preset['model'])
            for key, value in self.defaults.items():
                if value is not None:
                    preset.setdefault(key, value)
        return presets

    def get(self, preset_id):
        return next((p for p in self.presets() if p['id'] == preset_id), None)

    def default(self):
        presets = self.presets()
        for preset_id in (self.override, self.data.get('default')):
            preset = next((p for p in presets if p['id'] == preset_id), None)
            if preset:
                return preset
        return presets[0] if presets else None

    def fallback(self):
        return self.get(self.data.get('fallback') or 'gemini-flash')

    def available(self, preset):
        key = (preset['backend'], preset['model'], preset.get('base_url'))
        cached = self.probes.get(key)
        if cached and time.monotonic() - cached[0] < 10:
            return cached[1]
        if preset['backend'] == 'openrouter':
            ok = bool(os.environ.get('OPENROUTER_API_KEY'))
        elif preset['backend'] == 'sol':
            import shutil
            ok = shutil.which('pi') is not None
        else:
            import httpx
            key_value = os.environ.get('SELF_HOSTED_API_KEY')
            try:
                ok = httpx.get(preset['base_url'].rstrip('/') + '/models', timeout=2, trust_env=False,
                               headers={'Authorization': 'Bearer ' + key_value} if key_value else {}).is_success
            except Exception:
                ok = False
        self.probes[key] = (time.monotonic(), ok)
        return ok

    def public(self, preset, availability=True):
        row = {k: preset.get(k) for k in ('id', 'label', 'backend', 'model')}
        if availability:
            row['available'] = self.available(preset)
        return row


def episode_options(preset):
    return dict(preset_id=preset['id'], label=preset['label'], model_backend=preset['backend'],
                model=preset['model'], base_url=preset.get('base_url'),
                openrouter_model=preset['model'] if preset['backend'] == 'openrouter' else None,
                reasoning_effort=preset.get('reasoning_effort'), service_tier=preset.get('service_tier') or 'priority',
                max_context=preset.get('max_context'),
                max_total_input_tokens=preset.get('max_total_input_tokens'),
                max_total_output_tokens=preset.get('max_total_output_tokens'),
                providers=preset.get('providers'))


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
    options: dict = field(default_factory=dict)

    def emit(self, event):
        with self.condition:
            if self.done:
                return
            self.events.append(event)
            if event['type'] == 'done':
                self.done = True
            self.condition.notify_all()


class Service:
    def __init__(self, port, user_window=False, profile_dir=None, model_backend=None, reasoning_effort=None, service_tier='priority', windows_browser=False, demo_mode=False,
                 openrouter_model=OPENROUTER_MODEL, max_total_input_tokens=None, max_total_output_tokens=None,
                 base_url=None, model=None, preset=None, models_file=None):
        from dotenv import load_dotenv
        load_dotenv(paths.ENV_FILE, override=False)
        self.port = port
        self.demo_mode = demo_mode
        self.runs = {}
        self.conversations = {}
        self.lock = threading.RLock()
        self.window = UserWindow(port, profile_dir, windows_browser) if user_window or windows_browser else None
        self.context = mp.get_context('spawn')
        cli = None
        if model_backend:
            name = {'sol': MODEL, 'openrouter': openrouter_model}.get(model_backend) or model
            if not name:
                raise ValueError('--model is required with --model-backend selfhosted')
            cli = dict(id='cli', label=name, backend=model_backend, model=name, base_url=base_url,
                       reasoning_effort=reasoning_effort)
        self.models = ModelRegistry(models_file or APP / 'models.json', cli, dict(
            reasoning_effort=reasoning_effort, service_tier=service_tier,
            max_total_input_tokens=max_total_input_tokens, max_total_output_tokens=max_total_output_tokens))
        if preset:
            if not self.models.get(preset):
                raise ValueError('Unknown model preset ' + preset)
            self.models.override = preset

    @property
    def options(self):
        preset = self.models.default()
        return episode_options(preset) if preset else {}

    @property
    def model(self):
        return self.options.get('model')

    def choose_model(self, payload):
        """Fixed per conversation; an unavailable choice falls back with a visible notice."""
        conversation = payload.get('conversation_id')
        requested = self.conversations.get(conversation) or payload.get('model')
        preset = self.models.get(requested) if requested else None
        preset = preset or self.models.default()
        if preset is None:
            raise ValueError('No model presets are configured')
        notice = None
        if not self.models.available(preset):
            fallback = self.models.fallback()
            if fallback and fallback['id'] != preset['id'] and self.models.available(fallback):
                name = 'Self-hosted model' if preset['backend'] == 'selfhosted' else preset['label']
                notice = f"{name} unavailable — using {fallback['label']}"
                LOG.warning('Model %s unavailable; falling back to %s', preset['id'], fallback['id'])
                preset = fallback
        if conversation:
            self.conversations[conversation] = preset['id']
        return preset, notice

    def submit(self, payload, scripted=None):
        with self.lock:
            payload = dict(payload)
            if payload.get('_helper_of'):
                # Flock helpers get their own tab/window; the one-task-per-mode rule is for user tasks.
                payload['_background_target'] = self.window.call(
                    'helper_tab' if payload['mode'] == 'user_window' else 'helper_window')
            elif payload['mode'] == 'background_window':
                if not self.window:
                    raise ValueError('Start the backend with --user-window')
                if any(not r.done and r.payload['mode'] == 'background_window' for r in self.runs.values()):
                    raise ValueError('The background window already has an active task')
                payload['_background_target'] = self.window.call('background')
            if payload['mode'] == 'user_window' and not payload.get('_helper_of'):
                if not self.window:
                    raise ValueError('Start the backend with --user-window')
                if any(not r.done and r.payload['mode'] == 'user_window' for r in self.runs.values()):
                    raise ValueError('The shared window already has an active task')
            if getattr(self, 'models', None) is not None:
                preset, notice = self.choose_model(payload)
                options = episode_options(preset)
            else:  # Unit-test services built without a registry.
                preset, notice, options = None, None, dict(getattr(self, 'test_options', {}))
            run = Run(uuid4().hex, payload, options=options)
            payload.update(_run_id=run.run_id, _port=self.port)  # flock host tools call back into this service
            self.runs[run.run_id] = run
            run.emit({'type': 'status', 'state': 'starting'})
            if preset:
                run.emit({'type': 'model', 'id': preset['id'], 'label': preset['label'], 'notice': notice,
                          'conversation_id': payload.get('conversation_id')})
            if notice:
                run.emit({'type': 'step', 'summary': notice, 'index': 0})
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
            list(scripted) if scripted is not None else None, run.options))
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
                    if answered:
                        # The answer is already published; the client reconnects by event replay.
                        # Keep owning the episode until its process finishes.
                        run.retry_requested.clear()
                    else:
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
                    if run.payload.get('_helper_of'):
                        self.flock_helper_event(run, event)
                    if event['type'] == 'handover' and run.payload['mode'] == 'background_window':
                        try:
                            self.focus(run.run_id + ':' + event['tab_id'])
                        except Exception:
                            LOG.exception('Could not focus handover tab')
                            event = {**event, 'message': event['message'] +
                                ' Please open the tab yourself; Korp could not bring it to the front.'}
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

    # --- Flock: helper agents of a main Korp episode (see apps/raven/flock.py) ---
    def flock_state(self):
        if not hasattr(self, '_flock'):
            self._flock, self._flock_inbox, self._flock_cond = {}, {}, threading.Condition()
        return self._flock, self._flock_inbox, self._flock_cond

    def flock_spawn(self, parent_id, task, name, window):
        from apps.raven.flock import MAX_HELPERS
        helpers, inbox, cond = self.flock_state()
        parent = self.runs.get(parent_id)
        if not parent or parent.done or not parent.payload.get('flock'):
            raise ValueError('Unknown or finished main agent')
        if window not in ('new_window', 'this_window'):
            raise ValueError('window must be new_window or this_window')
        if sum(1 for h in helpers.values() if h['parent'] == parent_id and not h['closed']) >= MAX_HELPERS:
            return {'error': f'At most {MAX_HELPERS} helpers at a time; close one first.'}
        run = self.submit({'text': task, 'mode': 'user_window' if window == 'this_window' else 'background_window',
                           'conversation_id': parent.payload.get('conversation_id'), 'history': [],
                           '_helper_of': parent_id, '_helper_name': name})
        with cond:
            helpers[run.run_id] = dict(parent=parent_id, name=name, window=window, state='working',
                                       closed=False, replies=[], target=run.payload.get('_background_target'))
            inbox.setdefault(parent_id, [])
        parent.emit({'type': 'helper', 'action': 'spawned', 'id': run.run_id, 'name': name, 'window': window})
        LOG.info('Flock: %s spawned helper %s (%s, %s)', parent_id, run.run_id, name, window)
        if not getattr(parent, '_flock_watch', False):
            parent._flock_watch = True
            threading.Thread(target=self.flock_watch, args=(parent,), daemon=True).start()
        return {'helper_id': run.run_id, 'name': name, 'state': 'working'}

    def flock_helper_event(self, run, event):
        helpers, inbox, cond = self.flock_state()
        helper = helpers.get(run.run_id)
        parent = self.runs.get(run.payload['_helper_of'])
        if not helper or not parent:
            return
        if event['type'] == 'step' and event.get('summary'):
            parent.emit({'type': 'helper', 'action': 'step', 'id': run.run_id, 'summary': event['summary']})
        if event['type'] == 'final' and not helper['closed']:
            # A helper that answered with send_msg_to_user has finished: its answer is its report.
            self.flock_to_main(run.run_id, event.get('markdown', ''), final=True)

    def flock_to_main(self, helper_id, text, final=False):
        helpers, inbox, cond = self.flock_state()
        with cond:
            helper = helpers.get(helper_id)
            if not helper or helper['closed']:
                return {'error': 'This conversation has ended'}
            helper['state'] = 'finished' if final else 'waiting'
            inbox.setdefault(helper['parent'], []).append(
                {'helper_id': helper_id, 'name': helper['name'], 'text': text, 'finished': final})
            cond.notify_all()
        parent = self.runs.get(helper['parent'])
        if parent:
            parent.emit({'type': 'helper', 'action': 'reported', 'id': helper_id, 'name': helper['name']})
        return {'ok': True}

    def flock_wait_reply(self, helper_id, timeout):
        helpers, inbox, cond = self.flock_state()
        deadline = time.monotonic() + min(float(timeout), 120)
        with cond:
            while True:
                helper = helpers.get(helper_id)
                if not helper:
                    return {'error': 'Unknown helper'}
                if helper['closed']:
                    return {'closed': True, 'instruction': 'The main agent ended this conversation. Stop.'}
                if helper['replies']:
                    helper['state'] = 'working'
                    return {'reply': helper['replies'].pop(0)}
                left = deadline - time.monotonic()
                if left <= 0:
                    return {'pending': True}
                cond.wait(left)

    def flock_status(self, parent_id):
        helpers, _, _ = self.flock_state()
        rows = []
        for hid, h in helpers.items():
            if h['parent'] == parent_id:
                run = self.runs.get(hid)
                state = 'closed' if h['closed'] else ('stopped' if run and run.done and h['state'] == 'working'
                                                      else h['state'])
                rows.append({'helper_id': hid, 'name': h['name'], 'state': state})
        return rows

    def flock_wait_main(self, parent_id, timeout):
        helpers, inbox, cond = self.flock_state()
        deadline = time.monotonic() + min(float(timeout), 120)
        with cond:
            while True:
                messages = inbox.get(parent_id) or []
                active = [r for r in self.flock_status(parent_id) if r['state'] == 'working']
                if messages or not active or time.monotonic() >= deadline:
                    inbox[parent_id] = []
                    result = {'messages': messages, 'helpers': self.flock_status(parent_id)}
                    if not messages and not active:
                        result['note'] = 'No helper is working; message or close the paused ones.'
                    return result
                cond.wait(min(1.0, max(0.05, deadline - time.monotonic())))

    def flock_message(self, parent_id, helper_id, text):
        helpers, inbox, cond = self.flock_state()
        with cond:
            helper = helpers.get(helper_id)
            if not helper or helper['parent'] != parent_id:
                return {'error': 'Unknown helper of this agent'}
            run = self.runs.get(helper_id)
            if helper['closed'] or helper['state'] == 'finished' or (run and run.done):
                return {'error': 'That helper has finished; spawn a new helper for more work.'}
            helper['replies'].append(text)
            cond.notify_all()
        parent = self.runs.get(parent_id)
        if parent:
            parent.emit({'type': 'helper', 'action': 'resumed', 'id': helper_id})
        return {'ok': True, 'state': 'working'}

    def flock_close(self, parent_id, helper_id):
        helpers, inbox, cond = self.flock_state()
        with cond:
            helper = helpers.get(helper_id)
            if not helper or helper['parent'] != parent_id:
                return {'error': 'Unknown helper of this agent'}
            if helper['closed']:
                return {'ok': True, 'state': 'closed'}
            helper['closed'] = True
            cond.notify_all()
        parent = self.runs.get(parent_id)
        if parent:
            parent.emit({'type': 'helper', 'action': 'closed', 'id': helper_id})
        threading.Thread(target=self.flock_retire, args=(helper_id,), daemon=True).start()
        return {'ok': True, 'state': 'closed'}

    def flock_retire(self, helper_id):
        """Stop the helper's episode and close its own window (tabs in the user's window stay)."""
        helpers, _, _ = self.flock_state()
        time.sleep(1.5)  # let a paused message_main_agent call observe the close
        run = self.runs.get(helper_id)
        if run:
            self.cancel(run)
        helper = helpers.get(helper_id)
        if helper and helper['window'] == 'new_window' and helper.get('target') and self.window:
            try:
                self.window.call('close_helper_window', helper['target'])
            except Exception:
                LOG.exception('Could not close helper window')

    def flock_watch(self, parent):
        """Retire every helper when its main agent finishes or is cancelled."""
        with parent.condition:
            while not parent.done:
                parent.condition.wait(1)
        helpers, _, _ = self.flock_state()
        for hid, h in list(helpers.items()):
            if h['parent'] == parent.run_id and not h['closed']:
                self.flock_close(parent.run_id, hid)

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

    def end_headers(self):
        # Revalidate the app's own files on every load so a restart never leaves a stale script behind.
        if self.command == 'GET' and not self.path.startswith('/api/'):
            self.send_header('Cache-Control', 'no-cache')
        super().end_headers()

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
            return self.json(dict(service.options, ok=True, demo_mode=service.demo_mode,
                modes=['background', 'user_window', 'background_window'] if service.window else ['background']))
        if path == '/api/memory':
            from apps.raven.memory_store import MemoryStore
            store = MemoryStore()
            return self.json(dict(store.snapshot(), fields=store.describe()['fields']))
        if path == '/api/models':
            default, fallback = service.models.default(), service.models.fallback()
            return self.json(dict(default=default and default['id'], fallback=fallback and fallback['id'],
                presets=[service.models.public(p) for p in service.models.presets()]))
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

    def memory_change(self, delete):
        if not self.allowed_client():
            self.send_error(403, 'Local origin required')
            return
        from urllib.parse import unquote
        from apps.raven.memory_store import MemoryStore, FIELDS
        parts = [unquote(p) for p in urlsplit(self.path).path.strip('/').split('/')]
        if len(parts) != 3 or parts[:2] != ['api', 'memory'] or parts[2] not in FIELDS:
            return self.json({'error': 'Unknown memory field'}, 404)
        try:
            store = MemoryStore()
            if delete:
                return self.json(store.delete(parts[2]))
            value = json.loads(self.rfile.read(int(self.headers.get('Content-Length', '0'))) or '{}').get('value')
            if FIELDS[parts[2]]['type'] == 'number' and isinstance(value, str):
                value = float(value.replace(',', '.'))
                value = int(value) if value.is_integer() else value
            return self.json(store.update(parts[2], value))
        except Exception as exc:
            LOG.info('Memory edit rejected: %s', exc)
            return self.json({'problem': 'That value does not fit this field.'}, 400)

    def do_PUT(self):
        return self.memory_change(False)

    def do_DELETE(self):
        return self.memory_change(True)

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
                if not isinstance(data.get('text'), str) or not data['text'].strip() or data.get('mode') not in ('background', 'user_window', 'background_window', 'flock'):
                    raise ValueError('Expected text and mode background, user_window, background_window or flock')
                data = {k: v for k, v in data.items() if not k.startswith('_')}  # internal keys are server-set
                if data['mode'] == 'flock':  # the main agent works in the user's window and may spawn helpers
                    data.update(mode='user_window', flock=True)
                else:
                    data.pop('flock', None)
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
            if len(parts) == 3 and parts[:2] == ['api', 'flock']:
                action = parts[2]
                if action == 'spawn':
                    return self.json(service.flock_spawn(data['parent'], str(data['task']), str(data['name'])[:40], data['window']))
                if action == 'to_main':
                    return self.json(service.flock_to_main(data['helper'], str(data['text'])))
                if action == 'wait_reply':
                    return self.json(service.flock_wait_reply(data['helper'], data.get('timeout_seconds', 60)))
                if action == 'wait_main':
                    return self.json(service.flock_wait_main(data['parent'], data.get('timeout_seconds', 60)))
                if action == 'message':
                    return self.json(service.flock_message(data['parent'], data['helper'], str(data['text'])))
                if action == 'close':
                    return self.json(service.flock_close(data['parent'], data['helper']))
            if parts == ['api', 'model']:
                if not service.models.get(data.get('id')):
                    raise ValueError('Unknown model preset')
                service.models.override = data['id']
                LOG.info('Default model for new conversations: %s', data['id'])
                return self.json({'ok': True, 'default': data['id']})
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
    parser.add_argument('--model-backend', choices=list(BACKENDS),
                        help='Default model backend (default: the "default" preset in apps/raven/models.json)')
    parser.add_argument('--openrouter-model', default=OPENROUTER_MODEL,
                        help='Any OpenRouter tool-calling model slug, used with --model-backend openrouter')
    parser.add_argument('--openai-base-url', help='OpenAI-compatible endpoint for --model-backend selfhosted')
    parser.add_argument('--model', help='Model name for --model-backend selfhosted')
    parser.add_argument('--preset', help='Default preset id from apps/raven/models.json')
    parser.add_argument('--models-file', type=Path, help='Preset registry (default apps/raven/models.json)')
    parser.add_argument('--max-total-input-tokens', type=int,
                        help='Per-episode cumulative input-token budget (default 4,000,000)')
    parser.add_argument('--max-total-output-tokens', type=int,
                        help='Per-episode cumulative output-token budget (default 60,000)')
    parser.add_argument('--reasoning-effort', choices=['low', 'medium', 'high', 'xhigh'],
                        help='Applies to presets without their own reasoning_effort')
    parser.add_argument('--service-tier', choices=['priority', 'default'], default='priority')
    args = parser.parse_args()
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    server.daemon_threads = True
    server.service = Service(args.port, args.user_window, args.profile_dir,
        args.model_backend, args.reasoning_effort, args.service_tier, args.windows_browser, args.demo_mode,
        args.openrouter_model, args.max_total_input_tokens, args.max_total_output_tokens,
        args.openai_base_url, args.model, args.preset, args.models_file)
    print(f'Korp: http://localhost:{args.port}/panel.html', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.service.close()
        server.server_close()


if __name__ == '__main__':
    main()
