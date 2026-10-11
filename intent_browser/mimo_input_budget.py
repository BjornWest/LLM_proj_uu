"""Official MiMo text/tool/image request sizing; audio/video fail locally."""
from copy import deepcopy
import base64
from io import BytesIO
import math
import json

from .input_budget import QwenInputCounter


class MimoInputCounter(QwenInputCounter):
    """Reuse history normalization, using MiMo's own vocabulary and template.

    Image sizing uses MiMo's pinned Qwen2VL processor configuration, rather
    than the unrelated hard-coded Qwen3.8 budgets in the parent counter.
    """
    def __init__(self, model, entry, bundle, reasoning, *, shared_tokenizer=None):
        from jinja2.sandbox import ImmutableSandboxedEnvironment
        super().__init__(bundle / 'tokenizer.json', shared_tokenizer=shared_tokenizer)
        enabled = reasoning.get('enabled', reasoning.get('effort') != 'none')
        if type(enabled) is not bool:
            raise ValueError('MiMo reasoning.enabled must be boolean')
        env = ImmutableSandboxedEnvironment(trim_blocks=True, lstrip_blocks=True)
        env.filters['tojson'] = lambda value, **kwargs: json.dumps(value, **kwargs)
        template = env.from_string((bundle / 'chat_template.jinja').read_text())
        from .model_input_budget import _ConfiguredTemplate
        self.template = _ConfiguredTemplate(template, enable_thinking=enabled)
        self.processor = json.loads((bundle / 'preprocessor_config.json').read_text())
        self.provenance = {
            'method': 'mimo-official-local-template-v1', 'model': model,
            'repository': entry['repository'], 'revision': entry['revision'],
            'tokenizer_sha256': entry['files']['tokenizer.json']['sha256'],
            'template_sha256': entry['files']['chat_template.jinja']['sha256'],
            'processor_sha256': entry['files']['preprocessor_config.json']['sha256'],
            'reasoning_enabled': enabled, 'modalities': ['text', 'tools', 'image'],
            'scope': 'Complete next input using official MiMo tokenizer/template/processor configuration; '
                     'hosted formatting may differ. Not cumulative usage or output reservation.',
        }
        if shared_tokenizer is not None:
            self.provenance['tokenizer_service'] = self.tokenizer.provenance

    def __call__(self, messages, tools):
        selected = deepcopy(messages)
        image_extra = images = 0
        for message in selected:
            if message.get('role') not in ('system', 'user', 'assistant', 'tool'):
                raise ValueError('Unsupported role for MiMo input sizing')
            content = message.get('content')
            if isinstance(content, list):
                for index, part in enumerate(content):
                    if not isinstance(part, dict):
                        raise ValueError('Unsupported MiMo content part')
                    if part.get('type') == 'text' and set(part) <= {'type', 'text'} and isinstance(part.get('text'), str):
                        continue
                    if part.get('type') != 'image_url' or set(part) != {'type', 'image_url'}:
                        raise ValueError('Unsupported modality for MiMo input sizing')
                    url = part['image_url']['url']
                    if not url.startswith(('data:image/png;base64,', 'data:image/jpeg;base64,')):
                        raise ValueError('MiMo sizing needs retained PNG/JPEG bytes; no remote fetch')
                    from PIL import Image
                    with Image.open(BytesIO(base64.b64decode(url.split(',', 1)[1], validate=True))) as image:
                        width, height = image.size
                    factor = self.processor['patch_size'] * self.processor['merge_size']
                    if max(width, height) / min(width, height) > 200:
                        raise ValueError('Unsupported MiMo image aspect ratio')
                    h, w = round(height / factor) * factor, round(width / factor) * factor
                    if h * w > self.processor['max_pixels']:
                        scale = math.sqrt(height * width / self.processor['max_pixels'])
                        h, w = max(factor, math.floor(height / scale / factor) * factor), max(factor, math.floor(width / scale / factor) * factor)
                    elif h * w < self.processor['min_pixels']:
                        scale = math.sqrt(self.processor['min_pixels'] / (height * width))
                        h, w = math.ceil(height * scale / factor) * factor, math.ceil(width * scale / factor) * factor
                    image_extra += (h // factor) * (w // factor) - 1
                    images += 1
                    # Same literal sequence as the official render_content image
                    # branch. Parent normalization now sees no image and cannot
                    # apply its unrelated image budgets; add MiMo patch tokens.
                    content[index] = {'type': 'text', 'text': '<|vision_start|><|image_pad|><|vision_end|>'}
            elif content is not None and not isinstance(content, str):
                raise ValueError('Unsupported content for MiMo input sizing')
            for call in message.get('tool_calls') or []:
                arguments = call.get('function', call).get('arguments')
                if isinstance(arguments, str):
                    arguments = json.loads(arguments)
                if not isinstance(arguments, dict):
                    raise ValueError('MiMo tool arguments must be a JSON object')
        # The parent copies histories before normalizing arguments/reasoning.
        measured = super().__call__(selected, tools)
        return {**measured, 'input_tokens': measured['input_tokens'] + image_extra, 'images': images}
