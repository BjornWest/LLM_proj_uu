import json
from types import SimpleNamespace
import pytest

from browser_training.harness_bridge import (
    MappingArgumentsHarnessAdapter, TaskSelectingSessionFactory, normalize_tool_arguments,
)


def test_task_selector_maps_conversation_and_preserves_seed():
    received = []
    factory = SimpleNamespace(create=lambda *args, **kwargs: received.append((args, kwargs)))
    prompt = [{"role": "user", "content": "fixture-task"}]
    bridge = TaskSelectingSessionFactory(factory, lambda messages, seed: messages[0]["content"])
    bridge.create(prompt, seed=7, episode_id="episode-1")
    assert received == [(("fixture-task",), {"seed": 7, "episode_id": "episode-1"})]


def test_invalid_task_mapping_fails_before_client_creation():
    bridge = TaskSelectingSessionFactory(None, lambda messages, seed: [])
    with pytest.raises(ValueError, match="task ID"):
        bridge.create([])


def test_arguments_normalized_without_mutating_transcript():
    arguments = {"bid": "1", "text": "a quoted \"value\""}
    encoded = json.dumps(arguments)
    messages = [{"role": "assistant", "tool_calls": [{"id": "call-1", "type": "function",
        "function": {"name": "fill", "arguments": encoded}}]}]
    result = normalize_tool_arguments(messages)
    assert result[0]["tool_calls"][0]["function"]["arguments"] == arguments
    assert messages[0]["tool_calls"][0]["function"]["arguments"] == encoded


def test_non_object_tool_arguments_rejected():
    with pytest.raises(ValueError, match="JSON object"):
        normalize_tool_arguments([{"tool_calls": [{"function": {"arguments": "[1,2]"}}]}])


def test_adapter_delegates_loop_and_preserves_sampling():
    message = [{"tool_calls": [{"function": {"arguments": '{"bid":"1"}'}}]}]
    delegate = SimpleNamespace(run_white_box=lambda step, session, limits: step(message, ["click"], {"temperature": 1}))
    wrapped = MappingArgumentsHarnessAdapter(delegate)
    assert wrapped.run_white_box(lambda messages, tools, sampling: (
        messages[0]["tool_calls"][0]["function"]["arguments"], tools, sampling), None, None) == (
            {"bid": "1"}, ["click"], {"temperature": 1})
