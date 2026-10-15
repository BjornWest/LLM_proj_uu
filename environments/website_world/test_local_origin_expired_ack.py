"""Expired browser acknowledgements must not suppress/replay backend outcomes."""
import json
from types import SimpleNamespace

import httpx
import pytest
from playwright.sync_api import Error, TimeoutError

from environments.website_world.local_origins import LocalOriginBridge, OriginMap


def make_bridge(tmp_path, *, diagnostics=True):
    identity = OriginMap([dict(site_id='shop', name='shop', kind='retailer',
                              origin='http://localhost:8311')], world_id='test')
    value = LocalOriginBridge(identity,
        diagnostics_path=tmp_path/'phases.jsonl' if diagnostics else None)
    value.client.close()
    forwarded = []
    def respond(request):
        forwarded.append((request.method, request.url.path, request.content))
        return httpx.Response(200, text='private response', request=request)
    value.client = httpx.Client(transport=httpx.MockTransport(respond), trust_env=False)
    return value, forwarded


class Session:
    def __init__(self, rpc, error):
        self.rpc, self.error, self.calls = rpc, error, []
    def send(self, method, parameters):
        self.calls.append((method, parameters))
        if method == self.rpc:
            raise self.error
        return {'postData': 'private request'}


def paused(method='GET', *, offworld=False):
    return dict(requestId='fetch-1', networkId='network-1', request=dict(
        url='https://'+('outside' if offworld else 'shop')+'.test/api/order?private=query',
        method=method, headers={'X-Secret': 'private header'}, postData='private request'))


@pytest.mark.parametrize('method', ['GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE'])
@pytest.mark.parametrize('rpc', ['Fetch.fulfillRequest', 'Fetch.failRequest'])
def test_expired_ack_retains_unknown_effect_and_never_replays(tmp_path, method, rpc):
    bridge, forwarded = make_bridge(tmp_path)
    session = Session(rpc, Error('ImplToApiMapping.wrapper_func: Protocol error ('+rpc+'): Invalid InterceptionId.'))
    try:
        bridge._paused(session, paused(method, offworld=rpc=='Fetch.failRequest'))
        assert len(session.calls) == 1
        assert len(forwarded) == (rpc=='Fetch.fulfillRequest')
        if forwarded:
            assert forwarded[0] == (method, '/api/order', b'private request')
        assert bridge.expired_interception_ack_count == 1
        outcome, = bridge.expired_interception_acknowledgements
        assert outcome == dict(rpc_method=rpc, request_id='fetch-1', network_id='network-1',
                               method=method, browser_acknowledged=False,
                               backend_effects='unknown', replayed=False)
        records = [json.loads(s)for s in bridge.diagnostics_path.read_text().splitlines()]
        expired, = [r for r in records if r['phase']=='cdp_ack_expired']
        assert expired['backend_effects']=='unknown' and expired['browser_acknowledged'] is False
        assert expired['replayed'] is False
        assert not any(r['phase']=='callback_error' for r in records)
        assert 'private' not in json.dumps(outcome)
        assert 'private' not in bridge.diagnostics_path.read_text()
    finally:
        bridge.close()


@pytest.mark.parametrize('rpc,error', [
    ('Fetch.fulfillRequest', Error('Protocol error (Fetch.fulfillRequest): Target closed.')),
    ('Fetch.fulfillRequest', Error('Protocol error (Fetch.failRequest): Invalid InterceptionId.')),
    ('Fetch.fulfillRequest', Error('Protocol error (Fetch.fulfillRequest): Invalid InterceptionId. extra')),
    ('Fetch.fulfillRequest', TimeoutError('Protocol error (Fetch.fulfillRequest): Invalid InterceptionId.')),
    ('Fetch.fulfillRequest', ConnectionError('Protocol error (Fetch.fulfillRequest): Invalid InterceptionId.')),
    ('Fetch.fulfillRequest', KeyboardInterrupt()),
    ('Network.getRequestPostData', Error('Protocol error (Network.getRequestPostData): Invalid InterceptionId.')),
    ('Fetch.continueRequest', Error('Protocol error (Fetch.continueRequest): Invalid InterceptionId.')),
])
def test_unrelated_failures_propagate_identically(tmp_path, rpc, error):
    bridge, forwarded = make_bridge(tmp_path)
    session = Session(rpc,error)
    request=SimpleNamespace(url='https://shop.test/api/order',method='POST')
    try:
        with pytest.raises(type(error)) as caught:
            bridge._send_cdp(session,rpc,{},request)
        assert caught.value is error
        assert len(session.calls)==1 and forwarded==[]
        assert bridge.expired_interception_ack_count==0
        assert bridge.expired_interception_acknowledgements==[]
    finally:
        bridge.close()


def test_disabled_diagnostics_still_retains_bounded_unknown_post_acknowledgements(tmp_path):
    bridge, forwarded=make_bridge(tmp_path,diagnostics=False)
    session=Session('Fetch.fulfillRequest',Error('Protocol error (Fetch.fulfillRequest): Invalid InterceptionId.'))
    try:
        for index in range(70):
            request=paused('POST');request['requestId']=str(index)
            bridge._paused(session,request)
        assert len(forwarded)==70 and len(session.calls)==70
        assert bridge.expired_interception_ack_count==70
        assert len(bridge.expired_interception_acknowledgements)==64
        assert bridge.expired_interception_acknowledgements[0]['request_id']=='6'
        assert all(r['backend_effects']=='unknown' and r['replayed'] is False
                   for r in bridge.expired_interception_acknowledgements)
        assert list(tmp_path.iterdir())==[]
    finally:
        bridge.close()


def test_diagnostic_sink_failure_does_not_restore_callback_error_cascade(tmp_path):
    bridge, forwarded=make_bridge(tmp_path)
    bridge.diagnostics_path=tmp_path  # opening a directory for append fails
    try:
        bridge._paused(Session('Fetch.fulfillRequest',Error(
            'Protocol error (Fetch.fulfillRequest): Invalid InterceptionId.')),paused('POST'))
        assert bridge.diagnostics_error=='IsADirectoryError'
        assert bridge.expired_interception_ack_count==1
        assert len(forwarded)==1
    finally:
        bridge.close()
