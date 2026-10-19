"""BrowserGym 0.14.3 adapter for Raven's explicitly shared demo window."""
import time
from uuid import uuid4

from browsergym.core.env import BrowserEnv, _get_global_playwright
from intent_browser.open_internet import OpenWebTask
from intent_browser.navigation import origin


class PanelChat:
    """BrowserGym's message store; the actual chat UI is the Raven side panel."""
    def __init__(self):
        self.messages = []

    def add_message(self, role, msg):
        if role in ('user', 'user_image', 'assistant', 'infeasible'):
            self.messages.append(dict(role=role, message=msg, timestamp=time.time()))

    def _js_user_message_received_callback(self, msg):
        self.add_message('user', msg)

    def close(self):
        pass


class SharedWebTask(OpenWebTask):
    def setup(self, page):
        # Keep the current document, form state and scroll position on attach.
        def route(r):
            if r.request.is_navigation_request():
                url = r.request.url
                if url not in ('about:blank', 'about:srcdoc'):
                    try:
                        origin(url)
                    except ValueError:
                        r.abort('blockedbyclient')
                        return
            r.continue_()
        self.route = route
        self.context = page.context
        self.context.route('**/*', route)
        return self.goal, {}

    def teardown(self):
        if hasattr(self, 'context'):
            self.context.unroute('**/*', self.route)


class SharedBrowserEnv(BrowserEnv):
    def __init__(self, cdp_url, initial_target=None, **kwargs):
        super().__init__(**kwargs)
        self.cdp_url = cdp_url
        self.initial_target = initial_target

    def reset(self, seed=None, **kwargs):
        # Deliberately avoid BrowserEnv.reset's launch/new-context/new-page path.
        pw = _get_global_playwright()
        pw.selectors.set_test_id_attribute('bid')
        self.browser = pw.chromium.connect_over_cdp(self.cdp_url)
        context = self.browser.contexts[0]
        if self.initial_target:
            context = next(c for c in self.browser.contexts for p in c.pages
                           if page_target(c, p) == self.initial_target)
        active = self.initial_target or active_target(context)
        session = self.browser.new_browser_cdp_session()
        context_id = session.send('Target.getTargetInfo', {'targetId':active})['targetInfo']['browserContextId']
        session.detach()
        self.context = WebContext(context, context_id, background=bool(self.initial_target))
        self.context.set_default_timeout(5000)
        pages = [p for p in self.context.pages if not p.url.startswith('chrome-extension:')]
        self.page = next((p for p in pages if page_target(self.context, p) == active), None)
        if self.page is None:
            self.page = pages[0] if pages else self.context.new_page()
        self.task = self.task_entrypoint(seed=seed, **self.task_kwargs)
        self.chat = self.raven_chat = PanelChat()
        self.goal_object = [{'type': 'text', 'text': self.task.goal}]
        self.chat.add_message('user', self.task.goal)
        # Unique bindings avoid retained callbacks across CDP client lifetimes.
        self.binding = 'raven_activate_' + uuid4().hex
        self.context.expose_binding(self.binding, lambda source: self._activate_page_from_js(source['page']))
        self.activation_script = self.context.add_init_script(
            f"window.addEventListener('focus',()=>window.{self.binding}?.());")
        _, info = self.task.setup(self.page)
        self.start_time = time.time()
        self.last_action = self.last_action_error = ''
        self.infeasible_message_received = False
        return self._get_obs(), {'task_info': info}

    def close(self):
        # CDP Browser.close disconnects this client. Never close the persistent context.
        if self.task:
            self.task.teardown()
            self.task = None
        if self.browser:
            self.browser.close()
            self.browser = self.context = None


class BackgroundBrowserEnv(BrowserEnv):
    def reset(self, seed=None, **kwargs):
        # Native reset with an in-memory chat: no second hidden Chromium for chat.
        from types import FunctionType, MethodType, SimpleNamespace
        from apps.raven.browser_launch import demo_launch_options
        original = BrowserEnv.reset
        scope = dict(original.__globals__)
        self.raven_chat = PanelChat()
        scope['Chat'] = lambda **kw: self.raven_chat
        pw = _get_global_playwright()
        # BrowserGym passes args/ignore_default_args explicitly, so merge at
        # its launch call rather than duplicating those keyword arguments.
        def launch(**options):
            options.update(headless=False)
            options['args'] = [*options.get('args', []), '--start-minimized']
            return pw.chromium.launch(**demo_launch_options(**options))
        scope['_get_global_playwright'] = lambda: SimpleNamespace(
            selectors=pw.selectors, chromium=SimpleNamespace(launch=launch))
        reset = FunctionType(original.__code__, scope, original.__name__, original.__defaults__, original.__closure__)
        reset.__kwdefaults__ = original.__kwdefaults__
        result = MethodType(reset, self)(seed=seed, **kwargs)
        session = self.context.new_cdp_session(self.page)
        try:
            window = session.send('Browser.getWindowForTarget')['windowId']
            session.send('Browser.setWindowBounds', {'windowId': window, 'bounds': {'windowState': 'minimized'}})
        finally:
            session.detach()
        return result


