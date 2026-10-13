"""Prospective claim admission; supplied semantics, no extractor/model/regrade."""
from copy import deepcopy

import pytest
from jsonschema import ValidationError

from .test_variant_reset_task import fixture
from .variant_reset_execution import ResetAnswerGrader


def sample(quote="the Hedmark Ylva sandals don't come in black EU 38."):
    world, task, ref, args, binding, capsule, journal = fixture()
    grader = ResetAnswerGrader(world, task, ref, **args, binding=binding,
        capsule=capsule, completion=True, interaction={
            'main_trace_sha256': capsule['main_trace_sha256'], 'interaction': journal})
    answer = 'Requested options: size 38 and colour black. '+quote
    claims = {'interpretation': 'extracted', 'issues': [],
        'requested_selection': {
            'size_eu': {'value': '38', 'evidence': 'size 38'},
            'colour': {'value': 'black', 'evidence': 'colour black'}},
        'exact_combination_available': {'value': False, 'evidence': quote}, 'source_urls': []}
    return grader, answer, claims


@pytest.mark.parametrize('quote', [
    "the Hedmark Ylva sandals don't come in black EU 38.",
    'Black EU38 is absent from this range.',
    'They make the black one in 39, but skip 38.',
    'The requested combination is not available.',
])
def test_supplied_semantic_false_is_admitted_without_word_whitelist(quote):
    grader, answer, claims = sample(quote)
    before = deepcopy(claims)
    result = grader.grade(claims, answer)
    assert result['structured_claims_correct'] is True
    assert result['native_report']['components']['unavailable_disclosure']['status'] == 'pass'
    assert claims == before and result['claims'] == before


def test_valid_wrong_semantic_true_reaches_native_failure():
    grader, answer, claims = sample()
    claims['exact_combination_available']['value'] = True
    result = grader.grade(claims, answer)
    assert result['structured_claims_correct'] is False
    assert result['native_report']['components']['unavailable_disclosure']['status'] == 'fail'


@pytest.mark.parametrize('mutation', [
    'invented_quote', 'empty_quote', 'noncontiguous_quote', 'null_with_quote',
    'value_without_quote', 'invalid_boolean_type',
])
def test_semantic_admission_keeps_schema_and_span_provenance(mutation):
    grader, answer, claims = sample()
    field = claims['exact_combination_available']
    if mutation == 'invented_quote': field['evidence'] = 'Never said.'
    elif mutation == 'empty_quote': field['evidence'] = ''
    elif mutation == 'noncontiguous_quote': field['evidence'] = 'the Hedmark Ylva black EU 38.'
    elif mutation == 'null_with_quote': field['value'] = None
    elif mutation == 'value_without_quote': field['evidence'] = None
    else: field['value'] = 0
    with pytest.raises((ValueError, ValidationError)):
        grader.grade(claims, answer)


def test_missing_availability_stays_missing_and_fails_native_disclosure():
    grader, answer, claims = sample()
    claims['exact_combination_available'] = {'value': None, 'evidence': None}
    result = grader.grade(claims, answer)
    assert result['structured_claims_correct'] is False
    assert result['claims']['exact_combination_available']['value'] is None


def test_contradiction_ambiguity_and_issues_survive_and_cannot_pass():
    grader, answer, claims = sample()
    claims['interpretation'] = 'ambiguous'
    claims['issues'] = ['The answer gives contradictory availability statements.']
    before = deepcopy(claims)
    result = grader.grade(claims, answer)
    assert result['structured_claims_correct'] is False
    assert result['native_report']['components']['unambiguous_answer']['status'] == 'fail'
    assert claims == before and result['claims'] == before


@pytest.mark.parametrize('mutation', ['missing_value', 'fabricated_option_quote', 'fabricated_url'])
def test_literal_options_and_urls_keep_mechanical_grounding(mutation):
    grader, answer, claims = sample()
    if mutation == 'missing_value': claims['requested_selection']['size_eu']['value'] = '42'
    elif mutation == 'fabricated_option_quote': claims['requested_selection']['colour']['evidence'] = 'not said: black'
    else: claims['source_urls'] = [{'value': 'https://invented.test/', 'evidence': 'https://invented.test/'}]
    with pytest.raises((ValueError, ValidationError)):
        grader.grade(claims, answer)


@pytest.mark.parametrize('axis', ['status', 'source_urls', 'total', 'average'])
def test_literal_axis_grounding_does_not_use_flat_reserved_names(axis):
    from experiments.answer_grading.extraction import obj, claim
    grader, answer, claims = sample()
    grader.task['requested_selection'] = {axis: 'glossy'}
    grader.schema['properties']['requested_selection'] = obj({axis: claim()})
    claims['requested_selection'] = {axis: {'value': 'glossy', 'evidence': 'matte finish'}}
    with pytest.raises(ValueError, match='Option is absent'):
        grader.grade(claims, answer+' matte finish')
