"""Model identity/asset failures and official GLM request sizing (no providers)."""
import base64
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from PIL import Image

from intent_browser.model_input_budget import model_matched_input_counter, glm_image_tokens, REGISTRY


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / '.local/model-tokenizers'
REGISTRY_DATA = json.loads(REGISTRY.read_text())
INSTALLED = all((ASSETS / e['bundle'] / 'tokenizer.json').is_file()
                for e in REGISTRY_DATA['models'].values())


def backend(model='z-ai/glm-5.3-flash'):
    return SimpleNamespace(model=model, base_url='https://openrouter.ai/api/v1',
                           request_options={'reasoning': {'enabled': True}})


class SelectionTests(unittest.TestCase):
    def test_unknown_openrouter_model_never_falls_back_to_ax_tokenizer(self):
        with self.assertRaisesRegex(ValueError, 'No model-matched'):
            model_matched_input_counter(backend('unknown/model'), ax_tokenizer_path='unused')

    def test_missing_assets_fail_locally(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(ValueError, 'Missing local tokenizer'):
                model_matched_input_counter(backend(), assets_root=root)

    def test_mismatched_asset_rejected_before_loading(self):
        with tempfile.TemporaryDirectory() as root:
            entry = REGISTRY_DATA['models']['z-ai/glm-5.3-flash']
            bundle = Path(root) / entry['bundle']; bundle.mkdir()
            for name in entry['files']:
                (bundle / name).write_text('{}')
            with self.assertRaisesRegex(ValueError, 'mismatched'):
                model_matched_input_counter(backend(), assets_root=root)

    def test_qwen_model_cannot_load_glm_bundle(self):
        with tempfile.TemporaryDirectory() as root:
            wrong = Path(root) / REGISTRY_DATA['models']['qwen/qwen3.8-27b']['bundle']
            wrong.mkdir()
            (wrong / 'tokenizer.json').write_text('{"model":"glm"}')
            with self.assertRaisesRegex(ValueError, 'mismatched'):
                model_matched_input_counter(backend('qwen/qwen3.8-27b'), assets_root=root)


@unittest.skipUnless(INSTALLED, 'Explicit official tokenizer install required')
class OfficialAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.glm = model_matched_input_counter(backend(), assets_root=ASSETS)
        cls.qwen = model_matched_input_counter(backend('qwen/qwen3.8-27b'), assets_root=ASSETS)

    def test_complete_request_and_model_provenance(self):
        messages = [{'role': 'system', 'content': 'Be helpful'}, {'role': 'user', 'content': 'Count comments'}]
        measured = self.glm(messages, [])
        self.assertEqual(measured['model'], 'z-ai/glm-5.3-flash')
        self.assertEqual(measured['method'], 'glm-official-local-template-v1')
        self.assertGreater(measured['input_tokens'], 0)
        self.assertNotEqual(measured['tokenizer_sha256'], self.qwen(messages, [])['tokenizer_sha256'])

    def test_reasoning_tools_and_originals_are_preserved(self):
        messages = [{'role': 'user', 'content': 'Inspect'},
                    {'role': 'assistant', 'content': None,
                     'reasoning_details': [{'type': 'reasoning.text', 'text': 'Check the remaining comments.'}],
                     'tool_calls': [{'id': 'call1', 'type': 'function',
                                    'function': {'name': 'read', 'arguments': '{"limit": 2}'}}]},
                    {'role': 'tool', 'tool_call_id': 'call1', 'content': 'Two comments'}]
        tools = [{'type': 'function', 'function': {'name': 'read', 'parameters': {'type': 'object'}}}]
        before = deepcopy((messages, tools))
        measured = self.glm(messages, tools)
        self.assertEqual((messages, tools), before)
        shorter = deepcopy(messages); shorter[1]['reasoning_details'] = []
        self.assertGreater(measured['input_tokens'], self.glm(shorter, tools)['input_tokens'])

    def test_local_png_uses_glm_processor_sizing(self):
        data = BytesIO(); Image.new('RGB', (560, 280)).save(data, format='PNG')
        url = 'data:image/png;base64,' + base64.b64encode(data.getvalue()).decode()
        messages = [{'role': 'user', 'content': [{'type': 'image_url', 'image_url': {'url': url}}]}]
        result = self.glm(messages, [])
        self.assertEqual(result['images'], 1)
        self.assertEqual(glm_image_tokens(280, 560, self.glm.visible_counter.processor), 200)
        self.assertGreater(result['input_tokens'], 200)

    def test_remote_image_and_unsupported_modality_rejected_without_fetch(self):
        for part in [{'type': 'image_url', 'image_url': {'url': 'https://example.test/image.png'}},
                     {'type': 'input_audio', 'input_audio': {'data': 'anything'}}]:
            with self.assertRaises(ValueError):
                self.glm([{'role': 'user', 'content': [part]}], [])

    def test_glm_large_image_budget_and_small_image_minimum(self):
        processor = self.glm.visible_counter.processor
        self.assertGreaterEqual(glm_image_tokens(1, 1, processor), 16)
        self.assertLessEqual(glm_image_tokens(10000, 20000, processor), 8000)


if __name__ == '__main__':
    unittest.main()
