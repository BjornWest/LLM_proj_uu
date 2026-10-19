"""Window correctness and budget preflight, without browser/provider requests."""
from copy import deepcopy
import json
from pathlib import Path

from intent_browser.hindrance_context import PreflightInputCounter, WindowedConversation
from intent_browser.input_budget import QwenInputCounter
from scripts.hindrance_model_run import GradingFinalizationError, require_finalized
import pytest


def assistant(n):
    return {'role': 'assistant', 'content': 'Remember product P and address A.',
            'reasoning_details': [{'type': 'reasoning.text', 'text': 'Keep useful facts.'}],
            'tool_calls': [{'id': str(n), 'type': 'function',
                            'function': {'name': 'ax_read', 'arguments': '{}'}}]}


def test_window_preserves_actions_recent_bindings_goal_human_and_trace_copies():
    conversation = WindowedConversation(2)
    first = conversation.request('system', 'buy P', 'old page ' * 200, observation_source='obs0')
    original = deepcopy(first)
    for n in range(1, 4):
        conversation.record_batch(assistant(n), [({'nodes': ['huge AX result ' * 100]}, 'result'+str(n))])
        if n == 1:
            conversation.add_human_message('Please keep the address.', source_id='human')
        messages = conversation.request('system', 'buy P', 'page'+str(n), observation_source='obs'+str(n))
    assert first == original
    assert messages[1]['content'].startswith('USER GOAL: buy P')
    assert 'old page' not in messages[1]['content']
    assert 'Older browser evidence omitted' in messages[1]['content']
    assert [m for m in messages if m['role'] == 'assistant'] == [assistant(n) for n in range(1, 4)]
    assert [m['tool_call_id'] for m in messages if m['role'] == 'tool'] == ['1', '2', '3']
    assert any(m['content'] == 'Please keep the address.' for m in messages)
    bindings = conversation.bindings()
    assert 'human' in [b['content_id'] for b in bindings]
    assert 'obs0' not in [b['content_id'] for b in bindings]
    assert 'result1' not in [b['content_id'] for b in bindings]
    for b in bindings:
        content = messages[b['message_index']]['content']
        assert len(content[b['start']:b['end']]) == b['end'] - b['start']
    assert {'obs2', 'obs3', 'result2', 'result3'} <= {b['content_id'] for b in bindings}


def test_completed_grading_is_independent_of_policy_failure():
    require_finalized({'grading_error': None, 'grading': {'status': 'graded'},
                       'infrastructure_completed': False, 'error': 'HTTP 502'})
    with pytest.raises(GradingFinalizationError, match='capture failed'):
        require_finalized({'grading_error': 'capture failed', 'grading': {'status': 'failed'}})


def test_byte_preflight_avoids_tokenizing_and_falls_back_near_limit():
    class Visible:
        calls = 0
        def __call__(self, messages, tools):
            self.calls += 1
            return {'input_tokens': 123, 'method': 'test-exact'}
    visible = Visible()
    counter = PreflightInputCounter(visible, 150000)
    messages = [{'role': 'user', 'content': 'Read page'}]
    assert counter(messages, [])['method'] == 'hindrance-utf8-byte-preflight-bound-v1'
    assert visible.calls == 0
    counter.limit = 10
    assert counter(messages, [])['input_tokens'] == 123
    assert visible.calls == 1
    counter.limit = 150000
    opaque = {'role': 'assistant', 'content': '',
              'reasoning_details': [{'type': 'reasoning.encrypted', 'data': 'opaque'}]}
    counter.observe_completion({}, {'choices': [{'message': opaque}],
                                   'usage': {'completion_tokens': 10}})
    assert counter(messages + [opaque], [])['retained_hidden_tokens_estimate'] == 10
    with pytest.raises(ValueError, match='no matching provider usage'):
        counter(messages + [{**opaque, 'reasoning_details': [{'type': 'reasoning.encrypted', 'data': 'foreign'}]}], [])


def test_preflight_bound_exceeds_complete_qwen_template_measurement():
    path = Path(__file__).resolve().parents[1]/'.local/model-tokenizers/qwen3.8-27b-1d4bf0f2/tokenizer.json'
    if not path.exists():
        pytest.skip('Local tokenizer assets required')
    visible = QwenInputCounter(str(path))
    counter = PreflightInputCounter(visible, 150000)
    for text in ['ASCII content', 'Björkvägen 中文 🧑‍💻' * 40, json.dumps({'nodes': ['item'] * 100})]:
        messages = [{'role': 'system', 'content': 'Use browser tools'}, {'role': 'user', 'content': text},
                    assistant(1), {'role': 'tool', 'tool_call_id': '1', 'content': text}]
        tools = [{'type': 'function', 'function': {'name': 'ax_read', 'parameters': {'type': 'object'}}}]
        assert counter(messages, tools)['input_tokens'] >= visible(messages, tools)['input_tokens']


def test_historical_grade_recovery_keeps_error_and_does_not_rewrite_evidence(tmp_path):
    from intent_browser.automatic_grading import digest, file_hash
    from scripts.recover_hindrance_grades import recover
    trace = tmp_path/'runs'/'saved-episode'
    trace.mkdir(parents=True)
    binding = {'task_id': 'saved'}
    raw = {'binding_sha256': digest(binding), 'episode_id': trace.name, 'contract_id': 'saved',
           'raw_grade': {'status': 'inconclusive', 'order_grade': {'native_grade': {'order_outcome_correct': False}}}}
    (trace/'automatic-grade.json').write_text(json.dumps(raw))
    declaration = {'status': 'graded', 'episode_id': trace.name, 'contract_id': 'saved',
                   'grade_sha256': file_hash(trace/'automatic-grade.json'),
                   'binding': binding, 'binding_sha256': digest(binding)}
    (trace/'automatic-grading.json').write_text(json.dumps(declaration))
    (trace/'episode.json').write_text(json.dumps({'error': 'HTTP 502', 'grading_error': None, 'stop_reason': 'error'}))
    (trace/'suite-order-grade.json').write_text(json.dumps({'status': 'inconclusive'}))
    snapshots = {p: p.read_bytes() for p in trace.iterdir()}
    row = recover({'status': 'system_failure', 'error': 'Clean automatic grading failed: None',
                   'variant': 'clean', 'recipe_path': 'recipe.json'}, tmp_path)
    assert row['status'] == 'graded'
    assert row['grade']['status'] == 'inconclusive'
    assert row['policy_error'] == 'HTTP 502'
    assert all(p.read_bytes() == data for p, data in snapshots.items())
    (trace/'automatic-grade.json').write_text('{}')
    with pytest.raises(ValueError, match='intact completed grade'):
        recover({'variant': 'clean'}, tmp_path)
