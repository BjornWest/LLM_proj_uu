"""Default native correction: exact IDs/history, no rejected effects, real grade projection."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import httpx
import numpy as np
import pytest
from jsonschema import ValidationError

from intent_browser.ax_explorer import AXConfig
from intent_browser.automatic_grading import AutomaticGrading, file_hash
from intent_browser.backend import ChatCompletionsBackend, Completion
from intent_browser.evaluation import Evaluation
from intent_browser.harness import native_tools_profile, SemanticFeedback
from intent_browser.native_tools import NativeBrowserTools, NativeConversation
from intent_browser.runner import run_episode


def reply(calls, *, raw_arguments=False):
    return {'choices':[{'finish_reason':'tool_calls','message':{
        'role':'assistant','content':'Public plan','reasoning':'Retained plan',
        'tool_calls':[{'id':f'call-{i}','type':'function','function':{
            'name':name,'arguments':args if raw_arguments else json.dumps(args)}}
            for i,(name,args) in enumerate(calls)]}}]}


def parsed(raw, tools=None, **kw):
    return (tools or NativeBrowserTools(ax_tools=True,incremental_ax=True,batch_size=8)).parse_for_dispatch(
        Completion('',raw),batching=True,**kw)


def test_limit_description_and_saved_shape_have_no_clamping():
    tools=NativeBrowserTools(ax_tools=True,incremental_ax=True,batch_size=8)
    raw=reply([('ax_read',{'depth':3,'limit':52,'node_ref':'d2n60','offset':110,'view':'subtree'})])
    original=deepcopy(raw)
    with pytest.raises(ValidationError):tools.parse_batch(Completion('',raw))
    decisions,assistant,feedback,channel=parsed(raw,tools)
    assert decisions is None and channel=='native'
    assert assistant['tool_calls']==raw['choices'][0]['message']['tool_calls']
    assert assistant['reasoning']=='Retained plan'
    assert feedback[0]['argument_error']=={'parameter':'/limit','received_type':'integer','requirement':'maximum is 50.'}
    assert raw==original and json.loads(assistant['tool_calls'][0]['function']['arguments'])['limit']==52
    schema=next(d['function'] for d in tools.definitions() if d['function']['name']=='ax_read')['parameters']
    assert schema['properties']['limit']['maximum']==50
    assert 'AX nodes' in schema['properties']['limit']['description']
    assert 'may return fewer' in schema['properties']['limit']['description']


@pytest.mark.parametrize('args,parameter',[
    ({'bid':7,'value':'x'},'/bid'),({'bid':'1'},'(arguments)'),
    ({'bid':'1','value':'x','extra':'private'},'(arguments)'),
])
def test_schema_errors_are_bounded_and_whole_batch_is_rejected(args,parameter):
    raw=reply([('click',{'bid':'safe'}),('fill',args)])
    decisions,assistant,feedback,channel=parsed(raw)
    assert decisions is None and channel=='native' and len(feedback)==2
    assert [f['execution'] for f in feedback]==['not_executed','not_executed']
    assert feedback[0]['reason']=='batch_rejected_invalid_arguments'
    assert feedback[1]['argument_error']['parameter']==parameter
    assert 'private' not in json.dumps(feedback)
    assert assistant['tool_calls']==raw['choices'][0]['message']['tool_calls']


@pytest.mark.parametrize('arguments',['{"bid":','[]','{"bid":"a","bid":"b"}',
                                       '{"bid":"a","value":NaN}', '{"bid":"a","value":1e999}'])
def test_unreplayable_arguments_use_inert_channel(arguments):
    raw=reply([('fill',arguments)],raw_arguments=True)
    original=deepcopy(raw)
    decisions,assistant,feedback,channel=parsed(raw)
    assert decisions is None and channel=='controller' and feedback[0]['execution']=='not_executed'
    assert raw==original
    conversation=NativeConversation()
    first=conversation.request('System','Goal','First')
    notice=json.dumps({'execution':'not_executed','results':feedback},sort_keys=True)
    conversation.recover(raw,notice,notice_source='diagnostic')
    second=conversation.request('System','Goal','Fresh')
    assert second[:len(first)]==first
    assert not any('tool_calls' in message for message in second)
    assert not conversation.has_call_id('call-0')
    binding=next(b for b in conversation.bindings() if b['content_id']=='diagnostic')
    assert second[binding['message_index']]['content'][binding['start']:binding['end']]==notice


@pytest.mark.parametrize('variant',['duplicate','reused','unknown','missing_id','refusal',
                                    'bad_reasoning','terminal_first','nonstring_arguments'])
def test_malformed_or_unsafe_envelopes_never_become_corrections(variant):
    raw=reply([('fill',{'bid':'1'}),('click',{'bid':'2'})])
    message=raw['choices'][0]['message'];calls=message['tool_calls'];kw={}
    if variant=='duplicate':calls[1]['id']=calls[0]['id']
    elif variant=='reused':kw['has_call_id']=lambda i:i=='call-1'
    elif variant=='unknown':calls[1]['function']['name']='unknown'
    elif variant=='missing_id':calls[1]['id']=''
    elif variant=='refusal':message['refusal']='No'
    elif variant=='bad_reasoning':message['reasoning']={}
    elif variant=='terminal_first':calls[0]['function']={'name':'send_msg_to_user','arguments':'{"text":"Done"}'}
    else:calls[1]['function']['arguments']={}
    with pytest.raises(ValueError):parsed(raw,**kw)


def test_schema_error_does_not_hide_navigation_boundary_violation():
    raw=reply([('fill',{'bid':'1'}),('goto',{'url':'https://outside.invalid/'})])
    tools=NativeBrowserTools(names=('fill','goto'),navigation_origins=('https://inside.invalid',),batch_size=8)
    with pytest.raises(ValueError):parsed(raw,tools)


def test_likely_truncated_json_is_not_automatically_continued():
    raw=reply([('fill','{"bid":')],raw_arguments=True)
    raw['usage']={'completion_tokens':16}
    with pytest.raises(json.JSONDecodeError):
        NativeBrowserTools().parse_for_dispatch(Completion('',raw,{'max_tokens':16}))


def bind_grade(env,trace,obs):
    from intent_browser.automatic_grading import canonical_viewer_check
    return {'task_id':'argument-correction-fixture',
        'goal_sha256':hashlib.sha256(obs['goal'].encode()).hexdigest(),
        'reference_files':{str(env.reference):file_hash(env.reference)},
        'source_files':{str(p):file_hash(p) for p in
            {Path(__file__).resolve(),Path(__import__('intent_browser.automatic_grading',fromlist=['']).__file__).resolve(),
             Path(__import__('agent_trace.adapters.browsergym',fromlist=['']).__file__).resolve()}}}


def grade(env,trace,outcome):
    if outcome['error']:raise ValueError('Policy failure must not get a success grade')
    assert env.closed
    return {'task_id':'argument-correction-fixture','done':env.done}


def project_grade(raw,binding):
    return Evaluation('synthetic-native-argument-correction','v1',trust='native_state',
        task_completed=raw['done'],authorization_satisfied=True,
        limitations=['Synthetic state, not a benchmark outcome'])


def exercise(tmp_path, sequence, *, batch_size=8, max_steps=None, repeat_ids=False):
    requests=[];responses=[];actions=[]
    class Env:
        done=False;closed=False
        reference=tmp_path/'reference.json'
        @property
        def unwrapped(self):return self
        def obs(self):return {'goal':'Finish after correction','url':'http://fixture/',
            'last_action_error':'','axtree_object':{'nodes':[{'nodeId':'1','role':{'value':'button'},'name':{'value':'Fixture'}}]},
            'screenshot':np.zeros((2,2,3),dtype=np.uint8)}
        def reset(self,seed):return self.obs(),{}
        def step(self,action):
            actions.append(action);self.done=action.startswith('send_msg_to_user(')
            return self.obs(),0,False,False,{}
        def close(self):self.closed=True
    env=Env();env.reference.write_text('{"goal":"Finish after correction"}')
    def transport(request):
        requests.append(json.loads(request.content));raw=deepcopy(sequence[len(requests)-1])
        if not repeat_ids:
            for call in raw['choices'][0]['message'].get('tool_calls',[]):
                call['id']=str(len(requests))+'-'+call['id']
        responses.append(deepcopy(raw));return httpx.Response(200,json=raw)
    backend=ChatCompletionsBackend('https://fixture.invalid/v1','mock');backend.client.close()
    backend.client=httpx.Client(transport=httpx.MockTransport(transport))
    from tokenizers import Tokenizer, models
    tokenizer_path=tmp_path/'ax-tokenizer.json'
    Tokenizer(models.WordLevel({'[UNK]':0,'Fixture':1},unk_token='[UNK]')).save(str(tokenizer_path))
    profile=native_tools_profile(ax_config=AXConfig(str(tokenizer_path),incremental=True))
    profile=replace(profile,tools=replace(profile.tools,batch_size=batch_size),feedback_factory=SemanticFeedback)
    try:
        with patch('intent_browser.runner.observation_text',return_value='Fixture page'),\
                patch('intent_browser.harness.flatten_axtree_to_str',return_value='Fixture page'),\
                patch('intent_browser.runner.refresh_observation',side_effect=lambda e,**kw:e.obs()),\
                patch('intent_browser.batching.document_signature',return_value=[]):
            path,summary=run_episode(lambda _:env,backend,{'model':'offline-fixture','metadata_source':'scripted-fixture','tags':['scripted']},str(tmp_path/'runs'),
                max_steps=max_steps or len(sequence),max_input_tokens=None,harness_profile=profile,
                automatic_grading=AutomaticGrading('synthetic-argument-correction:v1',bind_grade,grade,project_grade),
                retry_policy=None)
    finally:backend.close()
    rows=[json.loads(line) for line in (path/'steps.jsonl').read_text().splitlines()]
    return path,summary,rows,requests,responses,actions


@pytest.mark.parametrize('batch_size',[1,8])
def test_real_runner_rejects_then_corrects_and_publishes_automatic_grade(tmp_path,batch_size):
    invalid=reply([('ax_read',{'node_ref':'d2n60','limit':52})])
    if batch_size>1:invalid['choices'][0]['message']['tool_calls'].insert(0,
        {'id':'valid-prefix','type':'function','function':{'name':'click','arguments':'{"bid":"1"}'}})
    path,summary,rows,requests,responses,actions=exercise(tmp_path,[invalid,reply([('send_msg_to_user',{'text':'Done'})])],batch_size=batch_size)
    assert summary['stop_reason']=='agent_finished' and summary['error'] is None
    assert summary['grading_error'] is None and summary['infrastructure_completed'] is True
    assert summary['evaluation']['task_completed'] is True
    assert json.loads((path/'automatic-grade-projection.json').read_text())['verified'] is True
    assert len(actions)==1 and actions[0].startswith('send_msg_to_user(')
    assert rows[0]['actions']==[] and rows[0]['browser_stepped'] is False
    assert all(m['not_executed'] and not m['action_dispatch_started'] for m in rows[0]['batch_calls'])
    assert rows[0]['model_response']==responses[0]
    tools=[m for m in requests[1]['messages'] if m['role']=='tool']
    assert [m['tool_call_id'] for m in tools]==[c['id'] for c in responses[0]['choices'][0]['message']['tool_calls']]
    assert 'maximum is 50' in tools[-1]['content']
    assert requests[1]['messages'][:len(requests[0]['messages'])]==requests[0]['messages']
    assert requests[1]['tools']==requests[0]['tools']
    assert all(item['confirmed'] for item in rows[1]['policy_delivery']['items'])
    assert 'decision_retry_count' not in summary
    assert json.loads((path/'metadata.json').read_text())['invalid_argument_feedback']['version']=='native-argument-rejection-v1'


def test_real_runner_malformed_json_feedback_allows_corrected_same_id(tmp_path):
    raw=reply([('fill','{"bid":')],raw_arguments=True)
    path,summary,rows,requests,_,actions=exercise(tmp_path,[raw,reply([('send_msg_to_user',{'text':'Done'})])],repeat_ids=True)
    assert summary['error'] is None and summary['infrastructure_completed'] is True and len(actions)==1
    assert rows[0]['argument_feedback_channel']=='controller'
    assert not any('tool_calls' in m for m in requests[1]['messages'])
    assert 'Arguments are not valid JSON' in requests[1]['messages'][-1]['content']
    assert any(i['kind']=='batch_result' and i['confirmed'] for i in rows[1]['policy_delivery']['items'])


def test_rejected_ids_cannot_be_reused_by_a_valid_terminal_response(tmp_path):
    invalid=reply([('ax_read',{'node_ref':'d2n60','limit':52})])
    _,summary,rows,requests,_,actions=exercise(tmp_path,[invalid,reply([('send_msg_to_user',{'text':'Done'})])],repeat_ids=True)
    assert 'Repeated native tool call ID' in summary['error'] and actions==[]
    assert len(requests)==2 and rows[0]['batch_stop_reason']=='invalid_tool_arguments'


def test_repeated_argument_errors_stop_at_normal_turn_budget_and_still_grade(tmp_path):
    invalid=reply([('ax_read',{'node_ref':'d2n60','limit':52})])
    _,summary,rows,requests,_,actions=exercise(tmp_path,[invalid,invalid],max_steps=2)
    assert summary['stop_reason']=='max_steps' and summary['error'] is None and actions==[]
    assert len(requests)==2 and len(rows)==2
    assert summary['infrastructure_completed'] is True and summary['evaluation']['task_completed'] is False


def test_corrected_ax_limit_executes_actual_context_query_before_finish(tmp_path):
    invalid=reply([('ax_read',{'node_ref':'d1n0','view':'subtree','limit':52})])
    valid=reply([('ax_read',{'node_ref':'d1n0','view':'subtree','limit':50})])
    _,summary,rows,requests,_,actions=exercise(tmp_path,[invalid,valid,reply([('send_msg_to_user',{'text':'Done'})])])
    assert summary['error'] is None and summary['infrastructure_completed'] is True
    assert len(requests)==3 and len(actions)==1
    member=rows[1]['batch_calls'][0]
    assert member['kind']=='ax_query' and not member.get('not_executed')
    assert 'limit=50' in member['action']
    assert member['policy_feedback']['tool']=='ax_read'


@pytest.mark.parametrize('arguments',['{"node_ref":"d1n0","limit":52}','{"node_ref":'])
def test_mimo_can_count_rejected_history_without_argument_repair(arguments):
    from types import SimpleNamespace
    from intent_browser.model_input_budget import model_matched_input_counter,REGISTRY
    root=REGISTRY.parent.parent/'.local/model-tokenizers'
    entry=json.loads(REGISTRY.read_text())['models']['xiaomi/mimo-v2.6-pro']
    if not (root/entry['bundle']/'tokenizer.json').exists():
        pytest.skip('Official MiMo assets must be installed explicitly; no downloads')
    tools=NativeBrowserTools(ax_tools=True,incremental_ax=True,batch_size=8)
    raw=reply([('ax_read',arguments)],raw_arguments=True)
    _,assistant,results,channel=parsed(raw,tools)
    conversation=NativeConversation();conversation.request('System','Goal','Initial')
    if channel=='native':conversation.record_batch(assistant,[(value,None) for value in results])
    else:conversation.recover(raw,json.dumps(results))
    history=conversation.request('System','Goal','Fresh')
    backend=SimpleNamespace(model='xiaomi/mimo-v2.6-pro',base_url='https://openrouter.ai/api/v1',request_options={})
    count=model_matched_input_counter(backend,assets_root=root)(history,tools.definitions())
    assert count['input_tokens']>0
    assert raw['choices'][0]['message']['tool_calls'][0]['function']['arguments']==arguments


@pytest.mark.parametrize('tool,args,parameter',[
    ('ax_read',{'node_ref':'d1n0','limit':50.0},'/limit'),
    ('ax_read',{'node_ref':'d1n0','offset':0.0},'/offset'),
    ('ax_search',{'query':'Fixture','limit':5.0},'/limit'),
])
def test_decimal_integer_arguments_reject_without_cast(tool,args,parameter):
    raw=reply([(tool,args)]);saved=deepcopy(raw)
    decisions,assistant,feedback,channel=parsed(raw)
    assert decisions is None and channel=='native' and raw==saved
    assert feedback[0]['argument_error']['parameter']==parameter
    assert 'without a decimal point' in feedback[0]['argument_error']['requirement']


@pytest.mark.parametrize('batch_size',[1,8])
def test_actual_runner_decimal_limit_can_be_corrected(tmp_path,batch_size):
    invalid=reply([('ax_read',{'node_ref':'d1n0','limit':50.0})])
    valid=reply([('ax_read',{'node_ref':'d1n0','limit':50})])
    _,summary,rows,_,_,actions=exercise(tmp_path,[invalid,valid,reply([('send_msg_to_user',{'text':'Done'})])],batch_size=batch_size)
    assert summary['error'] is None and summary['evaluation']['task_completed'] is True
    assert rows[0]['batch_calls'][0]['policy_feedback']['argument_error']['parameter']=='/limit'
    assert len(actions)==1


@pytest.mark.parametrize('arguments',[
    json.dumps({'bid':'1','value':'x'*60000}),
    json.dumps({'bid':'1','value':'x'*300000}),
    '['*1100+'0'+']'*1100,
    '{"bid":"1","value":'+ '['*40+'0'+']'*40 + '}',
])
def test_oversized_or_deep_proposals_get_bounded_inert_history(arguments):
    raw=reply([('fill',arguments)],raw_arguments=True)
    _,assistant,results,channel=parsed(raw)
    assert channel=='controller'
    conversation=NativeConversation();conversation.request('System','Goal','First')
    conversation.recover(raw,json.dumps(results))
    history=conversation.request('System','Goal','Next')
    assert not any('tool_calls' in m for m in history)
    assert len(json.dumps(history)) < 7000
    assert raw['choices'][0]['message']['tool_calls'][0]['function']['arguments']==arguments


def test_encoding_bound_is_actionable_and_actual_runner_continues(tmp_path):
    raw=reply([('fill',{'bid':'1','value':'x'*60000})])
    _,summary,rows,requests,_,actions=exercise(tmp_path,[raw,reply([('send_msg_to_user',{'text':'Done'})])],repeat_ids=True)
    assert summary['error'] is None and summary['evaluation']['task_completed'] is True
    assert len(actions)==1 and rows[0]['argument_feedback_channel']=='controller'
    assert 'maximum 4096 characters' in requests[1]['messages'][-1]['content']
    assert len(json.dumps(requests[1]['messages'])) < 9000


@pytest.mark.parametrize('value',['x'*4074,'\u200b'*700],ids=['ascii','escaped'])
def test_expanded_python_literal_size_is_recoverable(value):
    raw=reply([('fill',{'bid':'1','value':value})])
    # Ensure this exercises the serialized-action bound, not JSON encoding size.
    raw['choices'][0]['message']['tool_calls'][0]['function']['arguments']=json.dumps({'bid':'1','value':value},ensure_ascii=False,separators=(',',':'))
    _,_,results,_=parsed(raw)
    assert 'Serialized browser action exceeds maximum 4096 characters' in results[0]['argument_error']['requirement']


def test_rejected_single_call_viewer_count_and_timing_do_not_alias_click(tmp_path):
    from agent_trace.adapters.browsergym import project
    _,summary,rows,_,_,actions=exercise(tmp_path,[reply([('click',{'bid':'1'})]),
        reply([('ax_read',{'node_ref':'d1n0','limit':52})]),
        reply([('send_msg_to_user',{'text':'Done'})])],batch_size=1)
    assert summary['error'] is None and len(actions)==2
    assert rows[1]['batch_calls'][0]['execution_index']==1
    path=next((tmp_path/'runs').iterdir());projection=project(path)
    assert json.loads(next(m['text'] for m in projection['messages'] if m['title']=='Recorded execution summary'))['recorded_tool_calls']['skipped']==1
    skipped=[e for e in projection['messages'] if e.get('kind')=='tool' and e.get('execution_status')=='skipped']
    assert len(skipped)==1 and skipped[0].get('at') is None


def test_same_call_invalid_schema_cannot_navigate_outside_origin():
    tools=NativeBrowserTools(names=('goto',),navigation_origins=('https://inside.invalid',),batch_size=8)
    raw=reply([('goto',{'url':'https://outside.invalid/','extra':1})])
    decisions,_,results,_=parsed(raw,tools)
    assert decisions is None and results[0]['execution']=='not_executed'
    with pytest.raises(ValueError):
        parsed(reply([('goto',{'url':'https://outside.invalid/'})]),tools)
