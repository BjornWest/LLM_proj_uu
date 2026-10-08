"""Local model-matched request sizing, separate from AX output budgeting.

Assets are installed explicitly, pinned to official revisions, and never fetched
by a running episode. Hosted providers may still change their chat/vision
processing; retained provider usage is the authority for completed requests.
"""
from copy import deepcopy
import base64
import hashlib
from io import BytesIO
import json
import math
from pathlib import Path
from urllib.parse import urlparse

from .input_budget import OpaqueReasoningInputCounter, QwenInputCounter


REGISTRY = Path(__file__).with_name('model_tokenizers.json')


def _assets(model, assets_root):
    registry = json.loads(REGISTRY.read_text())
    if model not in registry['models']:
        raise ValueError(f'No model-matched input tokenizer registered for {model!r}; '
                         'register official assets or supply an explicit input_counter')
    entry = registry['models'][model]
    root = (Path(assets_root) if assets_root is not None else
            Path(__file__).resolve().parents[1] / '.local/model-tokenizers')
    bundle = root / entry['bundle']
    if bundle.is_symlink() or not bundle.is_dir():
        raise ValueError(f'Missing local tokenizer for {model}: {bundle}; '
                         f'run scripts/fetch_model_tokenizer.py {model}')
    for name, expected in entry['files'].items():
        path = bundle / name
        if (path.is_symlink() or not path.is_file() or
                hashlib.sha256(path.read_bytes()).hexdigest() != expected['sha256']):
            raise ValueError(f'Missing/mismatched {model} tokenizer asset: {path}')
    return entry, bundle


