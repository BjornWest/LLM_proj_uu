"""Model boundary: plain messages in, raw completion and metadata out."""

from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlparse
from copy import deepcopy

import httpx


@dataclass
class Completion:
    text: str
    raw: dict
    request: dict | None = None


class Backend(Protocol):
    def complete(self, messages: list[dict]) -> Completion: ...


class BackendResponseError(RuntimeError):
    def __init__(self, message, request, response):
        super().__init__(message)
        self.request_payload = request
        self.response_payload = response


class ChatCompletionsBackend:
    """Works with an OpenAI-compatible hosted API, Ollama, or vLLM.

    No automatic retries: each request is visible in the episode budget.
    Optional token/logprob fields are retained verbatim when supplied by a server.
    """

    def __init__(self, base_url: str, model: str, api_key: str | None = None,
                 timeout: float = 90, max_tokens: int = 128, *, request_options=None,
                 session_routing: bool = False):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.max_tokens = max_tokens
        self.request_options = deepcopy(request_options or {})
        self.session_routing = session_routing
        self.session_id = None
        if session_routing and (urlparse(self.base_url).hostname != 'openrouter.ai'
                                or 'preset' in self.request_options or model.startswith('@preset/')):
            raise ValueError('Session routing requires an OpenRouter model slug, without a preset')
        if session_routing and ('session_id' in self.request_options or
                                'order' in (self.request_options.get('provider') or {})):
            raise ValueError('Session routing owns session_id and must not specify provider.order')
        if set(self.request_options) & {"model", "messages", "temperature", "max_tokens", "stream"}:
            raise ValueError("request_options cannot override core generation settings")
        self.client = httpx.Client(
            timeout=timeout,
            headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
            trust_env=False,
        )

    def begin_episode(self, episode_id):
        if not self.session_routing:
            return None
        if not isinstance(episode_id, str) or not 1 <= len(episode_id) <= 256:
            raise ValueError('OpenRouter session_id must contain 1..256 characters')
        self.session_id = episode_id
        return {'session_id': episode_id, 'requested_model': self.model,
                'provider': deepcopy(self.request_options.get('provider'))}

    def complete(self, messages: list[dict]) -> Completion:
        if self.session_routing and self.session_id is None:
            raise ValueError('Begin an episode before sending a session-routed request')
        request = {
            "model": self.model, "messages": messages, "temperature": 0,
            "max_tokens": self.max_tokens, "stream": False,
            **self.request_options,
            **({'session_id': self.session_id} if self.session_routing else {}),
        }
        self.last_request = request
        response = self.client.post(self.base_url + "/chat/completions", json=request)
        try:
            raw = response.json()
        except ValueError:
            raw = {"unparsed_body": response.text}
        if not response.is_success:
            raise BackendResponseError(f"Model endpoint HTTP {response.status_code}", request, raw)
        try:
            content = raw["choices"][0]["message"].get("content")
        except (KeyError, IndexError, TypeError, AttributeError) as exc:
            raise BackendResponseError("Model endpoint returned an unexpected response shape", request, raw) from exc
        # Preserve raw usage/reasoning/refusal fields even when no text action
        # was returned; the action parser will reject the empty decision.
        return Completion(content if isinstance(content, str) else "", raw, request)

    def close(self):
        self.client.close()


class ManualBackend:
    def __init__(self, source="human"):
        self.source = source

    def complete(self, messages: list[dict]) -> Completion:
        print(messages[-1]["content"])
        return Completion(input("BrowserGym action> "), {"source": self.source})

    def close(self):
        pass
