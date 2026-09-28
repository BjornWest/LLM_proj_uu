"""Pre-dispatch input sizing; no cumulative usage or output reservation.

The current Qwen adapter uses local tokenizer/template assets and image sizing.
Hosted providers may use a different template/processor, so these are explicitly
local estimates, not a promise about provider billing. Other model backends can
supply their own counter to run_episode. The runner wraps this local estimator
with usage-backed opaque reasoning support; the bare Qwen counter stays strict.
"""
from copy import deepcopy
import base64
import hashlib
from io import BytesIO
import json
import math
from pathlib import Path

DEFAULT_MAX_STEPS = 200
DEFAULT_MAX_INPUT_TOKENS = 100_000


class QwenInputCounter:
    def __init__(self, tokenizer_path):
        from tokenizers import Tokenizer
        from jinja2.sandbox import ImmutableSandboxedEnvironment
        path = Path(tokenizer_path)
        template = path.with_name('chat_template.jinja')
        if not template.is_file():
            raise ValueError('Input limit requires local chat_template.jinja beside tokenizer.json')
        self.tokenizer = Tokenizer.from_file(str(path))
        env = ImmutableSandboxedEnvironment(trim_blocks=True, lstrip_blocks=True)
        env.filters['tojson'] = lambda value, **kwargs: json.dumps(value, ensure_ascii=False, **kwargs)
        def fail(message): raise ValueError(message)
        env.globals['raise_exception'] = fail
        self.template = env.from_string(template.read_text())
        self.provenance = {'method': 'qwen-local-template-v1',
            'tokenizer_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'template_sha256': hashlib.sha256(template.read_bytes()).hexdigest(),
            'scope': 'Estimated next input including tools, retained reasoning and images; hosted formatting may differ',
            'image_sizing': {'patch_size':16,'merge_size':2,'min_pixels':65536,'max_pixels':16777216}}

    def __call__(self, messages, tools):
        from PIL import Image
        selected = deepcopy(messages)
        image_extra = 0; images = 0
        for message in selected:
            if message.get('role') == 'assistant':
                details = message.get('reasoning_details')
                if details:
                    if any(d.get('type') != 'reasoning.text' for d in details):
                        raise ValueError('Cannot locally count opaque reasoning; supply a backend input counter')
                    message['reasoning_content'] = '\n'.join(d.get('text','') for d in details)
                else:
                    message['reasoning_content'] = message.get('reasoning_content') or message.get('reasoning') or ''
                for call in message.get('tool_calls', []):
                    function = call.get('function', call)
                    if isinstance(function.get('arguments'), str):
                        function['arguments'] = json.loads(function['arguments'])
            content = message.get('content')
            if not isinstance(content, list): continue
            for part in content:
                if part.get('type') == 'text': continue
                if part.get('type') != 'image_url':
                    raise ValueError('Unsupported modality for local input count')
                url = part['image_url']['url']
                if not url.startswith('data:image/png;base64,'):
                    raise ValueError('Input counting requires retained PNG bytes; no remote image fetch')
                with Image.open(BytesIO(base64.b64decode(url.split(',',1)[1],validate=True))) as image:
                    w,h = image.size
                if max(w,h)/min(w,h)>200: raise ValueError('Unsupported image aspect ratio')
                rw,rh = round(w/32)*32,round(h/32)*32
                if rw*rh>16777216:
                    scale=math.sqrt(w*h/16777216)
                    rw,rh=max(32,math.floor(w/scale/32)*32),max(32,math.floor(h/scale/32)*32)
                elif rw*rh<65536:
                    scale=math.sqrt(65536/(w*h))
                    rw,rh=math.ceil(w*scale/32)*32,math.ceil(h*scale/32)*32
                image_extra += (rw//32)*(rh//32)-1  # template already supplies one placeholder
                images += 1
        text = self.template.render(messages=selected,tools=tools or [],add_generation_prompt=True,
                                    enable_thinking=True,preserve_thinking=True)
        tokens=len(self.tokenizer.encode(text,add_special_tokens=False).ids)+image_extra
        return {**self.provenance,'input_tokens':tokens,'images':images}


class OpaqueReasoningInputCounter:
    """Preserve wire payloads; size opaque history using retained usage evidence.

    Visible text/images use the supplied local estimator. Each retained encrypted
    message adds its originating response's reasoning usage (or total completion
    usage when reasoning usage is absent). These are conservative cross-model
    estimates, not decrypted tokens or a guaranteed provider-token upper bound.
    Only retained messages count. Unattributed opaque blocks fail before dispatch.
    """
    def __init__(self, visible_counter):
        from threading import RLock
        self.visible_counter = visible_counter
        self._receipts = {}
        self._measurements = {}
        self._anchor = None
        self._lock = RLock()

    @staticmethod
    def _digest(value):
        return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                        separators=(',', ':')).encode()).hexdigest()

    @staticmethod
    def _tokens(value):
        return value if type(value) is int and value >= 0 else None

    @staticmethod
    def _opaque(message):
        details = message.get('reasoning_details') or []
        if not isinstance(details, list) or any(not isinstance(d, dict) for d in details):
            raise ValueError('Invalid reasoning_details for input sizing')
        if any(d.get('type') not in ('reasoning.text', 'reasoning.encrypted') for d in details):
            raise ValueError('Unsupported reasoning detail type for input sizing')
        return [d for d in details if d.get('type') == 'reasoning.encrypted']

    def observe_completion(self, request, response):
        """Record completed-request evidence without modifying it or the history.

        Missing usage does not invalidate an already completed action/answer.
        Its opaque block remains unattributed and blocks only a subsequent input.
        """
        if not isinstance(response, dict): return
        usage = response.get('usage') or {}
        if not isinstance(usage, dict): return
        choices = response.get('choices')
        message = (choices[0].get('message') if isinstance(choices, list) and len(choices) == 1
                   and isinstance(choices[0], dict) else None)
        details = usage.get('completion_tokens_details') or {}
        reasoning = self._tokens(details.get('reasoning_tokens')) if isinstance(details, dict) else None
        charge = reasoning if reasoning is not None else self._tokens(usage.get('completion_tokens'))
        # Unknown detail shapes are diagnosed at the next input boundary.
        try: opaque = self._opaque(message) if isinstance(message, dict) else []
        except ValueError: opaque = []
        with self._lock:
            if opaque and charge is not None:
                key = self._digest(opaque)
                receipt = {'tokens': charge, 'response_id': response.get('id'),
                           'basis': 'reported_reasoning_tokens' if reasoning is not None else
                                    'reported_completion_tokens_upper_estimate'}
                previous = self._receipts.get(key)
                if previous is None or charge > previous['tokens']:
                    self._receipts[key] = receipt
            prompt = self._tokens(usage.get('prompt_tokens'))
            if isinstance(request, dict) and isinstance(request.get('messages'), list) and prompt is not None:
                key = self._digest([request['messages'], request.get('tools', [])])
                previous = self._measurements.get(key)
                self._anchor = ({'messages': deepcopy(request['messages']),
                    'tools': deepcopy(request.get('tools', [])), 'prompt_tokens': prompt,
                    'measurement': previous, 'response_id': response.get('id')} if previous else None)

    def __call__(self, messages, tools):
        with self._lock:
            receipts = dict(self._receipts)
            anchor = self._anchor
        selected = deepcopy(messages)
        hidden = 0; evidence = []
        for message in selected:
            if message.get('role') != 'assistant': continue
            opaque = self._opaque(message)
            if not opaque: continue
            key = self._digest(opaque)
            receipt = receipts.get(key)
            if receipt is None:
                raise ValueError('Opaque reasoning has no matching provider usage evidence; '
                                 'supply an authoritative backend input counter')
            hidden += receipt['tokens']
            evidence.append({'block_group_sha256': key, **receipt})
            # This copy is only for local visible-token measurement. Neither the
            # outgoing request nor the persisted/replayed assistant is altered.
            message['reasoning_details'] = [d for d in message['reasoning_details']
                                           if d.get('type') == 'reasoning.text']
        measured = self.visible_counter(selected, tools)
        visible = measured['input_tokens']
        with self._lock:
            self._measurements[self._digest([messages, tools])] = {'visible': visible, 'hidden': hidden}
            while len(self._measurements) > 8:
                del self._measurements[next(iter(self._measurements))]
        if not evidence:
            return measured  # Plain-text/Qwen default remains byte-for-byte identical.
        estimated = visible + hidden
        anchored = None
        if (anchor and tools == anchor['tools'] and
                messages[:len(anchor['messages'])] == anchor['messages']):
            growth = max(0, visible-anchor['measurement']['visible']) + max(0, hidden-anchor['measurement']['hidden'])
            anchored = {'response_id': anchor['response_id'], 'prompt_tokens': anchor['prompt_tokens'],
                        'estimated_added_tokens': growth, 'input_tokens': anchor['prompt_tokens']+growth}
            estimated = max(estimated, anchored['input_tokens'])
        return {**measured, 'method': 'opaque-usage-anchored-input-v1', 'input_tokens': estimated,
                'visible_estimator': measured.get('method'), 'visible_input_tokens': visible,
                'retained_hidden_tokens_estimate': hidden, 'opaque_usage_evidence': evidence,
                'provider_anchor': anchored, 'exact_provider_tokens': False,
                'scope': 'Conservative next-input estimate: local visible tokens plus originating usage for retained opaque reasoning; '
                         'max with previous provider prompt usage plus estimated appended growth when prefix matches. '
                         'Not cumulative episode usage or a guaranteed bound; provider tokenization and signature handling may differ.'}
