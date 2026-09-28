"""Auditable Chat Completions <-> Responses translation, without agent machinery.

Unknown policy fields fail closed. Provider metadata is retained separately;
it is never inserted into the next policy input. No tool is executed here.
"""
from copy import deepcopy
import hashlib
import json


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':')).encode()).hexdigest()


def keys(value, allowed):
    if not isinstance(value, dict) or set(value) - set(allowed):
        raise ValueError('Unsupported protocol fields: ' + repr(set(value) - set(allowed)
                         if isinstance(value, dict) else type(value).__name__))


def text_parts(content, role):
    if isinstance(content, str):
        return [{'type': 'output_text' if role == 'assistant' else 'input_text', 'text': content}]
    if content is None and role == 'assistant':
        return []
    if not isinstance(content, list):
        raise ValueError('Expected text or explicit multimodal content')
    result = []
    for part in content:
        if part.get('type') == 'text':
            keys(part, ('type', 'text'))
            if not isinstance(part['text'], str):
                raise ValueError('Invalid text part')
            result.extend(text_parts(part['text'], role))
        elif part.get('type') == 'image_url' and role in ('user', 'tool'):
            keys(part, ('type', 'image_url'))
            keys(part['image_url'], ('url', 'detail'))
            image = part['image_url']
            # Never let the model transport fetch a local file or arbitrary URL.
            # The harness supplies inline screenshot bytes.
            if not isinstance(image.get('url'), str) or not image['url'].startswith('data:image/'):
                raise ValueError('Only harness-supplied inline images are supported')
            result.append({'type': 'input_image', 'image_url': image['url'],
                           **({'detail': image['detail']} if 'detail' in image else {})})
        else:
            raise ValueError('Unsupported content part')
    return result


def request_body(request, *, replay=None, reasoning_effort='medium', provider_output_limit=False):
    keys(request, ('model', 'messages', 'tools', 'tool_choice', 'parallel_tool_calls',
                   'temperature', 'max_tokens', 'stream', 'session_id'))
    if request.get('temperature', 0) != 0 or request.get('stream', False) is not False:
        raise ValueError('Unsupported generation setting')
    if not isinstance(request.get('model'), str) or not request['model']:
        raise ValueError('Model must be explicit')
    if not isinstance(request.get('messages'), list) or not request['messages']:
        raise ValueError('Messages must be nonempty')
    if reasoning_effort not in ('low', 'medium', 'high', 'xhigh'):
        raise ValueError('Reasoning effort must be explicit and enabled')
    items = []
    for message in request['messages']:
        keys(message, ('role', 'content', 'tool_calls', 'tool_call_id', 'reasoning_details'))
        role = message.get('role')
        if role not in ('system', 'developer', 'user', 'assistant', 'tool'):
            raise ValueError('Unsupported message role')
        if role != 'assistant' and ('tool_calls' in message or 'reasoning_details' in message):
            raise ValueError('Assistant-only fields on another role')
        if role != 'tool' and 'tool_call_id' in message:
            raise ValueError('Tool result ID on another role')
        # Preserve original Responses output ordering, item IDs and encrypted
        # reasoning only when the harness still supplies the identical message.
        original = (replay or {}).get(digest(message)) if role == 'assistant' else None
        if original is not None:
            items.extend(deepcopy(original))
            continue
        if role == 'tool':
            if not isinstance(message.get('tool_call_id'), str) or not message['tool_call_id']:
                raise ValueError('Missing tool call ID')
            output = message['content']
            if not isinstance(output, str):
                output = text_parts(output, role)
            items.append({'type': 'function_call_output', 'call_id': message['tool_call_id'], 'output': output})
            continue
        for detail in message.get('reasoning_details', []):
            if detail.get('format') != 'harness-responses-v1' or 'responses_item' not in detail:
                raise ValueError('Cannot losslessly replay foreign reasoning state')
            item = detail['responses_item']
            if item.get('type') != 'reasoning':
                raise ValueError('Reasoning state must contain only a reasoning item')
            items.append(deepcopy(item))
        parts = text_parts(message.get('content'), role)
        if parts:
            items.append({'role': role, 'content': parts})
        for call in message.get('tool_calls', []):
            keys(call, ('id', 'type', 'function'))
            keys(call.get('function'), ('name', 'arguments'))
            if call.get('type') != 'function' or not all(isinstance(v, str) and v for v in
                    (call.get('id'), call['function'].get('name'), call['function'].get('arguments'))):
                raise ValueError('Invalid function call')
            items.append({'type': 'function_call', 'call_id': call['id'], **deepcopy(call['function'])})
    tools = []
    for tool in request.get('tools', []):
        keys(tool, ('type', 'function'))
        fn = tool.get('function')
        keys(fn, ('name', 'description', 'parameters', 'strict'))
        if tool.get('type') != 'function' or not isinstance(fn.get('name'), str):
            raise ValueError('Only supplied function tools are supported')
        # Responses otherwise defaults to schema normalization/strictness that
        # differs from the Chat Completions non-strict default.
        tools.append({'type': 'function', 'strict': False, **deepcopy(fn)})
    choice = deepcopy(request.get('tool_choice', 'auto'))
    if isinstance(choice, dict):
        keys(choice, ('type', 'function'))
        keys(choice.get('function'), ('name',))
        if choice.get('type') != 'function':
            raise ValueError('Unsupported tool choice')
        choice = {'type': 'function', 'name': choice['function']['name']}
    elif choice not in ('auto', 'required', 'none'):
        raise ValueError('Unsupported tool choice')
    body = {'model': request['model'], 'store': False, 'stream': True,
            'instructions': '', 'input': items, 'tools': tools, 'tool_choice': choice,
            'reasoning': {'effort': reasoning_effort, 'summary': 'auto'},
            'include': ['reasoning.encrypted_content']}
    if 'parallel_tool_calls' in request:
        if type(request['parallel_tool_calls']) is not bool:
            raise ValueError('parallel_tool_calls must be boolean')
        body['parallel_tool_calls'] = request['parallel_tool_calls']
    if request.get('max_tokens') is not None:
        if type(request['max_tokens']) is not int or request['max_tokens'] <= 0:
            raise ValueError('Invalid output token limit')
        if not provider_output_limit:
            body['max_output_tokens'] = request['max_tokens']
    if request.get('session_id'):
        body['prompt_cache_key'] = request['session_id']
    return body


