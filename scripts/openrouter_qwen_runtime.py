"""Hosted Qwen admission using local estimates, never a serving parity claim."""
from copy import deepcopy
from contextlib import contextmanager
import json
import math
from pathlib import Path
import signal
import threading
import time

MODEL = 'qwen/qwen3.8-27b'
CONTEXT = 262144
INPUT_LIMIT = 150000
HOSTED_REQUEST_MAX_SECONDS = 180


def validate_limits(spec):
    if type(spec.get('formatter_quote_pair_schema', False)) is not bool:
        raise ValueError('Explicit boolean formatter quote-pair schema option required')
    finite = spec.get('hosted_limit_profile') == 'finite-task-limits-v1'
    if spec.get('hosted_limit_profile') not in (None, 'finite-task-limits-v1'):
        raise ValueError('Unknown hosted limit profile')
    if finite:
        if (type(spec.get('max_steps')) is not int or not 1 <= spec['max_steps'] <= 200
                or type(spec.get('max_input_tokens')) is not int
                or not 1 <= spec['max_input_tokens'] <= INPUT_LIMIT
                or spec.get('episode_timeout', 'missing') is not None
                or spec.get('server_context_tokens') != CONTEXT):
            raise ValueError('Explicit finite task/input limits and native context required')
    elif ('max_steps' not in spec or 'episode_timeout' not in spec
            or spec['max_steps'] is not None or spec['episode_timeout'] is not None
            or spec.get('max_input_tokens') != INPUT_LIMIT
            or spec.get('server_context_tokens') != CONTEXT):
        raise ValueError('Hosted Qwen requires explicit native context and no turn/episode ceiling')
    for key, maximum in (('max_tokens', 65536), ('request_timeout', HOSTED_REQUEST_MAX_SECONDS),
                         ('startup_timeout', 900), ('suite_timeout', 2**31-1)):
        value = spec.get(key)
        if type(value) is not int or not 0 < value <= maximum:
            raise ValueError('Positive finite hosted Qwen '+key+' required')
    if spec.get('runtime_limits') is not None:
        raise ValueError('Hosted inference must not emulate a GPU capacity controller')
    if not spec.get('shared_tokenizer') or not spec.get('shared_chromium'):
        raise ValueError('Hosted Qwen requires the qualified shared harness')
    for case in spec['cases']:
        limit = case.get('max_input_tokens')
        steps = case.get('max_steps')
        if finite and (type(limit) is not int or not 1 <= limit <= spec['max_input_tokens']
                or type(steps) is not int or not 1 <= steps <= spec['max_steps']):
            raise ValueError('Finite per-case input/turn limits required')
        if (case.get('policy_model') != MODEL or (not finite and limit != INPUT_LIMIT)
                or case.get('id') != 'qwen-'+case.get('task_id', '')):
            raise ValueError('Exact hosted Qwen model, task identity and input limit required')


class HostedRequestDeadline(KeyboardInterrupt):
    """Must bypass optional recording's ordinary Exception fallback/replay."""


