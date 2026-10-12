import copy
import datetime as dt
import http.client
import http.server
import json
from pathlib import Path
import subprocess
import sys
import threading
from uuid import UUID

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import verda_deadline as deadline

ID = str(UUID(int=1)); RUN = str(UUID(int=2)); VOLUME = str(UUID(int=3))
def spec():
    return {'instance_id': ID, 'run_id': RUN, 'hostname': 'qwen-test',
            'instance_type': '1RTXPRO6000.30V', 'location': 'FIN-02',
            'allocation_started_at': '2026-10-12T12:00:00Z',
            'provider_created_at': '2026-10-12T12:00:01Z',
            'deadline': '2026-10-12T12:01:00Z',
            'volume_ids': [VOLUME], 'delete_volume_ids': []}
def row():
    return {'id': ID, 'hostname': 'qwen-test', 'instance_type': '1RTXPRO6000.30V',
            'created_at': '2026-10-12T12:00:01Z', 'location': 'FIN-02',
            'tags': [{'key': 'run', 'value': RUN}], 'status': 'running',
            'volume_ids': [], 'os_volume_id': VOLUME, 'jupyter_token': 'never-record'}


class Clock:
    def __init__(self): self.t = 0
    def monotonic(self): return self.t
    def sleep(self, seconds): self.t += seconds


class Client:
    def __init__(self, rows, error_on_delete=False):
        self.rows = iter(rows); self.last = None; self.deletes = []; self.error_on_delete = error_on_delete
    def instance(self, instance_id, **kwargs):
        self.last = next(self.rows, self.last)
        return self.last
    def delete(self, body, **kwargs):
        self.deletes.append(body)
        if self.error_on_delete: raise TimeoutError('ambiguous acceptance')
        return True


def test_cli_defaults_to_network_free_plan(tmp_path):
    path = tmp_path / 'spec.json'; path.write_text(json.dumps(spec()))
    result = subprocess.run([sys.executable, '-B', str(SCRIPTS / 'verda_deadline.py'),
        '--spec', str(path)], check=True, capture_output=True, text=True, timeout=10,
        env={'PATH': '/usr/bin'})
    data = json.loads(result.stdout)
    assert data['no_create_API'] and data['delete']['volume_ids'] == []
    assert data['retained_volume_ids'] == [VOLUME]
    assert not (tmp_path / 'receipt.json').exists()


@pytest.mark.parametrize('field,value', [('deadline', '2026-10-12T11:59:59Z'),
    ('deadline', '2026-10-14T12:00:00Z'), ('allocation_started_at', '2026-10-12T12:00:02Z'),
    ('instance_id', 'not-uuid'), ('delete_volume_ids', [str(UUID(int=4))]),
    ('deadline', '2026-10-12T12:01:00'), ('location', ''),
    ('provider_created_at', '2026-10-12T13:00:00Z'), ('run_id', ID), ('volume_ids', [1])])
def test_bad_allocation_or_storage_boundaries_rejected(field, value):
    s = spec(); s[field] = value
    with pytest.raises(ValueError): deadline.plan(s)


def cleanup(client, tmp_path, s=None):
    clock = Clock()
    return deadline.cleanup(client, s or spec(), tmp_path / 'cleanup.json', reason='test',
                            monotonic=clock.monotonic, sleep=clock.sleep, confirmation_seconds=10)


def test_delete_acceptance_needs_actual_removal_and_never_records_tokens(tmp_path):
    deleting = row(); deleting['status'] = 'deleting'
    client = Client([row(), deleting, None])
    result = cleanup(client, tmp_path)
    assert result['delete_accepted'] and result['termination_confirmed']
    assert client.deletes == [deadline.plan(spec())['delete']]
    assert 'never-record' not in (tmp_path / 'cleanup.json').read_text()
    assert (tmp_path / 'cleanup.json').stat().st_mode & 0o777 == 0o600


def test_ambiguous_delete_is_read_back_without_reallocating(tmp_path):
    deleting = row(); deleting['status'] = 'deleting'
    client = Client([row(), deleting, None], error_on_delete=True)
    result = cleanup(client, tmp_path)
    assert result['termination_confirmed'] and not result['delete_accepted']
    assert len(client.deletes) == 1


def test_running_instance_never_marked_terminated_and_cleanup_retries_bounded(tmp_path):
    client = Client([row()], error_on_delete=True)
    with pytest.raises(RuntimeError): cleanup(client, tmp_path)
    saved = json.loads((tmp_path / 'cleanup.json').read_text())
    assert not saved['termination_confirmed'] and len(client.deletes) == 3


@pytest.mark.parametrize('field,value', [('hostname', 'someone-else'),
    ('instance_type', 'different'), ('tags', []), ('created_at', '2026-10-12T12:00:02Z')])
