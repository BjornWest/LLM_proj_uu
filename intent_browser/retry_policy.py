"""Opt-in, bounded model-decision recovery. Never retries a browser action."""
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
import json
import math

import httpx
from jsonschema import ValidationError
from .backend import BackendResponseError


def argument_diagnostic(exc):
    """Use structured validator facts, never an unbounded exception/schema dump.

    The path identifies an argument (or nested argument) without guessing from
    prose. Values and page/model text are not echoed into the recovery notice.
    Unknown constraints fall back to checking the named field's schema.
    """
    if isinstance(exc, json.JSONDecodeError):
        return {'problem': 'Arguments are not valid JSON', 'line': exc.lineno, 'column': exc.colno}
    if not isinstance(exc, ValidationError):
        return None
    path = list(exc.absolute_path)
    pointer = '/' + '/'.join(str(p).replace('~', '~0').replace('/', '~1') for p in path[:8]) if path else '(arguments)'
    value = exc.instance
    received = ('null' if value is None else 'boolean' if isinstance(value, bool) else
                'integer' if isinstance(value, int) else 'number' if isinstance(value, float) else
                'string' if isinstance(value, str) else 'array' if isinstance(value, list) else
                'object' if isinstance(value, dict) else 'unknown')
    def type_label(schema):
        kind = schema.get('type') if isinstance(schema, dict) else None
        if kind == 'array' and isinstance(schema.get('items'), dict):
            item = schema['items'].get('type')
            if isinstance(item, str): return f'array of {item} values'
        return kind if isinstance(kind, str) else None
    requirement = 'Check this parameter against the tool JSON schema.'
    if exc.validator == 'type':
        label = type_label(exc.schema)
        if label: requirement = 'Expected ' + label + '.'
    elif exc.validator == 'anyOf' and isinstance(exc.validator_value, list):
        labels = [type_label(s) for s in exc.validator_value[:4]]
        if len(exc.validator_value) <= 4 and all(labels):
            requirement = 'Expected ' + ' or '.join(labels) + '.'
    elif exc.validator in ('maximum', 'minimum', 'maxLength', 'minLength', 'maxItems', 'minItems'):
        requirement = f'{exc.validator} is {exc.validator_value}.'
    elif exc.validator == 'required':
        requirement = 'Supply all required parameters listed in the tool JSON schema.'
        if isinstance(value, dict) and isinstance(exc.validator_value, list):
            missing = [k for k in exc.validator_value if k not in value]
            if missing: requirement = 'Missing required parameters: ' + ', '.join(missing[:8]) + '.'
    elif exc.validator == 'additionalProperties':
        requirement = 'Remove parameters not allowed by the tool JSON schema.'
    elif exc.validator == 'enum':
        requirement = 'Use one of the allowed values listed in the tool JSON schema.'
    return {'parameter': pointer[:160], 'received_type': received, 'requirement': requirement[:240]}


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
    """Bounded correction: legacy episode allowance or opt-in replenishing chains."""
    max_retries: int = 1
    max_wait_seconds: float = 60.0
    scope: str = "episode"

    def __post_init__(self):
        if self.scope not in ("episode", "failure_chain"):
            raise ValueError("Retry scope must be episode or failure_chain")
        if type(self.max_retries) is not int or self.max_retries not in (0, 1):
            raise ValueError('Decision recovery supports zero or one retry per selected scope')
        if not isinstance(self.max_wait_seconds, (int, float)) or not 0 <= self.max_wait_seconds <= 60:
            raise ValueError('Retry wait limit must be between zero and 60 seconds')

    def describe(self):
        if self.scope == 'failure_chain':
            return {'version': 'bounded-decision-retry-v3',
                    'argument_feedback': 'structured-validator-path-v1',
                    'max_retries_per_failure_chain': self.max_retries,
                    'reset_after': 'successfully processed decision',
                    'max_wait_seconds': self.max_wait_seconds, 'counts_toward_max_steps': True,
                    'browser_action_replay': False, 'provider_exclusion': False}
        return {'version': 'bounded-decision-retry-v2', 'argument_feedback': 'structured-validator-path-v1',
                'max_retries_per_episode': self.max_retries,
                'max_wait_seconds': self.max_wait_seconds, 'counts_toward_max_steps': True,
                'browser_action_replay': False, 'provider_exclusion': False}

    def select(self, exc, phase, event, *, used, remaining_calls, consecutive_used=0):
        if not isinstance(exc, Exception):
            return None
        limit_used = consecutive_used if self.scope == 'failure_chain' else used
        if limit_used >= self.max_retries or remaining_calls <= 0 or event.get('browser_stepped'):
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
            from .completion_diagnostics import completion_diagnostic
            diagnostic=completion_diagnostic(raw,event.get('model_request'))
            if diagnostic and diagnostic['retry_unchanged'] is False:
                return None
            if 'Repeated native tool call ID' in str(exc):
                return None
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
            if self.scope == 'failure_chain' and isinstance(exc, (json.JSONDecodeError, ValidationError)):
                reason = 'invalid_tool_arguments'
            elif not isinstance(calls, list) or len(calls) != 1:
                reason = 'missing_tool_call' if not calls else 'multiple_tool_calls'
            elif isinstance(exc, (json.JSONDecodeError, ValidationError)):
                reason = 'invalid_tool_arguments'
        if reason is None or delay > self.max_wait_seconds:
            return None
        diagnostic = argument_diagnostic(exc) if reason == 'invalid_tool_arguments' else None
        notice = ('HARNESS RECOVERY NOTICE: The preceding model request produced no executable action. '
                          'No browser action from that response ran. Select exactly one available tool and supply '
                          'arguments matching its JSON schema. Double-check the parameter names, types and allowed '
                          'values in that schema before responding. Use the fresh observation below; do not assume an '
                          'earlier action needs repeating. This is the only recovery attempt.')
        if self.scope == 'failure_chain':
            notice = notice.replace('Select exactly one available tool', 'Select available tools within the advertised batch limit')
            notice = notice.replace('This is the only recovery attempt.',
                'This is the correction attempt for the current failure chain. A valid decision restores the correction allowance.')
        if diagnostic:
            notice += '\nArgument validation feedback: ' + json.dumps(diagnostic, ensure_ascii=False, sort_keys=True)
        return {'reason': reason, 'wait_seconds': delay, 'notice': notice,
                **({'argument_diagnostic': diagnostic} if diagnostic else {})}
