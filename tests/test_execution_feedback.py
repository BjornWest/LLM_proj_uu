from copy import deepcopy
import unittest
from intent_browser.execution_feedback import timeout_context, ExecutionAwareFeedback
from intent_browser.feedback_presentation import CompactFeedback, size
from intent_browser.harness import native_tools_profile


class ExecutionFeedbackTests(unittest.TestCase):
    def base(self, url='http://fixture/next'):
        return {'execution': 'action_error', 'error': 'TimeoutError: Locator.click: Timeout 500ms exceeded.\nDetails',
                'url_before': 'http://fixture/', 'url_after': url, 'page_events': [{'kind': 'navigation'}],
                'added_or_changed': ['heading Receipt'], 'removed_or_changed': []}

    def test_timeout_with_navigation_keeps_error_and_unknown_effect(self):
        raw = self.base(); original = deepcopy(raw)
        context = timeout_context(raw)
        self.assertEqual(context['action_effect'], 'unknown')
        self.assertTrue(context['url_changed'])
        self.assertEqual(context['navigation_events_observed'], 1)
        self.assertIn('URL changed', context['interpretation'])
        self.assertEqual(raw, original)
        raw['timeout_context'] = context
        selected = CompactFeedback()(raw, kind='browser_feedback')
        self.assertEqual(selected['execution'], 'action_error')
        self.assertEqual(selected['error'], original['error'].splitlines()[0])
        self.assertEqual(selected['timeout_context'], context)
        self.assertLessEqual(size(selected), 6000)

    def test_same_url_changes_never_prove_no_effect(self):
        raw = self.base(url='http://fixture/')
        context = timeout_context(raw)
        self.assertFalse(context['url_changed'])
        self.assertTrue(context['accessible_content_change_observed'])
        self.assertEqual(context['action_effect'], 'unknown')
        self.assertIn('does not establish', context['interpretation'])
        raw.update(page_events=[], added_or_changed=[])
        context = timeout_context(raw)
        self.assertFalse(context['accessible_content_change_observed'])
        self.assertEqual(context['action_effect'], 'unknown')

    def test_error_page_and_non_timeout_not_misreported_as_success(self):
        raw = self.base('chrome-error://chromewebdata/')
        self.assertTrue(timeout_context(raw)['current_document_is_browser_error'])
        self.assertEqual(timeout_context(raw)['action_effect'], 'unknown')
        for err in ('Error: navigation failed', '', None):
            raw['error'] = err
            self.assertIsNone(timeout_context(raw))

    def test_profile_is_explicit_and_does_not_change_prior_feedback(self):
        self.assertIs(native_tools_profile(timeout_feedback=True).feedback_factory, ExecutionAwareFeedback)
        self.assertEqual(native_tools_profile(timeout_feedback=True).name, 'core-tools-v5-feedback')
        self.assertNotEqual(native_tools_profile().feedback_factory, ExecutionAwareFeedback)

if __name__ == '__main__': unittest.main()