def test_identity_drift_blocks_wrong_instance_deletion(tmp_path, field, value):
    other = row(); other[field] = value; client = Client([other])
    with pytest.raises(RuntimeError): cleanup(client, tmp_path)
    assert not client.deletes


def test_storage_drift_deletes_owned_gpu_but_retains_all_volumes_and_reports_failure(tmp_path):
    current = row(); current['volume_ids'] = [str(UUID(int=4))]
    s = spec(); s['delete_volume_ids'] = [VOLUME]
    client = Client([current, None])
    with pytest.raises(RuntimeError): cleanup(client, tmp_path, s)
    assert client.deletes[0]['volume_ids'] == []
    saved = json.loads((tmp_path / 'cleanup.json').read_text())
    assert saved['termination_confirmed'] and saved['storage_policy_mismatch']


def test_wall_clock_jump_never_renews_relative_allowance(tmp_path):
    clock = Clock(); start = deadline.timestamp(spec()['allocation_started_at'])
    wall = lambda: start + 40 + clock.t if clock.t < 4 else start - 100 + clock.t
    client = Client([row(), row(), None])
    result = deadline.watch(client, spec(), tmp_path / 'receipt.json',
        wall=wall, monotonic=clock.monotonic, sleep=clock.sleep)
    assert result['reason'] == 'deadline' and 20 <= clock.t <= 24


def test_finish_marker_must_bind_the_exact_local_allocation(tmp_path):
    marker = tmp_path / 'finish.json'; marker.write_text(json.dumps({'run_id': 'stale', 'instance_id': ID}))
    client = Client([row(), row(), None])
    with pytest.raises(RuntimeError):
        deadline.watch(client, spec(), tmp_path / 'receipt.json', finish_marker=marker,
                       wall=lambda: deadline.timestamp(spec()['allocation_started_at']))
    assert json.loads((tmp_path / 'receipt.json').read_text())['reason'] == 'watch_failed'


def test_create_operation_rejected_before_auth_or_network():
    client = deadline.Client('fake-id', 'fake-secret')
    with pytest.raises(ValueError, match='cannot allocate'):
        client._call('POST', '/v1/instances', {})


def test_oauth_and_authenticated_call_share_one_timeout(monkeypatch):
    clock = Clock(); budgets = []
    class Response:
        status = 200
        length = 0
        def __init__(self, path): self.path = path
        def read(self, limit):
            if self.path == '/v1/oauth2/token':
                clock.t += 7
                return b'{"access_token":"fake-token"}'
            return b'[]'
    class Connection:
        def __init__(self, host, timeout): budgets.append(timeout); self.sock = self
        def connect(self): pass
        def shutdown(self, how): pass
        def request(self, method, path, body, headers): self.path = path
        def getresponse(self): return Response(self.path)
        def close(self): pass
    monkeypatch.setattr(deadline.time, 'monotonic', clock.monotonic)
    monkeypatch.setattr(deadline.http.client, 'HTTPSConnection', Connection)
    assert deadline.Client('fake-id', 'fake-secret').instance(ID) is None
    assert budgets == [10, 3]


def test_real_http_mock_auth_identity_delete_and_confirmation(tmp_path, monkeypatch):
    calls = []; state = {'deleted': False, 'query_count': 0}
    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'
        def log_message(self, *args): pass
        def respond(self, data):
            raw = json.dumps(data).encode()
            self.send_response(200); self.send_header('Content-Length', str(len(raw)))
            self.send_header('Connection', 'close'); self.end_headers(); self.wfile.write(raw)
        def do_POST(self):
            assert self.path == '/v1/oauth2/token'
            data = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            assert data['client_secret'] == 'fake-secret'
            calls.append(('POST', self.path))
            self.respond({'access_token': 'fake-token'})
        def do_GET(self):
            assert self.headers['Authorization'] == 'Bearer fake-token'
            calls.append(('GET', self.path)); state['query_count'] += 1
            if state['deleted']: self.respond([])
            else: self.respond(row())  # Documented single-object variant.
        def do_PUT(self):
            assert self.headers['Authorization'] == 'Bearer fake-token'
            data = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            assert data == deadline.plan(spec())['delete']
            calls.append(('PUT', self.path)); state['deleted'] = True
            self.respond(None)
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    monkeypatch.setattr(deadline.http.client, 'HTTPSConnection',
        lambda host, timeout: http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=timeout))
    try:
        result = cleanup(deadline.Client('fake-id', 'fake-secret'), tmp_path)
        assert result['termination_confirmed'] and state['query_count'] == 3
        assert [method for method, path in calls] == ['POST', 'GET', 'PUT', 'GET', 'GET']
        saved = (tmp_path / 'cleanup.json').read_text()
        assert 'fake-secret' not in saved and 'fake-token' not in saved and 'never-record' not in saved
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)


