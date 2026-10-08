"""Actual runner default selection and pre-dispatch failures, zero providers."""
from copy import deepcopy
from dataclasses import replace
import json
from unittest.mock import Mock, patch

import httpx
import numpy as np
import pytest

from intent_browser.backend import ChatCompletionsBackend
from intent_browser.harness import SemanticFeedback, native_tools_profile
from intent_browser.model_input_budget import REGISTRY, model_matched_input_counter
from tests.runner_diagnostics import run_episode
from tests.test_native_tools import response


class Counter:
    def __init__(self):
        self.requests = []
        self.completions = []

    def __call__(self, messages, tools):
        self.requests.append(deepcopy((messages, tools)))
        return {'input_tokens': 50, 'method': 'explicit-fixture-counter'}

    def observe_completion(self, request, raw):
        self.completions.append(deepcopy((request, raw)))


def exercise(tmp_path, *, model='z-ai/glm-5.3-flash', limit=100000,
             counter=None, factory=None):
    activity = {'environments': 0, 'resets': 0, 'requests': [], 'actions': []}

    class Env:
        def obs(self):
            return {'goal': 'Inspect', 'url': 'http://fixture/', 'last_action_error': '',
                    'axtree_object': {'nodes': [{'nodeId': '1',
                        'role': {'value': 'StaticText'}, 'name': {'value': 'Inspect'}}]},
                    'screenshot': np.zeros((2, 2, 3), dtype=np.uint8)}

        def reset(self, seed):
            activity['resets'] += 1
            return self.obs(), {}

        def step(self, action):
            activity['actions'].append(action)
            return self.obs(), 0, False, False, {}

        def close(self):
            pass

    def env_factory(_):
        activity['environments'] += 1
        return Env()

    def transport(request):
        activity['requests'].append(json.loads(request.content))
        raw = response('send_msg_to_user', {'text': 'Done'}, 'call-1')
        raw['usage'] = {'prompt_tokens': 50, 'completion_tokens': 10}
        return httpx.Response(200, json=raw)

    backend = ChatCompletionsBackend('https://openrouter.ai/api/v1', model)
    backend.client.close()
    backend.client = httpx.Client(transport=httpx.MockTransport(transport))
    profile = replace(native_tools_profile(), feedback_factory=SemanticFeedback)
    assert profile.ax_config is None  # AX budgeting cannot select the policy tokenizer.
    try:
        with patch('intent_browser.runner.observation_text', return_value='Inspect'), \
                patch('intent_browser.harness.flatten_axtree_to_str', return_value='Inspect'):
            options = dict(harness_profile=profile, max_steps=2,
                           max_input_tokens=limit, input_counter=counter)
            if factory is None:
                path, summary = run_episode(env_factory, backend, {}, str(tmp_path), **options)
            else:
                with patch('intent_browser.model_input_budget.model_matched_input_counter', factory):
                    path, summary = run_episode(env_factory, backend, {}, str(tmp_path), **options)
        rows = [json.loads(line) for line in (path / 'steps.jsonl').read_text().splitlines()]
        return summary, rows, activity, backend
    finally:
        backend.close()


@pytest.mark.parametrize('model', ['z-ai/glm-5.3-flash', 'qwen/qwen3.8-27b'])
def test_default_factory_receives_actual_backend_without_ax_config(tmp_path, model):
    counter = Counter()
    factory = Mock(return_value=counter)
    summary, rows, activity, backend = exercise(tmp_path, model=model, factory=factory)
    factory.assert_called_once_with(backend, ax_tokenizer_path=None)
    assert backend.model == model
    assert len(counter.requests) == 1 and len(counter.completions) == 1
    assert counter.requests[0][1]  # Native tool definitions reach the selected counter.
    assert rows[0]['input_budget']['method'] == 'explicit-fixture-counter'
    assert summary['stop_reason'] == 'agent_finished' and summary['error'] is None
    assert len(activity['requests']) == 1


def test_explicit_counter_bypasses_factory_even_for_unregistered_model(tmp_path):
    counter = Counter()
    factory = Mock(side_effect=AssertionError('Explicit counter must bypass factory'))
    summary, rows, activity, _ = exercise(tmp_path, model='unregistered/model',
                                        counter=counter, factory=factory)
    factory.assert_not_called()
    assert len(counter.requests) == 1 and len(counter.completions) == 1
    assert rows[0]['input_budget']['input_tokens'] == 50
    assert summary['stop_reason'] == 'agent_finished' and len(activity['requests']) == 1


def test_disabled_input_guard_never_constructs_default_counter(tmp_path):
    factory = Mock(side_effect=AssertionError('Disabled guard must bypass factory'))
    summary, rows, activity, _ = exercise(tmp_path, limit=None, factory=factory)
    factory.assert_not_called()
    assert 'input_budget' not in rows[0]
    assert summary['stop_reason'] == 'agent_finished' and len(activity['requests']) == 1


@pytest.mark.parametrize('failure', ['unknown_model', 'missing_assets', 'mismatched_assets'])
def test_selection_failure_precedes_environment_and_provider(tmp_path, failure):
    activity = {'env': 0, 'provider': 0}
    backend = ChatCompletionsBackend('https://openrouter.ai/api/v1',
                                    'unknown/model' if failure == 'unknown_model' else 'z-ai/glm-5.3-flash')
    backend.client.close()

    def transport(_):
        activity['provider'] += 1
        raise AssertionError('Selection failure dispatched inference')

    def environment(_):
        activity['env'] += 1
        raise AssertionError('Selection failure created an environment')

    backend.client = httpx.Client(transport=httpx.MockTransport(transport))
    if failure == 'mismatched_assets':
        entry = json.loads(REGISTRY.read_text())['models'][backend.model]
        bundle = tmp_path / entry['bundle']
        bundle.mkdir()
        for name in entry['files']:
            (bundle / name).write_text('{}')
    factory = lambda selected, **options: model_matched_input_counter(
        selected, **options, assets_root=tmp_path)
    try:
        with patch('intent_browser.model_input_budget.model_matched_input_counter', factory):
            with pytest.raises(ValueError, match='No model-matched|Missing local tokenizer|mismatched'):
                run_episode(environment, backend, {}, str(tmp_path / 'runs'),
                            max_input_tokens=100000, harness_profile=native_tools_profile())
        assert activity == {'env': 0, 'provider': 0}
        assert not (tmp_path / 'runs').exists()
    finally:
        backend.close()


@pytest.mark.parametrize('model,method', [
    ('z-ai/glm-5.3-flash', 'glm-official-local-template-v1'),
    ('qwen/qwen3.8-27b', 'qwen-local-template-v1'),
])
def test_installed_official_default_counter_records_model_and_stops_before_dispatch(tmp_path, model, method):
    entry = json.loads(REGISTRY.read_text())['models'][model]
    assets = REGISTRY.parent.parent / '.local/model-tokenizers' / entry['bundle']
    if not assets.is_dir():
        pytest.skip('Explicit official tokenizer installation required; no downloads')
    summary, rows, activity, _ = exercise(tmp_path, model=model, limit=1)
    assert summary['stop_reason'] == 'max_input_tokens' and summary['error'] is None
    assert activity['requests'] == [] and activity['actions'] == []
    assert rows[0]['model_dispatch_skipped'] is True
    assert rows[0]['input_budget']['model'] == model
    assert rows[0]['input_budget']['method'] == method
    assert rows[0]['input_budget']['tokenizer_sha256'] == entry['files']['tokenizer.json']['sha256']
