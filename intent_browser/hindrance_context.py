"""Hindrance-only opt-in history window and cheap input-budget preflight."""
from copy import deepcopy
import json

from .input_budget import OpaqueReasoningInputCounter
from .vision import VisionConversation


class WindowedConversation(VisionConversation):
    """Keep recent browser evidence, all actions/reasoning and the user's goal.

    Only bound browser evidence is replaced. Original requests remain in traces;
    dropped evidence is removed from future delivery bindings, never acknowledged
    as if it had been sent. Tool call/result IDs and human messages stay intact.
    """
    layout = 'hindrance-windowed-browser-evidence-v1'

    def __init__(self, keep_turns):
        super().__init__()
        self.keep_turns = keep_turns
        self._turn_ends = []

    def request(self, *args, **kwargs):
        super().request(*args, **kwargs)
        self._turn_ends.append(len(self._messages))
        if len(self._turn_ends) > self.keep_turns:
            cutoff = self._turn_ends[-self.keep_turns-1]
            stale = {}
            for binding in self._bindings:
                index = binding['message_index']
                message = self._messages[index]
                if index < cutoff and (message['role'] == 'tool' or
                        (index == 1 and message['role'] == 'user')):
                    stale.setdefault(index, []).append(binding)
            for index, spans in stale.items():
                content = self._messages[index]['content']
                text = content if isinstance(content, str) else content[0]['text']
                for span in sorted(spans, key=lambda b: b['start'], reverse=True):
                    text = text[:span['start']] + '[Older browser evidence omitted; read the current page again if needed.]' + text[span['end']:]
                if isinstance(content, str):
                    self._messages[index]['content'] = text
                else:
                    content[0]['text'] = text
            self._bindings = [b for b in self._bindings if b['message_index'] not in stale]
        return deepcopy(self._messages)


class PreflightInputCounter(OpaqueReasoningInputCounter):
    """Skip tokenization when a conservative byte bound fits the input limit.

    Text/template tokens are bounded with twice the serialized UTF-8 bytes plus
    8192 formatting tokens; opaque reasoning uses originating usage receipts.
    Images, unknown reasoning and requests near the limit use the usual complete
    Qwen template estimator. This bound is budget telemetry, never token usage.
    """
    def __init__(self, visible_counter, limit):
        super().__init__(visible_counter)
        self.limit = limit

    def __call__(self, messages, tools):
        selected = []
        hidden = 0
        for message in messages:
            if not isinstance(message.get('content'), (str, type(None))):
                return super().__call__(messages, tools)
            value = dict(message)
            if value.get('role') == 'assistant':
                try:
                    opaque = self._opaque(value)
                except ValueError:
                    return super().__call__(messages, tools)
                if opaque:
                    receipt = self._receipts.get(self._digest(opaque))
                    if receipt is None:
                        return super().__call__(messages, tools)
                    hidden += receipt['tokens']
                    value['reasoning_details'] = [d for d in value['reasoning_details'] if d.get('type') == 'reasoning.text']
            selected.append(value)
        size = len(json.dumps([selected, tools], ensure_ascii=False).encode('utf-8'))
        bound = 2 * size + 8192 + hidden
        if self.limit is not None and bound <= self.limit:
            return {'input_tokens': bound, 'method': 'hindrance-utf8-byte-preflight-bound-v1',
                    'serialized_utf8_bytes': size, 'retained_hidden_tokens_estimate': hidden,
                    'exact_provider_tokens': False,
                    'scope': 'Conservative budget bound; not measured prompt tokens. Exact local template estimate near limit.'}
        return super().__call__(messages, tools)
