"""Drop-in Backend running Pi's Codex transport in a tool-free child process."""
from copy import deepcopy
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import uuid

from intent_browser.backend import Completion, BackendResponseError
from .protocol import request_body, completion, digest

ROOT = Path(__file__).resolve().parents[2]


def save(path, value):
    with Path(path).open('x', encoding='utf8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)


class ExternalAgentBackend:
    supports_native_tools = True
    supports_images = True
    # Separate experiment: no claim of background inference/capture acceptance.
    supports_background_completion = False

    def __init__(self, model, artifacts, *, reasoning_effort='medium', max_tokens=16384,
                 timeout=180, pi_cli=None, command=None, lock_path=None, before_dispatch=None,
                 provider_output_limit=False):
        self.model, self.reasoning_effort = model, reasoning_effort
        self.max_tokens, self.timeout = max_tokens, timeout
        self.artifacts = Path(artifacts).resolve()
        self.artifacts.mkdir(parents=True, exist_ok=False)
        self.pi_cli = pi_cli or shutil.which('pi')
        if not self.pi_cli:
            raise ValueError('Pi must be installed and logged in separately')
        self.command = command or [shutil.which('node') or 'node', str(Path(__file__).with_name('worker.mjs'))]
        self.request_options = {}
        self.session_id = None
        self.replay = {}
        self.sequence = 0
        self.last_request = None
        self.failed = False
        self.before_dispatch = before_dispatch
        self.provider_output_limit = provider_output_limit
        self.mutex = threading.Lock()
        self._lease = None
        self.lock_path = Path(lock_path or ROOT / '.local/external-agent/subscription.lock')

    def configure_tools(self, options):
        if not {'tools', 'tool_choice'} <= set(options) or set(options) - {'tools', 'tool_choice', 'parallel_tool_calls'}:
            raise ValueError('Unexpected native tool configuration')
        # Tool updates belong to the harness, including screenshot/data tools.
        self.request_options = deepcopy(options)

    def begin_episode(self, episode_id):
        if self.session_id is not None:
            raise ValueError('Use a fresh external backend for each episode')
        if not isinstance(episode_id, str) or not episode_id:
            raise ValueError('Missing episode identity')
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._lease = self.lock_path.open('a')
        try:
            fcntl.flock(self._lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self._lease.close(); self._lease = None
            raise ValueError('Another external subscription episode is active') from None
        self.session_id = episode_id
        return {'session_id': episode_id, 'requested_model': self.model,
                'provider': 'openai-codex', 'transport': 'external-pi-v1',
                'billing': 'subscription', 'concurrency': 1}

    def complete(self, messages):
        if not self.mutex.acquire(blocking=False):
            raise ValueError('Concurrent completion calls are forbidden')
        try:
            return self._complete(messages)
        finally:
            self.mutex.release()

    def complete_request(self, request):
        """HTTP facade: preserve the ordinary harness request exactly."""
        if not self.mutex.acquire(blocking=False):
            raise ValueError('Concurrent completion calls are forbidden')
        try:
            if request.get('model') != self.model:
                raise ValueError('Request model differs from the declared bridge model')
            if request.get('session_id', self.session_id) != self.session_id:
                raise ValueError('This bridge serves one declared episode')
            return self._complete(None, incoming=request)
        finally:
            self.mutex.release()

    def _complete(self, messages, incoming=None):
        self.last_request = None
        if self.failed or not self.session_id or self._lease is None:
            raise ValueError('Fresh active episode required; failed calls are not retried')
        request = deepcopy(incoming) if incoming is not None else {'model': self.model, 'messages': deepcopy(messages), 'temperature': 0,
                   'max_tokens': self.max_tokens, 'stream': False, 'session_id': self.session_id,
                   **deepcopy(self.request_options)}
        payload = request_body(request, replay=self.replay, reasoning_effort=self.reasoning_effort,
                               provider_output_limit=self.provider_output_limit)
        payload.setdefault('prompt_cache_key', self.session_id)
        self.sequence += 1
        directory = self.artifacts / f'{self.sequence:04d}'
        directory.mkdir()
        request_id = str(uuid.uuid4())
        save(directory / 'harness-request.json', request)
        save(directory / 'mapping.json', {
            'version': 1, 'harness_request_sha256': digest(request),
            'responses_payload_sha256': digest(payload), 'added_policy_instructions': False,
            'external_tools': [], 'messages_order_preserved': True,
            'generation_differences': ['Responses streaming transport',
                'temperature omitted: Codex reasoning endpoint',
                'reasoning effort is explicit; cross-model reasoning is not identical'],
            'output_cap': {'requested_by_harness': request.get('max_tokens'),
                           'effective_mode': 'provider_default' if self.provider_output_limit else 'explicit',
                           'sent_max_output_tokens': payload.get('max_output_tokens'),
                           'explicit_operator_override': self.provider_output_limit},
        })
        self.last_request = request
        envelope = {'version': 1, 'id': request_id, 'payload': payload,
                    'artifact_dir': str(directory), 'pi_cli': str(self.pi_cli),
                    'timeout_ms': int(self.timeout * 1000)}
        # No workspace cwd, Pi settings, or shell parsing; input only over stdin.
        env = {key: value for key, value in os.environ.items() if key in
               ('PATH', 'HOME', 'USER', 'LANG', 'SYSTEMROOT', 'TMPDIR')}
        try:
            if self.before_dispatch is not None:
                self.before_dispatch()
            process = subprocess.run(self.command, input=json.dumps(envelope), capture_output=True,
                                     text=True, timeout=self.timeout + 10, cwd=directory, env=env)
            # Raw transport is already saved by the worker, including partial SSE.
            result = json.loads(process.stdout)
            if result.get('version') != 1 or result.get('id') != request_id:
                raise ValueError('Worker response identity mismatch')
            save(directory / 'bridge-result.json', result)
            if process.returncode or not result.get('ok') or result.get('sends') != 1:
                raise BackendResponseError('External model transport failed; see ' + str(directory),
                                           request, result, http_status=result.get('http_status'))
            raw = completion(result['response'])
            if result.get('output_source') == 'completed_stream_items':
                raw['external_bridge']['raw_response'] = deepcopy(result['raw_terminal'])
                raw['external_bridge']['output_source'] = 'completed_stream_items'
                raw['external_bridge']['assembled_response'] = deepcopy(result['response'])
            raw['external_bridge']['artifact_directory'] = str(directory)
            raw['external_bridge']['responses_request_sha256'] = digest(payload)
            raw['external_bridge']['output_cap'] = {'requested_by_harness': request.get('max_tokens'),
                'sent_max_output_tokens': payload.get('max_output_tokens'),
                'effective_mode': 'provider_default' if self.provider_output_limit else 'explicit'}
            save(directory / 'normalized-response.json', raw)
            message = raw['choices'][0]['message']
            self.replay[digest(message)] = deepcopy(result['response']['output'])
            return Completion(message.get('content') or '', raw, request)
        except Exception as exc:
            self.failed = True
            if not (directory / 'failure.json').exists():
                save(directory / 'failure.json', {'type': type(exc).__name__,
                     'dispatch_state': 'inspect dispatch.json; unknown on interruption',
                     'automatic_retries': 0})
            if isinstance(exc, BackendResponseError): raise
            raise BackendResponseError('External bridge failed; see ' + str(directory),
                                       request, {'error_type': type(exc).__name__}) from exc

    def close(self):
        if self._lease is not None:
            fcntl.flock(self._lease, fcntl.LOCK_UN)
            self._lease.close(); self._lease = None