def test_receipt_storage_failure_cannot_block_owned_vm_deletion(tmp_path, monkeypatch):
    def failed_save(*args): raise PermissionError('read-only private receipt')
    monkeypatch.setattr(deadline, 'save', failed_save)
    client = Client([row(), None])
    with pytest.raises(RuntimeError): cleanup(client, tmp_path)
    assert len(client.deletes) == 1


@pytest.mark.parametrize('absent', [None, {'id': ID, 'status': 'notfound'}])
def test_never_observed_instance_is_not_reported_as_terminated(tmp_path, absent):
    client = Client([absent])
    with pytest.raises(RuntimeError):
        deadline.watch(client, spec(), tmp_path / 'receipt.json',
                       wall=lambda: deadline.timestamp(spec()['allocation_started_at']))
    saved = json.loads((tmp_path / 'receipt.json').read_text())
    assert not saved['termination_confirmed'] and saved['unobserved_absence']
    assert not client.deletes


def test_delete_retries_spread_across_confirmation_window(tmp_path):
    clock = Clock(); times = []
    class Transient(Client):
        def delete(self, body, **kwargs):
            times.append(clock.t)
            raise deadline.APIError(503)
    with pytest.raises(RuntimeError):
        deadline.cleanup(Transient([row()]), spec(), tmp_path / 'receipt.json', reason='test',
            monotonic=clock.monotonic, sleep=clock.sleep, confirmation_seconds=18)
    assert times == [0, 6, 12]


def test_initial_transient_read_is_retried_without_early_deletion(tmp_path):
    clock = Clock(); start = deadline.timestamp(spec()['allocation_started_at'])
    class Transient(Client):
        def instance(self, *args, **kwargs):
            if clock.t == 0: raise deadline.APIError(503)
            return super().instance(*args, **kwargs)
    client = Transient([row(), row(), None])
    result = deadline.watch(client, spec(), tmp_path / 'receipt.json',
        wall=lambda:start + clock.t, monotonic=clock.monotonic, sleep=clock.sleep)
    assert result['reason'] == 'deadline' and clock.t >= 60
    assert result['termination_confirmed'] and len(client.deletes) == 1


def test_detached_disks_and_missing_tags_during_delete_do_not_undo_verified_ownership(tmp_path):
    deleting = {'id': ID, 'status': 'deleting'}
    result = cleanup(Client([row(), deleting, None]), tmp_path)
    assert result['termination_confirmed'] and not result['storage_policy_mismatch']


def test_207_action_error_is_not_an_accepted_delete(monkeypatch):
    client = deadline.Client('fake-id', 'fake-secret')
    monkeypatch.setattr(client, '_call', lambda *a, **kw: [
        {'instanceId': ID, 'action': 'delete', 'status': 'error', 'error': 'never-log-provider-body'}])
    with pytest.raises(deadline.ResponseError): client.delete(deadline.plan(spec())['delete'])


@pytest.fixture
def flaky_http_api():
    state = {'deleted': False, 'puts': 0, 'gets': 0, 'drop_read': False, 'drop_delete': False}
    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'
        def log_message(self, *args): pass
        def respond(self, data):
            raw = json.dumps(data).encode()
            self.send_response(200); self.send_header('Content-Length', str(len(raw)))
            self.send_header('Connection', 'close'); self.end_headers(); self.wfile.write(raw)
        def truncated(self):
            self.send_response(200); self.send_header('Content-Length', '100')
            self.send_header('Connection', 'close'); self.end_headers(); self.wfile.write(b'{"partial":')
            self.close_connection = True
        def do_POST(self):
            self.rfile.read(int(self.headers['Content-Length']))
            self.respond({'access_token': 'fake-token'})
        def do_GET(self):
            state['gets'] += 1
            if state['drop_read']:
                state['drop_read'] = False; self.truncated()
            else: self.respond([] if state['deleted'] else row())
        def do_PUT(self):
            self.rfile.read(int(self.headers['Content-Length']))
            state['puts'] += 1; state['deleted'] = True
            if state['drop_delete']: self.truncated()
            else: self.respond([{'instanceId': ID, 'action': 'delete', 'status': 'success'}])
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try: yield server, state
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)


@pytest.mark.parametrize('failure', ['drop_read', 'drop_delete'])
def test_partial_response_retries_or_reads_back_ambiguous_delete(tmp_path, monkeypatch, flaky_http_api, failure):
    server, state = flaky_http_api; state[failure] = True
    monkeypatch.setattr(deadline.http.client, 'HTTPSConnection',
        lambda host, timeout: http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=timeout))
    result = cleanup(deadline.Client('fake-id', 'fake-secret'), tmp_path)
    assert result['termination_confirmed'] and state['puts'] == 1
    assert 'ResponseError' in result['transport_error_types']
    if failure == 'drop_delete': assert not result['delete_accepted']


