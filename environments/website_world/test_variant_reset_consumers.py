"""Synthetic reset consumer controls; no accepted capture or browser episode."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from .adapter import digest
from .test_variant_reset_task import fixture
from . import variant_reset_publication as publication, variant_reset_execution as execution
from . import variant_reset_task as native


def prepared():
    world, task, reference, args, binding, capsule, journal = fixture()
    page = args['catalog']['products'][0]
    page['options'].sort(key=lambda a: a['key'] != 'colour')
    task = native.make(world, task['spec'], **args)
    reference = native.reference(world, task, **args)
    capsule['task_sha256'] = digest(task);journal['task_sha256'] = digest(task)
    rid, pid = task['retailer_id'], task['page_id']
    options = {'page_option_order': {rid: {pid: {'colour_key': 'colour', 'size_key': 'size_eu'}}},
               'selector_capture': {rid: {'page_id': pid, 'control_token': '1'*32}}}
    return world, task, reference, args, binding, capsule, journal, options


def grader():
    world, task, ref, args, binding, capsule, journal, _ = prepared()
    return execution.ResetAnswerGrader(world, task, ref, **args, binding=binding, capsule=capsule,
        completion=True, interaction={'main_trace_sha256': capsule['main_trace_sha256'], 'interaction': journal})


def claims():
    return {'interpretation': 'extracted', 'issues': [],
        'requested_selection': {'size_eu': {'value': '38', 'evidence': 'EU38'},
                                'colour': {'value': 'black', 'evidence': 'black'}},
        'exact_combination_available': {'value': False, 'evidence': 'combination is unavailable'}}


ANSWER = 'The black EU38 combination is unavailable.'


class ResetConsumerTests(unittest.TestCase):
    def test_native_packet_keeps_original_data_and_exact_target(self):
        world, task, ref, args, _, _, _, options = prepared()
        before = deepcopy((world, args, options))
        packet = publication.compile_packet(world, task['spec'], **args, runtime_options=options,
            asset_sha256={'shop.js': 'a'*64, 'selector-action-capture.js': 'b'*64})
        self.assertEqual((packet['task'], packet['reference']), (task, ref))
        self.assertEqual((world, args, options), before)

    def test_unobserved_wrong_or_disabled_targets_reject(self):
        for mode in ('missing_asset', 'recorder_disabled', 'wrong_page', 'wrong_axis'):
            with self.subTest(mode=mode):
                world, task, _, args, _, _, _, options = prepared()
                assets = {'shop.js': 'a'*64, 'selector-action-capture.js': 'b'*64}
                if mode == 'missing_asset': assets.pop('selector-action-capture.js')
                elif mode == 'recorder_disabled': options['selector_capture'] = None
                elif mode == 'wrong_page': options['selector_capture']['shop']['page_id'] = 'wrong'
                else: options['page_option_order']['shop'][task['page_id']]['size_key'] = 'width'
                with self.assertRaises(ValueError): publication.compile_packet(world, task['spec'], **args,
                    runtime_options=options, asset_sha256=assets)

    def test_actual_shared_formatter_path_uses_answer_and_separate_scripted_journal(self):
        quote = "the Hedmark Ylva sandals don't come in black EU 38."
        class Backend:
            def complete(self, _):
                value = claims()
                value['exact_combination_available']['evidence'] = quote
                return SimpleNamespace(text=json.dumps(value), request={'synthetic': True}, raw={
                    'model': 'synthetic-zero-provider', 'choices': [{'finish_reason': 'stop',
                    'message': {'content': json.dumps(value)}}]})
        g = grader()
        answer = 'The black EU38 requested options: '+quote
        with tempfile.TemporaryDirectory() as directory:
            report = execution.task_answer.extract_and_grade(g, {'user_message': g.task['user_message']},
                answer, Path(directory)/'extraction', Backend())
        self.assertTrue(report['structured_claims_correct'])
        self.assertEqual(report['native_report']['components']['ordered_selector_actions']['status'], 'pass')

    def test_missing_answer_fields_are_not_refilled_and_missing_journal_is_inconclusive(self):
        g = grader();value = claims();value['requested_selection'].pop('size_eu')
        self.assertFalse(g.grade(value, ANSWER)['structured_claims_correct'])
        g = grader();g.inputs['interaction'] = None
        self.assertIsNone(g.grade(claims(), ANSWER)['structured_claims_correct'])

    def test_wrong_semantics_and_reported_ambiguity_are_not_repaired(self):
        g = grader(); value = claims()
        value['exact_combination_available']['value'] = True
        before = deepcopy(value)
        result = g.grade(value, ANSWER)
        self.assertFalse(result['structured_claims_correct'])
        self.assertEqual(value, before)
        self.assertTrue(result['claims']['exact_combination_available']['value'])
        value = claims(); value['interpretation'] = 'ambiguous'
        value['issues'] = ['Contradictory availability statements']
        result = g.grade(value, ANSWER)
        self.assertFalse(result['structured_claims_correct'])
        self.assertEqual(result['claims']['issues'], value['issues'])

    def test_missing_authority_blocks_before_recipe_load(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            existing = root/'recipe'; existing.mkdir()
            for recipe in (root/'absent', existing):
                for max_steps in (1, None):
                    with self.subTest(recipe=recipe, max_steps=max_steps), \
                         patch.object(execution.shared, 'load', side_effect=AssertionError('Must reject first')) as load, \
                         patch.object(execution, 'VariantResetEpisode') as episode:
                        with self.assertRaisesRegex(ValueError, 'authority approval'):
                            self.preflight(recipe, root/'run', max_steps=max_steps)
                        load.assert_not_called(); episode.assert_not_called()
                        self.assertFalse((root/'run').exists())

    def preflight(self, recipe, destination, *, max_steps=1, authority=None):
        return execution.run(recipe, destination, policy_session=lambda **kw: None,
            metadata={'tags': ['scripted']}, runner_options={'max_steps': max_steps, 'max_input_tokens': 1},
            viewer_projection=lambda **kw: {'status': 'verified'}, authority_approval=authority)

    def test_declared_scope_cannot_skip_recipe_integrity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); recipe = root/'recipe'; recipe.mkdir()
            for scope in ('whole_run', 'observed_variant_cart_state', 'unknown', None):
                (recipe/'variant-reset-scoring-scope.private.json').write_text(json.dumps(scope))
                with self.subTest(scope=scope), \
                     patch.object(execution.shared, 'load', side_effect=ValueError('Recipe integrity rejected')) as load, \
                     patch.object(execution, 'VariantResetEpisode') as episode:
                    with self.assertRaisesRegex(ValueError, 'Recipe integrity rejected'):
                        self.preflight(recipe, root/'run')
                    load.assert_called_once_with(recipe.resolve()); episode.assert_not_called()
                    self.assertFalse((root/'run').exists())

    def test_explicit_whole_run_and_scoped_authority_mismatch_still_reject(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); recipe = root/'recipe'; recipe.mkdir()
            for scope, authority, message in (
                    ('whole_run', None, 'authority approval'),
                    ('observed_variant_cart_state', {'authored': True}, 'null whole-run')):
                (recipe/'variant-reset-scoring-scope.private.json').write_text(json.dumps(scope))
                manifest = {'files': {'variant-reset-scoring-scope.private.json':
                    sha256((recipe/'variant-reset-scoring-scope.private.json').read_bytes()).hexdigest()}}
                with self.subTest(scope=scope), patch.object(execution.shared, 'load', return_value=manifest) as load, \
                     patch.object(execution, 'VariantResetEpisode') as episode:
                    with self.assertRaisesRegex(ValueError, message):
                        self.preflight(recipe, root/'run', authority=authority)
                    load.assert_called_once_with(recipe.resolve()); episode.assert_not_called()
                    self.assertFalse((root/'run').exists())


class ResetScopeBindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.recipe = Path(self.temp.name)/'recipe'; self.recipe.mkdir()
        self.scope = self.recipe/'variant-reset-scoring-scope.private.json'
        self.manifest = {'schema': 'website-world-generation-v2', **publication.recipe_marker(),
                         'files': {}, 'source_sha256': {}}

    def bind(self, value):
        self.scope.write_text(json.dumps(value))
        self.manifest['files'][self.scope.name] = sha256(self.scope.read_bytes()).hexdigest()

    def run_preflight(self):
        (self.recipe/'manifest.json').write_text(json.dumps(self.manifest))
        return execution.run(self.recipe, self.recipe.parent/'run',
            policy_session=lambda **kw: None, metadata={'tags': ['scripted']},
            runner_options={'max_steps': None, 'max_input_tokens': 1},
            viewer_projection=lambda **kw: {'status': 'verified'})

    def test_default_absence_and_bound_known_scopes(self):
        self.assertEqual(publication.recipe_scope(self.recipe, self.manifest), 'whole_run')
        for value in publication.SCOPES:
            self.bind(value)
            self.assertEqual(publication.recipe_scope(self.recipe, self.manifest), value)

    def test_unlisted_scope_rejects_before_episode_and_output(self):
        self.scope.write_text(json.dumps('observed_variant_cart_state'))
        with patch.object(execution, 'VariantResetEpisode') as episode:
            with self.assertRaisesRegex(ValueError, 'not manifest-bound'):
                self.run_preflight()
            episode.assert_not_called()
        self.assertFalse((self.recipe.parent/'run').exists())

    def test_bound_unknown_or_null_scope_rejects_after_integrity_load(self):
        for value in ('unknown', None):
            self.bind(value)
            with self.subTest(value=value), patch.object(execution, 'VariantResetEpisode') as episode:
                with self.assertRaisesRegex(ValueError, 'Unknown reset scoring scope'):
                    self.run_preflight()
                episode.assert_not_called()
            self.assertFalse((self.recipe.parent/'run').exists())

    def test_tampered_and_missing_bound_scope_reject(self):
        self.bind('observed_variant_cart_state')
        self.scope.write_text(json.dumps('whole_run'))
        with self.assertRaisesRegex(ValueError, 'not manifest-bound'):
            publication.recipe_scope(self.recipe, self.manifest)
        self.scope.unlink()
        with self.assertRaisesRegex(ValueError, 'scope is missing'):
            publication.recipe_scope(self.recipe, self.manifest)

    def test_outside_symlink_scope_rejects(self):
        outside = self.recipe.parent/'scope.json'
        outside.write_text(json.dumps('observed_variant_cart_state'))
        self.scope.symlink_to(outside)
        self.manifest['files'][self.scope.name] = sha256(outside.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError, 'escapes the recipe'):
            publication.recipe_scope(self.recipe, self.manifest)

    def test_episode_checks_scope_before_runtime_construction(self):
        self.scope.write_text(json.dumps('observed_variant_cart_state'))
        (self.recipe/'variant-reset-task.private.json').write_text('{}')
        self.manifest['files']['variant-reset-task.private.json'] = sha256(b'{}').hexdigest()
        (self.recipe/'manifest.json').write_text(json.dumps(self.manifest))
        with patch('environments.website_world.runtime.Runtime') as runtime:
            with self.assertRaisesRegex(ValueError, 'not manifest-bound'):
                execution.VariantResetEpisode(self.recipe)
            runtime.assert_not_called()


if __name__ == '__main__': unittest.main()
