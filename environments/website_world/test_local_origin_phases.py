"""Optional bridge phase receipts with fake CDP and HTTP; no browser or host."""
import json
from types import SimpleNamespace

import httpx
import pytest

from environments.website_world.local_origins import LocalOriginBridge, OriginMap, PHASE_SCHEMA

SECRET = 'address-and-private-query-secret'


def identity():
    return OriginMap([{'site_id': 'shop', 'kind': 'retailer', 'name': 'Shop',
                       'origin': 'http://localhost:8311'}], world_id='source-fixture')


def event(**changes):
    request = {'url': 'https://shop.test/api/session?address=' + SECRET + '#' + SECRET,
               'method': 'POST', 'headers': {'X-Private': SECRET}, 'postData': SECRET}
    request.update(changes)
    return {'requestId': 'fetch-1', 'networkId': 'network-1', 'request': request}


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


class Session:
    def __init__(self, path=None, *, failure=None):
        self.path, self.failure, self.calls = path, failure, []

    def send(self, method, parameters):
        if self.path is not None:
            # Receipt is on disk before the original possibly blocking RPC.
            last = rows(self.path)[-1]
            assert last['phase'] == 'cdp_enter' and last['rpc_method'] == method
        self.calls.append((method, parameters))
        if method == self.failure:
            raise RuntimeError(SECRET)
        return {'postData': SECRET} if method == 'Network.getRequestPostData' else {}


def bridge(path, handler):
    value = LocalOriginBridge(identity(), diagnostics_path=path)
    value.client.close()
    value.client = httpx.Client(transport=httpx.MockTransport(handler), timeout=10,
                               follow_redirects=False, trust_env=False)
    return value


def response(request):
    return httpx.Response(200, text=SECRET, headers={'set-cookie': 'private=' + SECRET}, request=request)


def test_disabled_recorder_preserves_default_routing_and_creates_no_file(tmp_path):
    value = bridge(None, response)
    session = Session()
    try:
        value._paused(session, event())
        assert value.diagnostics_path is None and value.diagnostics_error is None
        assert [method for method, _ in session.calls] == ['Fetch.fulfillRequest']
        assert session.calls[0][1]['responseCode'] == 200
        assert list(tmp_path.iterdir()) == []
    finally:
        value.close()


def test_callback_http_and_cdp_receipts_append_flush_and_fsync_before_waits(tmp_path, monkeypatch):
    path = tmp_path/'phases'/'receipts.ndjson'
    path.parent.mkdir()
    path.write_text('{"previous":true}\n')
    synced = []
    import environments.website_world.local_origins as source
    original_fsync = source.os.fsync

    def fsync(fd):
        synced.append(rows(path)[-1]['phase'])
        original_fsync(fd)

    monkeypatch.setattr(source.os, 'fsync', fsync)

    def http(request):
        assert rows(path)[-1]['phase'] == 'http_enter'
        assert synced[-1] == 'http_enter'
        # Forwarding still retains the original request, not its log projection.
        assert request.url.query == ('address=' + SECRET).encode()
        assert request.content == SECRET.encode() and request.headers['X-Private'] == SECRET
        assert request.extensions['timeout']['read'] == 10
        return response(request)

    value = bridge(path, http)
    try:
        value._paused(Session(path), event())
        records = rows(path)
        assert records.pop(0) == {'previous': True}
        phases = [row['phase'] for row in records]
        assert phases == ['callback_enter', 'http_enter', 'http_exit', 'cdp_enter', 'cdp_exit', 'callback_exit']
        assert synced == phases
        assert all(row['schema'] == PHASE_SCHEMA for row in records)
        assert all(row['origin'] == 'https://shop.test' and row['path'] == '/api/session' for row in records)
        assert all(row['request_id'] == 'fetch-1' and row['network_id'] == 'network-1' for row in records)
        assert all(row['method'] == 'POST' for row in records)
        stamps = [row['monotonic_ns'] for row in records]
        assert stamps == sorted(stamps) and all(type(stamp) is int for stamp in stamps)
        assert SECRET not in path.read_text()
    finally:
        value.close()


