"""Regression: Qwen XML IDs, reasoning, and malformed/batched tool output."""
import json
from pathlib import Path
from types import SimpleNamespace
import pytest


def test_qwen_schema_aware_browser_response():
    transformers = pytest.importorskip('transformers')
    utils = pytest.importorskip('trl.chat_template_utils')
    from browser_training.project_harness import wire_response, configure_response_parser
    path = Path(__file__).resolve().parents[1] / '.cache/qwen38-tokenizer'
    if not path.exists():
        pytest.skip('Offline Qwen tokenizer not cached')
    tokenizer = configure_response_parser(transformers.AutoTokenizer.from_pretrained(path, local_files_only=True))
    tools = [dict(type='function', function=dict(name='click', description='Click', parameters=dict(
        type='object', properties=dict(bid=dict(type='string')), required=['bid'])))]
    prompt = tokenizer.apply_chat_template([dict(role='user', content='Click the button')], tools=tools,
                                          enable_thinking=True, add_generation_prompt=True, return_dict=False)
    call = '<tool_call>\n<function=click>\n<parameter=bid>\n107\n</parameter>\n</function>\n</tool_call>'
    def result(text):
        ids = tokenizer.encode(text, add_special_tokens=False)
        step = SimpleNamespace(prompt_ids=prompt, completion_ids=ids, logprobs=[-0.5]*len(ids))
        return wire_response(tokenizer, step, tools)
    raw = result('The requested button.\n</think>\n' + call + '<|im_end|>')
    message = raw['choices'][0]['message']
    assert json.loads(message['tool_calls'][0]['function']['arguments']) == {'bid': '107'}
    assert 'requested button' in message['reasoning_content']
    assert raw['choices'][0]['finish_reason'] == 'stop'
    # A batch remains a batch for the existing single-call harness to reject.
    assert len(result('</think>\n'+call+call+'<|im_end|>')['choices'][0]['message']['tool_calls']) == 2
    assert result('</think>\n'+call)['choices'][0]['finish_reason'] == 'length'
    assert not result('</think>\nnot a tool<|im_end|>')['choices'][0]['message'].get('tool_calls')


@pytest.mark.parametrize('stopping, expected', [(True, 'cancelled'), (False, 'infra_error')])
def test_shutdown_interruption_is_not_a_browser_failure(stopping, expected):
    from browser_training.monitored_harness import MonitoredSession, MonitoredHarnessAdapter
    records = []
    session = MonitoredSession(SimpleNamespace(close=lambda: None),
        SimpleNamespace(finish=lambda *args, **kwargs: records.append((args, kwargs))), 'episode', None)
    def run(step, active, limits):
        if stopping:
            active.close()  # Stop watcher while a sampling callback is draining.
        raise OSError('closed browser transport')
    with pytest.raises(OSError):
        MonitoredHarnessAdapter(SimpleNamespace(run_white_box=run)).run_white_box(None, session, None)
    session.close()
    assert len(records) == 1 and records[0][0][1]['status'] == expected
    assert records[0][0][1]['reward'] is None
