"""Map a TRL conversation to an existing OpenEnv BrowserGym session factory."""
import json


def normalize_tool_arguments(messages):
    """Qwen's template requires mappings; OpenEnv serializes arguments as JSON text."""
    result = []
    for message in messages:
        if not message.get("tool_calls"):
            result.append(message)
            continue
        calls = []
        for call in message["tool_calls"]:
            function = call["function"]
            arguments = function.get("arguments", {})
            if isinstance(arguments, str):
                arguments = json.loads(arguments)
            if not isinstance(arguments, dict):
                raise ValueError("Tool arguments must be a JSON object")
            calls.append({**call, "function": {**function, "arguments": arguments}})
        result.append({**message, "tool_calls": calls})
    return result


class MappingArgumentsHarnessAdapter:
    """Delegate the entire agent loop to OpenEnv, normalize only its model input."""
    def __init__(self, delegate):
        self.delegate = delegate

    def run_white_box(self, model_step, session, limits):
        def normalized_step(messages, tools, sampling):
            return model_step(normalize_tool_arguments(messages), tools, sampling)
        return self.delegate.run_white_box(normalized_step, session, limits)


class TaskSelectingSessionFactory:
    def __init__(self, session_factory, task_selector):
        self.session_factory = session_factory
        self.task_selector = task_selector

    def create(self, task, seed=None, episode_id=None):
        # TRL supplies a message list; BrowserGymSessionFactory expects a task ID.
        task_name = self.task_selector(task, seed)
        if not isinstance(task_name, str) or not task_name.strip():
            raise ValueError("Task selector must return a nonempty BrowserGym task ID")
        return self.session_factory.create(task_name, seed=seed, episode_id=episode_id)