class WebContext:
    """Keep Raven's own extension surfaces outside the agent's task tab list."""
    def __init__(self, context, browser_context_id=None, background=False):
        self._context = context
        self.browser_context_id = browser_context_id
        self.background = background

    @property
    def pages(self):
        pages = [p for p in self._context.pages if not p.url.startswith('chrome-extension:')]
        if not self.browser_context_id:
            return pages
        # Playwright 1.43 CDP attachments group pre-existing incognito targets
        # into the default wrapper. Filter by Chromium's actual context identity.
        selected = []
        from playwright.sync_api import Error as PlaywrightError
        for page in pages:
            session = None
            try:
                session = self._context.new_cdp_session(page)
                if session.send('Target.getTargetInfo')['targetInfo'].get('browserContextId') == self.browser_context_id:
                    selected.append(page)
            except PlaywrightError:
                if not page.is_closed():
                    raise
            finally:
                if session:
                    try:
                        session.detach()
                    except PlaywrightError:
                        if not page.is_closed():
                            raise
        return selected

    def new_page(self):
        if not self.background:
            return self._context.new_page()
        session = self._context.browser.new_browser_cdp_session()
        try:
            target = None
            with self._context.expect_page(predicate=lambda p: page_target(self._context, p) == target) as created:
                target = session.send('Target.createTarget', dict(url='about:blank',
                    browserContextId=self.browser_context_id, background=True))['targetId']
            return created.value
        finally:
            session.detach()

    def __getattr__(self, name):
        return getattr(self._context, name)


from intent_browser.human_browser import HumanBrowser


class SharedHumanBrowser(HumanBrowser):
    def start(self):
        self.raven_requested_handovers = set()
        self.raven_initial_pages = set(self.env.context.pages)
        super().start()
        # Only the current tab was assigned to Raven. Preserve all other user tabs.
        for tab_id, page in self.pages.items():
            if page is not self.env.page and self.states()[tab_id]['state'] == 'agent_controlled':
                self.controller.handover(tab_id, 'Existing user tab; human control retained.')
        self.emit()

    def _sync(self, budget=None):
        self.env.raven_drain_notes()
        return super()._sync(budget)

    def execute(self, decision):
        if decision.name == 'handover_tab':
            self.raven_requested_handovers.add(decision.arguments['tab_id'])
        if decision.name in ('handover_tab', 'tab_focus', 'new_tab', 'tab_close'):
            self.trace.event('raven_tab_tool_started', tool=decision.name, arguments=decision.arguments)
        if decision.name == 'new_tab':
            self.sync()
            blank = next((p for p in self.known_agent_pages
                          if not p.is_closed() and p.url == 'about:blank'
                          and self.states().get(self.id_for(p), {}).get('state') == 'agent_controlled'), None)
            if blank is not None:
                self.select(self.id_for(blank))
                self.emit()
                return {'tool':'new_tab', 'execution':'call_completed', 'active_tab_id':self.active}
        if decision.name == 'handover_tab':
            # Pause inference on this tab, retaining ordinary tab tools during
            # research. The general wait profile also disables those tools.
            self.wait_for_human = True
            try:
                return super().execute(decision)
            finally:
                self.wait_for_human = False
        return super().execute(decision)

    def close(self):
        # Only remove unused workspaces created by this episode. Human tabs survive.
        for page in self.known_agent_pages - self.raven_initial_pages:
            if not page.is_closed() and page.url == 'about:blank':
                page.close()
        self.raven_closing = True
        super().close()


def page_target(context, page):
    session = context.new_cdp_session(page)
    try:
        return session.send('Target.getTargetInfo')['targetInfo']['targetId']
    finally:
        session.detach()


def active_target(context):
    # CDP emulates focus/visibility for every attached Page. Chrome's own tab API
    # supplies actual active identity, including two tabs with identical URLs.
    worker = next(w for w in context.service_workers if w.url.startswith('chrome-extension:'))
    return worker.evaluate("""async () => {
      const [tab] = await chrome.tabs.query({active:true, lastFocusedWindow:true});
      const targets = await chrome.debugger.getTargets();
      return targets.find(target => target.tabId === tab.id).id;
    }""")
