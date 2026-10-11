"""Completed no-call replies recover on normal turns, with real grade publication."""
from copy import deepcopy
import json
import pytest
from intent_browser.backend import Completion
from intent_browser.native_tools import NativeBrowserTools, MissingNativeToolCall
from tests.test_native_argument_feedback import exercise, reply


def no_call(calls='omitted',finish='stop'):
    message={'role':'assistant','content':'Choose brown EU38.','reasoning':'The selected option matches.'}
    if calls!='omitted':message['tool_calls']=calls
    return {'choices':[{'finish_reason':finish,'message':message}]}


@pytest.mark.parametrize('calls',['omitted',None,[]])
@pytest.mark.parametrize('finish',['stop','tool_calls'])
def test_completed_empty_call_envelopes_need_controller_feedback_not_strict_parser_repair(calls,finish):
    raw=no_call(calls,finish);saved=deepcopy(raw)
    tools=NativeBrowserTools(batch_size=8)
    with pytest.raises(MissingNativeToolCall):tools.parse_for_dispatch(Completion('',raw),batching=True)
    for parser in (tools.parse_completion,tools.parse_batch):
        with pytest.raises(ValueError) as failure:parser(Completion('',raw))
        assert not isinstance(failure.value,MissingNativeToolCall)
    assert raw==saved


@pytest.mark.parametrize('variant',['refused','truncated','native_truncated','bad_role','bad_content','bad_calls','bad_reasoning'])
def test_unsafe_incomplete_or_malformed_envelopes_do_not_become_no_call_feedback(variant):
    raw=no_call();choice=raw['choices'][0];message=choice['message']
    if variant=='refused':message['refusal']='Refused'
    elif variant=='truncated':choice['finish_reason']='length'
    elif variant=='native_truncated':choice['native_finish_reason']='length'
    elif variant=='bad_role':message['role']='user'
    elif variant=='bad_content':message['content']=[{'type':'text','text':'Hello'}]
    elif variant=='bad_calls':message['tool_calls']={}
    elif variant=='bad_reasoning':message['reasoning']={}
    with pytest.raises(ValueError) as failure:
        NativeBrowserTools(batch_size=8).parse_for_dispatch(Completion('',raw),batching=True)
    assert not isinstance(failure.value,MissingNativeToolCall)


@pytest.mark.parametrize('batch_size',[1,8])
@pytest.mark.parametrize('calls',['omitted',None,[]])
def test_actual_runner_no_call_then_valid_finish_retains_reply_and_normal_grade(tmp_path,batch_size,calls):
    raw=no_call(calls)
    path,summary,rows,requests,responses,actions=exercise(tmp_path,[raw,reply([('send_msg_to_user',{'text':'Done'})])],batch_size=batch_size)
    assert summary['error'] is None and summary['stop_reason']=='agent_finished'
    assert summary['grading_error'] is None and summary['infrastructure_completed'] is True
    assert json.loads((path/'automatic-grade-projection.json').read_text())['verified'] is True
    assert len(requests)==2 and len(actions)==1 and actions[0].startswith('send_msg_to_user(')
    first=rows[0]
    assert first['model_response']==responses[0]
    assert first['not_executed'] and first['browser_stepped'] is False
    assert first['actions']==[] and first['action_dispatch_started'] is False
    assert 'tool_call_id' not in first and 'assistant_tool_message' not in first
    assert first['native_feedback_reason']=='missing_native_tool_call'
    initial=requests[0]['messages'];next_messages=requests[1]['messages']
    assert next_messages[:len(initial)]==initial
    retained=next_messages[len(initial)]
    assert retained['role']=='assistant' and retained['content']==raw['choices'][0]['message']['content']
    assert retained['reasoning']==raw['choices'][0]['message']['reasoning']
    assert 'tool_calls' not in retained and not any(m['role']=='tool' for m in next_messages)
    assert 'No native tool call was returned' in next_messages[-1]['content']
    assert 'send_msg_to_user' in next_messages[-1]['content']
    assert requests[0]['tools']==requests[1]['tools']
    assert all(item['confirmed'] for item in rows[1]['policy_delivery']['items'])
    assert 'decision_retry_count' not in summary
    assert json.loads((path/'metadata.json').read_text())['native_reply_feedback']['version']=='native-no-call-feedback-v1'


def test_repeated_no_call_replies_stop_at_declared_turn_limit_without_fake_success(tmp_path):
    _,summary,rows,requests,_,actions=exercise(tmp_path,[no_call(),no_call()],max_steps=2)
    assert summary['error'] is None and summary['stop_reason']=='max_steps'
    assert summary['evaluation']['task_completed'] is False and summary['infrastructure_completed'] is True
    assert len(requests)==len(rows)==2 and actions==[]
    assert all(row['not_executed'] for row in rows)
