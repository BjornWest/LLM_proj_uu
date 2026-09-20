"""Opt-in, bounded model-decision recovery. Never retries a browser action."""
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
import json
import math

import httpx
from jsonschema import ValidationError
from .backend import BackendResponseError


def retry_after_seconds(value, *, now=None):
    if value is None:
        return None
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        try:
            date = parsedate_to_datetime(value)
            if date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)
            seconds = (date - (now or datetime.now(timezone.utc))).total_seconds()
        except (TypeError, ValueError, OverflowError):
            return None
    return max(0.0, seconds) if math.isfinite(seconds) else None


@dataclass(frozen=True)
class DecisionRetryPolicy:
    """One additional request per episode, within existing call and budget caps."""
    max_retries: int = 1
    max_wait_seconds: float = 60.0

    def __post_init__(self):
        if type(self.max_retries) is not int or self.max_retries not in (0, 1):
            raise ValueError('Decision recovery supports zero or one retry per episode')
        if not isinstance(self.max_wait_seconds, (int, float)) or not 0 <= self.max_wait_seconds <= 60:
            raise ValueError('Retry wait limit must be between zero and 60 seconds')

    def describe(self):
        return {'version': 'bounded-decision-retry-v1', 'max_retries_per_episode': self.max_retries,
                'max_wait_seconds': self.max_wait_seconds, 'counts_toward_max_steps': True,
                'browser_action_replay': False, 'provider_exclusion': False}

    def select(self, exc, phase, event, *, used, remaining_calls):
        if not isinstance(exc, Exception):
            return None
        if used >= self.max_retries or remaining_calls <= 0 or event.get('browser_stepped'):
            return None
        delay, reason = 0.0, None
        raw = event.get('model_response') or {}
        if phase == 'model':
            if isinstance(exc, BackendResponseError) and getattr(exc, 'http_status', None) in (408, 429, 500, 502, 503, 504):
                reason = 'transient_http_' + str(exc.http_status)
                delay = max(2.0, retry_after_seconds(getattr(exc, 'retry_after', None)) or 0.0)
            elif isinstance(exc, (httpx.TimeoutException, httpx.NetworkError)):
                reason, delay = 'transport_failure', 2.0
        elif phase == 'action_parse' and isinstance(raw, dict):
            choices = raw.get('choices')
            choice = choices[0] if isinstance(choices, list) and len(choices) == 1 else {}
            if not isinstance(choice, dict):
                return None
            message = choice.get('message') or {}
            if not isinstance(message, dict) or message.get('role') != 'assistant' or message.get('refusal'):
                return None
            # Repeating a reasoning-length cutoff without a different budget is
            # not a repair. Refusals and guardrail/navigation failures stop too.
            if choice.get('finish_reason') not in ('stop', 'tool_calls'):
                return None
            calls = message.get('tool_calls')
            if not isinstance(calls, list) or len(calls) != 1:
                reason = 'missing_tool_call' if not calls else 'multiple_tool_calls'
            elif isinstance(exc, (json.JSONDecodeError, ValidationError)):
                reason = 'invalid_tool_arguments'
        if reason is None or delay > self.max_wait_seconds:
            return None
        return {'reason': reason, 'wait_seconds': delay,
                'notice': 'HARNESS RECOVERY NOTICE: The preceding model request produced no executable action. '
                          'No browser action from that response ran. Select exactly one available tool and supply '
                          'arguments matching its JSON schema. Use the fresh observation below; do not assume an '
                          'earlier action needs repeating. This is the only recovery attempt.'}
