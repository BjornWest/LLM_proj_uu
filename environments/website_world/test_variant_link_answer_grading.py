"""Tiny synthetic answer-grounding controls; no browser or inference dispatch."""
from copy import deepcopy
import unittest

from .test_variant_link_task import fixture
from . import variant_link_task as native
from .variant_link_answer_grading import VariantLinkGrader


def sample(mode):
    world, spec, inputs = fixture(mode)
    task = native.make(world, spec, **inputs)
    reference = native.reference(world, task, **inputs)
    grader = VariantLinkGrader(world, task, reference, **inputs)
    explanation = {'all': 'The link opens the exact variant. No further selection is needed.',
                   'colour': 'This partial link only encodes colour. You must select EU size 38.',
                   'none': 'This product-only link does not encode options. You must select EU size 38 and colour brown.'}[mode]
    answer = f'Brown38 sandals: EU size 38, colour brown. {task["url"]}\n{explanation}'
    entry = lambda value, evidence: {'value': value, 'evidence': evidence}
    missing = entry(None, None)
    claims = {'interpretation': 'extracted', 'issues': [],
              'url': entry(task['url'], task['url']),
              'selection': {'size_eu': entry('38', 'EU size 38'), 'colour': entry('brown', 'colour brown')},
              'link_encodes_full_selection': entry(mode == 'all', explanation),
              'recipient_must_select': entry(mode != 'all', explanation),
              'manual_selection': {
                  'size_eu': entry('38', explanation) if mode != 'all' else deepcopy(missing),
                  'colour': entry('brown', explanation) if mode == 'none' else deepcopy(missing)}}
    return grader, answer, claims


class VariantLinkAnswerTests(unittest.TestCase):
    def test_semantic_boolean_provenance_is_not_english_interpretation(self):
        grader, answer, claims = sample('colour')
        text = 'The recipient needs another step; the URL leaves part of the choice open.'
        answer += '\n'+text
        for key in ('link_encodes_full_selection','recipient_must_select'):
            claims[key]['evidence'] = text
        self.assertTrue(grader.grade(claims,answer)['structured_claims_correct'])
        claims['recipient_must_select']['value'] = False
        self.assertFalse(grader.grade(claims,answer)['structured_claims_correct'])

    def test_all_url_modes_pass_and_publish_shape_is_complete(self):
        for mode in ('all', 'colour', 'none'):
            grader, answer, claims = sample(mode)
            result = grader.grade(claims, answer)
            self.assertTrue(result['structured_claims_correct'])
            for key in ('oracle_grade', 'additional_checks', 'oracle_answer', 'claims',
                        'derivations', 'selected_candidate_assessment', 'limitations', 'check_details'):
                self.assertIn(key, result)

    def test_missing_option_is_not_filled_from_url_or_task(self):
        grader, answer, claims = sample('all')
        claims['selection'].pop('size_eu')
        result = grader.grade(claims, answer)
        self.assertFalse(result['structured_claims_correct'])
        self.assertIsNone(result['claims']['selection']['size_eu']['value'])

    def test_missing_explanation_does_not_become_false_or_no_manual_work(self):
        grader, answer, claims = sample('all')
        claims.pop('recipient_must_select')
        self.assertFalse(grader.grade(claims, answer)['structured_claims_correct'])

    def test_nonquoted_claim_is_rejected_and_wrong_boolean_is_graded_false(self):
        grader, answer, claims = sample('colour')
        altered = deepcopy(claims);altered['url']['evidence'] = 'not in answer'
        with self.assertRaises(ValueError): grader.grade(altered, answer)
        altered = deepcopy(claims);altered['recipient_must_select']['value'] = False
        self.assertFalse(grader.grade(altered, answer)['structured_claims_correct'])

    def test_ambiguous_answer_or_wrong_manual_option_fails(self):
        grader, answer, claims = sample('colour')
        claims['interpretation'] = 'ambiguous'
        self.assertFalse(grader.grade(claims, answer)['structured_claims_correct'])
        grader, answer, claims = sample('all')
        claims['manual_selection']['colour'] = deepcopy(claims['selection']['colour'])
        self.assertFalse(grader.grade(claims, answer)['structured_claims_correct'])

    def test_inputs_are_unchanged(self):
        grader, answer, claims = sample('colour')
        before = deepcopy(claims)
        grader.grade(claims, answer)
        self.assertEqual(claims, before)


if __name__ == '__main__':
    unittest.main()
