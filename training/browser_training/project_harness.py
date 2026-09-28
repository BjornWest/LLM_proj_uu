"""Frozen project harness via isolated browser processes; native TRL owns sampling/loss."""
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import threading
from copy import deepcopy

from .harness_bridge import normalize_tool_arguments
from .native_metrics import native_outcome


def configure_response_parser(tokenizer):
    from trl.chat_template_utils import add_response_schema
    if getattr(tokenizer, 'response_template', None) is None:
        tokenizer = add_response_schema(tokenizer)
    schema = deepcopy(tokenizer.response_template)
    field = schema['fields']['tool_calls']
    if field['content'] != 'xml-inline':
        raise ValueError('This bridge is qualified only for Qwen XML tool calls')
    # TRL's JSON value_parser eagerly turns XML "107" into int before HF's
    # schema-aware casting runs (which only handles raw strings). Keep XML text
    # intact and let the upstream tools= parser apply the actual parameter type.
    field['content_args'].pop('value_parser', None)
    tokenizer.response_template = schema
    return tokenizer


def wire_response(tokenizer, step, tools, *, turn=0):
    # Use the upstream parser with the actual tool schema: numeric browser IDs
    # in Qwen XML are string arguments, not JSON numbers. TRL's wrapper omits
    # tools= and OpenEnv's normalized LLMResponse also drops reasoning.
    try:
        message = tokenizer.parse_response(step.completion_ids, prefix=step.prompt_ids, tools=tools)
        if not isinstance(message, dict):
            raise ValueError('Missing assistant message')
    except (ValueError, TypeError):
        # Retain malformed output for the harness to reject, without executing it.
        message = dict(role='assistant', content=tokenizer.decode(step.completion_ids, skip_special_tokens=True))
    for i, call in enumerate(message.get('tool_calls') or []):
        call.setdefault('id', f'call_{turn}_{i}')
        call.setdefault('type', 'function')
        arguments = call['function'].get('arguments', {})
        if isinstance(arguments, dict):
            call['function']['arguments'] = json.dumps(arguments)
        # Invalid serialized arguments are NOT repaired.
    ended = bool(step.completion_ids and step.completion_ids[-1] == tokenizer.eos_token_id)
    return dict(choices=[dict(message=message, finish_reason='stop' if ended else 'length')],
                prompt_token_ids=step.prompt_ids, completion_token_ids=step.completion_ids,
                completion_logprobs=step.logprobs, response_source='native-TRL-token-parser')


class ProjectFactory:
    def __init__(self, frozen, browser_python, output, worker_script):
        self.settings = dict(frozen=str(frozen), browser_python=str(browser_python),
                             output=str(output), worker_script=str(worker_script))

    def create(self, task, seed=None, episode_id=None):
        if task != 'P11-clean':
            raise ValueError('Only the qualified P11-clean task is supported')
        return ProjectSession(**self.settings, seed=seed, episode_id=episode_id)


class ProjectSession:
    def __init__(self, *, frozen, browser_python, output, worker_script, seed, episode_id):
        self.directory = Path(output) / episode_id
        self.directory.mkdir(parents=True, exist_ok=False)
        self.result = None
        self.closed = False
        self.lock = threading.RLock()
        self.socket, child = socket.socketpair()
        self.socket.settimeout(120)
        self.stream = self.socket.makefile('rw')
        self.log = (self.directory / 'browser.log').open('w')
        command = [browser_python, '-I', worker_script, '--frozen', frozen,
                   '--output', str(self.directory), '--seed', str(seed or 0), '--fd', str(child.fileno())]
        try:
            self.process = subprocess.Popen(command, pass_fds=(child.fileno(),),
                stdout=self.log, stderr=subprocess.STDOUT, start_new_session=True,
                env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
        finally:
            child.close()

    def verify(self, transcript):
        from openenv.core.harness import VerifyResult
        if self.result is None:
            raise RuntimeError('Browser finished without persisted native evaluation')
        self.outcome = native_outcome(self.result['evaluation'])
        return VerifyResult(env_reward=self.outcome['reward'], done=True,
                            metrics={'step_count': self.result['steps']}, artifacts={'trace': self.result['trace']})

    def accept_result(self, result):
        self.result = result

    def close(self):
        with self.lock:
            if self.closed:
                return
            self.closed = True
            if self.process.poll() is None:
                # Interrupt the main browser thread so runner's finally grades before closing.
                self.process.send_signal(signal.SIGINT)
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            self.process.wait(timeout=5)
            try:
                self.socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.stream.close()
            self.socket.close()
            self.log.close()


def project_outcome(session, verify):
    return session.outcome


class ProjectAdapter:
    def __init__(self, tokenizer_path):
        self.tokenizer_path = str(tokenizer_path)

    def run_white_box(self, model_step, session, limits):
        from transformers import AutoTokenizer
        from openenv.core.harness import HarnessRolloutResult
        from openenv.core.env_server.mcp_types import Tool
        tokenizer = AutoTokenizer.from_pretrained(self.tokenizer_path, local_files_only=True)
        tokenizer = configure_response_parser(tokenizer)
        session.stream.write(json.dumps({'max_steps': limits.max_turns}) + '\n')
        session.stream.flush()
        messages, turns = [], 0
        while True:
            line = session.stream.readline()
            if not line:
                raise RuntimeError('Browser worker exited without a result; inspect browser.log')
            request = json.loads(line)
            if request['kind'] == 'result':
                session.accept_result(request)
                break
            if request['kind'] != 'sample' or turns >= limits.max_turns:
                raise RuntimeError('Unexpected browser sampling request')
            tools = [Tool(name=t['function']['name'], description=t['function']['description'],
                          input_schema=t['function']['parameters']) for t in request['options']['tools']]
            step = model_step(normalize_tool_arguments(request['messages']), tools, dict(limits.sampling))
            raw = wire_response(tokenizer, step, request['options']['tools'], turn=turns)
            messages = request['messages'] + [raw['choices'][0]['message']]
            session.stream.write(json.dumps(raw) + '\n')
            session.stream.flush()
            turns += 1
        if session.process.wait(timeout=15) != 0:
            raise RuntimeError('Browser worker failed after grading')
        return HarnessRolloutResult(messages=messages, done=True, metrics={'turns': turns, 'tool_calls': turns})


def project_tasks(source_hash):
    return [dict(task_id='P11-clean', task_family='tricky-music', task_template='P11-clean',
                 split='rl_train', harness_revision=source_hash, verifier_revision=source_hash,
                 environment_revision='9fc287a252ddee32e579575bec50e33568070272de2e81ef5c9033bde19eb90e',
                 tokenizer_revision='Qwen3.8-1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0')]
