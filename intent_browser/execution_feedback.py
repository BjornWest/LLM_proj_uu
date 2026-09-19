"""Explain ambiguous action timeouts using public before/after browser evidence.

Never repair an exception into success, infer an action had no effect, retry an
interaction, or consult private task state. This is an opt-in policy presentation.
"""
from .browser_feedback import CoreBrowserFeedback


def timeout_context(result):
    error = result.get('error')
    if not isinstance(error, str) or not error.startswith('TimeoutError:'):
        return None
    before, after = result.get('url_before'), result.get('url_after')
    changed = before != after if isinstance(before, str) and isinstance(after, str) else None
    navigation = sum(e.get('kind') == 'navigation' for e in result.get('page_events', []))
    return {
        'action_effect': 'unknown',
        'url_changed': changed,
        'navigation_events_observed': navigation,
        'accessible_content_change_observed': bool(result.get('added_or_changed') or result.get('removed_or_changed')),
        'current_document_is_browser_error': isinstance(after, str) and after.startswith('chrome-error://'),
        'interpretation': ('The browser call timed out, but the page URL changed.' if changed else
                           'The browser call timed out; an unchanged URL does not establish that nothing happened.'),
        'next_step': 'Inspect the current page and observed effects before deciding what to do. Do not blindly repeat a state-changing action. Navigation or content changes do not prove task success.',
    }


class ExecutionAwareFeedback(CoreBrowserFeedback):
    def after_action(self, env, before, observation):
        result = super().after_action(env, before, observation)
        context = timeout_context(result)
        if context is not None:
            result['timeout_context'] = context
        return result
