"""Extractor values, genuine quotes and typed arithmetic remain separate."""
from copy import deepcopy

import pytest

from .extraction import claim, obj, validate_claims, money_minor
from .factual import validate_details


@pytest.mark.parametrize('kind,value,text', [
    ('integer', 123, 'One hundred and twenty-three items were counted.'),
    ('boolean', False, "They don't come in that configuration."),
    ('boolean', True, 'It includes the requested accessory.'),
])
def test_extractor_interpretation_is_not_repeated_by_validator(kind, value, text):
    schema = obj({'result': claim(kind), 'source_urls': {'type': 'array', 'items': {}}})
    payload = {'result': {'value': value, 'evidence': text}, 'source_urls': []}
    before = deepcopy(payload)
    assert validate_claims(payload, text, schema=schema) == before
    assert payload == before
    payload['result']['evidence'] = 'An invented quote.'
    with pytest.raises(ValueError, match='exact final-answer quote'):
        validate_claims(payload, text, schema=schema)


@pytest.mark.parametrize('amount', ['', '-1', '+1', 'NaN', 'Infinity', '1e2', '.50',
                                   '1.', '1.234', '1.2.3', ' 1.00', '1,00', True, 1])
def test_amount_shape_rejects_without_answer_regex(amount):
    with pytest.raises(ValueError):
        money_minor({'amount': amount, 'currency': 'SEK', 'evidence': 'A real quote.'})


@pytest.mark.parametrize('amount,minor', [('0', 0), ('0.00', 0), ('12', 1200),
                                        ('12.3', 1230), ('12.34', 1234),
                                        ('100000000000000000000.01', 10000000000000000000001)])
def test_money_conversion_is_exact_and_evidence_wording_independent(amount, minor):
    assert money_minor({'amount': amount, 'currency': 'SEK',
                        'evidence': 'The price was given above.'}) == minor


def test_factual_details_keep_exact_quote_but_trust_extracted_numeric_value():
    answer = 'It takes about a dozen days.'
    rows = [{'offer_url': None, 'value': 12, 'evidence': answer}]
    validate_details(rows, answer)
    for number in (-1, float('inf'), float('nan')):
        with pytest.raises(ValueError, match='Invalid extracted detail number'):
            validate_details([{**rows[0], 'value': number}], answer)
    with pytest.raises(ValueError, match='exact final-answer quote'):
        validate_details([{**rows[0], 'evidence': 'Made up.'}], answer)