def coherent_claim_schema(schema):
    """Refine nullable claim pairs on the wire; preserve all native constraints.

    This is structural decoding only. It neither checks meaning nor repairs a
    returned claim. Other objects and existing composite schemas stay intact.
    """
    def visit(value):
        if not isinstance(value, dict):
            return deepcopy(value)
        node = deepcopy(value)
        # Only traverse schema locations, never instance data such as enum,
        # const, default or examples.
        for key in ('properties', 'patternProperties', '$defs', 'definitions', 'dependentSchemas'):
            if isinstance(node.get(key), dict):
                node[key] = {name: visit(item) for name, item in node[key].items()}
        for key in ('items', 'additionalProperties', 'additionalItems', 'contains',
                    'propertyNames', 'not', 'if', 'then', 'else', 'unevaluatedProperties',
                    'unevaluatedItems', 'contentSchema'):
            if isinstance(node.get(key), dict):
                node[key] = visit(node[key])
            elif key == 'items' and isinstance(node.get(key), list):
                node[key] = [visit(item) for item in node[key]]
        for key in ('allOf', 'anyOf', 'oneOf', 'prefixItems'):
            if isinstance(node.get(key), list):
                node[key] = [visit(item) for item in node[key]]
        properties = node.get('properties', {})
        if (node.get('type') != 'object' or set(properties) != {'value', 'evidence'}
                or set(node.get('required', [])) != {'value', 'evidence'}
                or node.get('additionalProperties') is not False
                or any(key in node for key in ('anyOf', 'oneOf', 'allOf', 'not', 'if'))):
            return node
        fields = [properties['value'], properties['evidence']]
        if any(not isinstance(field, dict) or not isinstance(field.get('type'), list)
               or 'null' not in field['type'] for field in fields):
            return node
        if set(fields[1]['type']) != {'string', 'null'}:
            return node
        from jsonschema.validators import validator_for
        branches = []
        from referencing.exceptions import Unresolvable
        try:
            nullable = all(validator_for(field)(field).is_valid(None) for field in fields)
        except Unresolvable as exc:
            raise ValueError('Quote-pair schema cannot resolve field-local references; no dispatch') from exc
        if nullable:
            branches.append({'type': 'object', 'properties': {
                'value': {'type': 'null'}, 'evidence': {'type': 'null'}},
                'required': ['value', 'evidence'], 'additionalProperties': False})
        nonnull = deepcopy(properties)
        possible = True
        for field in nonnull.values():
            types = [kind for kind in field['type'] if kind != 'null']
            possible = possible and bool(types)
            field['type'] = types[0] if len(types) == 1 else types
            if 'enum' in field:
                field['enum'] = [item for item in field['enum'] if item is not None]
                possible = possible and bool(field['enum'])
        if possible:
            branches.append({'type': 'object', 'properties': nonnull,
                'required': ['value', 'evidence'], 'additionalProperties': False})
        # Keep the original properties/enum/ranges beside the new conjunction;
        # these branches must never admit something the native schema rejects.
        if branches:
            node['anyOf'] = branches
        else:
            node['not'] = {}  # No coherent pair satisfies the original fields.
        return node
    return visit(deepcopy(schema))


@contextmanager
def request_watchdog(seconds):
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError('Hosted request watchdog requires the browser/main thread')
    previous = signal.getsignal(signal.SIGALRM)
    timer = signal.getitimer(signal.ITIMER_REAL)
    started = time.monotonic()
    def expired(*_):
        signal.setitimer(signal.ITIMER_REAL, 0)
        raise HostedRequestDeadline('Hosted request total-duration watchdog expired')
    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, min(seconds, timer[0]) if timer[0] else seconds)
    try:
        yield
    finally:
        # A cohort termination can intentionally install SIG_IGN during cleanup.
        if signal.getsignal(signal.SIGALRM) is expired:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous)
            if timer[0]:
                signal.setitimer(signal.ITIMER_REAL, max(.001, timer[0]-(time.monotonic()-started)), timer[1])


