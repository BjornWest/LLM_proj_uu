"""Synthetic selection/scope controls; actual browser acceptance is separate."""
from copy import deepcopy
import json

import pytest

from .adapter import digest
from . import simulated_order_address_grading as grading


@pytest.fixture
def example():
    expected = {'recipient': 'Ada Nilsson', 'street': 'Ekvägen',
        'house_number': '12', 'unit': '24', 'postcode': '123 45',
        'city': 'Uppsala', 'country': 'SE'}
    actual = {'name': 'Ada Nilsson', 'street': 'Ekvägen 12',
        'unit': '24', 'postcode': '12345', 'city': 'Uppsala'}
    task = {'task_id': 'synthetic-address-task', 'retailer_id': 'r1',
            'delivery_address': expected}
    binding = {'runtime_id': 'synthetic-runtime', 'episode_binding': {
        'episode_id': 'synthetic-episode', 'task_sha256': digest(task),
        'source_union_sha256': 'a' * 64, 'capture_implementation_sha256': 'b' * 64}}
    storage_binding = {'origin': 'https://synthetic.example',
        'storage_key': 'website-drafts.state.r1', 'implicit_country': 'SE'}
    reference = {'task_id': task['task_id'], 'task_sha256': digest(task),
        'retailer_id': 'r1', 'expected_address': deepcopy(expected),
        'implicit_country': 'SE', 'scoring_scope': grading.SCOPE}
    evidence = {'schema_version': 'website-simulated-order-address-capture-v1',
        'task_id': task['task_id'], 'task_sha256': digest(task), 'binding': deepcopy(binding),
        'episode_id': 'synthetic-episode', 'main_trace_sha256': 'c' * 64,
        'full_effects': 'unknown', 'complete_effect_envelope': None,
        'order_outcome_scored': False, 'ledger': {
            'task_sha256': digest(task), 'episode_id': 'synthetic-episode',
            'main_trace_sha256': 'c' * 64, 'effect_journal': None},
        'checkout_storage': {}}
    for phase, name in (('before', 'before_policy'),
                        ('after', 'after_policy_before_context_close')):
        evidence['ledger'][phase] = {'phase': name, 'order_snapshot': {
            'runtime_id': binding['runtime_id'],
            'episode_binding': deepcopy(binding['episode_binding']), 'orders': []}}
    evidence['checkout_storage']['after'] = {'phase': 'after',
        'binding': deepcopy(binding), 'episode_id': 'synthetic-episode',
        'retailer_id': 'r1', **storage_binding, 'storage_state': {
            'cookies': [], 'origins': [{'origin': storage_binding['origin'],
                'localStorage': [{'name': storage_binding['storage_key'],
                                  'value': json.dumps({'address': actual})}]}]}}
    return task, reference, evidence, binding, storage_binding, actual


def run(example):
    task, reference, evidence, binding, storage_binding, _ = example
    return grading.grade(task, reference, evidence, binding=binding,
        storage_binding=storage_binding, episode_id='synthetic-episode',
        main_trace_sha256='c' * 64)


def orders(example, *addresses):
    example[2]['ledger']['after']['order_snapshot']['orders'] = [
        {'retailer_id': 'r1', 'order_id': 'synthetic-' + str(index),
         'address': deepcopy(address)} for index, address in enumerate(addresses)]


def test_null_effect_envelope_does_not_block_address_score(example):
    result = run(example)
    assert result['verdict'] == 'pass'
    assert result['full_effects'] == 'unknown'
    assert result['full_order_completion'] == 'not_assessed'
    assert result['selected_evidence']['kind'] == 'terminal_checkout'


def test_submitted_address_wins_even_when_saved_checkout_would_pass(example):
    orders(example, {**example[5], 'unit': ''})
    result = run(example)
    assert result['verdict'] == 'fail'
    assert result['components']['address']['checks']['unit'] is False


def test_submitted_address_survives_cleared_form(example):
    orders(example, example[5])
    example[2]['checkout_storage']['after']['storage_state']['origins'] = []
    assert run(example)['verdict'] == 'pass'


def test_latest_submission_rule_preserves_all_records(example):
    orders(example, {**example[5], 'unit': ''}, example[5])
    before = deepcopy(example[2])
    result = run(example)
    assert result['verdict'] == 'pass'
    assert result['selected_evidence']['order_id'] == 'synthetic-1'
    assert example[2] == before
    assert len(example[2]['ledger']['after']['order_snapshot']['orders']) == 2


def test_latest_incorrect_submission_cannot_hide_behind_earlier_success(example):
    orders(example, example[5], {**example[5], 'unit': ''})
    assert run(example)['verdict'] == 'fail'


def test_baseline_orders_do_not_replace_terminal_checkout(example):
    orders(example, example[5])
    example[2]['ledger']['before']['order_snapshot']['orders'] = deepcopy(
        example[2]['ledger']['after']['order_snapshot']['orders'])
    entry = example[2]['checkout_storage']['after']['storage_state']['origins'][0]['localStorage'][0]
    entry['value'] = json.dumps({'address': {**example[5], 'unit': ''}})
    result = run(example)
    assert result['selected_evidence']['kind'] == 'terminal_checkout'
    assert result['verdict'] == 'fail'


@pytest.mark.parametrize('change', ['missing_state', 'foreign_origin', 'foreign_episode',
                                  'foreign_runtime', 'duplicate_storage', 'missing_address'])
def test_missing_or_unbound_evidence_is_inconclusive(example, change):
    evidence = example[2]
    checkout = evidence['checkout_storage']['after']
    if change == 'missing_state':
        checkout['storage_state']['origins'] = []
    elif change == 'foreign_origin':
        checkout['origin'] = 'https://foreign.example'
    elif change == 'foreign_episode':
        evidence['episode_id'] = 'another-episode'
    elif change == 'foreign_runtime':
        evidence['ledger']['after']['order_snapshot']['runtime_id'] = 'another-runtime'
    elif change == 'duplicate_storage':
        entries = checkout['storage_state']['origins'][0]['localStorage']
        entries.append(deepcopy(entries[0]))
    elif change == 'missing_address':
        checkout['storage_state']['origins'][0]['localStorage'][0]['value'] = '{}'
    assert run(example)['verdict'] == 'inconclusive'


def test_projection_is_visibly_address_only(example):
    report = run(example)
    projected = grading.project_native({'task_id': example[0]['task_id'],
        'native_grade': report}, {'task_id': example[0]['task_id']})
    assert projected.task_completed is True
    assert projected.verifier == 'simulated-order-address-only'
    assert 'not full ordering success' in projected.limitations[0]