def completion(response):
    """Project a raw Responses terminal object; never repair tool arguments."""
    if not isinstance(response, dict) or not isinstance(response.get('output'), list):
        raise ValueError('Missing Responses output')
    text, calls, details, refusals = [], [], [], []
    for item in response['output']:
        kind = item.get('type')
        if kind == 'function_call':
            calls.append({'id': item['call_id'], 'type': 'function', 'function': {
                'name': item['name'], 'arguments': item['arguments']}})
        elif kind == 'message' and item.get('role') == 'assistant':
            for part in item.get('content', []):
                if part.get('type') == 'output_text': text.append(part['text'])
                elif part.get('type') == 'refusal': refusals.append(part['refusal'])
                else: raise ValueError('Unsupported assistant content')
        elif kind == 'reasoning':
            encrypted = item.get('encrypted_content')
            details.append({'type': 'reasoning.encrypted' if encrypted else 'reasoning.text',
                            'format': 'harness-responses-v1',
                            **({'data': encrypted} if encrypted else {'text': '\n'.join(
                                p['text'] for p in item.get('summary', []) if 'text' in p)}),
                            'responses_item': deepcopy(item)})
        else:
            raise ValueError('Unsupported output item; no built-in provider tools allowed: ' + str(kind))
    message = {'role': 'assistant', 'content': ''.join(text) or None}
    if calls: message['tool_calls'] = calls
    if details: message['reasoning_details'] = details
    if refusals: message['refusal'] = '\n'.join(refusals)
    status = response.get('status')
    finish = ('tool_calls' if calls else 'stop') if status == 'completed' else (
        'length' if status == 'incomplete' else 'error')
    usage = response.get('usage')
    normalized = None
    if isinstance(usage, dict):
        normalized = {dst: usage[src] for src, dst in (
            ('input_tokens', 'prompt_tokens'), ('output_tokens', 'completion_tokens'),
            ('total_tokens', 'total_tokens'), ('input_tokens_details', 'prompt_tokens_details'),
            ('output_tokens_details', 'completion_tokens_details')) if src in usage}
    return {'id': response.get('id'), 'model': response.get('model'),
            'choices': [{'index': 0, 'finish_reason': finish, 'message': message}],
            'usage': normalized, 'provider': 'openai-codex',
            'external_bridge': {'version': 1, 'raw_response': deepcopy(response),
                                'reported_cost': None, 'billing': 'subscription'}}