def test_http_timeout_records_error_and_preserves_original_502_fulfillment(tmp_path):
    path = tmp_path/'receipts.ndjson'

    def failure(request):
        raise httpx.ReadTimeout(SECRET, request=request)

    value = bridge(path, failure)
    session = Session(path)
    try:
        value._paused(session, event())
        records = rows(path)
        assert [row['phase'] for row in records] == [
            'callback_enter', 'http_enter', 'http_error', 'http_exit', 'cdp_enter', 'cdp_exit', 'callback_exit']
        assert records[2]['error_type'] == 'ReadTimeout' and records[3]['failed'] is True
        assert records[-1]['failed'] is False  # callback successfully fulfilled the existing 502
        assert session.calls[-1][1]['responseCode'] == 502
        assert SECRET not in path.read_text()
    finally:
        value.close()


@pytest.mark.parametrize('rpc', ('Network.getRequestPostData', 'Fetch.fulfillRequest', 'Fetch.failRequest'))
def test_cdp_exception_records_phase_and_propagates_without_replay(tmp_path, rpc):
    path = tmp_path/'receipts.ndjson'
    value = bridge(path, response)
    session = Session(path, failure=rpc)
    request = event()
    if rpc == 'Network.getRequestPostData':
        request['request'].pop('postData')
        request['request']['hasPostData'] = True
    elif rpc == 'Fetch.failRequest':
        request['request']['url'] = 'https://outside.test/private/' + SECRET
    try:
        with pytest.raises(RuntimeError, match=SECRET):
            value._paused(session, request)
        records = rows(path)
        assert [row['phase'] for row in records[-4:]] == ['cdp_error', 'cdp_exit', 'callback_error', 'callback_exit']
        assert records[-4]['rpc_method'] == rpc and records[-4]['error_type'] == 'RuntimeError'
        assert len([call for call in session.calls if call[0] == rpc]) == 1
        assert SECRET not in path.read_text()
        if rpc == 'Fetch.failRequest':
            assert all(row['origin'] is None and row['path'] == '<redacted>' for row in records)
    finally:
        value.close()


def test_post_body_rpc_and_unknown_path_redaction(tmp_path):
    path = tmp_path/'receipts.ndjson'
    value = bridge(path, response)
    session = Session(path)
    request = event(url='https://shop.test/private/' + SECRET)
    request['request'].pop('postData')
    request['request']['hasPostData'] = True
    try:
        value._paused(session, request)
        records = rows(path)
        assert records[1]['phase'] == 'cdp_enter' and records[1]['rpc_method'] == 'Network.getRequestPostData'
        assert all(row['path'] == '<redacted>' for row in records)
        assert SECRET not in path.read_text()
    finally:
        value.close()


def test_recording_io_failure_disables_only_sink_not_routing(tmp_path):
    value = bridge(tmp_path, response)  # opening the directory for append fails
    session = Session()
    try:
        value._paused(session, event())
        assert value.diagnostics_error == 'IsADirectoryError'
        assert [method for method, _ in session.calls] == ['Fetch.fulfillRequest']
        assert session.calls[0][1]['responseCode'] == 200
    finally:
        value.close()


def test_direct_route_still_records_http_without_requiring_cdp_callback(tmp_path):
    path = tmp_path/'receipts.ndjson'
    value = bridge(path, response)
    fulfilled = []
    route = SimpleNamespace(fulfill=lambda **fields: fulfilled.append(fields))
    request = SimpleNamespace(url='https://shop.test/api/order?' + SECRET, method='POST',
                              all_headers=lambda: {}, post_data_buffer=SECRET.encode())
    try:
        value.route(route, request)
        records = rows(path)
        assert [row['phase'] for row in records] == ['http_enter', 'http_exit']
        assert all(row['request_id'] is None and row['network_id'] is None for row in records)
        assert fulfilled[0]['status'] == 200 and SECRET not in path.read_text()
    finally:
        value.close()
