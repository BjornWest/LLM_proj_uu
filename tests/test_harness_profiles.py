import json
import tempfile
import unittest
from copy import deepcopy
from unittest.mock import patch

import numpy as np

from intent_browser.backend import Completion
from intent_browser.evaluation import Evaluation
from intent_browser.harness import AppendConversation, BrowserTools, HarnessProfile, SemanticFeedback
from intent_browser.runner import run_episode


class Env:
    def __init__(self): self.actions = []; self.closed = False
    def observation(self, tree):
        return {'goal': 'Test public page', 'url': 'http://local.test/',
                'axtree_object': tree, 'last_action_error': '',
                'privileged': 'SECRET-GRADER', 'screenshot': np.zeros((2, 2, 3), dtype=np.uint8)}
    def reset(self, seed): return self.observation("[1] button 'Add'\n[2] status 'Count 0'"), {}
    def step(self, action):
        self.actions.append(action)
        return self.observation(f"[1] button 'Add'\n[2] status 'Count {len(self.actions)}'\n[3] alert 'Added'"), 0, False, False, {'private': 'SECRET-GRADER'}
    def close(self): self.closed = True


class Backend:
    def __init__(self, actions): self.actions = iter(actions); self.requests = []
    def complete(self, messages):
        self.requests.append(deepcopy(messages))
        self.last_request = {'messages': messages}
        output = next(self.actions)
        return Completion(output, {'source': 'offline-test'}, self.last_request)


