import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from intent_browser.team_worker import TeamBackend, Broker, Publisher
from intent_browser.backend import BackendResponseError


@pytest.mark.parametrize('result_kind', ['graded', 'technical_error', 'missing'])
def test_publisher_uses_authoritative_artifact_and_archives_both_phases(tmp_path, result_kind):
    import zipfile
    from intent_browser.task_finalization import finalize_task_run
    from intent_browser.evaluation import Evaluation
    directory = tmp_path / 'episode'; directory.mkdir()
    original = Evaluation('pre-close', '1', task_completed=None).to_dict()
    (directory / 'evaluation.json').write_text(json.dumps(original))
    (directory / 'episode.json').write_text(json.dumps({'evaluation': original}))
    (directory / 'events.jsonl').write_text(json.dumps({'event': 'environment_close_completed'}) + '\n')
    calls = []
    class Broker:
        def post(self, operation, value): calls.append((operation, value)); return {}
    publisher = Publisher(Broker(), {'id': 'job', 'lease': 'lease'}, tmp_path)
    publisher.directory = directory
    publisher.project = lambda: {'steps': [], 'runtime': {}, 'image': None}
    publisher.thread.start()
    result = None
    if result_kind != 'missing':
        def grade(*args):
            assert not any(op == 'update' and row.get('snapshot', {}).get('status') for op, row in calls)
            if result_kind == 'technical_error': raise RuntimeError('Offline verifier failure')
            return Evaluation('native-post-close', '1', task_completed=True, authorization_satisfied=None)
        result = finalize_task_run(SimpleNamespace(grading_phase='after_browser_close', finalize_after_close=grade), directory, {})
    publisher.finish(authoritative_result=result, require_authoritative=True)
    final = calls[-1][1]['snapshot']
    if result_kind == 'missing':
        assert final['evaluation'] is None and final['status'] == 'error'
    else:
        assert final['evaluation'] == result['evaluation']
        assert final['evaluation']['safe_success'] is None
        assert final['status'] == ('finished' if result_kind == 'graded' else 'error')
        assert final['evaluation_source'] == 'authoritative-evaluation.json'
    with zipfile.ZipFile(tmp_path / 'trace.zip') as archive:
        expected = {str(Path(directory.name) / p.relative_to(directory)) for p in directory.rglob('*') if p.is_file()}
        assert len(archive.namelist()) == len(set(archive.namelist()))
        assert set(archive.namelist()) == expected
        for p in directory.rglob('*'):
            if p.is_file(): assert archive.read(str(Path(directory.name) / p.relative_to(directory))) == p.read_bytes()
    assert json.loads((directory / 'evaluation.json').read_text()) == original


class Recorder:
    def __init__(self, directory, reject=False):
        self.directory=directory;self.calls=[];self.reject=reject
    def checkpoint(self):self.calls.append('checkpoint')
    def rpc(self, operation, **data):
        self.calls.append((operation,data))
        if self.reject:raise RuntimeError('Budget rejected')
        if operation == 'settle': return {'status': 'settled'}
        return {'amount_usd':0.1,'max_tokens':data['max_tokens']}


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


def test_new_worker_requires_acknowledged_exact_output_ceiling(tmp_path):
    model,publisher=backend(tmp_path,lambda request:pytest.fail('No model call without exact reservation'))
    assert model.max_tokens==4096
    assert model.request_options['reasoning']=={'enabled':True}
    publisher.rpc=lambda *args,**kwargs:{'amount_usd':.1}  # old broker
    with pytest.raises(RuntimeError,match='acknowledge'):
        model.complete([{'role':'user','content':'goal'}])
    assert model.last_request is None
    assert len((tmp_path/'team-reservations.jsonl').read_text().splitlines())==1
    model.close()


def test_custom_ceiling_sent_and_reserved_exactly(tmp_path):
    publisher=Recorder(tmp_path)
    model=TeamBackend(publisher,{'DAYLIGHT_OPENROUTER_API_KEY':'offline','OPENROUTER_MAX_TOKENS':'2048'})
    model.client.close()
    model.client=httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(200,json={
        'choices':[{'message':{'content':"send_msg_to_user('Done')",'reasoning':'retained'}}],'usage':{'cost':.001}})))
    model.begin_episode('custom-limit')
    result=model.complete([{'role':'user','content':'goal'}])
    assert result.request['max_tokens']==2048
    assert result.text=="send_msg_to_user('Done')"
    assert result.raw['choices'][0]['message']['reasoning']=='retained'
    reservation=next(data for event in publisher.calls if isinstance(event,tuple) for op,data in [event] if op=='reserve')
    assert reservation['max_tokens']==2048
    model.close()


