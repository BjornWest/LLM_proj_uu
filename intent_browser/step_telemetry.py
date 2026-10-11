"""Opt-in, immediately flushed native step diagnostics; never replay or abort.

Hooks are instance-local and scoped to one existing env.step. No extra browser
requests, payload logging, background thread or process signals are involved.
"""
from contextlib import contextmanager
from functools import wraps
from importlib.metadata import version
import json
import os
from pathlib import Path
import threading
import time
from types import FunctionType, MethodType


VERSION = 'native-env-step-telemetry-v1'
ARTIFACT = 'env-step-telemetry.jsonl'
_MISSING = object()
_PHASE_METHODS = ('pre_step', 'post_step', '_wait_dom_loaded',
                  '_active_page_check', '_wait_for_user_message',
                  '_task_validate', '_get_obs')


def resolve_step_telemetry(value=None):
    if value is None:
        raw = os.environ.get('HARNESS_ENV_STEP_TELEMETRY', '0')
        if raw not in ('0', '1'):
            raise ValueError('HARNESS_ENV_STEP_TELEMETRY must be 0 or 1')
        return raw == '1'
    if type(value) is not bool:
        raise ValueError('env_step_telemetry must be boolean or None')
    return value


def _label(value):
    # Only protocol names, never request values, URL, expression or exception text.
    if isinstance(value, str) and 0 < len(value) <= 100 and all(
            c.isascii() and (c.isalnum() or c in '._-') for c in value):
        return value
    return 'unknown'


