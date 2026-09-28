"""Avoid public-object conversion for reviewed, plain-JSON observation RPCs.

Chromium still extracts the data; Playwright still owns the connection, thread,
error handling and cancellation. No global monkeypatch and no command retries.
Other methods, instrumented sessions and unreviewed versions use the public API.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache, partial
from importlib.metadata import version
from types import FunctionType

from playwright.sync_api import CDPSession
from playwright._impl._connection import Connection

_PUBLIC_SEND = CDPSession.send
_REQUEST = ContextVar('capture_json_request', default=None)
_STATE_ATTRIBUTE = '_intent_capture_json_replies'
_DISPATCH = Connection.dispatch
_SEND = Connection._send_message_to_server
_MISSING = object()
_JSON_METHODS = frozenset({'DOMSnapshot.captureSnapshot', 'Accessibility.getFullAXTree'})


@lru_cache(maxsize=1)
def _reviewed_version():
    return version('playwright') == '1.44.0'


class _RawReplies:
    """Connection-local, request-ID-scoped success path for CDP JSON only.

    Retain upstream dispatch for events, object creation, errors, cancelled
    callbacks, closure and unexpected reply shapes. Never disable reference
    conversion globally, even while a capture is awaiting its reply.
    """
    def __init__(self, connection):
        self.connection = connection
        self.users = 0
        self.pending = {}
        self.previous = {name:vars(connection).get(name, _MISSING)
                         for name in ('dispatch', '_send_message_to_server')}
        self.dispatch_original = connection.dispatch
        self.send_original = connection._send_message_to_server
        connection.dispatch = self.dispatch
        connection._send_message_to_server = self.send

    def send(self, obj, method, params, no_reply=False):
        tag = _REQUEST.get()
        selected = (tag is not None and tag[0] is obj and method == 'send'
                    and not no_reply and isinstance(params, dict)
                    and params.get('method') == tag[1] and tag[1] in _JSON_METHODS)
        # The pinned sender allocates this ID synchronously before any optional
        # nested tracing messages. Verify callback identity before accepting it.
        request_id = self.connection._last_id + 1
        callback = self.send_original(obj, method, params, no_reply)
        if selected and self.connection._callbacks.get(request_id) is callback:
            self.pending[request_id] = callback
        return callback

    def dispatch(self, message):
        request_id = message.get('id')
        expected = self.pending.pop(request_id, None)
        connection = self.connection
        result = message.get('result')
        if (expected is not None and not connection._closed_error
                and connection._callbacks.get(request_id) is expected
                and not expected.future.cancelled() and not expected.no_reply
                and not message.get('error') and type(result) is dict
                and set(result) == {'result'} and type(result['result']) is dict):
            # Same normal-success callback completion as Connection.dispatch;
            # only its recursive GUID-to-channel conversion is omitted.
            del connection._callbacks[request_id]
            expected.future.set_result(result)
            return
        return self.dispatch_original(message)

    def close(self):
        for name, value in self.previous.items():
            if value is _MISSING:
                delattr(self.connection, name)
            else:
                setattr(self.connection, name, value)
        delattr(self.connection, _STATE_ATTRIBUTE)
        self.pending.clear()


@contextmanager
def _raw_reply_scope(impl, method):
    connection = getattr(impl, '_connection', None)
    state = getattr(connection, _STATE_ATTRIBUTE, None)
    if state is None:
        # Respect other connection instrumentation; the public-conversion-only
        # optimization can still operate without touching its dispatcher.
        if (type(connection) is not Connection
                or getattr(connection.dispatch, '__func__', None) is not _DISPATCH
                or getattr(connection._send_message_to_server, '__func__', None) is not _SEND):
            yield
            return
        state = _RawReplies(connection)
        setattr(connection, _STATE_ATTRIBUTE, state)
    state.users += 1
    token = _REQUEST.set((impl, method))
    try:
        yield
    finally:
        _REQUEST.reset(token)
        state.users -= 1
        if not state.users:
            state.close()


async def _send_plain(impl, method, params):
    # Scope lives in the actual coroutine/task, including nested or overlapping
    # calls on this owner loop. Native wrap_api_call/deadlines remain in effect.
    with _raw_reply_scope(impl, method):
        return await impl.send(method=method, params=params)


def send_json(session, method, params=None):
    """Internal CDP JSON parameters only; never Page/ElementHandle arguments.

    CDP returns JSON, not Playwright implementation handles. Its generated public
    send() applies from_maybe_impl anyway, recursively copying the whole result.
    Skip both generic object-conversion passes for these replies. JSON decoding,
    error dispatch and deadline wrappers remain active. If dispatch fails, propagate it: do not retry via public send.
    """
    if (method in _JSON_METHODS and _reviewed_version()
            and type(session) is CDPSession
            and getattr(session.send, '__func__', None) is _PUBLIC_SEND):
        return session._sync(_send_plain(session._impl_obj, method, params))
    return session.send(method, params)


class _Session:
    def __init__(self, session):
        self._session = session

    def send(self, method, params=None):
        return send_json(self._session, method, params)

    def __getattr__(self, name):
        return getattr(self._session, name)


class _Context:
    def __init__(self, context):
        self._context = context

    def new_cdp_session(self, target):
        if isinstance(target, _Page):
            target = target._page
        return _Session(self._context.new_cdp_session(target))

    def __getattr__(self, name):
        return getattr(self._context, name)


class _Page:
    def __init__(self, page):
        self._page = page
        self.context = _Context(page.context)

    def __getattr__(self, name):
        return getattr(self._page, name)


def extract_json(extractor, page, *args, **kwargs):
    """Scope the transport adapter to one upstream extraction call.

    Used only by BrowserGym DOM/AX extractors which create CDP sessions from
    page.context; their extraction, merging and BID processing stay unchanged.
    """
    return extractor(_Page(page), *args, **kwargs)


def capture_json(bound_capture, *, screenshots=True):
    """Apply the same adapter to an unmodified native BrowserGym _get_obs.

    Only this invocation's extraction globals are replaced, preserving upstream
    retries, marking, screenshots and cleanup. Used by native pipeline fallback.
    """
    from browsergym.core.env import BrowserEnv
    # HumanBrowser and other lifecycle owners may replace the saved callback;
    # never clone/bypass their custody, guards or error handling.
    if getattr(bound_capture, '__func__', None) is not BrowserEnv._get_obs:
        return bound_capture()
    original = bound_capture.__func__
    scope = dict(original.__globals__)
    for name in ('extract_dom_snapshot', 'extract_merged_axtree'):
        scope[name] = partial(extract_json, scope[name])
    if not screenshots:
        scope['extract_screenshot'] = lambda page: None
    capture = FunctionType(original.__code__, scope, original.__name__,
                           original.__defaults__, original.__closure__)
    capture.__kwdefaults__ = original.__kwdefaults__
    return capture(bound_capture.__self__)
