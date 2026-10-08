"""Prepared synthetic branch-selection controls; no native grade or formatter."""
from copy import deepcopy
import pytest

from environments.website_world.compound_answer_delivery_v1 import (
    SCHEMA, SOURCE, UnsupportedDeliveredAnswer, select_answer_path,
)


def records(stop='agent_finished', messages=None):
    messages=[] if messages is None else messages
    return ({'schema_version':SCHEMA,'source':SOURCE,'text':messages[-1] if messages else None,
        'assistant_messages':messages,'stop_reason':stop,'initial_chat_messages_excluded':2,
        'technical_error':None,'correctness':None},
        {'stop_reason':stop,'trace_complete':True,'error':None,'execution_error':None,
         'cleanup_errors':[],'terminated':False,'truncated':stop!='agent_finished'})


@pytest.mark.parametrize('stop', ['agent_finished','max_steps','max_input_tokens'])
@pytest.mark.parametrize('messages', [[],[' ','\n\t']])
def test_clean_missing_answer_is_selected(stop, messages):
    natural,terminal=records(stop,messages);before=deepcopy((natural,terminal))
    assert select_answer_path(natural,terminal)=='missing_answer'
    assert (natural,terminal)==before


def test_complete_final_answer_retains_extraction():
    assert select_answer_path(*records(messages=['A completed answer']))=='extract_completed_answer'


@pytest.mark.parametrize('stop', ['max_steps','max_input_tokens'])
@pytest.mark.parametrize('messages', [['Answer'],['Earlier answer',' ']])
def test_nonempty_at_cap_is_explicitly_unsupported(stop, messages):
    with pytest.raises(UnsupportedDeliveredAnswer): select_answer_path(*records(stop,messages))


def test_prior_nonempty_reply_with_blank_finish_is_not_missing():
    with pytest.raises(UnsupportedDeliveredAnswer): select_answer_path(*records(messages=['Earlier answer',' ']))


@pytest.mark.parametrize('key,value', [('trace_complete',False),('recording_error','failed'),
    ('error','provider failure'),('execution_error','action failed'),('cleanup_errors',['close failed']),
    ('terminated',True),('truncated',False),('stop_reason','environment_truncated')])
def test_terminal_failure_or_contradiction_is_not_a_task_verdict(key,value):
    natural,terminal=records('max_steps');terminal[key]=value
    with pytest.raises(ValueError):select_answer_path(natural,terminal)


@pytest.mark.parametrize('key,value', [('text','invented'),('assistant_messages',None),
    ('assistant_messages',[{}]),('initial_chat_messages_excluded',True),('technical_error','failure'),
    ('source','proposed policy output'),('schema_version','unknown'),('correctness',True),
    ('stop_reason','agent_finished')])
def test_malformed_or_contradictory_answer_is_not_absence(key,value):
    natural,terminal=records('max_steps');natural[key]=value
    with pytest.raises(ValueError):select_answer_path(natural,terminal)


def test_missing_answer_artifact_fields_are_not_empty_output():
    natural,terminal=records();natural.pop('assistant_messages')
    with pytest.raises(ValueError):select_answer_path(natural,terminal)


def test_prior_reply_with_null_text_is_corrupt_not_missing():
    natural,terminal=records('max_steps',['An actual reply']);natural['text']=None
    with pytest.raises(ValueError,match='contradicts'):select_answer_path(natural,terminal)