class HarnessTests(unittest.TestCase):
    def run_case(self, backend=None, profile=None, env=None, task=None, paced=False):
        backend = backend or Backend(["click('1')", "send_msg_to_user('Done')"])
        profile = profile or HarnessProfile()
        env = env or Env()
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        with patch('intent_browser.harness.flatten_axtree_to_str', side_effect=lambda x: x), \
             patch('intent_browser.runner.observation_text', side_effect=lambda obs: obs['axtree_object']), \
             patch('intent_browser.runner.refresh_observation', side_effect=lambda _: env.observation("[1] button 'Add'\n[2] status 'Current'")):
            root, summary = run_episode(lambda _: env, backend, {}, tmp.name, max_steps=8,
                harness_profile=profile, episode_task=task, before_observation=(lambda: None) if paced else None)
        rows = [json.loads(s) for s in (root/'steps.jsonl').read_text().splitlines()]
        return root, summary, rows, backend, env

    def test_prefix_is_retained_beyond_four_actions_and_saved_requests_are_immutable(self):
        backend = Backend(["click('1')"]*6 + ["send_msg_to_user('Done')"])
        _, summary, rows, _, _ = self.run_case(backend)
        self.assertIsNone(summary['error'])
        for previous, current in zip(rows, rows[1:]):
            self.assertEqual(current['messages'][:len(previous['messages'])], previous['messages'])
        self.assertEqual(sum(m['role']=='assistant' for m in rows[-1]['messages']), 6)
        for row, request in zip(rows, backend.requests):
            self.assertEqual(row['messages'], request)
            self.assertEqual(row['model_request']['messages'], request)
            self.assertNotIn('SECRET-GRADER', json.dumps(request))

    def test_transition_feedback_survives_pacing_but_ids_are_not_in_feedback(self):
        _, _, rows, _, _ = self.run_case(paced=True)
        feedback = rows[0]['policy_feedback']
        self.assertIn("alert 'Added'", feedback['added_or_changed'])
        self.assertNotIn('[3]', json.dumps(feedback))
        self.assertIn("alert 'Added'", json.dumps(rows[1]['messages']))
        self.assertNotIn('Added', rows[1]['messages'][-1]['content'])
        self.assertIn('Current', rows[1]['messages'][-1]['content'])

    def test_profile_is_reusable_without_cross_episode_history(self):
        profile = HarnessProfile()
        for _ in range(2):
            root, _, rows, _, _ = self.run_case(profile=profile)
            self.assertEqual(len(rows[0]['messages']), 3)
            self.assertEqual(json.loads((root/'metadata.json').read_text())['harness_profile']['name'], profile.name)

    def test_task_requires_explicit_profile_adoption_before_any_work(self):
        class Task:
            def prepare(self, trace): raise AssertionError('must not prepare')
        with self.assertRaisesRegex(ValueError, 'not adopted'):
            run_episode(lambda _: self.fail('must not create'), object(), {},
                        episode_task=Task(), harness_profile=HarnessProfile())

    def test_adopted_task_gets_evaluation_before_close_without_leaking_evidence(self):
        env = Env()
        class Task:
            supported_harness_profiles = ('append-feedback-v1',)
            def prepare(self, trace): return {'private': 'SECRET-GRADER'}
            def capture_initial(self, *args): return {'private': 'SECRET-GRADER'}
            def after_step(self, *args): return {'private': 'SECRET-GRADER'}
            def evaluate(self, current, trace, outcome):
                assert not current.closed
                return Evaluation('fixture', '1')
        _, summary, rows, _, _ = self.run_case(env=env, task=Task())
        self.assertTrue(env.closed)
        self.assertIsNone(summary['error'])
        self.assertNotIn('SECRET-GRADER', json.dumps([r['messages'] for r in rows]))

    def test_disabled_action_is_rejected_without_browser_mutation(self):
        profile = HarnessProfile(tools=BrowserTools(('noop', 'send_msg_to_user')))
        _, summary, rows, _, env = self.run_case(profile=profile)
        self.assertEqual(env.actions, [])
        self.assertEqual(rows[0]['failure_phase'], 'action_parse')
        self.assertIn('disabled', summary['error'])

    def test_transport_timeout_keeps_current_attempt(self):
        class TimeoutBackend(Backend):
            def complete(self, messages):
                if self.requests:
                    self.last_request = {'messages': messages}
                    raise TimeoutError('test timeout')
                return super().complete(messages)
        _, summary, rows, _, env = self.run_case(TimeoutBackend(["click('1')"]))
        self.assertIn('TimeoutError', summary['error'])
        self.assertEqual(rows[1]['messages'], rows[1]['model_request']['messages'])
        self.assertEqual(env.actions, ["click('1')"])

    def test_feedback_failure_after_mutation_never_repeats_action(self):
        class Broken(SemanticFeedback):
            def after_action(self, *args): raise RuntimeError('feedback unavailable')
        _, summary, rows, _, env = self.run_case(profile=HarnessProfile(feedback_factory=Broken))
        self.assertEqual(env.actions, ["click('1')"])
        self.assertEqual(rows[0]['failure_phase'], 'feedback_after_action')
        self.assertIn('feedback unavailable', summary['error'])

    def test_swapping_observation_adapter_changes_exact_delivered_and_saved_text(self):
        def adapter(obs, *, limit): return f"CUSTOM {limit}: {obs['url']}"
        root, _, rows, _, _ = self.run_case(profile=HarnessProfile(observation=adapter))
        for row in rows:
            text = (root/row['observation']['text']).read_text()
            self.assertEqual(text, 'CUSTOM 16000: http://local.test/')
            self.assertIn(text, row['messages'][-1]['content'])

    def test_conversation_rejects_silent_goal_change_and_backend_cannot_mutate_it(self):
        context = AppendConversation()
        first = context.request('system', 'goal', 'page')
        first[0]['content'] = 'tampered'
        context.record('noop()', {})
        self.assertEqual(context.request('system', 'goal', 'next')[0]['content'], 'system')
        with self.assertRaises(ValueError): context.request('system', 'other goal', 'page')

    def test_diff_retains_duplicate_counts_and_bounds_large_changes(self):
        env = Env(); feedback = SemanticFeedback(max_lines=2, max_line_chars=20)
        with patch('intent_browser.harness.flatten_axtree_to_str', side_effect=lambda x: x):
            before = feedback.before_action(env, env.observation("[1] button 'x'"))
            result = feedback.after_action(env, before, env.observation("[1] button 'x'\n[2] button 'x'\n[3] status '"+'a'*100+"'\n[4] status 'z'"))
        self.assertEqual(result['added_or_changed'][0], "button 'x'")
        self.assertEqual(result['omitted_lines']['added'], 1)
        self.assertIn('[line truncated]', result['added_or_changed'][1])


if __name__ == '__main__': unittest.main()