def glm_image_tokens(height, width, processor):
    """Official Glm5Next aligned canvas/patch count, without GPU preprocessing.

    Mirrors HF Glm5Next smart_resize and image_grid_thw.prod()/merge_size**2.
    Source: transformers/models/glm5_next/image_processing_glm5_next.py.
    """
    factor = processor['patch_size'] * processor['merge_size'] * processor['patch_expand_factor']
    frames = processor['temporal_patch_size']
    minimum = processor['min_image_tokens'] * frames * factor**2
    maximum = processor['max_image_tokens'] * frames * factor**2
    align = lambda value: math.ceil(value / factor) * factor
    h, w = align(height), align(width)
    if frames * h * w < minimum:
        scale = math.sqrt(minimum / (frames * height * width))
        h, w = align(max(1, math.ceil(height * scale))), align(max(1, math.ceil(width * scale)))
    if frames * h * w > maximum:
        low, high = 1, height
        h = w = factor
        while low <= high:
            content_height = (low + high) // 2
            candidate_h = align(content_height)
            candidate_w = align(max(1, math.floor(width * content_height / height)))
            if frames * candidate_h * candidate_w <= maximum:
                h, w = candidate_h, candidate_w
                low = content_height + 1
            else:
                high = content_height - 1
    return (h // processor['patch_size']) * (w // processor['patch_size']) // processor['merge_size']**2


class GlmInputCounter:
    def __init__(self, model, entry, bundle, *, reasoning_effort=None):
        from jinja2.sandbox import ImmutableSandboxedEnvironment
        from tokenizers import Tokenizer
        self.model = model
        # ASCII JSON reserialization is semantically identical to the pinned
        # official file and avoids its direct-load incompatibility with 0.23.2.
        self.tokenizer = Tokenizer.from_str(json.dumps(json.loads((bundle / 'tokenizer.json').read_text())))
        env = ImmutableSandboxedEnvironment(trim_blocks=True, lstrip_blocks=True,
                                            extensions=['jinja2.ext.loopcontrols'])
        env.filters['tojson'] = lambda value, **kwargs: json.dumps(value, **kwargs)
        self.template = env.from_string((bundle / 'chat_template.jinja').read_text())
        self.processor = json.loads((bundle / 'processor_config.json').read_text())['image_processor']
        self.reasoning_effort = reasoning_effort
        self.provenance = {
            'method': 'glm-official-local-template-v1', 'model': model,
            'repository': entry['repository'], 'revision': entry['revision'],
            'tokenizer_sha256': entry['files']['tokenizer.json']['sha256'],
            'template_sha256': entry['files']['chat_template.jinja']['sha256'],
            'processor_sha256': entry['files']['processor_config.json']['sha256'],
            'registry_sha256': hashlib.sha256(REGISTRY.read_bytes()).hexdigest(),
            'reasoning_effort': reasoning_effort or 'max',
            'scope': 'Complete next input using official model tokenizer/template and image processor sizing; '
                     'hosted processing may differ. Not cumulative usage or an output reservation.',
        }

    def __call__(self, messages, tools):
        from PIL import Image
        selected = deepcopy(messages)
        image_extra = images = 0
        for message in selected:
            if message['role'] not in ('system', 'user', 'assistant', 'tool'):
                raise ValueError('Unsupported role for GLM input sizing')
            if message['role'] == 'assistant':
                details = message.get('reasoning_details')
                if details:
                    if any(d.get('type') != 'reasoning.text' for d in details):
                        raise ValueError('Opaque reasoning requires usage-backed input sizing')
                    message['reasoning_content'] = '\n'.join(d.get('text', '') for d in details)
                else:
                    message['reasoning_content'] = message.get('reasoning_content') or message.get('reasoning') or ''
                for call in message.get('tool_calls', []):
                    function = call.get('function', call)
                    if isinstance(function.get('arguments'), str):
                        function['arguments'] = json.loads(function['arguments'])
                    if not isinstance(function.get('arguments'), dict):
                        raise ValueError('Tool arguments must be a JSON object')
            content = message.get('content')
            if not isinstance(content, list):
                if content is not None and not isinstance(content, str):
                    raise ValueError('Unsupported content for GLM input sizing')
                continue
            for part in content:
                if part.get('type') == 'text':
                    continue
                if part.get('type') != 'image_url':
                    raise ValueError('Unsupported modality for GLM input sizing')
                url = part['image_url']['url']
                if not url.startswith(('data:image/png;base64,', 'data:image/jpeg;base64,')):
                    raise ValueError('Image sizing requires retained PNG/JPEG bytes; no remote fetch')
                with Image.open(BytesIO(base64.b64decode(url.split(',', 1)[1], validate=True))) as image:
                    width, height = image.size
                # The official template already emits one <|image|> placeholder.
                image_extra += glm_image_tokens(height, width, self.processor) - 1
                images += 1
        text = self.template.render(messages=selected, tools=tools or [], add_generation_prompt=True,
                                    reasoning_effort=self.reasoning_effort)
        count = len(self.tokenizer.encode(text, add_special_tokens=False).ids) + image_extra
        return {**self.provenance, 'input_tokens': count, 'images': images}


def model_matched_input_counter(backend, *, ax_tokenizer_path=None, assets_root=None):
    """Default factory for a bounded episode; explicit caller counters bypass it.

    OpenRouter always needs an exact registered model; AX text tokenization is
    not evidence of the policy model's tokenizer. Non-OpenRouter legacy/fake
    backends retain their existing AX-counter behavior until explicitly adopted.
    """
    model = getattr(backend, 'model', None)
    is_openrouter = urlparse(getattr(backend, 'base_url', '')).hostname == 'openrouter.ai'
    registry = json.loads(REGISTRY.read_text())
    if not is_openrouter and model not in registry['models']:
        if not ax_tokenizer_path:
            raise ValueError('Input limit requires an explicit counter or local tokenizer')
        return OpaqueReasoningInputCounter(QwenInputCounter(ax_tokenizer_path))
    entry, bundle = _assets(model, assets_root)
    if entry['counter'] == 'qwen':
        counter = QwenInputCounter(bundle / 'tokenizer.json')
        counter.provenance.update(model=model, repository=entry['repository'], revision=entry['revision'],
                                  registry_sha256=hashlib.sha256(REGISTRY.read_bytes()).hexdigest())
    elif entry['counter'] == 'glm':
        reasoning = getattr(backend, 'request_options', {}).get('reasoning') or {}
        counter = GlmInputCounter(model, entry, bundle, reasoning_effort=reasoning.get('effort'))
    else:
        raise ValueError('Unsupported registered input counter: ' + entry['counter'])
    return OpaqueReasoningInputCounter(counter)
