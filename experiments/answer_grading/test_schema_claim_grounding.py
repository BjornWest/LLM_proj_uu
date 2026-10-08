"""Shared quote/null boundary; no native world, provider or historical regrade."""
from copy import deepcopy

import pytest
from jsonschema import ValidationError

from .extraction import SCHEMA, claim, obj, validate_claims


def schema_for(name, kind='integer'):
    return obj({name: claim(kind), 'source_urls': {'type': 'array', 'items':
        obj({'value': {'type': 'string'}, 'evidence': {'type': 'string'}})}})


def payload(name, value, evidence):
    return {name: {'value': value, 'evidence': evidence}, 'source_urls': []}


@pytest.mark.parametrize('name', ['population_count', 'positive', 'negative', 'neutral',
                                 'mixed', 'not_assessed', 'written_review_count', 'assessed_count'])
def test_task_specific_counts_require_actual_quote_and_numeric_value(name):
    schema = schema_for(name)
    answer = 'There are 3 relevant reports, with 12 other reports.'
    good = payload(name, 3, '3 relevant reports')
    before = deepcopy(good)
    assert validate_claims(good, answer, schema=schema) == good
    assert good == before
    for invalid in (payload(name, 3, 'Fabricated 3 reports'),
                    payload(name, 3, '12 other reports'),
                    payload(name, 3, None)):
        with pytest.raises(ValueError):
            validate_claims(invalid, answer, schema=schema)


@pytest.mark.parametrize('kind,value', [('integer', 3), ('string', 'blue'), ('boolean', True)])
def test_every_declared_claim_requires_quote_or_consistent_null(kind, value):
    schema = schema_for('custom', kind)
    assert validate_claims(payload('custom', None, None), 'No answer.', schema=schema)
    with pytest.raises(ValueError, match='Absent claim'):
        validate_claims(payload('custom', None, 'No answer.'), 'No answer.', schema=schema)
    with pytest.raises(ValueError, match='exact final-answer quote'):
        validate_claims(payload('custom', value, 'Fabricated'), 'No answer.', schema=schema)


def test_task_specific_string_is_not_supplied_by_unrelated_quote():
    schema = schema_for('product_name', 'string')
    answer = 'The Blue Shoe is preferable.'
    assert validate_claims(payload('product_name', 'Blue Shoe', 'Blue Shoe'), answer, schema=schema)
    with pytest.raises(ValueError, match='String claim'):
        validate_claims(payload('product_name', 'Red Shoe', answer), answer, schema=schema)


@pytest.mark.parametrize('value', [True, 3.5, '3', -3])
def test_task_specific_count_keeps_strict_integer_and_nonnegative_validation(value):
    with pytest.raises((ValueError, ValidationError)):
        validate_claims(payload('positive', value, '3 reports'), '3 reports', schema=schema_for('positive'))


def test_status_normalization_stays_with_existing_semantic_contract():
    schema = obj({'status': claim(enum=['selection', None]), 'source_urls': {'type': 'array', 'items': {}}})
    answer = 'I recommend this shoe.'
    assert validate_claims(payload('status', 'selection', answer), answer, schema=schema)


def test_non_claim_object_with_value_but_no_evidence_is_not_misclassified():
    schema = obj({'configuration': obj({'value': {'type': 'integer'}}),
                  'source_urls': {'type': 'array', 'items': {}}})
    value = {'configuration': {'value': 3}, 'source_urls': []}
    assert validate_claims(value, 'No claim.', schema=schema) == value


@pytest.mark.parametrize('answer,evidence', [('-3 reports', '-3'), ('-3 reports', '3'),
                                           ('\u2212 3 reports', '3'), ('3,500 reports', '3'),
                                           ('13 reports', '3'), ('3.5 reports', '3')])
def test_count_cannot_crop_a_signed_or_larger_numeral(answer, evidence):
    with pytest.raises(ValueError, match='Integer claim'):
        validate_claims(payload('positive', 3, evidence), answer, schema=schema_for('positive'))


@pytest.mark.parametrize('value,answer,evidence', [(3, '3. End.', '3'),
                                                (3500, '3,500 reports', '3,500'),
                                                (3500, '3 500 reports', '3 500')])
def test_complete_count_preserves_punctuation_and_grouped_numeric_values(value, answer, evidence):
    assert validate_claims(payload('positive', value, evidence), answer, schema=schema_for('positive'))


@pytest.mark.parametrize('presentation', ['765,00 SEK', '765 SEK', '1 234,50 SEK'])
def test_trusted_semantic_binding_keeps_normalized_decimal_quote(presentation):
    value = '1234.50' if presentation.startswith('1 ') else '765.00'
    schema = schema_for('statistic_sek', 'string')
    assert validate_claims(payload('statistic_sek', value, presentation), presentation,
                           schema=schema, semantic_fields=('statistic_sek',))


def test_semantic_defer_never_bypasses_quote_null_or_type_checks():
    schema = schema_for('statistic_sek', 'string')
    for invalid in (payload('statistic_sek', '765.00', 'Fabricated'),
                    payload('statistic_sek', None, '765 SEK'),
                    payload('statistic_sek', 765, '765 SEK')):
        with pytest.raises((ValueError, ValidationError)):
            validate_claims(invalid, '765 SEK', schema=schema, semantic_fields=('statistic_sek',))


@pytest.mark.parametrize('fields', [('unknown',), 'statistic_sek', ('source_urls',), None])
def test_semantic_defer_rejects_unknown_or_non_claim_fields(fields):
    with pytest.raises(ValueError, match='Semantic fields'):
        validate_claims(payload('statistic_sek', '765.00', '765 SEK'), '765 SEK',
                        schema=schema_for('statistic_sek', 'string'), semantic_fields=fields)


def test_default_money_and_citation_grounding_remain_independent():
    value = {}
    for name, spec in SCHEMA['properties'].items():
        if name == 'interpretation': value[name] = 'extracted'
        elif spec.get('type') == 'array': value[name] = []
        elif {'value', 'evidence'} <= spec.get('properties', {}).keys():
            value[name] = {'value': None, 'evidence': None}
        else: value[name] = None
    answer = 'I recommend https://shop.test/product for 1 234,50 SEK.'
    value['status'] = {'value': 'selection', 'evidence': 'I recommend'}
    value['total'] = {'amount': '1234.50', 'currency': 'SEK', 'evidence': '1 234,50 SEK'}
    value['source_urls'] = [{'value': 'https://shop.test/product', 'evidence': 'https://shop.test/product'}]
    assert validate_claims(value, answer) == value
    invalid = deepcopy(value); invalid['total']['amount'] = '1250.00'
    with pytest.raises(ValueError, match='Monetary claim'):
        validate_claims(invalid, answer)
    invalid = deepcopy(value); invalid['source_urls'][0]['value'] = 'https://foreign.test/'
    with pytest.raises(ValueError, match='Citation'):
        validate_claims(invalid, answer)