@pytest.mark.parametrize('stop_signal', ['SIGINT', 'SIGTERM', 'SIGHUP', 'SIGQUIT',
                                      'SIGHUP,SIGTERM', 'SIGTERM,SIGHUP', 'SIGINT,SIGTERM', 'SIGINT,SIGQUIT'])
def test_real_execute_cli_cleans_up_on_terminal_signals(tmp_path, flaky_http_api, stop_signal):
    import os, signal, time
    server, state = flaky_http_api
    now = dt.datetime.now(dt.timezone.utc)
    s = spec()
    s.update(allocation_started_at=now.isoformat(), provider_created_at=now.isoformat(),
             deadline=(now + dt.timedelta(minutes=2)).isoformat())
    # Bind the fake provider's row to this fresh allocation, without real secrets.
    original_row = row
    def actual_row():
        data = original_row(); data['created_at'] = s['provider_created_at']; return data
    # Handler resolves its global row callable for this test only.
    globals()['row'] = actual_row
    driver = tmp_path / 'drive.py'
    driver.write_text('import sys,http.client\n'
        'sys.path.insert(0,' + repr(str(SCRIPTS)) + ')\nimport verda_deadline as d\n'
        'd.http.client.HTTPSConnection=lambda host,timeout: http.client.HTTPConnection("127.0.0.1",'
        + str(server.server_port) + ',timeout=timeout)\nd.main()\n')
    spec_path = tmp_path / 'spec.json'; spec_path.write_text(json.dumps(s))
    receipt = tmp_path / 'receipt.json'
    process = subprocess.Popen([sys.executable, '-B', str(driver), '--spec', str(spec_path),
        '--execute', '--receipt', str(receipt)], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env={'PATH': '/usr/bin', 'VERDA_CLIENT_ID': 'fake-id', 'VERDA_CLIENT_SECRET': 'fake-secret'})
    try:
        ready_until = time.monotonic() + 8
        while time.monotonic() < ready_until:
            if process.poll() is not None: break
            if receipt.exists() and json.loads(receipt.read_text()).get('status') == 'watching': break
            time.sleep(.02)
        assert process.poll() is None and receipt.exists()
        assert json.loads(receipt.read_text())['status'] == 'watching'
        for name in stop_signal.split(','):
            process.send_signal(getattr(signal, name))
        out, err = process.communicate(timeout=12)
        assert process.returncode == 0, err.decode()
        saved = json.loads(receipt.read_text())
        assert saved['reason'] == 'signal' and saved['termination_confirmed']
        assert state['puts'] == 1 and state['deleted']
        assert b'fake-secret' not in out + err and b'fake-token' not in out + err
    finally:
        globals()['row'] = original_row
        if process.poll() is None: process.kill(); process.communicate(timeout=2)


def test_receipt_and_stderr_failure_still_delete_and_report_outcome(tmp_path, monkeypatch):
    class BrokenLog:
        def write(self, data): raise OSError('full disk or closed terminal')
        def flush(self): raise OSError('full disk or closed terminal')
    monkeypatch.setattr(deadline.sys, 'stderr', BrokenLog())
    def failed_save(*args): raise PermissionError('receipt unavailable')
    monkeypatch.setattr(deadline, 'save', failed_save)
    client = Client([row(), None])
    with pytest.raises(RuntimeError, match='termination_confirmed=True, receipt_persisted=False'):
        cleanup(client, tmp_path)
    assert len(client.deletes) == 1


def test_single_absent_response_does_not_confirm_an_existing_instance(tmp_path):
    clock = Clock(); client = Client([None, row(), None, None])
    result = deadline.cleanup(client, spec(), tmp_path / 'receipt.json', reason='test',
        ownership_observed=True, monotonic=clock.monotonic, sleep=clock.sleep, confirmation_seconds=12)
    assert result['termination_confirmed'] and len(client.deletes) == 1
    assert result['consecutive_absent_reads'] == 2


def test_malformed_instance_object_is_retryable(monkeypatch):
    client = deadline.Client('fake-id', 'fake-secret')
    monkeypatch.setattr(client, '_call', lambda *a, **kw: {'message': 'not an instance'})
    with pytest.raises(deadline.ResponseError): client.instance(ID)


def test_expired_watch_goes_directly_to_cleanup_with_normal_read_budget(tmp_path):
    clock = Clock()
    class SlowRead(Client):
        def instance(self, *a, timeout=10):
            assert timeout > .05
            return super().instance(*a)
    client = SlowRead([row(), None])
    result = deadline.watch(client, spec(), tmp_path / 'receipt.json',
        wall=lambda:deadline.timestamp(spec()['deadline']) + 1,
        monotonic=clock.monotonic, sleep=clock.sleep)
    assert result['reason'] == 'deadline' and result['termination_confirmed']
    assert len(client.deletes) == 1