class MemoizedCounter:
    """Reuse the runner's same-request measurement; preserve wire key order."""
    def __init__(self, counter):
        self.counter, self.key, self.value = counter, None, None

    def __call__(self, messages, tools):
        key = json.dumps([messages, tools], ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        if key != self.key:
            self.value = self.counter(messages, tools)
            self.key = key
        return deepcopy(self.value)

    def observe_completion(self, request, response):
        self.key = self.value = None
        observer = getattr(self.counter, 'observe_completion', None)
        if callable(observer):
            observer(request, response)


class HostedQwenBackend:
    """Count before every dispatch; keep provider usage authoritative.

    The official local counter covers messages, retained reasoning, images and
    tools. A formatter's wire schema adds a separately labelled conservative
    local estimate, because hosted schema injection is not observable locally.
    No exact parity, extra completion or automatic retry is inferred.
    """
    supports_background_completion = False
    supports_native_tools = True
    supports_images = True
    requires_browser_thread = True

    def __init__(self, raw, counter, *, phase, maximum, deadline, timeout,
                 directory=None, meter=lambda row: None, clock=time.time,
                 quote_pair_schema=False, input_limit=INPUT_LIMIT):
        if raw.model != MODEL or raw.base_url != 'https://openrouter.ai/api/v1':
            raise ValueError('Exact OpenRouter Qwen backend required')
        if phase not in ('policy', 'formatter'):
            raise ValueError('Unknown hosted Qwen phase')
        if type(quote_pair_schema) is not bool or (quote_pair_schema and phase != 'formatter'):
            raise ValueError('Quote-pair schema is a boolean formatter-only option')
        if (type(maximum) is not int or not 0 < maximum <= 65536
                or type(timeout) is not int or not 0 < timeout <= HOSTED_REQUEST_MAX_SECONDS
                or type(deadline) not in (int, float) or not math.isfinite(deadline)
                or deadline <= clock()):
            raise ValueError('Bounded output/request and future suite deadline required')
        if type(input_limit) is not int or not 1 <= input_limit <= INPUT_LIMIT:
            raise ValueError('Hosted input limit must be an integer within 150000')
        self.input_limit = input_limit
        self.raw, self.counter = raw, counter
        self.phase, self.maximum = phase, maximum
        self.deadline, self.timeout, self.clock = deadline, timeout, clock
        self.directory = None if directory is None else Path(directory)
        self.meter, self.closed, self.dispatched = meter, False, False
        self.quote_pair_schema = quote_pair_schema
        self.model, self.base_url = raw.model, raw.base_url

    @property
    def request_options(self):
        return self.raw.request_options

    @request_options.setter
    def request_options(self, value):
        if self.closed or self.dispatched or type(value) is not dict:
            raise ValueError('Open formatter options required before dispatch')
        self.raw.request_options = deepcopy(value)

    @property
    def last_request(self):
        return self.raw.last_request

    def configure_tools(self, options):
        if self.phase != 'policy' or self.closed:
            raise ValueError('Formatter is tool-free')
        self.raw.configure_tools(options)

    def begin_episode(self, episode_id):
        return self.raw.begin_episode(episode_id)

    def complete(self, messages):
        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError('Hosted request watchdog requires the browser/main thread')
        return self._complete(messages)

    def _complete(self, messages):
        if self.closed or (self.phase == 'formatter' and self.dispatched):
            raise RuntimeError('Closed or already-dispatched hosted formatter; no retry')
        schema_path = schema_bytes = None
        if self.phase == 'formatter':
            if self.directory is None or self.directory.name != 'transport':
                raise ValueError('Exact saved-consumer formatter transport required')
            if any(k in self.raw.request_options for k in ('tools', 'tool_choice', 'parallel_tool_calls')):
                raise ValueError('Formatter must remain tool-free')
            schema_path = self.directory.parent/'extraction'/'schema.json'
            if schema_path.is_symlink() or not schema_path.is_file():
                raise ValueError('Missing exact extractor schema')
            schema_bytes = schema_path.read_bytes()
            schema = json.loads(schema_bytes)
            if type(schema) is not dict:
                raise ValueError('Extractor schema must be an object')
            if self.quote_pair_schema:
                schema = coherent_claim_schema(schema)
                if self.directory.is_symlink():
                    raise ValueError('Formatter transport must not be a symlink')
            self.raw.request_options['response_format'] = {'type': 'json_schema',
                'json_schema': {'name': 'answer', 'strict': True, 'schema': schema}}
        selected = deepcopy(messages)
        measured = self.counter(selected, self.raw.request_options.get('tools', []))
        tokens = measured.get('input_tokens')
        schema_tokens = 0
        if schema_path is not None:
            extra = self.counter([{'role': 'user', 'content': json.dumps(
                self.raw.request_options['response_format'], ensure_ascii=False)}], [])
            schema_tokens = extra.get('input_tokens')
        if (type(tokens) is not int or tokens < 0 or type(schema_tokens) is not int
                or schema_tokens < 0):
            raise ValueError('Invalid model-matched complete-input estimate')
        tokens += schema_tokens
        if tokens > self.input_limit or tokens >= CONTEXT:
            raise ValueError(f'Hosted complete input exceeds {self.input_limit}/context; no dispatch')
        remaining = self.deadline-self.clock()
        if remaining <= 0:
            raise TimeoutError('Suite deadline elapsed; no dispatch')
        self.raw.max_tokens = min(self.maximum, CONTEXT-tokens)
        self.raw.client.timeout = min(self.timeout, remaining)
        if schema_path is not None and schema_path.read_bytes() != schema_bytes:
            raise ValueError('Extractor schema changed during admission')
        self.meter({'event': 'hosted_input_admission', 'phase': self.phase,
            'estimated_complete_input_tokens': tokens, 'formatter_schema_bound_tokens': schema_tokens,
            'max_tokens': self.raw.max_tokens, 'counter': measured,
            'scope': 'Official local estimate; hosted processing may differ; provider usage authoritative'})
        if self.phase == 'formatter' and self.quote_pair_schema:
            self.directory.mkdir(parents=True, exist_ok=True)
            with (self.directory/'response-format-schema.json').open('x') as stream:
                json.dump(schema, stream, ensure_ascii=False, indent=2, allow_nan=False)
        self.dispatched = True
        completion=self._request(selected,min(self.timeout,remaining))
        # Policy usage observation belongs to the runner, once, on this same
        # counter instance. A one-shot formatter has no following request.
        return completion

    def _request(self, messages, seconds):
        with request_watchdog(seconds):return self.raw.complete(messages)

    def close(self):
        self.closed = True
        self.raw.close()


class BackgroundHostedQwenBackend(HostedQwenBackend):
    """Owner-created hosted backend with a thread-safe total request deadline.

    The pipeline completion worker waits on one HTTP operation. On deadline it
    closes only that transport, with bounded cleanup observation. A transport
    that cannot stop is poisoned and close refuses to certify its cleanup; the
    caller must retain/quarantine that case. If a transport returns a late reply,
    retain it without action execution; a real socket abort can instead lose the
    reply and end with a read error, leaving remote usage unknown. No retries.
    """
    supports_background_completion=True
    supports_native_tools=True
    supports_images=True
    requires_browser_thread=False

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.owner=threading.get_ident()
        self.operation_lock=threading.Lock()
        self.request_thread=self.abort_thread=None
        self.poisoned=False
        self.interrupted_completion=None
        self.interrupted_error=None
        self.abort_error=None

    def complete(self,messages):
        if self.poisoned:raise RuntimeError('Previous hosted request cleanup uncertain; no retry')
        if not self.operation_lock.acquire(blocking=False):
            raise RuntimeError('Overlapping hosted request; no dispatch')
        try:return self._complete(messages)
        finally:self.operation_lock.release()

    def _request(self,messages,seconds):
        # Admission logging/schema writes may consume the remaining suite time.
        # Recheck immediately before starting HTTP, without reading the browser.
        seconds=min(seconds,self.deadline-self.clock())
        if seconds<=0:raise TimeoutError('Suite deadline elapsed; no dispatch')
        self.raw.client.timeout=seconds
        cutoff=time.monotonic()+seconds
        done=threading.Event();outcome={}
        def call():
            try:outcome['completion']=self.raw.complete(messages)
            except BaseException as error:outcome['error']=error
            finally:
                outcome['finished_at']=time.monotonic()
                if self.poisoned and 'completion' in outcome:
                    self.interrupted_completion=outcome['completion']
                if self.poisoned and 'error' in outcome:
                    self.interrupted_error=outcome['error']
                done.set()
        self.request_thread=threading.Thread(target=call,name='hosted-qwen-http',daemon=True)
        self.request_thread.start()
        timely=done.wait(max(0,cutoff-time.monotonic()))
        if not timely or outcome.get('finished_at',float('inf'))>cutoff:
            self.poisoned=True
            def abort():
                try:self.raw.close()
                except BaseException as error:self.abort_error=error
            self.abort_thread=threading.Thread(target=abort,name='hosted-qwen-abort',daemon=True)
            self.abort_thread.start()
            self.abort_thread.join(1)
            self.request_thread.join(1)
            if 'completion'in outcome:self.interrupted_completion=outcome['completion']
            error=HostedRequestDeadline('Hosted total request deadline expired; no retry or action')
            error.add_note('Transport cleanup remains unverified until request/abort workers stop.')
            if self.abort_error is not None:error.add_note('Transport close also failed: '+repr(self.abort_error))
            raise error
        if 'error'in outcome:raise outcome['error']
        return outcome['completion']

    def close(self):
        if threading.get_ident()!=self.owner:
            raise RuntimeError('Only the creating owner may close a hosted backend')
        if not self.operation_lock.acquire(blocking=False):
            raise RuntimeError('Hosted completion still running; cleanup unverified')
        try:
            if any(worker is not None and worker.is_alive() for worker in (self.request_thread,self.abort_thread)):
                raise RuntimeError('Hosted HTTP/abort worker still live; cleanup unverified')
            if self.abort_error is not None:raise RuntimeError('Hosted transport cleanup failed') from self.abort_error
            self.raw.close()
            self.closed=True
        finally:self.operation_lock.release()

    @contextmanager
    def _owner_configuration(self):
        if threading.get_ident()!=self.owner or self.poisoned:
            raise RuntimeError('Hosted configuration requires its healthy creating owner')
        if not self.operation_lock.acquire(blocking=False):
            raise RuntimeError('Hosted request running; configuration rejected')
        try:yield
        finally:self.operation_lock.release()

    @HostedQwenBackend.request_options.setter
    def request_options(self,value):
        with self._owner_configuration():
            HostedQwenBackend.request_options.fset(self,value)

    def configure_tools(self,options):
        with self._owner_configuration():super().configure_tools(options)

    def begin_episode(self,episode_id):
        with self._owner_configuration():return super().begin_episode(episode_id)
