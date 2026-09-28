"""Recoverable browser failures must survive policy presentation unchanged in raw traces."""
from copy import deepcopy
from dataclasses import replace
import json
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from intent_browser.ax_context import AXContext
from intent_browser.ax_explorer import AXConfig, encoded
from intent_browser.batching import batch_result
from intent_browser.feedback_presentation import CompactFeedback, summarize_action_error
from intent_browser.harness import SemanticFeedback, native_tools_profile
from intent_browser.runner import run_episode
from tests.test_ax_explorer import TOKENIZER, node, observation
from tests.test_native_batch import response


ERROR = 'TimeoutError: Locator.click: Timeout 30000ms exceeded.\nCall log:\n' + ''.join(
    f'  - retrying click action, attempt #{i}\n'
    '  - element is visible, enabled and stable\n'
    '  - <div bid="368">quantity control</div> intercepts pointer events\n'
    '  - <input bid="377" role="spinbutton"/> intercepts pointer events\n'
    for i in range(62))


class ErrorPresentationTests(unittest.TestCase):
    def test_shared_summary_retains_unique_blockers_not_retries(self):
        raw = {'execution': 'action_error', 'error': ERROR, 'tool': 'click'}
        saved = deepcopy(raw)
        single = CompactFeedback()(raw, kind='browser_feedback')
        batch = batch_result(raw)
        for result in (single, batch):
            self.assertEqual(result['execution'], 'action_error')
            self.assertTrue(result['error_details_omitted'])
            self.assertEqual(result['error'].count('intercepts pointer events'), 2)
            self.assertIn('spinbutton', result['error'])
            self.assertNotIn('attempt #', result['error'])
            self.assertIn('not confirmed', result['recovery_hint'])
        self.assertEqual(single['error'], batch['error'])
        self.assertEqual(raw, saved)

    def test_unknown_errors_and_short_errors_remain_honest(self):
        self.assertEqual(summarize_action_error('ValueError: missing field'), 'ValueError: missing field')
        out = batch_result({'execution': 'action_error', 'error': 'E'*10000})
        self.assertTrue(out['error_details_omitted'])
        self.assertLess(len(out['error']), 650)
        self.assertNotIn('recovery_hint', out)
        self.assertEqual(batch_result({'execution': 'call_completed', 'error': None}),
                         {'execution': 'call_completed', 'error': None})

    def test_long_target_keeps_blocker_reason_and_small_feedback_budget(self):
        from intent_browser.execution_feedback import timeout_context
        raw = {'execution': 'action_error', 'error':
               'TimeoutError: Locator.click\n<div ' + 'attribute="x" '*1000 + '> intercepts pointer events',
               'url_before': 'http://before/'+'x'*2000, 'url_after': 'http://after/'+'y'*2000}
        raw['timeout_context'] = timeout_context(raw)
        result = CompactFeedback(max_chars=2400)(raw, kind='browser_feedback')
        self.assertIn('intercepts pointer events', result['error'])
        self.assertLessEqual(len(json.dumps(result, ensure_ascii=False, sort_keys=True)), 2400)


