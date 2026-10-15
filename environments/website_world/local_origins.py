"""One world identity map and a context-local, loopback-only browser bridge.

Readable URLs are an explicit new-episode projection. They require this bridge;
the machine's DNS/hosts configuration and ordinary localhost previews are untouched.
"""
from copy import deepcopy
from collections import Counter
from hashlib import sha256
from contextlib import contextmanager
import ipaddress
import base64
import json
import os
from pathlib import Path
import re
from threading import Lock
from time import monotonic, monotonic_ns
import unicodedata
from types import SimpleNamespace
from urllib.parse import urljoin, urlsplit

import httpx
from intent_browser.checkpoint_browser import LogicalOrigins
from intent_browser.navigation import origin

VERSION = 'website-local-origins-v1'
PHASE_SCHEMA = 'website-local-origin-phases-v1'
_PHASE_PATHS = frozenset(('/', '/api/session', '/api/basket-quote', '/api/order'))
_PHASE_METHODS = frozenset(('GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS', 'TRACE', 'CONNECT'))


def _origin(url):
    parsed = urlsplit(url)
    if parsed.username is not None or parsed.password is not None:
        raise ValueError('Origin credentials are unsupported')
    canonical = origin(url)
    default = ':443' if parsed.scheme == 'https' else ':80'
    return canonical[:-len(default)] if canonical.endswith(default) else canonical


def _slug(name):
    ascii_name = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode()
    return re.sub('[^a-z0-9]+', '-', ascii_name.lower()).strip('-')[:48].rstrip('-') or 'site'


