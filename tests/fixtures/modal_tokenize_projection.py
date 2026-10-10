"""Offline fixture: unchanged reviewed tokenize projection, no server."""
from copy import deepcopy

def tokenize_payload(body):
    # Exact prompt fields shared with pinned ChatCompletionRequest. Sampling and
    # output limits do not change prompt rendering. Never silently drop extras.
    if set(body) - {'model', 'messages', 'temperature', 'max_tokens', 'stream',
                    'tools', 'tool_choice', 'parallel_tool_calls'}:
        raise ValueError('Unqualified complete-request fields')
    if body.get('stream') is not False:
        raise ValueError('This pilot qualifies non-streaming chat only')
    if body.get('tool_choice', 'auto') not in {'auto', 'none'}:
        raise ValueError('Unqualified tool_choice')
    if body.get('tools') and body.get('tool_choice') == 'none':
        raise ValueError('Tool schema with tool_choice none is outside this pilot')
    result = deepcopy({k: body[k] for k in ('model', 'messages')})
    # vLLM 0.28 ChatCompletionRequest performs this alias normalization;
    # TokenizeChatRequest does not. Match generation's canonical reasoning
    # precedence in a count-only copy, preserving the original generation wire.
    for message in result['messages']:
        reasoning_content = message.pop('reasoning_content', None)
        if reasoning_content is not None and message.get('reasoning') is None:
            message['reasoning'] = reasoning_content
    if body.get('tools') and body.get('tool_choice', 'auto') != 'none':
        result['tools'] = deepcopy(body['tools'])
    return result