@unittest.skipUnless(TOKENIZER.is_file(), 'Existing local tokenizer required')
class AXErrorTests(unittest.TestCase):
    def fixture(self, budget=2000):
        o = observation([node(0, 'RootWebArea', 'Cart', [1, 2]),
                         node(1, 'button', 'Increase Value', bid=370),
                         node(2, 'spinbutton', 'Quantity', bid=377)])
        return AXContext(AXConfig(str(TOKENIZER), incremental=True, overview_tokens=budget)), o

    def test_error_change_clear_and_delivery_tracking(self):
        x, o = self.fixture()
        x.prepare_observation(o); x.acknowledge()
        o['last_action_error'] = ERROR
        raw = deepcopy(o)
        # Trace-only rendering must not consume a not-yet-delivered error.
        trace = json.loads(x.overview(o))
        delivered = json.loads(x.prepare_observation(o))
        self.assertEqual(trace, delivered)
        self.assertIn('intercepts pointer events', delivered['last_action_error'])
        self.assertTrue(delivered['last_action_error_details_omitted'])
        self.assertLessEqual(x.tokens(encoded(delivered)), 2000)
        x.acknowledge()
        self.assertNotIn('last_action_error', x.page_update(o))
        x.acknowledge()
        # Even if two raw errors share the same headline, changed detail matters.
        o['last_action_error'] += '\nnew final diagnostic'
        self.assertIn('last_action_error', x.page_update(o))
        x.acknowledge()
        o['last_action_error'] = ''
        self.assertTrue(x.page_update(o)['last_action_error_cleared'])
        self.assertEqual(raw['last_action_error'], ERROR)

    def test_minimum_budget_escaped_errors_long_urls_verbose_metadata(self):
        for error in (ERROR, '\x00\x01\x02'*10000, '錯誤'*10000):
            with self.subTest(error=error[:30]):
                x, o = self.fixture(512)
                o['last_action_error'] = error
                o['url'] += '?query=' + '\x00漢字'*10000
                x.feedback_metadata = {'capture': 'large diagnostics '*10000}
                result = x.page_update(o, verbose=True)
                self.assertLessEqual(x.tokens(encoded(result)), 512)
                self.assertTrue(result['last_action_error_details_omitted'])
                self.assertTrue(result['url_partial'])
                self.assertTrue(result['metadata_omitted'])
                self.assertEqual(set(x.pending), {item['ref'] for item in result['items']})

    def test_runner_continues_after_error_preserves_raw_and_stops_batch(self):
        for batch_size in (1, 8):
            with self.subTest(batch_size=batch_size), tempfile.TemporaryDirectory() as temp:
                _, original = self.fixture()
                class Env:
                    actions = None
                    error = ''
                    def obs(self):
                        o = deepcopy(original)
                        o.update(goal='Set quantity to two', last_action_error=self.error,
                                 screenshot=np.zeros((2, 2, 3), dtype=np.uint8))
                        return o
                    def reset(self, seed):
                        self.actions = []
                        return self.obs(), {}
                    def step(self, action):
                        self.actions.append(action)
                        self.error = ERROR if action.startswith('click(') else ''
                        return self.obs(), 0, False, False, {}
                    def close(self): pass
                env = Env(); requests = []
                class Backend:
                    def configure_tools(self, options):
                        self.options = options
                    def complete(self, messages):
                        requests.append(deepcopy(messages)); i = len(requests)
                        calls = ([('click', {'bid': '370'})] * (2 if batch_size > 1 else 1)
                                 if i == 1 else [('fill', {'bid': '377', 'value': '2'})]
                                 if i == 2 else [('send_msg_to_user', {'text': 'Done'})])
                        result = response(calls)
                        for call in result.raw['choices'][0]['message']['tool_calls']:
                            call['id'] = f'{i}-' + call['id']
                        result.request = {'messages': messages}
                        return result
                profile = replace(native_tools_profile(
                    compact_feedback=True, parallel_tool_calls=None, batch_size=batch_size,
                    ax_config=AXConfig(str(TOKENIZER), incremental=True)), feedback_factory=SemanticFeedback)
                with patch('intent_browser.runner.refresh_observation', side_effect=lambda e:e.obs()), \
                     patch('intent_browser.runner.observation_text', return_value='trace-only tree'), \
                     patch('intent_browser.harness.flatten_axtree_to_str', return_value='Cart'), \
                     patch('intent_browser.batching.document_signature', return_value=[]):
                    path, summary = run_episode(lambda _:env, Backend(), {}, temp,
                                                max_steps=3, harness_profile=profile)
                self.assertIsNone(summary['error'])
                self.assertEqual(len(requests), 3)
                self.assertEqual(sum(a.startswith('click(') for a in env.actions), 1)
                self.assertTrue(any(a.startswith('fill(') for a in env.actions))
                self.assertNotIn('attempt #61', json.dumps(requests[1]))
                self.assertIn('intercepts pointer events', json.dumps(requests[1]))
                raw = json.loads((path/'browser_feedback-raw-000.json').read_text())
                self.assertEqual(raw['error'], ERROR)
                rows = [json.loads(s) for s in (path/'steps.jsonl').read_text().splitlines()]
                self.assertTrue(all(i['confirmed'] for i in rows[1]['policy_delivery']['items']))
                if batch_size > 1:
                    self.assertTrue(rows[0]['batch_calls'][1]['not_executed'])
                    self.assertEqual(rows[0]['batch_stop_reason'], 'tool_error_inspect_effects_before_retry')


if __name__ == '__main__':
    unittest.main()