class OriginMap:
    def __init__(self, records, *, world_id):
        rows = deepcopy(list(records))
        if len({r['site_id'] for r in rows}) != len(rows):
            raise ValueError('Duplicate site identity')
        physical = set()
        for row in rows:
            url = row['origin']; parsed = urlsplit(url)
            if parsed.scheme != 'http' or parsed.path or parsed.query or parsed.fragment:
                raise ValueError('Transport must be a bare HTTP loopback origin')
            address = parsed.hostname
            if address != 'localhost':
                try:
                    if not ipaddress.ip_address(address).is_loopback:
                        raise ValueError('Non-loopback transport')
                except (ValueError, TypeError) as error:
                    raise ValueError('Transport must be loopback') from error
            canonical = _origin(url)
            if canonical in physical:
                raise ValueError('Duplicate transport origin')
            physical.add(canonical)
            row['origin'] = canonical
        slugs = [_slug(r['name']) for r in rows]
        counts = Counter(slugs)
        self._rows = []
        for row, slug in zip(rows, slugs):
            if counts[slug] > 1:
                slug += '-' + sha256(row['site_id'].encode()).hexdigest()[:10]
            self._rows.append({'site_id': row['site_id'], 'name': row['name'], 'kind': row['kind'],
                               'logical_origin': 'https://' + slug + '.test', 'transport_origin': row['origin']})
        # Hash suffixes must not collide with a literal name's slug either.
        if len({r['logical_origin'] for r in self._rows}) != len(rows):
            raise ValueError('Readable origin collision')
        self.world_id = world_id
        self._forward = {r['logical_origin']: r['transport_origin'] for r in self._rows}
        self._inverse = {v: k for k, v in self._forward.items()}
        pattern = '(?:' + '|'.join(re.escape(v) for v in sorted(self._inverse, key=len, reverse=True)) + ')'
        self._pattern = re.compile(pattern + r'''(?=$|[/#?\s"'<>])''') if rows else None

    @property
    def descriptor(self):
        return {'schema': VERSION, 'world_id': self.world_id, 'sites': deepcopy(self._rows)}

    def _translate(self, url, mapping):
        declared = _origin(url)
        if declared not in mapping:
            raise ValueError('URL outside declared world')
        parsed = urlsplit(url)
        # Slice the literal authority rather than the canonical spelling (:80,
        # hostname case), retaining the exact path/query/fragment representation.
        literal = parsed.scheme + '://' + parsed.netloc
        return mapping[declared] + url[len(literal):]

    def to_transport(self, url):
        return self._translate(url, self._forward)

    def to_public(self, url):
        return self._translate(url, self._inverse)

    def rewrite(self, text):
        return self._pattern.sub(lambda m: self._inverse[m.group()], text) if self._pattern else text

    def project(self, value):
        if isinstance(value, str):
            return self.rewrite(value)
        if isinstance(value, dict):
            return {self.project(k): self.project(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return type(value)(self.project(v) for v in value)
        return deepcopy(value)


class LocalOriginBridge(LogicalOrigins):
    """Reuse checkpoint routing registration, with Website transport/cookie rules.

    Browser storage, rather than httpx's shared localhost cookie jar, owns cookies.
    Each browser context receives its own bridge; no cookie crosses a site or context.
    """
    def __init__(self, identity, *, diagnostics_path=None):
        """Optionally append flushed/fsynced NDJSON around existing waits.

        Disabled by default; Runtime does not opt in automatically. Only declared
        origins and root/commerce API paths are emitted; other paths are redacted.
        Bodies, query strings, fragments, headers and exception messages are never
        recorded. Recording failures disable this sink, preserving routing behavior;
        `diagnostics_error` then gives only the exception class to the caller.
        """
        self.diagnostics_path = None if diagnostics_path is None else Path(diagnostics_path)
        self.diagnostics_error = None
        self._diagnostics_lock = Lock()
        self.identity = identity
        rows = identity.descriptor['sites']
        super().__init__({r['site_id']: r['logical_origin'] for r in rows},
                         {r['site_id']: r['transport_origin'] for r in rows})
        self.closed = False
        self.sessions = []
        self.pages = set()
        # A page can abandon an intercepted response during navigation. Keep
        # bounded, body/URL-free acknowledgement evidence even without a file
        # sink. Expiry never establishes whether a forwarded mutation committed.
        self.expired_interception_ack_count = 0
        self.expired_interception_acknowledgements = []

    def _record_phase(self, phase, request, **fields):
        if self.diagnostics_path is None or self.diagnostics_error is not None:
            return
        try:
            declared = _origin(request.url)
            logical = declared if declared in self.mapping else None
            path = urlsplit(request.url).path or '/'
        except (ValueError, TypeError):
            logical, path = None, None
        method = request.method
        row = {'schema': PHASE_SCHEMA, 'monotonic_ns': monotonic_ns(), 'phase': phase,
               'request_id': getattr(request, '_phase_request_id', None),
               'network_id': getattr(request, '_phase_network_id', None),
               'method': method if isinstance(method, str) and method in _PHASE_METHODS else None,
               'origin': logical, 'path': path if path in _PHASE_PATHS else '<redacted>', **fields}
        try:
            with self._diagnostics_lock:
                self.diagnostics_path.parent.mkdir(parents=True, exist_ok=True)
                with self.diagnostics_path.open('a', encoding='utf-8') as stream:
                    stream.write(json.dumps(row, ensure_ascii=True, allow_nan=False) + '\n')
                    stream.flush()
                    os.fsync(stream.fileno())
        except (OSError, ValueError, TypeError) as error:
            self.diagnostics_error = type(error).__name__

    @contextmanager
    def _phase(self, name, request, **fields):
        self._record_phase(name + '_enter', request, **fields)
        failed = False
        try:
            yield
        except BaseException as error:
            failed = True
            self._record_phase(name + '_error', request, error_type=type(error).__name__, **fields)
            raise
        finally:
            self._record_phase(name + '_exit', request, failed=failed, **fields)

    def _send_cdp(self, session, method, parameters, request):
        from playwright.sync_api import Error as PlaywrightError
        with self._phase('cdp', request, rpc_method=method):
            try:
                return session.send(method, parameters)
            except PlaywrightError as error:
                # Do not leak this terminal request-ID acknowledgement into
                # Playwright's event-listener error slot: it would prevent the
                # next unrelated CDP command from being sent. No HTTP or CDP
                # request is retried. Other protocol/target/transport errors
                # retain their normal failure path.
                suffix = f'Protocol error ({method}): Invalid InterceptionId.'
                if (type(error) is not PlaywrightError
                        or method not in ('Fetch.fulfillRequest', 'Fetch.failRequest')
                        or not error.message.endswith(suffix)):
                    raise
                outcome = {
                    'rpc_method': method,
                    'request_id': getattr(request, '_phase_request_id', None),
                    'network_id': getattr(request, '_phase_network_id', None),
                    'method': request.method if isinstance(request.method, str)
                              and request.method in _PHASE_METHODS else None,
                    'browser_acknowledged': False,
                    'backend_effects': 'unknown',
                    'replayed': False,
                }
                self.expired_interception_ack_count += 1
                self.expired_interception_acknowledgements.append(outcome)
                del self.expired_interception_acknowledgements[:-64]
                self._record_phase('cdp_ack_expired', request, rpc_method=method,
                    browser_acknowledged=False, backend_effects='unknown', replayed=False)
                return {}

    def replace(self, text):
        return self.identity.rewrite(text)

    def attach(self, context):
        # Playwright route() sees only the first request in a redirect chain.
        # A separate Chromium Fetch session covers every hop without DNS. Reuse
        # the checkpoint primitive's declared mapping/client, not its redirect gap.
        if len(context.pages) != 1 or context.service_workers:
            raise ValueError('Readable origins require one existing task page and no service workers')
        def guard(route, request):
            try:
                self.identity.to_transport(request.url)
            except ValueError:
                route.abort('blockedbyclient')
                return
            page = request.frame.page
            if page not in self.pages:
                route.abort('blockedbyclient')
                return
            route.fallback()
        context.route('**/*', guard)
        def attach_page(page):
            session = context.new_cdp_session(page)
            self.sessions.append(session)
            session.on('Fetch.requestPaused', lambda event: self._paused(session, event))
            session.send('Fetch.enable', {'patterns': [{'urlPattern': '*', 'requestStage': 'Request'}]})
            session.send('Network.setBypassServiceWorker', {'bypass': True})
            session.send('Network.setCacheDisabled', {'cacheDisabled': True})
            self.pages.add(page)
        for page in context.pages:
            attach_page(page)
        context.on('close', lambda *_: self.close())

    def _paused(self, session, event):
        data = event['request']
        request = SimpleNamespace(url=data['url'], method=data['method'],
                                  _phase_request_id=event['requestId'],
                                  _phase_network_id=event.get('networkId'))
        with self._phase('callback', request):
            self._forward_paused(session, event, request)

    def _forward_paused(self, session, event, request):
        data = event['request']
        headers = {k.lower(): v for k, v in data['headers'].items()}
        body = None
        if data.get('postDataEntries'):
            body = b''.join(base64.b64decode(row['bytes']) for row in data['postDataEntries'])
        elif data.get('postData') is not None:
            body = data['postData'].encode('utf-8')
        elif data.get('hasPostData'):
            # Current native checkout sends bounded UTF-8 JSON, never file uploads.
            body = self._send_cdp(session, 'Network.getRequestPostData',
                                 {'requestId': event['networkId']}, request)['postData'].encode('utf-8')
        request.all_headers = lambda: headers
        request.post_data_buffer = body
        bridge = self
        class Response:
            def abort(self, reason):
                bridge._send_cdp(session, 'Fetch.failRequest',
                                 {'requestId': event['requestId'], 'errorReason': 'BlockedByClient'}, request)

            def fulfill(self, *, status, body, headers=None):
                values = []
                for key, value in (headers or {}).items():
                    for part in value.split('\n') if key.lower() == 'set-cookie' else [value]:
                        values.append({'name': key, 'value': part})
                payload = body.encode('utf-8') if isinstance(body, str) else body
                bridge._send_cdp(session, 'Fetch.fulfillRequest',
                                 {'requestId': event['requestId'], 'responseCode': status,
                                  'responseHeaders': values, 'body': base64.b64encode(payload).decode('ascii')}, request)
        self.route(Response(), request)

    def close(self):
        if not self.closed:
            self.closed = True
            super().close()

    def _cookie(self, value, logical, physical):
        def domain(match):
            declared = match.group(2).strip().lstrip('.').lower()
            if declared == urlsplit(physical).hostname:
                return match.group(1) + urlsplit(logical).hostname
            return match.group()
        return re.sub(r'(?i)(;\s*domain\s*=\s*)([^;]+)', domain, value)

    def route(self, route, request):
        try:
            logical = _origin(request.url)
            target = self.identity.to_transport(request.url)
        except ValueError:
            route.abort('blockedbyclient')
            return
        physical = self.mapping[logical]
        headers = {k: v for k, v in request.all_headers().items() if k.lower() not in
                   ('host', 'content-length', 'accept-encoding', 'connection')}
        for key in ('origin', 'referer'):
            if key in headers:
                try:
                    headers[key] = self.identity.to_transport(headers[key])
                except ValueError:
                    route.abort('blockedbyclient')
                    return
        try:
            # Standalone Request deliberately bypasses Client.build_request's
            # cookie merging across localhost ports. Only Chromium's cookie is sent.
            with self._phase('http', request):
                response = self.client.send(httpx.Request(request.method, target, headers=headers,
                                           content=request.post_data_buffer), follow_redirects=False)
            self.client.cookies.clear()
        except httpx.HTTPError:
            route.fulfill(status=502, body='Local site transport unavailable')
            return
        result = {k: self.replace(v) for k, v in response.headers.items() if k.lower() not in
                  ('content-length', 'content-encoding', 'transfer-encoding', 'connection', 'set-cookie')}
        if 'location' in result:
            raw = response.headers['location']
            if '\\' in raw or any(ord(c) < 33 for c in raw) or raw.startswith('//'):
                route.fulfill(status=502, body='Ambiguous redirect rejected')
                return
            location = urljoin(request.url, self.replace(raw))
            try:
                self.identity.to_transport(location)
            except ValueError:
                route.fulfill(status=502, body='Off-world redirect rejected')
                return
            result['location'] = location
        cookies = response.headers.get_list('set-cookie')
        if cookies:
            result['set-cookie'] = '\n'.join(self._cookie(v, logical, physical) for v in cookies)
        body = response.content
        mime = response.headers.get('content-type', '').lower()
        if any(t in mime for t in ('text/', 'json', 'javascript')):
            try:
                body = self.replace(body.decode('utf-8')).encode('utf-8')
            except UnicodeDecodeError:
                route.fulfill(status=502, body='Unsupported local text encoding')
                return
        route.fulfill(status=response.status_code, headers=result, body=body)


class InitialPageNetwork:
    """Setup-only Chromium target request observer; never a completeness claim.

    Attach on about:blank before native initial navigation. A separate Network
    session observes actual Chromium identities even when dual Fetch routing
    hides requests from Playwright. No forwarding, capture or replay is added.
    """
    def __init__(self, page):
        self.page = page
        self.session = None
        self.pending = {}
        self.last_activity = monotonic()
        self.document_seen = False
        self.started_requests = self.finished_requests = self.failed_requests = 0
        self.redirect_hops = self.failed_mutations = 0
        self.observation_error = None
        self.record = {'scope': 'initial_task_start_page_network_quietness',
                       'status': 'not_waited', 'semantic_completeness': 'unclaimed'}

    def __enter__(self):
        if self.session is not None or self.page.url not in ('about:blank', ''):
            raise ValueError('Observe an unused task page before initial navigation')
        self.session = self.page.context.new_cdp_session(self.page)
        try:
            self.main_frame_id = self.session.send('Page.getFrameTree')['frameTree']['frame']['id']
            self.session.on('Network.requestWillBeSent', self._started)
            self.session.on('Network.loadingFinished', self._finished)
            self.session.on('Network.loadingFailed', self._failed)
            self.session.send('Network.enable')
        except BaseException as error:
            try:
                self.close()
            except Exception as cleanup_error:
                error.add_note('Initial-page observer cleanup failed: ' + type(cleanup_error).__name__)
            raise
        return self

    def _started(self, event):
        identity = event.get('requestId')
        if not isinstance(identity, str):
            self.observation_error = 'invalid_request_identity'
            return
        self.last_activity = monotonic()
        self.started_requests += 1
        self.redirect_hops += int('redirectResponse' in event)
        self.pending[identity] = event.get('request', {}).get('method')
        if event.get('type') == 'Document' and event.get('frameId') == self.main_frame_id:
            self.document_seen = True

    def _terminal(self, event, *, failed):
        identity = event.get('requestId')
        if not isinstance(identity, str):
            self.observation_error = 'invalid_terminal_identity'
            return
        self.last_activity = monotonic()
        method = self.pending.pop(identity, None)
        if failed:
            self.failed_requests += 1
            if method in ('POST', 'PUT', 'PATCH', 'DELETE'):
                self.failed_mutations += 1
        else:
            self.finished_requests += 1

    def _finished(self, event):
        self._terminal(event, failed=False)

    def _failed(self, event):
        self._terminal(event, failed=True)

    def wait(self, *, timeout_ms=5000, quiet_ms=100):
        if (type(timeout_ms) is not int or type(quiet_ms) is not int
                or not 0 < quiet_ms < timeout_ms):
            raise ValueError('Declare positive quiet interval below the finite timeout')
        if self.session is None or self.record['status'] != 'not_waited':
            raise ValueError('Initial-page network observation is once-only')
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        started = monotonic()
        self.record.update(timeout_ms=timeout_ms, quiet_ms=quiet_ms, status='failed',
                           observation='Chromium Network events attached before initial navigation')
        try:
            while True:
                now = monotonic()
                if self.observation_error is not None:
                    raise ValueError('Initial-page network observation failed: ' + self.observation_error)
                if now - started >= timeout_ms / 1000:
                    raise PlaywrightTimeoutError('Initial task-page network quietness exceeded '
                                                + str(timeout_ms) + 'ms')
                if (self.document_seen and not self.pending
                        and now - max(started, self.last_activity) >= quiet_ms / 1000):
                    self.record['status'] = 'passed'
                    break
                # Pump Chromium callbacks; no DOM capture, HTTP call or action.
                self.page.wait_for_timeout(min(20, max(1, (timeout_ms / 1000 - (now - started)) * 1000)))
        finally:
            elapsed = monotonic() - started
            self.record.update(elapsed_seconds=elapsed, overrun_seconds=max(0., elapsed-timeout_ms/1000),
                document_seen=self.document_seen, pending_requests=len(self.pending),
                started_requests=self.started_requests, finished_requests=self.finished_requests,
                failed_requests=self.failed_requests, redirect_hops=self.redirect_hops,
                failed_mutations=self.failed_mutations, failed_mutation_backend_effects='unknown')
        return deepcopy(self.record)

    def close(self):
        if self.session is not None:
            session, self.session = self.session, None
            session.detach()

    def __exit__(self, kind, error, traceback):
        try:
            self.close()
        except Exception as cleanup_error:
            if error is None:
                raise
            error.add_note('Initial-page observer cleanup failed: ' + type(cleanup_error).__name__)
