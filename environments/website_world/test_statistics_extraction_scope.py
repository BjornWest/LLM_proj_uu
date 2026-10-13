"""One changed prompt/schema contract control plus unchanged-grader regression locks.

Claims are supplied by these fixtures, not extracted by a model. Actual count
selection, ambiguity and quote reliability require Evaluation extraction tests.
"""
from copy import deepcopy
import json

import pytest
from jsonschema.exceptions import ValidationError

from experiments.answer_grading.extraction import claim
from experiments.answer_grading.task_answer import messages
from environments.website_world import catalog_statistics_grading as grading


def fixture(monkeypatch, operation='count', grain='model'):
    # Hand-authored counts/reference isolate the extraction contract and grading.
    # Native world/source validation is covered by existing statistics tests.
    count, total = (7, 9) if grain == 'model' else (11, 15)
    reference = {'population_count': count, 'operation': operation, 'grain': grain,
                 'aggregate_sek': None if operation == 'count' else '20.00',
                 'statistic_defined': True, 'observations': []}
    monkeypatch.setattr(grading.native, 'reference', lambda *args, **kwargs: deepcopy(reference))
    task = {'operation': operation, 'grain': grain, 'comparison_site_id': 'comparison-00',
            'comparison_site_name': 'Price Index'}
    world = {'products': []}
    surrounding = {'sites': [{'site_id': 'comparison-00', 'product_ids': [], 'listings': []}]}
    sites = [{'site_id': 'comparison-00', 'kind': 'aggregator', 'name': 'Price Index',
              'origin': 'https://compare.test'}]
    grader = grading.CatalogStatisticsGrader(world, task, reference, sites, surrounding=surrounding)
    label = 'models' if grain == 'model' else 'model/retailer listings'
    statement = f'There are {count} priced {label} out of {total} {label} in the catalog.'
    if operation != 'count':
        statement += f' The {operation} price over those {count} priced observations is 20.00 SEK.'
    text = statement + ' https://compare.test/'
    values = {'status': 'summary', 'comparison_url': 'https://compare.test/',
              'population_count': count, 'statistic_sek': reference['aggregate_sek'],
              'currency': None if operation == 'count' else 'SEK', 'undefined': None}
    claims = {'interpretation': 'extracted', 'issues': [], 'source_urls': [],
              **{key: {'value': value, 'evidence': text if value is not None else None}
                 for key, value in values.items()}}
    return grader, text, claims, count, total


@pytest.mark.parametrize('operation', ['count', 'mean', 'median', 'minimum', 'maximum'])
@pytest.mark.parametrize('grain', ['model', 'listing'])
def test_supplied_requested_and_wider_counts_retain_native_outcomes(monkeypatch, operation, grain):
    grader, text, claims, count, total = fixture(monkeypatch, operation, grain)
    before = deepcopy(claims)
    assert grader.grade(claims, text)['structured_claims_correct']
    assert claims == before
    claims['population_count']['value'] = total
    wrong = deepcopy(claims)
    result = grader.grade(claims, text)
    assert result['claims']['population_count']['value'] == total
    assert not result['oracle_grade']['requirements']['population_count']
    assert not result['structured_claims_correct']
    assert claims == wrong  # Native grading does not repair extraction to count.


@pytest.mark.parametrize('operation', ['count', 'mean', 'median'])
def test_supplied_null_count_is_not_filled_by_native_grading(monkeypatch, operation):
    grader, _, claims, _, total = fixture(monkeypatch, operation)
    text = f'The catalog has {total} models. I could not determine the priced population. https://compare.test/'
    for key in ('population_count', 'statistic_sek', 'currency', 'undefined'):
        claims[key] = {'value': None, 'evidence': None}
    claims['status'] = {'value': 'uncertain', 'evidence': text}
    claims['comparison_url']['evidence'] = text
    result = grader.grade(claims, text)
    assert result['claims']['population_count']['value'] is None
    assert not result['oracle_grade']['requirements']['population_count']
    assert not result['structured_claims_correct']


def test_supplied_median_divisor_is_rejected_by_native_count(monkeypatch):
    grader, text, claims, _, _ = fixture(monkeypatch, 'median', 'listing')
    text += ' For an even median, the two middle prices are averaged.'
    assert grader.grade(claims, text)['structured_claims_correct']
    claims['population_count'] = {'value': 2, 'evidence': text}
    assert not grader.grade(claims, text)['oracle_grade']['requirements']['population_count']


def test_count_schema_changes_descriptions_only_and_extractor_sees_no_reference(monkeypatch):
    grader, text, _, count, _ = fixture(monkeypatch, 'mean')
    field = deepcopy(grader.schema['properties']['population_count'])
    assert 'wider catalog total' in field['properties']['value']['description']
    assert 'requested population count' in field['properties']['evidence']['description']
    field['properties']['value'].pop('description')
    field['properties']['evidence']['description'] = claim('integer')['properties']['evidence']['description']
    assert field == claim('integer')
    public = {'user_message': 'How many distinct priced models are on Price Index?', 'memories': []}
    private_marker = 'private-reference-test-marker'
    caller_data = {**public, 'native_reference': grader.reference, 'private_marker': private_marker}
    prepared = messages(caller_data, text, grader.schema, instructions=grader.extraction_instructions)
    assert json.loads(prepared[1]['content']) == {'public_task': public, 'final_answer': text}
    # The actual message builder filters caller-only data; task/answer are exact.
    assert private_marker not in json.dumps(prepared)
    assert 'native_reference' not in json.dumps(prepared)
    assert 'population denominator' not in grader.extraction_instructions
    assert 'never to supply a missing count' in grader.extraction_instructions
    assert 'Do not count listed rows' in grader.extraction_instructions
    assert 'Different counts for different scopes' in grader.extraction_instructions


def test_existing_schema_and_quote_rejections_are_preserved(monkeypatch):
    grader, text, claims, _, _ = fixture(monkeypatch)
    claims['population_count']['evidence'] = 'not an authentic answer quote'
    with pytest.raises(ValueError, match='quote'):
        grader.grade(claims, text)
    claims['population_count'] = {'value': True, 'evidence': text}
    with pytest.raises(ValidationError):
        grader.grade(claims, text)
