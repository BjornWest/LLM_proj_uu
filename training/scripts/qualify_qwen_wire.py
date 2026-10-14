#!/usr/bin/env python3
"""Once-per-stack Qwen image/history/schema/input-boundary parity probes.

Default is a plan with no imports of GPU libraries or serving calls. --execute
requires an already approved, owned SM120 server. This writes wire evidence,
never a stack capability or dispatch approval. Subsequent instances reuse the
capability through qwen_suite_qualification.py without repeating generation.
"""
from copy import deepcopy
import argparse
import base64
from hashlib import sha256
import http.client
import io
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parent))
from qwen_suite_qualification import (read_pin, pin, publish, endpoint,
                                      owned_listener, close_socket, models,
                                      serving_command)

MODEL = 'Qwen/Qwen3.8-27B-FP8'
REVISION = '017b9c7af6b5689d5dd426a76e0bc077eb5ca20a'
CONTEXT = 262144
BOUNDARY = 250000
GEOMETRY = dict(min_pixels=65536, max_pixels=16777216, patch_size=16,
                merge_size=2, temporal_patch_size=2)
RUNTIME_SHA256 = '35b5d8aa7bcf54f6940e41aa355a3e63288d0b5e51ad7ce4a9b729013d98d563'


def wire(value):
    # Hash and send the exact insertion order consumed by Evaluation's encoder.
    return json.dumps(value, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode()


def source_runtime(row):
    if row['sha256'] != RUNTIME_SHA256:
        raise ValueError('Use the independently reviewed exact runtime source')
    data = read_pin(row)
    namespace = {'__file__': row['path'], '__name__': '_qwen_wire_runtime'}
    exec(compile(data, row['path'], 'exec'), namespace)
    if namespace['MODEL'] != MODEL or namespace['CONTEXT'] != CONTEXT:
        raise ValueError('Exact reviewed native Qwen runtime required')
    return namespace


def png(width, height):
    from PIL import Image
    stream = io.BytesIO()
    Image.new('RGB', (width, height), 'white').save(stream, format='PNG')
    return {'type': 'image_url', 'image_url': {
        'url': 'data:image/png;base64,' + base64.b64encode(stream.getvalue()).decode()}}


def processor_counter(snapshot):
    """Actual pinned official processor; no model weights or CUDA forward."""
    from PIL import Image
    from vllm.transformers_utils.processor import get_processor
    from vllm.entrypoints.openai.chat_completion.protocol import ChatCompletionToolsParam
    processor = get_processor(str(snapshot), local_files_only=True, **GEOMETRY)
    image = processor.image_processor
    if (image.patch_size != 16 or image.merge_size != 2 or image.temporal_patch_size != 2
            or image.size != {'shortest_edge': 65536, 'longest_edge': 16777216}):
        raise ValueError('Official effective image geometry differs')

    def count(payload):
        messages = official_messages(payload['messages'])
        for message in messages:
            if isinstance(message.get('content'), list):
                for item in message['content']:
                    if item.get('type') == 'image_url':
                        url = item['image_url']['url']
                        if not url.startswith('data:image/png;base64,'):
                            raise ValueError('Only generated bounded PNG probe data accepted')
                        data = base64.b64decode(url.split(',', 1)[1], validate=True)
                        picture = Image.open(io.BytesIO(data)).convert('RGB')
                        item.clear(); item.update(type='image', image=picture)
        tools = ([ChatCompletionToolsParam.model_validate(tool).model_dump()
                  for tool in payload['tools']] if payload.get('tools') else None)
        rendered = processor.apply_chat_template(messages, tools=tools,
            tokenize=True, return_dict=True, add_generation_prompt=True,
            enable_thinking=True, preserve_thinking=True)
        ids = rendered['input_ids']
        ids = ids[0] if ids and isinstance(ids[0], list) else ids
        if not isinstance(ids, list) or any(type(i) is not int or i < 0 for i in ids):
            raise ValueError('Official processor must return integer token IDs')
        return ids
    return count


def official_messages(messages):
    """HF representation after vLLM0.28's documented chat normalization.

    chat_utils._parse_chat_message_content emits both reasoning aliases;
    _postprocess_messages converts JSON tool-argument strings into objects.
    Generation and /tokenize wires stay unchanged and preserve insertion order.
    """
    result = deepcopy(messages)
    for message in result:
        if message.get('reasoning') is not None:
            message['reasoning_content'] = message['reasoning']
        for call in message.get('tool_calls') or []:
            function = call.get('function', call)
            arguments = function.get('arguments')
            if not arguments:
                function['arguments'] = {}
            elif isinstance(arguments, str):
                function['arguments'] = json.loads(arguments)
                if function['arguments'] is None: function['arguments'] = {}
    return result


def request(body, messages, *, tools=True):
    system = [deepcopy(m) for m in body.get('messages', []) if m.get('role') == 'system']
    value = dict(model=MODEL, messages=system + messages, temperature=0, max_tokens=2, stream=False)
    if tools:
        value.update(tools=deepcopy(body['tools']), tool_choice='auto', parallel_tool_calls=False)
    return value


def probes(template, projection, reference):
    if template.get('model') != MODEL or not isinstance(template.get('tools'), list) or not template['tools']:
        raise ValueError('Bind the actual planned native tool schema, not a fabricated replacement')
    if not any(m.get('role') == 'system' for m in template.get('messages', [])):
        raise ValueError('Bind the actual planned system message to cover system-plus-tools rendering')
    selected = []
    for w, h in ((64, 64), (1280, 720), (2048, 1024)):
        selected.append((f'image-{w}x{h}', request(template, [{'role': 'user', 'content': [
            {'type': 'text', 'text': 'Inspect this page.'}, png(w, h)]}]), False))
    tool = template['tools'][0]['function']['name']
    history = [{'role': 'user', 'content': [{'type': 'text', 'text': 'Inspect the page.'}, png(1280, 720)]},
        {'role': 'assistant', 'content': None, 'reasoning_content': 'First inspect the target, then compare its price.',
         'tool_calls': [{'id': 'parity-1', 'type': 'function', 'function': {'name': tool, 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'parity-1', 'content': 'The page is visible.'},
        {'role': 'user', 'content': [{'type': 'text', 'text': 'Continue.'}, png(2048, 1024)]}]
    selected.append(('retained-history', request(template, history), True))
    boundary = request(template, [{'role': 'user', 'content': ' x' * (BOUNDARY - 2048)}])
    for _ in range(6):
        actual = len(reference(projection(boundary)))
        if actual == BOUNDARY:
            break
        repeats = boundary['messages'][-1]['content'].count(' x') + BOUNDARY - actual
        if not 0 < repeats < CONTEXT:
            raise ValueError('Native schema overhead prevents this bounded boundary probe')
        boundary['messages'][-1]['content'] = ' x' * repeats
    if len(reference(projection(boundary))) != BOUNDARY:
        raise ValueError('Could not construct exact250k complete input; do not shorten the probe silently')
    selected.append(('250000-input-boundary', boundary, True))
    schema = request(template, [{'role': 'user', 'content': 'Return a structured result.'}], tools=False)
    schema['response_format'] = {'type': 'json_schema', 'json_schema': {'name': 'wire_probe', 'strict': True,
        'schema': {'type': 'object', 'properties': {'answer': {'type': 'string'}},
                   'required': ['answer'], 'additionalProperties': False}}}
    selected.append(('structured-output', schema, True))
    return selected


class StopRequested(BaseException):
    """A stop request must survive libraries catching Exception/OSError."""


class ExchangeResult(dict):
    def __init__(self, value, observation):
        super().__init__(value)
        self.observation = observation


class ExchangeError(RuntimeError):
    def __init__(self, observation):
        self.observation = observation
        super().__init__('Parity exchange failed: ' + observation.get('error_type', 'unknown')
                         + '; HTTP=' + str(observation.get('http_status')))


def http_exchange(origin, path, body, *, deadline, owner):
    _, port = endpoint(origin, '')
    owned_listener(owner, port)
    remaining = min(600, deadline - time.time())
    if remaining <= 0 or not math.isfinite(remaining):
        raise TimeoutError('Original rental ended')
    end = time.monotonic() + remaining
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=remaining)
    timer = None
    expired = threading.Event()
    observed = {'request_started': False, 'request_written': False,
                'headers_received': False, 'response_received': False}
    chunks = []
    data = b''
    response = None
    transport = None
    limit = 16 << 20
    def expire():
        expired.set()
        close_socket(transport)
    def preserve():
        # Keep raw bytes independently of JSON parsing, owner checks and errors.
        raw = b''.join(chunks)
        declared = observed.get('declared_content_length')
        observed.update(body_bytes=len(raw), body_sha256=sha256(raw).hexdigest(),
            raw_body=raw, body_prefix_base64=base64.b64encode(raw[:64 << 10]).decode(),
            body_truncated=len(raw) > limit,
            body_incomplete=(response is not None and declared is not None and len(raw) < declared),
            deadline_timer_fired=expired.is_set())
        return raw
    try:
        conn.connect()
        transport = conn.sock
        timer = threading.Timer(max(.001, end - time.monotonic()), expire)
        timer.daemon = True; timer.start()
        observed['request_started'] = True
        conn.request('POST', path, wire(body), {'Content-Type': 'application/json'})
        observed['request_written'] = True
        response = conn.getresponse()
        observed.update(http_status=response.status, headers_received=True)
        declared = response.getheader('Content-Length')
        observed['declared_content_length'] = int(declared) if declared is not None else None
        limit = 16 << 20 if response.status == 200 else 64 << 10
        size = 0
        while size <= limit:
            # read1 preserves chunks already received if a later read fails.
            try:
                chunk = response.read1(min(64 << 10, limit + 1 - size))
            except http.client.IncompleteRead as error:
                chunks.append(error.partial)
                raise
            if not chunk: break
            chunks.append(chunk); size += len(chunk)
        data = preserve()
        observed['response_received'] = not (observed['body_incomplete'] or observed['body_truncated'])
        if observed['deadline_timer_fired'] or time.monotonic() >= end or time.time() >= deadline:
            raise TimeoutError('Parity response exceeded original lifetime')
        if response.status != 200 or observed['body_incomplete'] or observed['body_truncated']:
            raise ValueError('Complete bounded parity HTTP200 required')
        def invalid_constant(value): raise ValueError('Invalid JSON constant: ' + value)
        def finite_float(value):
            number = float(value)
            if not math.isfinite(number): raise ValueError('Nonfinite JSON number')
            return number
        result = json.loads(data, parse_constant=invalid_constant, parse_float=finite_float)
        if not isinstance(result, dict): raise ValueError('JSON object response required')
        observed['received_response'] = result
        owned_listener(owner, port)
        if time.monotonic() >= end or time.time() >= deadline:
            raise TimeoutError('Parity response exceeded original lifetime')
        return ExchangeResult(result, observed)
    except BaseException as error:
        preserve()
        observed.update(error_type='TimeoutError' if expired.is_set() else type(error).__name__)
        raise ExchangeError(observed) from error
    finally:
        if timer is not None: timer.cancel()
        conn.close()


def qualify(selected, projection, reference, exchange, record, save_response=deepcopy):
    """Pure comparison core. Tests use fake exchange; no evidence authority here."""
    required = {'image-64x64', 'image-1280x720', 'image-2048x1024',
                'retained-history', '250000-input-boundary', 'structured-output'}
    if len(selected) != len(required) or {x[0] for x in selected} != required:
        raise ValueError('Complete six-probe qualification required')
    rows = []
    generations = 0
    for label, body, generate in selected:
        payload = projection(body)
        ids = reference(payload)
        if label == '250000-input-boundary' and len(ids) != BOUNDARY:
            raise ValueError('Boundary must be250k complete input tokens')
        if generate is not (label in {'retained-history', '250000-input-boundary', 'structured-output'}):
            raise ValueError('Use exactly the five bounded diagnostic generations')
        row = {'probe': label, 'request_sha256': sha256(wire(body)).hexdigest(),
            'tokenize_payload_sha256': sha256(wire(payload)).hexdigest(),
            'official_input_tokens': len(ids), 'official_token_ids_sha256': sha256(wire(ids)).hexdigest(),
            'server_count': {'state': 'dispatch_attempt'}, 'generations': []}
        rows.append(row); record(rows)
        try:
            measured = exchange('/tokenize', payload)
        except BaseException as error:
            row['server_count'].update(state='failed', error_type=type(error).__name__)
            if isinstance(error, ExchangeError): row['server_count']['observation'] = save_response(error.observation)
            record(rows); raise
        row['server_count'] = {key: deepcopy(value) for key, value in measured.items() if key != 'tokens'}
        row['server_count']['token_ids_sha256'] = sha256(wire(measured.get('tokens'))).hexdigest()
        record(rows)
        if (type(measured.get('count')) is not int or measured['count'] != len(ids)
                or measured.get('max_model_len') != CONTEXT or measured.get('tokens') != ids):
            row['server_count']['mismatch_response'] = save_response(measured)
            record(rows)
            raise ValueError('Official/server complete token parity differs: ' + label)
        if generate:
            variants = [body]
            if label == 'retained-history':
                variants.append({**body, 'max_tokens': 1, 'parallel_tool_calls': True})
            elif label == 'structured-output':
                # Same tool-free messages with no grammar: proves schema does
                # not add hidden prompt text in this exact installed server.
                variants.append({k: v for k, v in body.items() if k != 'response_format'})
            for variant in variants:
                diagnostic = {**variant, 'return_token_ids': True}
                generations += 1
                attempt = {'request_sha256': sha256(wire(diagnostic)).hexdigest(), 'state': 'dispatch_attempt'}
                row['generations'].append(attempt); record(rows)
                try:
                    done = exchange('/v1/chat/completions', diagnostic)
                except BaseException as error:
                    attempt.update(state='failed', error_type=type(error).__name__)
                    if isinstance(error, ExchangeError): attempt['observation'] = save_response(error.observation)
                    record(rows); raise
                attempt.update(state='response_received', response=save_response(done))
                record(rows)  # Preserve the response before any parity failure.
                usage = done.get('usage', {})
                if (usage.get('prompt_tokens') != len(ids) or done.get('prompt_token_ids') != ids
                        or type(usage.get('completion_tokens')) is not int
                        or not 0 < usage['completion_tokens'] <= variant['max_tokens']):
                    raise ValueError('Generation prompt/output parity differs: ' + label)
                attempt['state'] = 'parity_passed'; record(rows)
    return {'wire_serialization': 'json-insertion-order-v1', 'diagnostic_generation_requests': generations,
            'checks': {'image_input_count_parity': True, 'retained_reasoning_count_parity': True,
                'prompt_usage_parity': True, 'input_boundary_forward': True,
                'output_controls_prompt_independent': True, 'native_tool_wire': True,
                'structured_output_prompt_independent': True}, 'probes': rows}


def gpu_check():
    # The child exits and releases its CUDA context before the long prefill.
    checked = subprocess.run([sys.executable, '-I', '-B', '-c',
        'import torch,json; print(json.dumps({"gpus":torch.cuda.device_count(),'
        '"capability":list(torch.cuda.get_device_capability(0)) if torch.cuda.device_count() else []}))'],
        capture_output=True, text=True, timeout=30)
    if checked.returncode:
        raise ValueError('GPU inspection subprocess failed')
    result = json.loads(checked.stdout)
    if result != {'gpus': 1, 'capability': [12, 0]}:
        raise ValueError('Use the approved singleSM120 host; no localGTX1070 test')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('runtime', 'request', 'launch', 'owner', 'rental'):
        p.add_argument('--' + name, type=Path, required=True)
        p.add_argument('--' + name + '-sha256', required=True)
    p.add_argument('--snapshot', type=Path, required=True)
    p.add_argument('--origin', default='http://127.0.0.1:8000')
    p.add_argument('--deadline-utc', type=float, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--execute', action='store_true')
    args = p.parse_args()
    endpoint(args.origin, '')
    if not math.isfinite(args.deadline_utc): raise ValueError('Finite rental deadline required')
    bindings = {key: {'path': str(getattr(args, key).absolute()), 'sha256': getattr(args, key + '_sha256')}
                for key in ('runtime', 'request', 'launch', 'owner', 'rental')}
    # Plan checks exact input bytes, but never probes sockets or imports torch.
    values = {key: read_pin(row) for key, row in bindings.items()}
    if not args.execute:
        print(json.dumps({'status': 'plan_only', 'generation_requests': 5,
            'boundary_complete_input_tokens': BOUNDARY, 'maximum_generated_tokens': 9,
            'probes': ['image64', 'image1280', 'image2048', 'history', 'boundary250k', 'schema'],
            'no_GPU_HTTP_download_or_dispatch': True, 'inputs': bindings}))
        return
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', PYTHONDONTWRITEBYTECODE='1')
    gpu_check()
    snapshot = args.snapshot.resolve(strict=True)
    if snapshot.name != REVISION or snapshot.parent.parent.name != 'models--Qwen--Qwen3.8-27B-FP8':
        raise ValueError('Pinned official HF snapshot required')
    launch, owner = (json.loads(values[k]) for k in ('launch', 'owner'))
    rental = json.loads(values['rental'])
    for key in ('run_id', 'instance_id'):
        if str(UUID(rental[key])) != rental[key]: raise ValueError('Canonical current run/instance IDs required')
    if (rental.get('qualification_authorized') is not True
            or type(rental.get('approved_rental_seconds')) is not int
            or not 0 < rental['approved_rental_seconds'] <= 86400
            or type(rental.get('allocation_utc')) not in (int, float)
            or not math.isfinite(rental['allocation_utc'])
            or rental['allocation_utc'] + rental['approved_rental_seconds'] != args.deadline_utc
            or rental.get('deadline_utc') != args.deadline_utc
            or rental['run_id'] == rental['instance_id']
            or rental.get('serving_session_id') != launch['attempt_id']
            or not rental['allocation_utc'] <= time.time() < args.deadline_utc):
        raise ValueError('Bind the approved finite diagnostic allowance and original allocation deadline')
    if (launch.get('status') != 'source_checks_passed_before_exec' or launch.get('pid') != owner.get('pid')
            or snapshot != Path(launch['command'][5]) or args.deadline_utc <= time.time()):
        raise ValueError('Current owned serving launch/snapshot/lifetime required')
    expected = serving_command(snapshot, port=endpoint(args.origin, '')[1],
        max_num_seqs=int(launch['launch_settings']['max_num_seqs']),
        memory_fraction=float(launch['launch_settings']['gpu_memory_utilization']))
    if launch['command'] != expected:
        raise ValueError('Run the probes from the exact serving Python/profile, with no extra argv')
    owned_listener(owner, endpoint(args.origin, '')[1])
    actual = models(args.origin, timeout=min(10, args.deadline_utc - time.time()))
    if len(actual.get('data', [])) != 1 or any(
            row.get('id') != MODEL or row.get('max_model_len') != CONTEXT for row in actual['data']):
        raise ValueError('Actual native262k model metadata required')
    parent = args.output.parent
    if not parent.is_dir() or parent.stat().st_uid != os.geteuid() or parent.stat().st_mode & 0o077:
        raise ValueError('Use an existing private owned run directory as output parent')
    args.output.mkdir(mode=0o700, exist_ok=False)
    rows = []
    sequence = 0
    response_sequence = 0
    def save_response(value):
        nonlocal response_sequence
        response_sequence += 1
        observation = value.observation if isinstance(value, ExchangeResult) else value
        if isinstance(observation, dict) and 'raw_body' in observation:
            # A 200 body can be16MiB. Store exact bytes once, separate from small
            # metadata/proofs, so malformed JSON and token mismatches remain inspectable.
            raw_path = args.output / f'response-{response_sequence:03}.body'
            with raw_path.open('xb') as stream:
                os.chmod(raw_path, 0o600)
                stream.write(observation['raw_body']); stream.flush(); os.fsync(stream.fileno())
            metadata = {k: v for k, v in observation.items() if k not in ('raw_body', 'received_response')}
            metadata['raw_body_artifact'] = pin(raw_path)
            parsed = observation.get('received_response', {})
            metadata['usage'] = deepcopy(parsed.get('usage')) if isinstance(parsed, dict) else None
            saved = publish(args.output / f'response-{response_sequence:03}.json', metadata)
            return {'artifact': saved, 'raw_body_artifact': metadata['raw_body_artifact'],
                    'usage': metadata['usage'], 'http_status': metadata.get('http_status')}
        saved = publish(args.output / f'response-{response_sequence:03}.json', value)
        return {'artifact': saved, 'usage': deepcopy(value.get('usage')) if isinstance(value, dict) else None,
                'http_status': value.get('http_status') if isinstance(value, dict) else None}
    def record(value):
        nonlocal sequence, rows
        rows = deepcopy(value); sequence += 1
        publish(args.output / f'progress-{sequence:03}.json', {'passed': False, 'probes': rows})
    report = {'status': 'failed', 'passed': False, 'synthetic': False, 'inputs': bindings,
        'serving_session_id': launch['attempt_id'], 'deadline_utc': args.deadline_utc,
        'metadata': {'tags': ['model', 'serving-diagnostic']},
        'allow_ungraded': True, 'ungraded_reason': 'Infrastructure token/usage parity probe; no browser task or task outcome.',
        'scope': 'Once-only actual wire/processor/GPU-forward comparisons; no capability or dispatch approval.'}
    original_handlers = {}
    stopped = []
    def stop(signum, frame):
        stopped.append(signum)
        raise StopRequested('Wire qualification interrupted by signal' + str(signum))
    for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        original_handlers[signum] = signal.signal(signum, stop)
    try:
        runtime = source_runtime(bindings['runtime'])
        counter = processor_counter(snapshot)
        selected = probes(json.loads(values['request']), runtime['tokenize_payload'], counter)
        result = qualify(selected, runtime['tokenize_payload'], counter,
            lambda path, body: http_exchange(args.origin, path, body, deadline=args.deadline_utc, owner=owner),
            record, save_response=save_response)
        for row in bindings.values(): read_pin(row)
        if stopped: raise StopRequested('Stop request prevents qualification success')
        report.update(result, status='wire_qualification_passed', passed=True,
                      counter_projection_sha256=runtime['projection_sha256']())
    except BaseException as error:
        report.update(error_type=type(error).__name__, error=str(error), probes=rows)
        raise
    finally:
        try:
            report['diagnostic_generation_attempts'] = sum(len(row['generations']) for row in rows)
            report['stopped_by_signal'] = stopped
            if stopped: report.update(passed=False, status='failed')
            publish(args.output / 'wire-proof.json', report)
        finally:
            for signum, handler in original_handlers.items(): signal.signal(signum, handler)


if __name__ == '__main__':
    main()
