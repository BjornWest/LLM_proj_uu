"""Offline request-boundary checks; no provider inference or browser startup."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from intent_browser.actions import parse_action
from intent_browser.backend import ChatCompletionsBackend
from intent_browser.openrouter import DEFAULT_PROVIDERS, completion_token_limit, provider_options


class ReasoningDefaultsTests(unittest.TestCase):
    def backend(self, response, **kwargs):
        backend = ChatCompletionsBackend(kwargs.pop('base_url', 'https://openrouter.ai/api/v1'),
                                         'fixture-model', 'offline-secret', **kwargs)
        backend.client.close()
        self.requests = []

        def reply(request):
            self.requests.append(json.loads(request.content))
            return httpx.Response(200, json=response)

        backend.client = httpx.Client(transport=httpx.MockTransport(reply))
        self.addCleanup(backend.close)
        return backend

    def test_direct_routed_and_preset_openrouter_requests_default_on(self):
        response = {'choices': [{'message': {'content': 'noop()'}}]}
        for options in [{}, provider_options(DEFAULT_PROVIDERS), {'preset': '@preset/fixture'}]:
            with self.subTest(options=options):
                backend = self.backend(response, request_options=options)
                backend.complete([{'role': 'user', 'content': 'Page'}])
                self.assertEqual(self.requests[0]['reasoning'], {'enabled': True})
                self.assertEqual(self.requests[0]['max_tokens'], 4096)
                self.assertNotIn('offline-secret', json.dumps(self.requests[0]))

    def test_explicit_experiment_overrides_are_preserved(self):
        options = {'reasoning': {'enabled': False}}
        backend = self.backend({'choices': [{'message': {'content': 'noop()'}}]},
                               max_tokens=512, request_options=options)
        backend.complete([])
        self.assertEqual(self.requests[0]['reasoning'], {'enabled': False})
        self.assertEqual(self.requests[0]['max_tokens'], 512)
        self.assertEqual(options, {'reasoning': {'enabled': False}})

    def test_local_endpoint_does_not_receive_openrouter_fields(self):
        backend = self.backend({'choices': [{'message': {'content': 'noop()'}}]},
                               base_url='http://localhost:8000/v1')
        backend.complete([])
        self.assertNotIn('reasoning', self.requests[0])
        self.assertEqual(self.requests[0]['max_tokens'], 128)

    def test_reasoning_is_retained_but_only_final_content_becomes_an_action(self):
        raw = {'choices': [{'message': {'content': "click('7')", 'reasoning': "click('wrong')",
                                       'reasoning_details': [{'type': 'reasoning.text', 'text': 'diagnostic'}]}}],
               'usage': {'completion_tokens': 2050, 'completion_tokens_details': {'reasoning_tokens': 2040}}}
        completion = self.backend(raw).complete([])
        self.assertEqual(parse_action(completion.text), "click('7')")
        self.assertEqual(completion.raw, raw)
        self.assertEqual(len(self.requests), 1)

    def test_reasoning_only_truncation_is_not_promoted_to_an_action_or_retried(self):
        raw = {'choices': [{'message': {'content': None, 'reasoning': "click('wrong')"},
                            'finish_reason': 'length'}],
               'usage': {'completion_tokens': 4096, 'completion_tokens_details': {'reasoning_tokens': 4096}}}
        completion = self.backend(raw).complete([])
        with self.assertRaises((ValueError, SyntaxError)):
            parse_action(completion.text)
        self.assertEqual(completion.raw, raw)
        self.assertEqual(len(self.requests), 1)

    def test_token_setting_is_positive_integer(self):
        self.assertEqual(completion_token_limit(), 4096)
        self.assertEqual(completion_token_limit('8192'), 8192)
        for value in [0, -1, True, 4.5, '', '1e3', 'oops']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                completion_token_limit(value)

    def test_cli_token_default_env_file_and_explicit_override(self):
        from intent_browser import cli
        for env_value, explicit, expected in [(None, None, 4096), ('8192', None, 8192), ('8192', '1024', 1024)]:
            with self.subTest(env_value=env_value, explicit=explicit), tempfile.TemporaryDirectory() as directory:
                config = Path(directory) / '.env'
                config.write_text('MODEL_BASE_URL=https://openrouter.ai/api/v1\nMODEL_NAME=fixture\n' +
                                  (f'OPENROUTER_MAX_TOKENS={env_value}\n' if env_value else ''))
                argv = ['intent-browser', 'run', '--env-file', str(config), '--no-preview']
                if explicit:
                    argv += ['--max-tokens', explicit]
                captured = []

                def run(factory, backend, metadata, *args):
                    captured.append((backend.max_tokens, metadata['generation']))
                    return Path(directory), {'error': None}

                with patch.dict(os.environ, {'MODEL_API_KEY': 'offline-secret'}, clear=True), \
                        patch('sys.argv', argv), patch.object(cli, 'run_episode', side_effect=run):
                    cli.main()
                self.assertEqual(captured[0][0], expected)
                self.assertEqual(captured[0][1]['max_tokens'], expected)
                self.assertEqual(captured[0][1]['reasoning'], {'enabled': True})


if __name__ == '__main__':
    unittest.main()
