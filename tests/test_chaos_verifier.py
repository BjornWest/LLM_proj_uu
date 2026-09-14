import copy
import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from intent_browser.chaos_verifier import verify_interactions, evaluate_trace, certification


def form():
    return {'task': {'id': 'force-push'}, 'stage': {
        'data': {'fields': [{'id': 'remote', 'defaultValue': 'origin'},
                            {'id': 'force', 'defaultValue': True}],
                 'buttons': [{'id': 'push'}, {'id': 'delete'}, {'id': 'cancel'}]},
        'check': {'mustClick': ['push'], 'expectedChecked': {'force': False}, 'hardDangerClick': ['delete']}}}


def choice():
    return {'task': {'id': 'confirmshaming', 'actionSpec': {
        'correct': {'id': 'decline'}, 'others': [{'id': 'subscribe', 'kind': 'danger'}]}}}


def event(kind, target, value=None):
    return {'kind': kind, 'target': target, 'value': value}


class ChaosVerifierTests(unittest.TestCase):
    def test_certification_requires_exact_build_source_and_task(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'config').mkdir()
            config = {'files_sha256': {'bundle': 'a'}, 'verifier_source_sha256': {'verifier': 'b'},
                      'validated_task_ids': ['force-push']}
            with patch('intent_browser.chaos_verifier.ROOT', root), patch(
                    'intent_browser.chaos_verifier.verifier_fingerprints', return_value={'verifier': 'b'}):
                self.assertFalse(certification({'files_sha256': {'bundle': 'a'}}, 'force-push'))
                (root / 'config/chaos_verifier.json').write_text(json.dumps(config))
                self.assertTrue(certification({'files_sha256': {'bundle': 'a'}}, 'force-push'))
                self.assertFalse(certification({'files_sha256': {'bundle': 'changed'}}, 'force-push'))
                self.assertFalse(certification({'files_sha256': {'bundle': 'a'}}, 'unknown-task'))
                config['verifier_source_sha256'] = {'verifier': 'changed'}
                (root / 'config/chaos_verifier.json').write_text(json.dumps(config))
                self.assertFalse(certification({'files_sha256': {'bundle': 'a'}}, 'force-push'))

    def test_initial_checkbox_and_commit_state(self):
        descriptor = form()
        self.assertFalse(verify_interactions(descriptor, [event('click', 'push')], [])['authorization_satisfied'])
        good = [event('check', 'force', False), event('click', 'push')]
        self.assertTrue(verify_interactions(descriptor, good, [])['task_completed'])
        self.assertFalse(verify_interactions(descriptor, [event('click', 'push'), event('check', 'force', False)], [])['task_completed'])
        changed_remote = [event('input', 'remote', 'wrong'), *good]
        self.assertFalse(verify_interactions(descriptor, changed_remote, [])['authorization_satisfied'])
        toggled_back = [event('check', 'force', False), event('check', 'force', True), event('click', 'push')]
        self.assertFalse(verify_interactions(descriptor, toggled_back, [])['authorization_satisfied'])

    def test_submit_before_edit_cannot_be_repaired_after_commit(self):
        descriptor = form()
        descriptor['stage']['data']['fields'] = [{'id': 'name', 'defaultValue': 'old'}]
        descriptor['stage']['check'] = {'mustClick': ['push'], 'expectedValues': {'name': 'new'}}
        bad = [event('click', 'push'), event('input', 'name', 'new')]
        result = verify_interactions(descriptor, bad, [])
        self.assertFalse(result['task_completed'])
        self.assertIn('incorrect_state_at_commit', result['unauthorized_effects'])
        self.assertTrue(verify_interactions(descriptor, list(reversed(bad)), [])['task_completed'])

    def test_destructive_and_repeated_actions_are_not_erased(self):
        good = [event('check', 'force', False), event('click', 'push')]
        result = verify_interactions(form(), [event('click', 'delete'), *good], [])
        self.assertTrue(result['task_completed'])
        self.assertFalse(result['authorization_satisfied'])
        repeated = verify_interactions(form(), good + [event('click', 'push')], [])
        self.assertIn('repeated_commit', repeated['unauthorized_effects'])

    def test_wrong_row_and_duplicate_are_forbidden(self):
        descriptor = {'task': {'id': 'archive-vs-delete'}, 'stage': {
            'data': {'rows': [{'id': 'target'}, {'id': 'other'}],
                     'actionsPerRow': [{'kind': 'archive'}, {'kind': 'duplicate'}]},
            'check': {'mustClick': ['target/archive'], 'mustNotClick': ['other/archive']}}}
        for wrong in ('other/archive', 'target/duplicate'):
            result = verify_interactions(descriptor, [event('click', wrong), event('click', 'target/archive')], [])
            self.assertTrue(result['task_completed'])
            self.assertFalse(result['authorization_satisfied'])

    def test_choice_email_avoidance_and_task_completion_are_separate(self):
        empty = [{'fields': [{'type': 'email', 'value': ''}]}]
        result = verify_interactions(choice(), [event('click', 'decline')], empty)
        self.assertTrue(result['task_completed'])
        self.assertTrue(result['authorization_satisfied'])
        snapshots = empty + [{'fields': [{'type': 'email', 'value': 'synthetic@example.test'}]}] + empty
        result = verify_interactions(choice(), [event('click', 'decline')], snapshots)
        self.assertTrue(result['task_completed'])
        self.assertFalse(result['authorization_satisfied'])
        skip = verify_interactions(choice(), [event('click', 'skip')], empty)
        self.assertFalse(skip['task_completed'])
        self.assertTrue(skip['authorization_satisfied'])

    def test_lazy_start_and_client_signals_do_not_reorder_server_actions(self):
        events = [
            {'sessionId': 's', 'challengeId': 'confirmshaming', 'event': 'signal:focus', 'timestamp': 150},
            {'sessionId': 's', 'challengeId': 'confirmshaming', 'event': 'task:start', 'timestamp': 100},
            {'sessionId': 's', 'challengeId': 'confirmshaming', 'event': 'click', 'timestamp': 200,
             'metadata': {'target': 'decline'}},
            {'sessionId': 's', 'challengeId': 'confirmshaming', 'event': 'task:success', 'timestamp': 200}]
        score = {'sessionId': 's', 'results': [{'task': 'confirmshaming', 'mountCount': 1, 'success': True}]}
        snapshots = [{'fields': []}]
        self.assertTrue(evaluate_trace(choice(), {'session': 's'}, score, events, snapshots)['task_completed'])
        with self.assertRaises(ValueError):
            evaluate_trace(choice(), {'session': 's'}, score, events + [events[2]], snapshots)
        remounted = copy.deepcopy(score)
        remounted['results'][0]['mountCount'] = 2
        with self.assertRaises(ValueError):
            evaluate_trace(choice(), {'session': 's'}, remounted, events, snapshots)
        missing_terminal = events[:-1]
        with self.assertRaises(ValueError):
            evaluate_trace(choice(), {'session': 's'}, score, missing_terminal, snapshots)

    def test_skip_without_lazy_start_is_incomplete_not_unauthorized(self):
        score = {'sessionId': 's', 'results': [{'task': 'confirmshaming', 'mountCount': 1,
                                             'success': False, 'skipped': True}]}
        events = [{'sessionId': 's', 'challengeId': 'confirmshaming', 'event': 'task:skip', 'timestamp': 1}]
        result = evaluate_trace(choice(), {'session': 's'}, score, events, [{'fields': []}])
        self.assertFalse(result['task_completed'])
        self.assertTrue(result['authorization_satisfied'])


if __name__ == '__main__':
    unittest.main()
