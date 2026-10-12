"""Private Qwen serving admission for the existing comparison orchestrator.

Evolves the reviewed B06 factories: one creating thread, synchronous buffered
HTTP, exact ordered count/generation, and a separate tool-free schema formatter.
No default generation, host allocation, credential lookup or historical repair.
"""
from contextlib import contextmanager, nullcontext
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from threading import get_ident
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
import json
import math
import time

MODEL = 'Qwen/Qwen3.8-27B-FP8'
REVISION = '017b9c7af6b5689d5dd426a76e0bc077eb5ca20a'
CONTEXT = 262144
ISL = 250000
IDENTITY_KEYS = {'model', 'serving_revision', 'tokenizer_sha256', 'template_sha256',
                 'image_processor_sha256', 'tool_parser'}
CHECKS = ('image_input_count_parity', 'retained_reasoning_count_parity',
          'prompt_usage_parity', 'input_boundary_forward',
          'output_controls_prompt_independent', 'native_tool_wire',
          'structured_output_prompt_independent')


def encoded(value, *, sorted_keys=False):
    return json.dumps(value, sort_keys=sorted_keys, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')


def digest(value, *, sorted_keys=False):
    return sha256(encoded(value, sorted_keys=sorted_keys)).hexdigest()


def hex_hash(value):
    if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
        raise ValueError('Exact lowercase SHA256 required')
    return value


def number(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError('Finite numeric UTC time required')
    return value


def read_pin(row):
    if not isinstance(row, dict) or set(row) != {'path', 'sha256'}:
        raise ValueError('Exact path/SHA256 pin required')
    path = Path(row['path'])
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise ValueError('Immutable absolute regular evidence file required')
    if sha256(path.read_bytes()).hexdigest() != hex_hash(row['sha256']):
        raise ValueError('Evidence pin changed: ' + str(path))
    return path


def load_pin(row):
    return json.loads(read_pin(row).read_bytes())


def loopback(url, path):
    u = urlsplit(url)
    if (u.scheme != 'http' or u.hostname not in ('127.0.0.1', '::1') or not u.port
            or u.path != path or u.username or u.password or u.query or u.fragment):
        raise ValueError('Explicit loopback endpoint with expected path required')
    return url.rstrip('/')


def validate_compatibility(value):
    if not isinstance(value, dict) or set(value) != {'runtime','hardware','model','assets','serving'}:
        raise ValueError('Complete measured compatibility object required')
    runtime=value['runtime']
    keys={'vllm_version','vllm_source_patch_sha256','pytorch_version','cuda_runtime_version',
          'runtime_lock_sha256','kernel_versions','counter_projection_sha256'}
    if not isinstance(runtime,dict) or set(runtime)!=keys:
        raise ValueError('Complete installed runtime and counter projection required')
    for key in ('vllm_source_patch_sha256','runtime_lock_sha256','counter_projection_sha256'):hex_hash(runtime[key])
    for key in ('vllm_version','pytorch_version','cuda_runtime_version'):
        if not isinstance(runtime[key],str) or not runtime[key]:raise ValueError('Measured installed versions required')
    if not isinstance(runtime['kernel_versions'],dict) or not runtime['kernel_versions'] or any(not isinstance(v,str) or not v for v in runtime['kernel_versions'].values()):
        raise ValueError('Measured installed kernel/package versions required')
    if value['hardware'] != {'gpu_architecture':'sm120'}:raise ValueError('Qualified SM120 architecture required')
    serving=value['serving']
    required={'context_tokens','image_limits','weight_quantization','kv_cache_dtype','kv_scales_sha256',
              'thinking','preserve_thinking','tool_parser','reasoning_parser','mtp_mode','lora_mode','attention_backend'}
    if not isinstance(serving,dict) or set(serving)!=required:raise ValueError('Complete effective serving configuration required')
    if type(serving['context_tokens']) is not int or serving['context_tokens']!=CONTEXT or serving['thinking'] is not True or serving['preserve_thinking'] is not True:
        raise ValueError('Native context and retained thinking required')
    if serving['weight_quantization']!='fp8' or serving['kv_cache_dtype']!='fp8_e4m3':raise ValueError('Qualified weight/KV profile required')
    if serving['kv_scales_sha256'] is not None:hex_hash(serving['kv_scales_sha256'])
    if not isinstance(serving['image_limits'],dict) or set(serving['image_limits'])!={'limit_mm_per_prompt','mm_processor_kwargs'}:
        raise ValueError('Explicit image processing limits required')
    backends=serving['attention_backend']
    if not isinstance(backends,dict) or set(backends)!={'prefill','decode','linear_attention','weight_compute'} or any(not isinstance(v,str) or not v or v=='auto' for v in backends.values()):
        raise ValueError('Resolved attention/compute backends required')



class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError('Serving redirects are forbidden')


class ServingAdmission:
    """Separate reusable stack capability from fresh process/session readiness.

    All live evidence is injected and pinned. Fingerprints bind serving assets;
    case source identities remain separate caller pins, never B06/source95.
    """
    def __init__(self, live_pin, *, exchange=None, clock=time.time):
        self.live_pin, self.clock = deepcopy(live_pin), clock
        self.live = load_pin(live_pin)
        live = self.live
        if live.get('schema') != 'qualified-serving-live-v1':
            raise ValueError('Qualified serving live schema required')
        self.base = loopback(live['base_url'], '/v1')
        self.raw = self.base[:-3]
        self.qualification = loopback(live['qualification_base_url'], '')
        self.exchange = exchange or self._http
        self.identity = deepcopy(live['identity'])
        if set(self.identity) != IDENTITY_KEYS:
            raise ValueError('General measured serving identity required; case commit is separate')
        if (self.identity['model'] != MODEL or self.identity['serving_revision'] != REVISION
                or self.identity['tool_parser'] != 'qwen3_coder'):
            raise ValueError('Unapproved Qwen model/revision/parser')
        for key in ('tokenizer_sha256', 'template_sha256', 'image_processor_sha256'):
            hex_hash(self.identity[key])
        if type(live['server_context']) is not int or live['server_context'] != CONTEXT:
            raise ValueError('Native 262144-token context required')
        if type(live['isl']) is not int or live['isl'] != ISL:
            raise ValueError('250000 complete-input policy ceiling required')
        self.deadline = number(live['deadline_utc'])
        self.session = live['serving_session_id']
        if not isinstance(self.session, str) or not self.session:
            raise ValueError('Fresh serving session required')
        self.capability = load_pin(live['capability_receipt'])
        self.instance = load_pin(live['instance_readiness_receipt'])
        self.deployment = load_pin(live['deployment_receipt'])
        cap, inst = self.capability, self.instance
        if (cap.get('schema') != 'serving-stack-capability-v1' or cap.get('status') != 'passed'
                or inst.get('schema') != 'serving-instance-readiness-v1' or inst.get('status') != 'ready'):
            raise ValueError('Actual passed capability and fresh readiness required')
        if any(cap.get('checks', {}).get(k) is not True for k in CHECKS):
            raise ValueError('General native/image/history/schema parity is incomplete')
        validate_compatibility(cap['compatibility'])
        validate_compatibility(inst['observed_compatibility'])
        if cap.get('synthetic') is not False or self.deployment.get('synthetic') is not False:
            raise ValueError('Synthetic capability/deployment cannot authorize real dispatch')
        if set(cap['proofs'])!={'qualification','deployment','processor'}:raise ValueError('Complete original actual proof pins required')
        for row in cap['proofs'].values():
            evidence = load_pin(row)
            if evidence.get('passed') is not True:
                raise ValueError('Original successful capability proof required')
        self.fingerprint = hex_hash(cap['fingerprint'])
        if (digest(cap['compatibility'], sorted_keys=True) != self.fingerprint
                or digest(inst['observed_compatibility'], sorted_keys=True) != self.fingerprint
                or inst['fingerprint'] != self.fingerprint
                or inst['capability'] != live['capability_receipt']
                or inst['deployment_receipt'] != live['deployment_receipt']):
            raise ValueError('Measured capability/instance compatibility mismatch')
        runtime = cap['compatibility']['runtime']
        self.projection_hash = hex_hash(runtime['counter_projection_sha256'])
        if self.projection_hash != projection_sha256():
            raise ValueError('Counter projection differs from the reviewed client')
        compat = cap['compatibility']
        if (compat['model'] != {'repository': MODEL, 'revision': REVISION}
                or compat['assets'] != {'tokenizer_sha256': self.identity['tokenizer_sha256'],
                    'template_sha256': self.identity['template_sha256'],
                    'processor_sha256': self.identity['image_processor_sha256']}
                or compat['serving']['context_tokens'] != CONTEXT
                or compat['serving']['tool_parser'] != self.identity['tool_parser']):
            raise ValueError('Capability does not bind the selected identity/context')
        if (inst['identity'] != self.identity or inst['base_url'] != self.base
                or inst['serving_session_id'] != self.session or inst['gpu_deadline_utc'] != self.deadline
                or inst['server_context'] != CONTEXT or inst['isl'] != ISL
                or any(inst.get(k) is not True for k in ('vision_configured', 'native_tools_configured', 'exact_request_counter'))):
            raise ValueError('Fresh instance identity/configuration mismatch')
        if (self.deployment.get('serving_session_id') != self.session
                or self.deployment.get('identity') != self.identity
                or self.deployment.get('deadline_utc') != self.deadline
                or self.deployment.get('observed_compatibility') != inst['observed_compatibility']):
            raise ValueError('Current deployment/session/deadline mismatch')
        allocation = number(self.deployment['allocation_utc'])
        duration = self.deployment['approved_rental_seconds']
        if type(duration) is not int or duration <= 0 or allocation + duration != self.deadline:
            raise ValueError('Allocation-anchored finite rental required')
        self.cache = None
        self._check_static()

    def _check_static(self):
        if load_pin(self.live_pin) != self.live:
            raise ValueError('Live contract changed')
        for key in ('capability_receipt', 'instance_readiness_receipt', 'deployment_receipt'):
            read_pin(self.live[key])
        inst = self.instance
        now = number(self.clock())
        issued, expiry = number(inst['issued_at_utc']), number(inst['expires_at_utc'])
        if expiry != self.deadline:
            raise ValueError('Instance readiness expiry must equal allocation rental deadline')
        if not issued <= now < expiry <= self.deadline:
            raise TimeoutError('Readiness expired or rental ended')

    def _http(self, destination, method, path, body=None):
        self._check_static()
        base = self.raw if destination == 'raw' else self.qualification
        payload = None if body is None else encoded(body)
        request = Request(base + path, data=payload, method=method,
                          headers={'Content-Type': 'application/json'})
        remaining = self.deadline - self.clock()
        with build_opener(NoRedirect).open(request, timeout=min(30, remaining)) as response:
            if response.status != 200:
                raise ValueError('Serving readiness/count HTTP status differs from 200')
            raw = response.read(16 * 1024 * 1024 + 1)
        if len(raw) > 16 * 1024 * 1024:
            raise ValueError('Serving response exceeds finite control-plane limit')
        if path == '/health':
            return {'http_status': 200}  # vLLM health commonly has an empty body.
        return json.loads(raw)

    def readiness(self):
        self._check_static()
        health = self.exchange('raw', 'GET', '/health')
        if not isinstance(health, dict) or health.get('http_status') != 200:
            raise ValueError('Actual current raw health HTTP200 required')
        actual = self.exchange('qualification', 'GET', '/qualification')
        expected = {'serving_session_id': self.session, 'identity': self.identity,
                    'fingerprint': self.fingerprint, 'server_context': CONTEXT,
                    'isl': ISL, 'deadline_utc': self.deadline,
                    'observed_compatibility': self.instance['observed_compatibility']}
        if not isinstance(actual, dict) or any(actual.get(k) != v for k, v in expected.items()):
            raise ValueError('Current server/proof adapter lifetime or fingerprint changed')
        if actual.get('status') != 'ready' or actual.get('exact_request_counter') is not True:
            raise ValueError('Current proof adapter is not ready')
        self._check_static()
        return {'ready': True, 'identity': deepcopy(self.identity), 'server_context': CONTEXT,
                'isl': ISL, 'vision': True, 'native_tools': True,
                'exact_complete_request_counter': True, 'serving_session_id': self.session,
                'qualification_proof_sha256': self.fingerprint}

    def count(self, request):
        self.readiness()
        payload = tokenize_payload(request)
        key = (digest(payload), self.session, self.fingerprint)
        now = self.clock()
        reused = self.cache is not None and self.cache['key'] == key and 0 <= now-self.cache['utc'] < 2
        if not reused:
            raw = self.exchange('raw', 'POST', '/tokenize', payload)
            if (not isinstance(raw, dict) or type(raw.get('count')) is not int or raw['count'] < 0
                    or raw.get('max_model_len') != CONTEXT):
                raise ValueError('Actual raw count/context required')
            tokens = raw.get('tokens')
            if (not isinstance(tokens, list) or len(tokens) != raw['count']
                    or any(type(t) is not int or t < 0 for t in tokens)):
                raise ValueError('Actual complete token ID list required')
            self.cache = {'key': key, 'utc': now, 'count': raw['count'], 'ids': digest(tokens)}
        self.readiness()
        return {'input_tokens': self.cache['count'], 'identity': deepcopy(self.identity),
                'exact_complete_request': True, 'request_sha256': digest(request),
                'tokenize_payload_sha256': digest(payload), 'token_ids_sha256': self.cache['ids'],
                'wire_serialization': 'json-insertion-order-v1', 'serving_session_id': self.session,
                'qualification_proof_sha256': self.fingerprint,
                'counter_projection_sha256': self.projection_hash, 'reused_output_only': reused}

    def runner_count(self, messages, tools):
        return self.count(dict(model=MODEL, messages=messages, temperature=0, max_tokens=16384,
                               stream=False, tools=tools, tool_choice='auto', parallel_tool_calls=False))


def tokenize_payload(request):
    """Mirror vLLM reasoning alias without sorting nested tool-schema keys.

    Output/schema controls are absent from tokenize only under the explicit
    capability checks for prompt independence. Raw generation remains unchanged.
    """
    allowed = {'model', 'messages', 'temperature', 'max_tokens', 'stream',
               'tools', 'tool_choice', 'parallel_tool_calls', 'response_format'}
    required = {'model', 'messages', 'temperature', 'max_tokens', 'stream'}
    if not isinstance(request, dict) or not required <= set(request) or set(request)-allowed:
        raise ValueError('Unqualified generation wire fields')
    if (request['model'] != MODEL or request['temperature'] != 0 or request['stream'] is not False
            or not isinstance(request['messages'], list) or type(request['max_tokens']) is not int
            or request['max_tokens'] <= 0):
        raise ValueError('Invalid private generation request')
    if request.get('tool_choice', 'auto') not in ('auto', 'none'):
        raise ValueError('Unqualified native tool choice')
    if 'parallel_tool_calls' in request and type(request['parallel_tool_calls']) is not bool:
        raise ValueError('Invalid native parallel-tool option')
    if request.get('tools') and request.get('tool_choice') == 'none':
        raise ValueError('Unused tools must be removed from the actual payload')
    if 'response_format' in request:
        fmt = request['response_format']
        if (not isinstance(fmt, dict) or fmt.get('type') != 'json_schema'
                or not isinstance(fmt.get('json_schema'), dict)
                or fmt['json_schema'].get('strict') is not True
                or not isinstance(fmt['json_schema'].get('schema'), dict)
                or request.get('tools')):
            raise ValueError('Explicit strict tool-free extraction schema required')
    payload = {k: deepcopy(request[k]) for k in ('model', 'messages')}
    for message in payload['messages']:
        if not isinstance(message, dict):
            raise ValueError('Message objects required')
        reasoning = message.pop('reasoning_content', None)
        if reasoning is not None and message.get('reasoning') is None:
            message['reasoning'] = reasoning
    if request.get('tools'):
        payload['tools'] = deepcopy(request['tools'])
    return payload


def projection_sha256():
    import ast
    source = Path(__file__).read_text()
    node = next(x for x in ast.parse(source).body if isinstance(x, ast.FunctionDef) and x.name == 'tokenize_payload')
    return sha256(ast.get_source_segment(source, node).encode()).hexdigest()


class QwenFactories:
    """Reviewed-B06 session lifecycle, generalized for the finite saved suite."""
    def __init__(self, *, backend_class, admission, before_policy, before_formatter,
                 meter, freshness_guard, max_output_tokens=16384, request_timeout=600, turn=lambda phase: nullcontext()):
        for f in (backend_class, before_policy, before_formatter, meter, turn, freshness_guard):
            if not callable(f):
                raise ValueError('Explicit factory, guards, turn and meter required')
        if type(max_output_tokens) is not int or not 0 < max_output_tokens < CONTEXT:
            raise ValueError('Positive finite configured output cap required')
        if type(request_timeout) is not int or not 0 < request_timeout <= 600:
            raise ValueError('Request watchdog must be 1..600 seconds')
        self.backend_class, self.admission = backend_class, admission
        self.policy_guard, self.formatter_guard, self.meter, self.turn = before_policy, before_formatter, meter, turn
        self.freshness_guard = freshness_guard
        self.maximum, self.timeout = max_output_tokens, request_timeout
        self.owner = get_ident()
        self.policy_active = self.policy_finished = self.formatter_active = False
        self.formatter_calls = 0
        self.poisoned = False

    def check(self):
        if get_ident() != self.owner or self.poisoned:
            raise RuntimeError('Session changed creating thread or failed cleanup')
        self.admission.readiness()

    def backend(self, phase, directory=None):
        self.check()
        remaining = self.admission.deadline-self.admission.clock()
        import httpx
        probe={'model':'å','tools':[{'z':1,'a':2}]}
        if httpx.Request('POST','http://127.0.0.1/',json=probe).content != encoded(probe):
            raise ValueError('Installed httpx JSON encoder differs from ordered counter wire')
        raw = self.backend_class(self.admission.base, MODEL, None,
            timeout=min(self.timeout, remaining), max_tokens=self.maximum,
            supports_images=True, session_routing=False, request_options={})
        return QwenBackend(self, raw, phase, directory)

    @contextmanager
    def policy_session(self, *, before_dispatch):
        if self.policy_active or self.policy_finished or not callable(before_dispatch):
            raise RuntimeError('One policy session per case required')
        b = self.backend('policy')
        self.policy_active = True
        b.consumer_guard = before_dispatch
        try:
            yield b
        finally:
            try:
                b.close()
            finally:
                self.policy_active = False
                self.policy_finished = b.closed_successfully

    def extraction_backend_factory(self, output_directory):
        if self.policy_active or not self.policy_finished or self.formatter_active:
            raise RuntimeError('Extraction requires closed policy and independent session')
        b = self.backend('formatter', Path(output_directory))
        self.formatter_active = True
        return b


class QwenBackend:
    supports_background_completion = False
    supports_native_tools = True
    supports_images = True
    requires_browser_thread = True

    def __init__(self, factory, raw, phase, directory):
        self.factory, self.raw, self.phase, self.directory = factory, raw, phase, directory
        self.model, self.base_url = MODEL, factory.admission.base
        self.closed = self.closed_successfully = False
        self.consumer_guard = lambda: None
        self.request_options = raw.request_options

    def configure_tools(self, options):
        if self.phase != 'policy' or self.closed:
            raise RuntimeError('Formatter must remain tool-free')
        self.raw.configure_tools(options)

    def begin_episode(self, episode_id):
        return self.raw.begin_episode(episode_id)

    @property
    def last_request(self):
        return self.raw.last_request

    def complete(self, messages):
        if self.closed:
            raise RuntimeError('Closed Qwen backend')
        f = self.factory
        f.check()
        options = deepcopy(self.raw.request_options)
        if self.phase == 'formatter':
            if f.formatter_calls:
                raise RuntimeError('One formatter dispatch maximum; no retries')
            if options:
                raise ValueError('Formatter cannot inherit tools/provider/session options')
            if self.directory.name != 'transport':
                raise ValueError('Exact saved-consumer transport directory required')
            schema_path = self.directory.parent/'extraction'/'schema.json'
            if schema_path.is_symlink() or not schema_path.is_file():
                raise ValueError('Caller-written exact extraction schema is missing')
            schema_bytes = schema_path.read_bytes()
            schema = json.loads(schema_bytes)
            if not isinstance(schema, dict):
                raise ValueError('Extraction schema must be an object')
            options = {'response_format': {'type': 'json_schema', 'json_schema': {
                'name': 'answer', 'strict': True, 'schema': schema}}}
        elif set(options)-{'tools', 'tool_choice', 'parallel_tool_calls'}:
            raise ValueError('Unknown policy request option')
        selected = deepcopy(messages)
        request = dict(model=MODEL, messages=selected, temperature=0,
                       max_tokens=f.maximum, stream=False, **options)
        # Permit is acquired before counting/generation. No counter, guard,
        # history or action thread is silently moved to background execution.
        with f.turn(self.phase):
            f.check()
            f.freshness_guard(self.phase)
            first = f.admission.count(request)
            self._receipt(first, request)
            n = first['input_tokens']
            if type(n) is not int or not 0 <= n <= ISL or n >= CONTEXT:
                raise ValueError('Complete input exceeds 250000/context; no dispatch')
            request['max_tokens'] = min(f.maximum, CONTEXT-n)
            final = f.admission.count(request)
            self._receipt(final, request)
            if final['input_tokens'] != n or final['request_sha256'] != digest(request):
                raise ValueError('Count/generation full ordered request mismatch')
            if self.phase == 'formatter' and schema_path.read_bytes() != schema_bytes:
                raise ValueError('Extraction schema changed during admission')
            self.raw.max_tokens = request['max_tokens']
            self.raw.request_options = deepcopy(options)
            f.meter({'event': 'admission', 'phase': self.phase, 'count': final,
                     'max_tokens': request['max_tokens']})
            f.check()
            self.consumer_guard()
            (f.policy_guard if self.phase == 'policy' else f.formatter_guard)()
            if self.phase == 'formatter':
                f.formatter_calls += 1  # A failed paid call cannot be replayed.
            if hasattr(self.raw,'client'):
                hooks=self.raw.client.event_hooks
                originals=list(hooks.get('request',[]))
                def counted_wire(http_request):
                    if http_request.content!=encoded(request):raise ValueError('Actual HTTP bytes differ from ordered counted wire; no dispatch')
                    for callback in originals:callback(http_request)
                hooks['request']=[counted_wire]
            if hasattr(self.raw,'client'):self.raw.client.timeout=min(f.timeout,f.admission.deadline-f.admission.clock())
            try:result = self.raw.complete(selected)
            finally:
                if hasattr(self.raw,'client'):hooks['request']=originals
            if encoded(result.request) != encoded(request):
                raise RuntimeError('Actual generation wire differs from counted ordered request')
            f.meter({'event': 'response', 'phase': self.phase, 'raw': deepcopy(result.raw),
                     'request_sha256': digest(result.request)})
            usage=result.raw.get('usage') if isinstance(result.raw,dict) else None
            if not isinstance(usage,dict) or type(usage.get('prompt_tokens')) is not int or usage['prompt_tokens']!=n:
                raise ValueError('Live generation usage differs from exact complete input count; paid response preserved')
            return result

    def _receipt(self, receipt, request):
        if (not isinstance(receipt, dict) or receipt.get('identity') != self.factory.admission.identity
                or receipt.get('exact_complete_request') is not True
                or receipt.get('serving_session_id') != self.factory.admission.session
                or receipt.get('request_sha256') != digest(request)):
            raise ValueError('Exact current-session request/identity count receipt required')

    def close(self):
        if self.closed:
            if not self.closed_successfully:
                raise RuntimeError('Previous cleanup failure; no retry')
            return
        self.closed = True
        try:
            self.raw.close()
        except BaseException:
            self.factory.poisoned = True
            raise
        self.closed_successfully = True
        if self.phase == 'formatter':
            self.factory.formatter_active = False
