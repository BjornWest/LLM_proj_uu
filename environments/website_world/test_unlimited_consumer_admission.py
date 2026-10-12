"""Actual consumer admission/dispatch checks without browsers or providers."""
from contextlib import contextmanager
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from . import review_saved_runner as review
from . import variant_reset_execution as reset


class PolicyLimitAdmission(unittest.TestCase):
    def test_invalid_or_missing_limits_reject_before_setup(self):
        invalid = [None, [], {}, {'max_input_tokens': 1000}, {'max_steps': None},
                   {'max_steps': 1}, *[{'max_steps': v, 'max_input_tokens': 1000}
                       for v in [True, False, 0, -1, 1.5, '20']],
                   *[{'max_steps': None, 'max_input_tokens': v}
                       for v in [None, True, False, 0, -1, 1.5, '1000']]]
        with TemporaryDirectory() as directory:
            output = Path(directory)/'output'
            for module in [reset, review]:
                for options in invalid:
                    with self.subTest(consumer=module.__name__, options=options), \
                            patch.object(reset.shared, 'load') as load, \
                            patch.object(review, 'SavedReviewEpisode') as episode:
                        with self.assertRaisesRegex(ValueError, 'max_steps'):
                            module.run('missing-recipe', output, policy_session=lambda: None,
                                metadata={'tags': ['scripted']}, runner_options=options,
                                viewer_projection=lambda **_: None, quota_guard=lambda: None)
                        load.assert_not_called()
                        episode.assert_not_called()
                        self.assertFalse(output.exists())

    def test_reserved_grading_bindings_still_reject_with_unlimited_turns(self):
        for module in [reset, review]:
            for key in ['automatic_grading', 'allow_ungraded', 'episode_task', 'backend']:
                with self.subTest(consumer=module.__name__, key=key), \
                        patch.object(reset.shared, 'load') as load, \
                        patch.object(review, 'SavedReviewEpisode') as episode:
                    with self.assertRaisesRegex(ValueError, 'bindings'):
                        module.run('missing-recipe', 'missing-output', policy_session=lambda: None,
                            metadata={'tags': ['scripted']},
                            runner_options={'max_steps': None, 'max_input_tokens': 1000, key: True},
                            viewer_projection=lambda **_: None, quota_guard=lambda: None)
                    load.assert_not_called()
                    episode.assert_not_called()


class ReviewRunnerForwarding(unittest.TestCase):
    def test_explicit_none_and_finite_limit_forward_unchanged(self):
        for steps in [None, 7]:
            with self.subTest(max_steps=steps), TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                recipe = root/'recipe'; recipe.mkdir()
                public = {'schema_version': 'connected-world-manual-v1', 'task_id': 'authored-review',
                          'user_message': 'Summarize the saved reviews.', 'memories': [],
                          'environment_context': {}, 'start_url': 'https://authored.test/'}
                (recipe/'pin').mkdir()
                for name in ['pin/world.private.json', 'catalog-review-reference.private.json',
                             'surrounding.private.json']:
                    (recipe/name).write_text('{}')
                (recipe/'catalog-review-task.private.json').write_text(json.dumps(public))
                events, forwarded = [], []
                viewer = ModuleType('agent_trace.adapters.browsergym'); viewer.__file__ = __file__

                class Episode:
                    def __init__(self, output):
                        self.public = deepcopy(public)
                        self.task = SimpleNamespace(make_env=lambda: None, files={})
                        self.profile = SimpleNamespace(name='authored')
                        self.site_discovery = None
                    def export_private_runtime(self, destination):
                        destination.mkdir()
                        (destination/'site-registry.private.json').write_text('{}')
                        (destination/'manifest.json').write_text('{}')
                        return {'files': {'site-registry.private.json': sha256(b'{}').hexdigest()}}
                    def __enter__(self): return self
                    def __exit__(self, *args): events.append('runtime-close')

                @contextmanager
                def policy_session(**kwargs):
                    events.append('policy-open')
                    try: yield object()
                    finally: events.append('policy-close')

                def runner(*args, automatic_grading, **kwargs):
                    self.assertEqual(automatic_grading.phase, 'external')
                    forwarded.append(deepcopy({k: kwargs[k] for k in ['max_steps', 'max_input_tokens']}))
                    events.append('runner')
                    # Stop at the real call boundary: no browser, provider or synthetic verdict.
                    raise RuntimeError('authored no-provider dispatch boundary')

                options = {'max_steps': steps, 'max_input_tokens': 1000}
                with patch.dict('sys.modules', {'agent_trace.adapters.browsergym': viewer}), \
                        patch.object(review, 'SavedReviewEpisode', Episode):
                    result = review.run(recipe, root/'run', policy_session=policy_session,
                        metadata={'tags': ['scripted']}, runner_options=options,
                        viewer_projection=lambda **_: None, quota_guard=lambda: events.append('quota'),
                        runner=runner)
                self.assertEqual(forwarded, [options])
                self.assertEqual(options, {'max_steps': steps, 'max_input_tokens': 1000})
                self.assertEqual(result['status'], 'system_failure')
                self.assertEqual(result['reason'], 'authored no-provider dispatch boundary')
                self.assertEqual(events, ['quota', 'policy-open', 'runner', 'policy-close', 'runtime-close'])
                self.assertIsNone(result['native_grade'])