class EnvStepTelemetry:
    def __init__(self, directory, *, max_records=20000, max_bytes=4 * 1024 * 1024):
        if type(max_records) is not int or not 2 <= max_records <= 200000:
            raise ValueError('Invalid step telemetry record cap')
        if type(max_bytes) is not int or not 1024 <= max_bytes <= 16 * 1024 * 1024:
            raise ValueError('Invalid step telemetry byte cap')
        if version('browsergym-core') != '0.14.3' or version('playwright') != '1.44.0':
            raise ValueError('Step telemetry requires reviewed BrowserGym 0.14.3 / Playwright 1.44.0')
        self.owner_thread = threading.get_ident()
        self.origin = time.monotonic()
        self.stream = (Path(directory) / ARTIFACT).open('x', encoding='utf-8')
        self.max_records, self.max_bytes = max_records, max_bytes
        self.records = self.bytes = self.next_id = 0
        self.limited = False
        self.write_error = None
        self.active = False
        self.closed = False
        self.stack = []
        self.pending = {}
        self.step_index = None
        self.tool = None

    def describe(self):
        return {'enabled': True, 'version': VERSION, 'artifact': ARTIFACT,
                'max_records': self.max_records, 'max_bytes': self.max_bytes,
                'limited': self.limited, 'write_error_type': self.write_error,
                'scope': 'env.step only; flushed starts before waits; no deadlines, extra RPCs or policy data'}

    def _emit(self, event, **fields):
        if self.closed or self.limited or self.write_error:
            return
        row = {'version': VERSION, 'event': event,
               'seconds': time.monotonic() - self.origin,
               'step': self.step_index, 'tool': self.tool, **fields}
        raw = json.dumps(row, ensure_ascii=True, separators=(',', ':')) + '\n'
        # Reserve space and one record for an explicit cap marker.
        charge = len(raw.encode('utf-8'))
        if self.records >= self.max_records - 1 or self.bytes + charge > self.max_bytes - 512:
            self.limited = True
            raw = json.dumps({'version': VERSION, 'event': 'telemetry_limit',
                'seconds': row['seconds'], 'step': self.step_index,
                'records': self.records, 'bytes': self.bytes}, separators=(',', ':')) + '\n'
            charge = len(raw.encode('utf-8'))
        try:
            self.stream.write(raw)
            self.stream.flush()  # Survives an outer process timeout; no fsync or background backlog.
            self.records += 1
            self.bytes += charge
        except OSError as exc:
            # Diagnostic I/O must not turn a committed browser action into an error.
            self.write_error = _label(type(exc).__name__)

    def _id(self):
        self.next_id += 1
        return self.next_id

    @contextmanager
    def _phase(self, name):
        token = self._id()
        parent = self.stack[-1] if self.stack else None
        self._emit('phase_started', phase=name, phase_id=token, parent_phase_id=parent)
        self.stack.append(token)
        error = None
        try:
            yield
        except BaseException as exc:
            error = _label(type(exc).__name__)
            raise
        finally:
            self.stack.pop()
            self._emit('phase_finished', phase=name, phase_id=token, error_type=error)

    def _wrap(self, name, callback):
        @wraps(callback)
        def wrapped(*args, **kwargs):
            with self._phase(name):
                return callback(*args, **kwargs)
        return wrapped

    @contextmanager
    def observe(self, env, *, step, tool):
        if self.closed or self.active or threading.get_ident() != self.owner_thread:
            raise ValueError('Step telemetry requires an open, nonnested owner-thread scope')
        from browsergym.core.env import BrowserEnv
        page = getattr(env, 'page', None)
        connection = getattr(getattr(page, '_impl_obj', None), '_connection', None)
        # Refuse unsupported connection shapes before dispatch, never load another browser.
        if connection is None or not callable(getattr(connection, '_send_message_to_server', None)):
            raise ValueError('Step telemetry requires the existing Playwright connection')
        if getattr(connection, '_intent_step_telemetry_owner', None) is not None:
            raise ValueError('Step telemetry connection already has an active owner')
        saved = []
        self.active = True
        self.step_index, self.tool = step, _label(tool)
        self.pending = {}

        def replace(obj, name, value):
            previous = vars(obj).get(name, _MISSING)
            setattr(obj, name, value)
            saved.append((obj, name, previous, value))

        def send(obj, method, params, no_reply=False):
            token = self._id()
            detail = {'rpc_id': token, 'method': _label(method),
                      'channel_type': _label(getattr(obj, '_type', 'unknown')),
                      'phase_id': self.stack[-1] if self.stack else None,
                      'no_reply': bool(no_reply)}
            if method == 'send' and isinstance(params, dict):
                detail['cdp_method'] = _label(params.get('method'))
            self.pending[token] = detail
            self._emit('rpc_started', **detail)
            try:
                callback = original_send(obj, method, params, no_reply)
            except BaseException as exc:
                self.pending.pop(token, None)
                self._emit('rpc_finished', **detail, error_type=_label(type(exc).__name__))
                raise

            def finished(future):
                if not self.active or token not in self.pending:
                    return
                self.pending.pop(token, None)
                error = 'CancelledError' if future.cancelled() else None
                if not error:
                    failure = future.exception()
                    if failure is not None:
                        error = _label(type(failure).__name__)
                self._emit('rpc_finished', **detail, error_type=error)
            callback.future.add_done_callback(finished)
            return callback

        try:
            original_send = connection._send_message_to_server
            replace(connection, '_intent_step_telemetry_owner', self)
            replace(connection, '_send_message_to_server', send)
            for name in _PHASE_METHODS:
                callback = getattr(env, name, None)
                if callable(callback):
                    replace(env, name, self._wrap(name, callback))
            # Clone only the native step's globals for this instance, preserving
            # the original code/closure and execute function. Never patch a package global.
            original_step = env.step
            if getattr(original_step, '__func__', None) is BrowserEnv.step:
                original = original_step.__func__
                scope = dict(original.__globals__)
                scope['execute_python_code'] = self._wrap('action_execution', scope['execute_python_code'])
                clone = FunctionType(original.__code__, scope, original.__name__,
                                     original.__defaults__, original.__closure__)
                clone.__kwdefaults__ = original.__kwdefaults__
                replace(env, 'step', MethodType(clone, env))
            else:
                self._emit('execution_boundary_unavailable', reason='non_native_step_wrapper')
            with self._phase('env_step'):
                yield
        finally:
            self._emit('step_scope_finished', pending_rpc_ids=list(self.pending)[:100],
                       pending_rpc_count=len(self.pending))
            self.active = False
            for obj, name, previous, installed in reversed(saved):
                if vars(obj).get(name, _MISSING) is not installed:
                    self._emit('hook_changed', hook=name)
                    continue  # Preserve a newer owner rather than overwriting it.
                if previous is _MISSING:
                    delattr(obj, name)
                else:
                    setattr(obj, name, previous)
            self.pending.clear()

    def close(self):
        if self.closed:
            return
        try:
            self.stream.close()
        except OSError as exc:
            self.write_error = _label(type(exc).__name__)
        self.closed = True
