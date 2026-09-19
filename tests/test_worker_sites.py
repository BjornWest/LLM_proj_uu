import json
from uuid import uuid4
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading

import httpx
import pytest

from intent_browser.worker_sites import WorkerSites
from scripts.worker_site_service import WorkerPool, worker_handler


class Reader:
    ids = [1, 4, 8]
    baselines = []
    def __init__(self, *args): pass
    def submission_ids(self): return list(self.ids)
    def posts_since(self, baseline):
        self.baselines.append(list(baseline))
        return [{'id': i} for i in self.ids if i not in baseline]
    def vote_state(self, target): return {'target': target}
    def wishlist_state(self): return {'items': [], 'options': []}


@pytest.fixture
def service(tmp_path):
    seen = []
    class Upstream(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_GET(self):
            seen.append({'path': self.path, 'headers': dict(self.headers)})
            self.send_response(302 if self.path == '/escape' else 200)
            if self.path == '/escape': self.send_header('Location', '///outside.invalid/secret')
            self.send_header('Content-Length', '2'); self.end_headers(); self.wfile.write(b'ok')
    upstream = ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
    threading.Thread(target=upstream.serve_forever, daemon=True).start()
    cfg = {'browser_origin': 'http://worker-environment.test', 'proxy_origin': None,
           'tasks': {'posts': {'site_id': 'webarena-forum', 'revision': 'r1', 'family': 'webarena.posts'},
                     'vote': {'site_id': 'webarena-forum', 'revision': 'r2', 'family': 'webarena.votes', 'target_id': 47}},
           'sites': [{'site_id': s, 'image_id': 'test-image', 'upstream_origin': f'http://127.0.0.1:{upstream.server_port}',
                      'account_headers': {'X-Test-Account': 'fixture'}} for s in ['webarena-shopping', 'webarena-forum']]}
    def reset(slot):
        slot.update(container_id='test-container', reset_report_sha256='test-reset')
    pool = WorkerPool(cfg, tmp_path, resetter=reset, reader_factory=Reader)
    for slot in pool.slots.values(): reset(slot); slot.update(status='ready', generation=1)
    server = ThreadingHTTPServer(('127.0.0.1', 0), worker_handler(pool, 'x' * 43))
    cfg['proxy_origin'] = f'http://127.0.0.1:{server.server_port}'
    threading.Thread(target=server.serve_forever, daemon=True).start()
    client = WorkerSites(cfg['proxy_origin'], 'x' * 43)
    try: yield pool, client, seen
    finally:
        client.close(); server.shutdown(); server.server_close(); upstream.shutdown(); upstream.server_close(); pool.close()


def test_scoped_state_retains_full_host_baseline_and_exact_identity(service):
    pool, service, seen = service
    Reader.ids = [1, 4, 8]
    lease = service.acquire('posts', 'r1', str(uuid4()))
    identity = lease.attest()
    assert identity['instance_id'] == 'test-container'
    assert lease.state_read('forum.submission_ids', {}) == [1, 4, 8]
    Reader.ids = [1, 2, 4, 8, 9]  # Includes a new ID below the previous maximum.
    assert lease.state_read('forum.posts_since', {'baseline_ids': [1, 4, 8]}) == [{'id': 2}, {'id': 9}]
    with pytest.raises(ValueError): lease.state_read('forum.posts_since', {'baseline_ids': [8]})
    with pytest.raises(RuntimeError, match='403'): lease.state_read('shopping.wishlist_state', {})
    assert Reader.baselines[-1] == [1, 4, 8]
    lease.close()
    with pytest.raises(RuntimeError, match='released'): lease.attest()


def test_private_http_proxy_scope_headers_redirect_and_revocation(service):
    pool, service, seen = service
    lease = service.acquire('vote', 'r2', str(uuid4()))
    assert lease.state_read('forum.vote_state', {'target_id': 47}) == {'target': 47}
    with pytest.raises(ValueError): lease.state_read('forum.vote_state', {'target_id': 48})
    proxy = lease.browser_proxy
    with httpx.Client(proxy=httpx.Proxy(proxy['server'], auth=(proxy['username'], proxy['password'])),
                      trust_env=False, follow_redirects=True) as browser:
        assert browser.get(lease.origin + '/').status_code == 200
        headers = {k.lower(): v for k, v in seen[-1]['headers'].items()}
        assert headers['x-test-account'] == 'fixture'
        assert not {'proxy-authorization', 'x-daylight-lease', 'authorization'} & headers.keys()
        assert browser.get('http://outside.invalid/').status_code == 403
        assert browser.get(lease.origin + '/escape').status_code == 502
        assert len(seen) == 2
        lease.close()
        assert browser.get(lease.origin + '/').status_code == 410
        assert len(seen) == 2


def test_exact_admission_and_http_operation_arguments(service):
    pool, service, _ = service
    for payload in [dict(task_id=[], revision='r1', session_id=str(uuid4())),
                    dict(task_id='posts', revision='r1', session_id=str(uuid4()), sql='bad')]:
        assert pool.control('acquire', payload)[0] == 400
    with pytest.raises(RuntimeError, match='409'): service.acquire('posts', 'wrong', str(uuid4()))
    lease = service.acquire('posts', 'r1', str(uuid4()))
    token = lease.browser_proxy['password']
    assert pool.control('state', {'lease_token': token, 'operation': []})[0] == 400
    assert pool.control('state', {'lease_token': token, 'operation': 'forum.posts_since', 'baseline_ids': []})[0] == 400
    assert pool.control('state', {'lease_token': token, 'operation': 'forum.posts_since'})[0] == 409
    pool.slots['webarena-forum']['container_id'] = 'replaced'
    with pytest.raises(RuntimeError, match='changed'): lease.attest()
    lease.close()


def test_failed_release_is_not_replayed():
    requests = []
    def transport(request):
        requests.append(request)
        return httpx.Response(503)
    client = WorkerSites('http://localhost', 'x' * 43, transport=httpx.MockTransport(transport))
    from intent_browser.worker_sites import WorkerLease
    lease = WorkerLease(client, {'identity': {'instance_id': 'i', 'reset_id': 'r'}, 'lease_token': 'private'})
    with pytest.raises(RuntimeError): lease.close()
    lease.close()
    assert len(requests) == 1
    client.close()
