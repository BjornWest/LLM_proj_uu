import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from intent_browser.team_worker import TeamBackend, Broker, Publisher
from intent_browser.backend import BackendResponseError


class Recorder:
    def __init__(self, directory, reject=False):
        self.directory=directory;self.calls=[];self.reject=reject
    def checkpoint(self):self.calls.append('checkpoint')
    def rpc(self, operation, **data):
        self.calls.append((operation,data))
        if self.reject:raise RuntimeError('Budget rejected')
        return {'amount_usd':0.1}


def backend(tmp_path, handler, reject=False):
    publisher=Recorder(tmp_path,reject)
    model=TeamBackend(publisher,{'DAYLIGHT_OPENROUTER_API_KEY':'offline-test-only'})
    model.client.close()
    model.client=httpx.Client(transport=httpx.MockTransport(handler),event_hooks={'response':[model.record_transport]})
    model.begin_episode('test-episode')
    return model,publisher


def test_reserve_before_single_dispatch_exact_request_and_transport(tmp_path):
    sent=[]
    def handler(request):
        assert publisher.calls[-1][0]=='reserve'
        sent.append(request)
        return httpx.Response(200,json={'choices':[{'message':{'content':"click('4')"}}],
            'model':'qwen/qwen3.8-27b','provider':'chutes','usage':{'cost':0.001}})
    model,publisher=backend(tmp_path,handler)
    messages=[{'role':'user','content':'Select Ångström'}]
    result=model.complete(messages)
    assert len(sent)==1
    recorded=next(data for call in publisher.calls if isinstance(call,tuple) for operation,data in [call] if operation=='reserve')
    assert recorded['request_sha256']==hashlib.sha256(sent[0].content).hexdigest()
    assert recorded['input_bytes']==len(sent[0].content)
    assert result.request==json.loads(sent[0].content)
    assert result.request['messages']==messages
    assert result.request['session_id']=='test-episode'
    assert 'preset' not in result.request
    log=json.loads((tmp_path/'model-transport.jsonl').read_text())
    assert log['request_body']==sent[0].content.decode()
    assert log['http_status']==200
    assert 'Authorization' not in json.dumps(log)
    model.close()


def test_lease_loss_after_response_retains_response_but_does_not_deliver_action(tmp_path):
    model,publisher=backend(tmp_path,lambda request:httpx.Response(200,json={
        'choices':[{'message':{'content':"click('4')"}}],'usage':{'cost':0.001}}))
    count=0
    def checkpoint():
        nonlocal count
        count+=1
        if count==2:raise RuntimeError('Lease lost')
    publisher.checkpoint=checkpoint
    with pytest.raises(BackendResponseError,match='before action delivery') as error:
        model.complete([{'role':'user','content':'goal'}])
    assert error.value.response_payload['choices'][0]['message']['content']=="click('4')"
    assert error.value.request_payload['session_id']=='test-episode'
    assert len((tmp_path/'model-transport.jsonl').read_text().splitlines())==1
    model.close()


def test_rejected_budget_never_dispatches_or_retains_stale_request(tmp_path):
    def handler(request):pytest.fail('Model must not be called')
    model,publisher=backend(tmp_path,handler,reject=True)
    model.last_request={'old':'request'}
    with pytest.raises(RuntimeError,match='Budget rejected'):model.complete([{'role':'user','content':'goal'}])
    assert model.last_request is None
    assert not (tmp_path/'model-transport.jsonl').exists()
    model.close()


@pytest.mark.parametrize('failure',['timeout','429','unknown_cost'])
def test_failed_calls_keep_reservation_and_exact_current_request_without_retry(tmp_path,failure):
    sent=[]
    def handler(request):
        sent.append(request)
        if failure=='timeout':raise httpx.ReadTimeout('offline timeout',request=request)
        if failure=='429':return httpx.Response(429,json={'error':{'message':'offline rate limit'}},headers={'retry-after':'60'})
        return httpx.Response(200,json={'choices':[{'message':{'content':"click('4')"}}],'usage':{}})
    model,publisher=backend(tmp_path,handler)
    with pytest.raises((httpx.ReadTimeout,BackendResponseError)):model.complete([{'role':'user','content':'current'}])
    assert len(sent)==1
    assert model.last_request['messages'][-1]['content']=='current'
    assert len((tmp_path/'team-reservations.jsonl').read_text().splitlines())==1
    assert model.index==1
    if failure!='timeout':
        log=json.loads((tmp_path/'model-transport.jsonl').read_text())
        assert log['http_status']==(429 if failure=='429' else 200)
        if failure=='429':
            assert json.loads(log['response_body'])=={'error':{'message':'offline rate limit'}}
            assert log['retry_after']=='60'
        else:
            assert json.loads(log['response_body'])['usage']=={}
    model.close()


def test_pacing_precedes_checkpoint_and_source_capture(monkeypatch,tmp_path):
    model,publisher=backend(tmp_path,lambda request:None)
    events=[]
    model.last_finished=100
    monkeypatch.setattr('intent_browser.team_worker.time.monotonic',lambda:104)
    monkeypatch.setattr('intent_browser.team_worker.time.sleep',lambda seconds:events.append(('sleep',seconds)))
    publisher.checkpoint=lambda:events.append('checkpoint')
    result=model.before_observation()
    assert events==[('sleep',6),'checkpoint']
    assert result['pace_seconds']==6
    model.close()


def test_transport_requires_https_except_explicit_loopback():
    for url in ['http://public.example','https://user:password@example.com','https://example.com/path','https://example.com?token=x']:
        with pytest.raises(ValueError):Broker(url,'x'*64)
    broker=Broker('http://127.0.0.1:8883','x'*64);broker.client.close()
