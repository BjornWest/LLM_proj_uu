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
    def __init__(self, cdp_url, **kwargs):
        super().__init__(**kwargs)
        self.cdp_url = cdp_url

    def reset(self, seed=None, **kwargs):
        # Deliberately avoid BrowserEnv.reset's launch/new-context/new-page path.
        pw = _get_global_playwright()
        pw.selectors.set_test_id_attribute('bid')
        self.browser = pw.chromium.connect_over_cdp(self.cdp_url)
        self.context = WebContext(self.browser.contexts[0])
        self.context.set_default_timeout(5000)
        pages = [p for p in self.context.pages if not p.url.startswith('chrome-extension:')]
        visible = [p for p in pages if p.evaluate('document.visibilityState === "visible"')]
        self.page = (visible or pages)[-1] if pages else self.context.new_page()
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
        from types import FunctionType, MethodType
        original = BrowserEnv.reset
        scope = dict(original.__globals__)
        self.raven_chat = PanelChat()
        scope['Chat'] = lambda **kw: self.raven_chat
        reset = FunctionType(original.__code__, scope, original.__name__, original.__defaults__, original.__closure__)
        reset.__kwdefaults__ = original.__kwdefaults__
        return MethodType(reset, self)(seed=seed, **kwargs)


class WebContext:
    """Keep Raven's own extension surfaces outside the agent's task tab list."""
    def __init__(self, context):
        self._context = context

    @property
    def pages(self):
        return [p for p in self._context.pages if not p.url.startswith('chrome-extension:')]

    def __getattr__(self, name):
        return getattr(self._context, name)
