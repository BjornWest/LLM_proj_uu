"""Official text/tool formatting, isolation and fail-closed MiMo controls."""
from copy import deepcopy
import base64
from io import BytesIO
from PIL import Image
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest

from jinja2.sandbox import ImmutableSandboxedEnvironment
from tokenizers import Tokenizer
from intent_browser.model_input_budget import model_matched_input_counter, REGISTRY

MODEL = 'xiaomi/mimo-v2.6-pro'
ASSETS = Path(os.environ.get('MIMO_TEST_ASSETS', Path(__file__).resolve().parents[1] / '.local/model-tokenizers'))
ENTRY = json.loads(REGISTRY.read_text())['models'][MODEL]
INSTALLED = (ASSETS / ENTRY['bundle'] / 'tokenizer.json').is_file()


@unittest.skipUnless(INSTALLED, 'Explicit official MiMo tokenizer install required')
class MimoTests(unittest.TestCase):
    def counter(self, reasoning=None):
        backend = SimpleNamespace(model=MODEL, base_url='https://openrouter.ai/api/v1',
                                  request_options={'reasoning': reasoning or {'enabled': True}})
        return model_matched_input_counter(backend, assets_root=ASSETS)

    def test_official_complete_request_and_originals(self):
        entry = json.loads(REGISTRY.read_text())['models'][MODEL]
        bundle = ASSETS / entry['bundle']
        tokenizer = Tokenizer.from_file(str(bundle / 'tokenizer.json'))
        env = ImmutableSandboxedEnvironment(trim_blocks=True, lstrip_blocks=True)
        env.filters['tojson'] = lambda value, **kw: json.dumps(value, **kw)
        template = env.from_string((bundle / 'chat_template.jinja').read_text())
        tools = [{'type': 'function', 'function': {'name': 'read', 'parameters': {'type': 'object'}}}]
        messages = [{'role': 'system', 'content': 'Be helpful'},
                    {'role': 'user', 'content': [{'type': 'text', 'text': 'Read naïve comments.'}]},
                    {'role': 'assistant', 'content': None,
                     'reasoning_details': [{'type': 'reasoning.text', 'text': 'Check page two.'}],
                     'tool_calls': [{'id': '1', 'type': 'function',
                                     'function': {'name': 'read', 'arguments': '{"limit": 2}'}}]},
                    {'role': 'tool', 'tool_call_id': '1', 'content': 'Two comments'}]
        original = deepcopy((messages, tools))
        rendered = deepcopy(messages)
        rendered[2]['reasoning_content'] = 'Check page two.'
        rendered[2]['tool_calls'][0]['function']['arguments'] = {'limit': 2}
        for enabled in (True, False):
            with self.subTest(enabled=enabled):
                expected = template.render(messages=rendered, tools=tools,
                                           add_generation_prompt=True, enable_thinking=enabled)
                measured = self.counter({'enabled': enabled})(messages, tools)
                self.assertEqual(measured['input_tokens'], len(tokenizer.encode(expected, add_special_tokens=False).ids))
                self.assertEqual(measured['model'], MODEL)
                self.assertEqual(measured['images'], 0)
                self.assertEqual(measured['reasoning_enabled'], enabled)
        self.assertEqual((messages, tools), original)

    def test_reasoning_and_tools_increase_input(self):
        counter = self.counter()
        plain = [{'role': 'user', 'content': 'Hello'}]
        extra = plain + [{'role': 'assistant', 'content': '', 'reasoning': 'Check every relevant comment carefully.'}]
        self.assertGreater(counter(extra, [])['input_tokens'], counter(plain, [])['input_tokens'])
        self.assertGreater(counter(plain, [{'type': 'function', 'function': {'name': 'read'}}])['input_tokens'], counter(plain, [])['input_tokens'])

    def test_unsupported_modality_role_arguments_and_settings_fail(self):
        for messages in ([{'role': 'developer', 'content': 'X'}],
                         [{'role': 'user', 'content': [{'type': 'image_url', 'image_url': {'url': 'https://example.test/x'}}]}],
                         [{'role': 'user', 'content': 3}],
                         [{'role': 'user', 'content': [{'type': 'text', 'text': 'X', 'image_url': {'url': 'x'}}]}],
                         [{'role': 'assistant', 'content': '', 'tool_calls': [{'function': {'name': 'read', 'arguments': '[1]'}}]}],
                         [{'role': 'assistant', 'content': '', 'reasoning_details': [{'type': 'reasoning.encrypted', 'data': 'unknown'}]}]):
            with self.subTest(messages=messages), self.assertRaises(ValueError):
                self.counter()(messages, [])
        with self.assertRaises(ValueError):
            self.counter({'enabled': 'yes'})

    def test_local_image_uses_pinned_processor_and_preserves_input(self):
        data = BytesIO(); Image.new('RGB', (320, 320)).save(data, format='PNG')
        url = 'data:image/png;base64,' + base64.b64encode(data.getvalue()).decode()
        messages = [{'role': 'user', 'content': [{'type': 'image_url', 'image_url': {'url': url}}]}]
        original = deepcopy(messages)
        counter = self.counter()
        measured = counter(messages, [])
        visible = counter([{'role': 'user', 'content': '<|vision_start|><|image_pad|><|vision_end|>'}], [])
        self.assertEqual(measured['input_tokens'], visible['input_tokens'] + 99)
        self.assertEqual(measured['images'], 1)
        self.assertEqual(messages, original)

    def test_missing_assets_rejected(self):
        backend = SimpleNamespace(model=MODEL, base_url='https://openrouter.ai/api/v1', request_options={})
        with self.assertRaisesRegex(ValueError, 'Missing local tokenizer'):
            model_matched_input_counter(backend, assets_root=ASSETS / 'absent')


if __name__ == '__main__':
    unittest.main()
