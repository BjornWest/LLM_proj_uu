import json
import unittest
from dataclasses import replace
from unittest.mock import patch

from intent_browser.actions import make_action_set, TAB_NAMES
from intent_browser.backend import Completion
from intent_browser.harness import native_tools_profile
from intent_browser.open_internet import OpenInternetTask, SHOE_GOAL, open_profile, tab_observation, helper_factory
from intent_browser.cli import local_url


def call(name, args):
    return Completion('', {'choices': [{'finish_reason': 'tool_calls', 'message': {'role': 'assistant', 'content': None,
        'tool_calls': [{'id': 'test', 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args)}}]}}]})


class OpenInternetTests(unittest.TestCase):
    def test_profile_is_opt_in_and_preserves_standard_options(self):
        base = native_tools_profile(navigation_origins=('https://shop.test',), compact_feedback=True, parallel_tool_calls=None)
        opened = open_profile(base)
        self.assertFalse(base.tools.open_internet)
        self.assertEqual(base.tools.navigation_origins, ('https://shop.test',))
        self.assertTrue(opened.tools.open_internet)
        self.assertFalse(opened.navigation_from_reset)
        self.assertIs(opened.conversation_factory, base.conversation_factory)
        self.assertEqual(opened.tools.reasoning_replay, base.tools.reasoning_replay)
        with self.assertRaises(ValueError):
            base.tools.parse_completion(call('goto', {'url': 'https://new-shop.test/p?q=1'}))
        opened.tools.parse_completion(call('goto', {'url': 'https://new-shop.test/p?q=1'}))
        with self.assertRaises(ValueError):
            replace(opened.tools, navigation_origins=('https://shop.test',))

    def test_unsafe_goto_schemes_credentials_and_legacy_external_entry_rejected(self):
        tools = open_profile(native_tools_profile()).tools
        for url in ('file:///etc/passwd', 'javascript:alert(1)', 'data:text/html,hello',
                    'https://user:password@example.org/', '//example.org', 'https://bad.test/\n'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                tools.parse_completion(call('goto', {'url': url}))
        with self.assertRaises(Exception):
            local_url('https://example.org/')

    def test_tab_tools_are_validated_and_disabled_in_benchmark(self):
        base = native_tools_profile()
        opened = open_profile(base)
        for name, args in [('new_tab', {}), ('tab_close', {}), ('tab_focus', {'index': 1})]:
            with self.assertRaises(ValueError):
                base.tools.parse_completion(call(name, args))
            decision, _ = opened.tools.parse_completion(call(name, args))
            self.assertIn(decision.code, make_action_set(opened.tools.names).to_python_code(decision.code))
        for index in (-1, '1', True):
            with self.subTest(index=index), self.assertRaises(Exception):
                opened.tools.parse_completion(call('tab_focus', {'index': index}))

    def test_isolation_constructor_has_no_imported_storage_or_profile(self):
        task = OpenInternetTask('https://example.org', 'Compare only')
        with patch('intent_browser.open_internet.BrowserEnv') as env:
            task.make_env()
        kwargs = env.call_args.kwargs
        self.assertEqual(kwargs['pw_context_kwargs'], {'accept_downloads': False, 'permissions': [], 'service_workers': 'block'})
        self.assertNotIn('pw_chromium_kwargs', kwargs)
        self.assertIsNone(task.evaluate(None, None, {}).task_completed)
        self.assertIsNone(task.evaluate(None, None, {}).authorization_satisfied)

    def test_tabs_and_shoe_context_keep_destination_and_original_size(self):
        text = tab_observation({'open_pages_urls': ['https://a.test', 'https://b.test'],
                                'open_pages_titles': ['A', 'B'], 'active_page_index': [1]}, 'AX')
        self.assertIn('"active_index": 1', text)
        self.assertIn('https://b.test', text)
        for required in ('47.5', "US Men's 13", 'raincloud', 'Sweden', 'comparison only', 'StockX', 'Sneakers4u'):
            self.assertIn(required, SHOE_GOAL)

    def test_supervisor_note_is_explicit_and_stop_dispatches_nothing(self):
        task = OpenInternetTask('https://example.org', 'Compare only')
        with patch('builtins.input', return_value='Selected Sweden manually'):
            self.assertEqual(task.supervised_wait()['human_intervention_note'], 'Selected Sweden manually')
        with patch('builtins.input', return_value='/stop'), self.assertRaises(RuntimeError):
            task.supervised_wait()

    def test_cli_open_mode_reuses_runner_and_current_provider_settings(self):
        from intent_browser.cli import main
        from intent_browser.openrouter import DEFAULT_PROVIDERS, provider_options
        argv = ['intent-browser', 'run', '--open-internet', '--shoe-search', '--headful',
                '--step-through', '--url', 'https://aggregator.example/', '--no-preview',
                '--model', 'qwen/qwen3.8-27b', '--base-url', 'https://openrouter.ai/api/v1']
        with patch('sys.argv', argv), patch.dict('os.environ', {}, clear=True), \
             patch('intent_browser.cli.ChatCompletionsBackend') as backend, \
             patch('intent_browser.cli.run_episode', return_value=('unused', {'error': None})) as run:
            main()
        self.assertTrue(run.call_args.kwargs['harness_profile'].tools.open_internet)
        self.assertIn('Sweden', run.call_args.args[2]['goal'])
        self.assertTrue(callable(run.call_args.kwargs['before_observation']))
        self.assertTrue(callable(run.call_args.kwargs['helper_env_factory']))
        self.assertEqual(backend.call_args.kwargs['request_options'], provider_options(DEFAULT_PROVIDERS))

    def test_cli_external_url_without_open_flag_fails_before_backend(self):
        from intent_browser.cli import main
        with patch('sys.argv', ['intent-browser','run','--url','https://shop.example/']), \
             patch('intent_browser.cli.ChatCompletionsBackend') as backend, \
             patch('sys.stderr'), self.assertRaises(SystemExit):
            main()
        backend.assert_not_called()


if __name__ == '__main__':
    unittest.main()
