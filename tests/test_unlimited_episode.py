"""Opt-in unlimited decisions, real runner/transport, no provider/browser calls."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import re
from pathlib import Path
from unittest.mock import patch

import httpx
import numpy as np
import pytest

from agent_trace.adapters import browsergym as grade_viewer
import intent_browser.automatic_grading as grading_module
from intent_browser.automatic_grading import AutomaticGrading, file_hash
from intent_browser.backend import ChatCompletionsBackend
from intent_browser.delegation import AgentLimits, AgentRuntime
from intent_browser.evaluation import Evaluation
from intent_browser.harness import SemanticFeedback, native_tools_profile, with_subagents
from intent_browser.retry_policy import DecisionRetryPolicy
from intent_browser.runner import run_episode
from tests.test_native_tools import response


def bind(env, trace, obs):
    return {'task_id': 'unlimited-fixture',
            'goal_sha256': hashlib.sha256(obs['goal'].encode()).hexdigest(),
            'reference_files': {str(env.reference): file_hash(env.reference)},
            'source_files': {str(p.resolve()): file_hash(p.resolve()) for p in
                             (Path(__file__), Path(grading_module.__file__), Path(grade_viewer.__file__))}}


def grade(env, trace, outcome):
    return {'completed': env.done, 'actions': len(env.actions)}


def project(raw, binding):
    return Evaluation('fixture-native-state', 'v1', trust='native_state',
                      task_completed=raw['completed'], authorization_satisfied=True)


class Counter:
    def __init__(self, values=()):
        self.values = list(values)
        self.calls = 0

    def __call__(self, messages, tools):
        self.calls += 1
        return {'input_tokens': self.values[self.calls - 1] if self.calls <= len(self.values) else 10,
                'method': 'complete-request-fixture'}


def exercise(tmp_path, sequence, *, max_steps=None, counter=None, retry=None,
             truncated=False, max_input_tokens=100, delegation=False, raw_factory=None):
    requests = []

    class Env:
        def __init__(self):
            self.reference = tmp_path / 'reference.json'
            self.reference.write_text('{"goal":"Fixture"}')
            self.actions = []
            self.done = False
            self.unwrapped = self

        def obs(self):
            return {'goal': 'Fixture', 'url': 'http://fixture/', 'last_action_error': '',
                    'axtree_object': {'nodes': []},
                    'screenshot': np.zeros((2, 2, 3), dtype=np.uint8)}

        def reset(self, seed): return self.obs(), {}

        def step(self, action):
            self.actions.append(action)
            self.done = action.startswith('send_msg_to_user')
            return self.obs(), 0, False, truncated, {}

        def close(self): pass

    env = Env()

    def transport(request):
        requests.append(json.loads(request.content))
        if raw_factory is not None:
            return httpx.Response(200, json=raw_factory(requests[-1]))
        item = sequence[len(requests) - 1]
        if item == 'missing':
            raw = response()
            raw['choices'][0]['message']['tool_calls'] = []
        elif item == 'fail':
            return httpx.Response(503, json={'error': {'message': 'fixture unavailable'}})
        else:
            name, arguments = ('send_msg_to_user', {'text': 'Done'}) if item == 'finish' else ('noop', {'wait_ms': 0})
            raw = response(name, arguments, 'call-' + str(len(requests)))
        return httpx.Response(200, json=raw)

    backend = ChatCompletionsBackend('https://fixture.invalid/v1', 'fixture')
    backend.client.close()
    backend.client = httpx.Client(transport=httpx.MockTransport(transport))
    profile = replace(native_tools_profile(), feedback_factory=SemanticFeedback)
    if delegation:
        profile = with_subagents(profile, AgentLimits(total_model_calls=None, child_steps=None))
    try:
        with patch('intent_browser.runner.observation_text', return_value='Fixture'), \
                patch('intent_browser.harness.flatten_axtree_to_str', return_value='Fixture'), \
                patch('intent_browser.runner.refresh_observation', side_effect=lambda e: e.obs() if hasattr(e, 'obs') else e._get_obs()), \
                patch('intent_browser.batching.document_signature', return_value=[]):
            directory, summary = run_episode(lambda _: env, backend,
                {'driver': 'scripted_validation', 'tags': ['scripted']}, tmp_path / 'runs',
                max_steps=max_steps, max_input_tokens=max_input_tokens, input_counter=counter or Counter(),
                harness_profile=profile, retry_policy=retry,
                automatic_grading=AutomaticGrading('fixture-v1', bind, grade, project))
        rows = [json.loads(line) for line in (directory / 'steps.jsonl').read_text().splitlines()]
        return directory, summary, rows, requests, env
    finally:
        backend.close()


def test_unlimited_exceeds_default_turn_bound_and_still_grades(tmp_path):
    directory, summary, rows, requests, env = exercise(tmp_path, ['wait'] * 201 + ['finish'])
    assert len(requests) == 202 and len(env.actions) == 202
    assert summary['stop_reason'] == 'agent_finished' and summary['error'] is None
    assert summary['success'] is True and summary['grading']['status'] == 'graded'
    assert json.loads((directory / 'metadata.json').read_text())['max_steps'] is None
    assert json.loads((directory / 'automatic-grade-projection.json').read_text())['verified'] is True
    assert all(r['input_budget']['limit'] == 100 for r in rows)


def test_unlimited_stops_on_next_isl_before_dispatch_and_grades(tmp_path):
    counter = Counter([100, 100, 101])
    directory, summary, rows, requests, env = exercise(tmp_path, ['wait', 'wait'], counter=counter)
    assert len(requests) == len(env.actions) == 2
    assert counter.calls == 3 and rows[-1]['model_dispatch_skipped'] is True
    assert summary['stop_reason'] == 'max_input_tokens' and summary['truncated'] is True
    assert summary['error'] is None and summary['grading']['status'] == 'graded'


def test_final_answer_does_not_trigger_post_answer_isl_check(tmp_path):
    counter = Counter([100, 101])
    _, summary, _, requests, _ = exercise(tmp_path, ['finish'], counter=counter)
    assert counter.calls == len(requests) == 1
    assert summary['success'] is True and summary['stop_reason'] == 'agent_finished'


def test_finite_limit_preserves_existing_stop_and_grading(tmp_path):
    _, summary, _, requests, _ = exercise(tmp_path, ['wait', 'wait', 'finish'], max_steps=2)
    assert len(requests) == 2 and summary['stop_reason'] == 'max_steps'
    assert summary['truncated'] is True and summary['grading']['status'] == 'graded'


def test_unlimited_environment_truncation_still_stops(tmp_path):
    _, summary, _, requests, _ = exercise(tmp_path, ['wait'], truncated=True)
    assert len(requests) == 1 and summary['stop_reason'] == 'environment_truncated'
    assert summary['grading']['status'] == 'graded'


def test_unlimited_failure_chain_gets_one_retry_then_retains_null_remaining(tmp_path):
    _, summary, rows, requests, _ = exercise(tmp_path, ['missing', 'missing'],
        retry=DecisionRetryPolicy(scope='failure_chain'))
    assert len(requests) == 2 and summary['decision_retry_count'] == 1
    assert rows[-1]['decision_retry_unavailable']['reason'] == 'failure_chain_limit'
    assert rows[-1]['decision_retry_unavailable']['remaining_calls'] is None
    assert summary['error'] is not None and summary['grading']['status'] == 'graded'


def test_unlimited_retry_corrected_and_metadata_has_no_decision_cap(tmp_path):
    directory, summary, rows, requests, _ = exercise(tmp_path, ['missing', 'finish'],
        retry=DecisionRetryPolicy(scope='failure_chain'))
    assert len(requests) == 2 and summary['decision_retry_count'] == 1
    assert summary['success'] is True
    assert json.loads((directory / 'metadata.json').read_text())['decision_retry_policy']['counts_toward_max_steps'] is False


@pytest.mark.parametrize('max_steps', [0, -1, True, 1.5, 'unlimited'])
def test_invalid_steps_block_before_environment(tmp_path, max_steps):
    with pytest.raises(ValueError, match='max_steps must'):
        run_episode(lambda _: pytest.fail('Environment started'), object(), {}, tmp_path,
                    max_steps=max_steps, allow_ungraded=True, ungraded_reason='Offline fixture')


def test_unlimited_requires_isl_guard_before_environment(tmp_path):
    with pytest.raises(ValueError, match='requires a positive max_input_tokens'):
        run_episode(lambda _: pytest.fail('Environment started'), object(), {}, tmp_path,
                    max_steps=None, allow_ungraded=True, ungraded_reason='Offline fixture')


def test_unlimited_rejects_hidden_finite_shared_call_cap(tmp_path):
    with pytest.raises(ValueError, match='total_model_calls=None'):
        run_episode(lambda _: pytest.fail('Environment started'), object(), {}, tmp_path,
                    max_steps=None, max_input_tokens=100, input_counter=Counter(),
                    harness_profile=with_subagents(native_tools_profile()),
                    allow_ungraded=True, ungraded_reason='Offline fixture')


@pytest.mark.parametrize('field', ['total_model_calls', 'child_steps'])
@pytest.mark.parametrize('value', [0, -1, True, 1.5])
def test_optional_agent_limits_reject_invalid_values(field, value):
    with pytest.raises(ValueError): AgentLimits(**{field: value})


def test_unlimited_shared_calls_keep_parent_child_request_isolation():
    class Backend:
        def __init__(self): self.request_options = {}; self.session_id = None; self.records = []
        def configure_tools(self, options): self.request_options.update(options)
        def begin_episode(self, episode_id): self.session_id = episode_id
        def complete(self, messages):
            self.records.append({'session': self.session_id, 'options': deepcopy(self.request_options)})
            return 'fixture'
    backend = Backend()
    runtime = AgentRuntime(backend, AgentLimits(total_model_calls=None, child_steps=None), None)
    def root(actor):
        view = actor['backend']; view.configure_tools({'tools': ['parent']}); view.begin_episode('root')
        def helper(child):
            child['backend'].configure_tools({'tools': ['child']}); child['backend'].begin_episode('child')
            for _ in range(2):
                runtime.before_observation(child); child['backend'].complete([])
        child = runtime.add(helper, parent=actor['id'], browser='none')
        for _ in range(201):
            runtime.before_observation(actor); view.complete([])
        runtime.suspend(('wait', child['id'], float('inf')))
        assert child['state'] == 'finished'
    runtime.run(root)
    assert runtime.calls == len(backend.records) == 203
    assert {r['session'] for r in backend.records} == {'root', 'child'}
    assert all(r['options']['tools'] == (['parent'] if r['session'] == 'root' else ['child']) for r in backend.records)
    assert runtime.limits.describe()['total_model_calls'] is None
    assert runtime.limits.describe()['child_steps'] is None


def test_actual_unlimited_parent_and_child_share_grading_scope(tmp_path):
    calls = {'parent': 0, 'child': 0}
    def raw(body):
        parent = any(tool['function']['name'] == 'spawn_agent' for tool in body['tools'])
        role = 'parent' if parent else 'child'
        calls[role] += 1
        if parent and calls[role] == 1:
            name, arguments = 'spawn_agent', {'task': 'Summarize supplied evidence', 'browser': 'none'}
        elif parent and calls[role] == 2:
            target = re.findall(r'"agent_id":\s*"([^" ]+)"', json.dumps(body['messages']).replace('\\"', '"'))[-1]
            name, arguments = 'wait_agent', {'agent_id': target, 'timeout_seconds': 1}
        else:
            name, arguments = 'send_msg_to_user', {'text': 'Done'}
        return response(name, arguments, f'{role}-{calls[role]}')
    directory, summary, rows, requests, env = exercise(tmp_path, [], delegation=True, raw_factory=raw)
    assert summary['success'] is True and summary['error'] is None
    assert calls == {'parent': 3, 'child': 1}
    agents = json.loads((directory / 'agents.json').read_text())
    assert agents['limits']['total_model_calls'] is None and agents['total_model_calls'] == 4
    children = [a for a in agents['agents'] if a['parent_agent_id']]
    assert len(children) == 1 and children[0]['state'] == 'finished'
    child = next((directory / 'children').iterdir())
    assert json.loads((child / 'metadata.json').read_text())['max_steps'] is None
    assert json.loads((child / 'automatic-grading.json').read_text())['status'] == 'auxiliary'
    assert not (child / 'automatic-grade.json').exists()
