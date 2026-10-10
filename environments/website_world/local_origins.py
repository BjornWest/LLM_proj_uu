"""One world identity map and a context-local, loopback-only browser bridge.

Readable URLs are an explicit new-episode projection. They require this bridge;
the machine's DNS/hosts configuration and ordinary localhost previews are untouched.
"""
from copy import deepcopy
from collections import Counter
from hashlib import sha256
import ipaddress
import base64
import re
import unicodedata
from types import SimpleNamespace
from urllib.parse import urljoin, urlsplit

import httpx
from intent_browser.checkpoint_browser import LogicalOrigins
from intent_browser.navigation import origin

VERSION = 'website-local-origins-v1'


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
    def __init__(self, identity):
        self.identity = identity
        rows = identity.descriptor['sites']
        super().__init__({r['site_id']: r['logical_origin'] for r in rows},
                         {r['site_id']: r['transport_origin'] for r in rows})
        self.closed = False
        self.sessions = []
        self.pages = set()

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
        headers = {k.lower(): v for k, v in data['headers'].items()}
        body = None
        if data.get('postDataEntries'):
            body = b''.join(base64.b64decode(row['bytes']) for row in data['postDataEntries'])
        elif data.get('postData') is not None:
            body = data['postData'].encode('utf-8')
        elif data.get('hasPostData'):
            # Current native checkout sends bounded UTF-8 JSON, never file uploads.
            body = session.send('Network.getRequestPostData', {'requestId': event['networkId']})['postData'].encode('utf-8')
        request = SimpleNamespace(url=data['url'], method=data['method'],
                                  all_headers=lambda: headers, post_data_buffer=body)
        class Response:
            def abort(self, reason):
                session.send('Fetch.failRequest', {'requestId': event['requestId'], 'errorReason': 'BlockedByClient'})

            def fulfill(self, *, status, body, headers=None):
                values = []
                for key, value in (headers or {}).items():
                    for part in value.split('\n') if key.lower() == 'set-cookie' else [value]:
                        values.append({'name': key, 'value': part})
                payload = body.encode('utf-8') if isinstance(body, str) else body
                session.send('Fetch.fulfillRequest', {'requestId': event['requestId'], 'responseCode': status,
                              'responseHeaders': values, 'body': base64.b64encode(payload).decode('ascii')})
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
