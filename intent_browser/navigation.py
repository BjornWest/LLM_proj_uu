"""Opt-in single-tab navigation boundary, separate from private task grading.

This restricts document navigation, not all network traffic or server-side
side effects. It is not a sandbox for arbitrary hostile websites. Chromium
Fetch interception checks each HTTP redirect before it is sent.
"""
from urllib.parse import urlsplit


def origin(url):
    if not isinstance(url, str) or not url or any(ord(c) <= 32 for c in url) or '\\' in url:
        raise ValueError('Expected an absolute HTTP(S) URL without whitespace or backslashes')
    parts = urlsplit(url)
    if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username is not None or parts.password is not None:
        raise ValueError('Only absolute HTTP(S) URLs without credentials are allowed')
    host = parts.hostname.encode('idna').decode('ascii').lower()
    if ':' in host:
        host = '[' + host + ']'
    port = parts.port if parts.port is not None else (443 if parts.scheme == 'https' else 80)
    return f'{parts.scheme}://{host}:{port}'


def validate_origins(values):
    if not isinstance(values, tuple) or not values:
        raise ValueError('Navigation requires a nonempty tuple of trusted allowed origins')
    for value in values:
        parts = urlsplit(value)
        if parts.path not in ('', '/') or parts.query or parts.fragment:
            raise ValueError('Configure origins, not URL paths, queries or fragments')
    return tuple(dict.fromkeys(origin(value) for value in values))


def validate_url(url, allowed_origins):
    if origin(url) not in allowed_origins:
        raise ValueError('URL is outside the configured navigation origins')


def reload():
    """Reload the active page; this can resubmit a form, so inspect the context first.

    Examples:
        reload()
    """
    page.reload()  # noqa: F821 -- BrowserGym injects the active page.


class NavigationBoundary:
    """Single existing task page only; new windows are not enabled by this profile."""
    def __init__(self, allowed_origins, record):
        self.allowed = validate_origins(allowed_origins)
        self.record = record
        self.blocked = []
        self.session = self.context = None

    def _allowed(self, url):
        try:
            validate_url(url, self.allowed)
            return True
        except ValueError:
            return False

    def _block(self, url, reason):
        item = {'url': url, 'reason': reason}
        self.blocked.append(item)
        self.record(item)

    def start(self, env):
        self.page = env.unwrapped.page
        self.context = self.page.context
        if len(self.context.pages) != 1:
            raise ValueError('Navigation profile currently supports one task tab')
        validate_url(self.page.url, self.allowed)
        if self.context.service_workers:
            raise ValueError('Navigation profile does not support active service workers')
        self.session = self.context.new_cdp_session(self.page)
        self.session.send('Network.setBypassServiceWorker', {'bypass': True})
        self.session.on('Fetch.requestPaused', self._paused)
        self.session.send('Fetch.enable', {'patterns': [{'urlPattern': '*', 'resourceType': 'Document', 'requestStage': 'Request'}]})
        # The main-page CDP handler covers redirects. This outer route rejects
        # new-window requests before their first request (no popup CDP race).
        self.context.route('**/*', self._route)
        self.context.on('page', self._new_page)

    def _route(self, route):
        request = route.request
        if request.is_navigation_request():
            try:
                same_page = request.frame.page == self.page
            except Exception:
                same_page = False
            if not same_page or not self._allowed(request.url):
                self._block(request.url, 'new_tab_disabled' if not same_page else 'origin_not_allowed')
                route.abort('blockedbyclient')
                return
        route.fallback()

    def _paused(self, event):
        url = event['request']['url']
        if self._allowed(url):
            self.session.send('Fetch.continueRequest', {'requestId': event['requestId']})
        else:
            self._block(url, 'origin_not_allowed')
            self.session.send('Fetch.failRequest', {'requestId': event['requestId'], 'errorReason': 'BlockedByClient'})

    def _new_page(self, page):
        if page != self.page:
            self._block(page.url, 'new_tab_disabled')

    def check_active(self):
        # Do not close a page from its creation callback: BrowserGym may still
        # be installing its own listeners. End this unsupported episode instead
        # of letting a policy operate an unguarded second tab.
        if len(self.context.pages) != 1 or self.page.is_closed():
            raise ValueError('Navigation profile supports one task tab; a new or closed tab ends this episode')

    def take_blocked(self):
        items, self.blocked = self.blocked, []
        return items

    def close(self):
        if self.context:
            self.context.remove_listener('page', self._new_page)
            self.context.unroute('**/*', self._route)
        if self.session:
            self.session.detach()
