"""Synthetic reset consumer controls; no accepted capture or browser episode."""
from copy import deepcopy
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
        with patch.object(execution.shared, 'load', side_effect=AssertionError('Must reject first')):
            with self.assertRaises(ValueError): execution.run('absent', 'absent-output',
                policy_session=lambda **kw: None, metadata={}, runner_options={'max_steps': 1, 'max_input_tokens': 1},
                viewer_projection=lambda **kw: {'status': 'verified'}, authority_approval=None)


if __name__ == '__main__': unittest.main()