def test_native_tools_reserve_exact_schemas_and_multistep_messages(tmp_path):
    sent=[]
    def handler(request):
        sent.append(request)
        return httpx.Response(200,json={'choices':[{'message':{'content':None,'tool_calls':[{'id':'call2','type':'function','function':{'name':'browser','arguments':'{"action":"done"}'}}]}}],'usage':{'cost':0.001}})
    model,publisher=backend(tmp_path,handler)
    options={'tools':[{'type':'function','function':{'name':'browser','parameters':{'type':'object','properties':{'action':{'type':'string'}}}}}], 'tool_choice':'required','parallel_tool_calls':False}
    model.configure_tools(options)
    messages=[{'role':'user','content':'Find Ångström'}, {'role':'assistant','content':None,'reasoning':'Retained provider reasoning','tool_calls':[{'id':'call1','type':'function','function':{'name':'browser','arguments':'{"action":"inspect"}'}}]}, {'role':'tool','tool_call_id':'call1','content':'Observed page'}]
    result=model.complete(messages);reservation=next(c[1] for c in publisher.calls if isinstance(c,tuple) and c[0]=='reserve')
    actual=sent[0].content
    assert reservation['input_bytes']==len(actual)
    assert reservation['request_sha256']==hashlib.sha256(actual).hexdigest()
    assert json.loads(actual)['messages']==messages
    assert all(json.loads(actual)[k]==v for k,v in options.items())
    assert result.raw['choices'][0]['message']['tool_calls'][0]['id']=='call2'
    model.close()


def test_publisher_counts_child_cost_without_cross_session_provider_warning(tmp_path):
    folder=tmp_path/'parent';folder.mkdir()
    (folder/'metadata.json').write_text(json.dumps({'runtime':{},'model':'scripted'}))
    root={'step':0,'model_request':{'session_id':'parent'},'model_response':{'provider':'A','usage':{'cost':.001}}}
    (folder/'steps.jsonl').write_text(json.dumps(root)+'\n')
    child=folder/'children/child';child.mkdir(parents=True)
    row={'step':0,'model_request':{'session_id':'child'},'model_response':{'provider':'B','usage':{'cost':.002}}}
    (child/'steps.jsonl').write_text(json.dumps(row)+'\n')
    publisher=Publisher(SimpleNamespace(post=lambda *_:{}),{'id':'job','lease':'lease'},tmp_path)
    publisher.directory=folder
    result=publisher.project()
    assert result['cost']['reported_usd']==pytest.approx(.003)
    assert result['cost']['model_attempts']==2
    assert result['cost']['scope']=='parent and helpers'
    assert not result['cost']['alerts']
    assert len(result['steps'])==1


def test_settlement_precedes_action_and_retains_parse_failure_cost(tmp_path):
    model, publisher = backend(tmp_path, lambda request: httpx.Response(200, json={
        'id': 'gen-cost', 'usage': {'cost': .001}, 'choices': []}))
    with pytest.raises(BackendResponseError, match='response shape'):
        model.complete([{'role': 'user', 'content': 'goal'}])
    settlements = [x[1] for x in publisher.calls if isinstance(x, tuple) and x[0] == 'settle']
    assert len(settlements) == 1
    assert json.loads(settlements[0]['response_text'])['usage']['cost'] == .001
    assert (tmp_path / 'team-settlements.jsonl').exists()
    model.close()


def test_failed_cost_write_retains_raw_response_and_stops_action(tmp_path):
    model, publisher = backend(tmp_path, lambda request: httpx.Response(200, json={
        'id': 'gen-cost', 'usage': {'cost': .001}, 'choices': [{'message': {'content': "click('4')"}}]}))
    original = publisher.rpc
    def rpc(operation, **data):
        if operation == 'settle': raise RuntimeError('Offline storage failure')
        return original(operation, **data)
    publisher.rpc = rpc
    with pytest.raises(BackendResponseError, match='accounting failed') as error:
        model.complete([{'role': 'user', 'content': 'goal'}])
    assert error.value.response_payload['usage']['cost'] == .001
    assert (tmp_path / 'model-transport.jsonl').exists()
    model.close()


def test_live_projection_preserves_native_calls_and_execution_boundaries():
    from intent_browser.team_worker import project_step_calls
    rows = [
        {'action': "fill(bid='13', value='Aurora')", 'browser_stepped': True, 'policy_feedback': {'execution': 'call_completed'}},
        {'action': "ax_search(query='Blue')", 'kind': 'ax_query', 'policy_feedback': {'tool': 'ax_search', 'items': []}},
        {'action': "click(bid='14')", 'not_executed': True, 'policy_feedback': {'execution': 'not_executed', 'reason': 'document_or_navigation_changed'}},
        {'action': "click(bid='99')", 'browser_stepped': True, 'action_error': 'Not found'},
    ]
    projected = project_step_calls({'action': None, 'batch_calls': rows})
    assert [c['status'] for c in projected] == ['recorded', 'recorded', 'skipped', 'failed']
    assert [c['action'] for c in projected] == [r['action'] for r in rows]
    assert not projected[1]['browser_stepped']
    assert projected[2]['stop_reason'] == 'document_or_navigation_changed'
    assert project_step_calls({'action': "click('1')"}) is None
    clipped = project_step_calls({'batch_calls': [{'action': 'a'*10000}]})[0]
    assert clipped['action_truncated'] and len(clipped['action']) == 200
    assert clipped['status'] == 'unconfirmed'
