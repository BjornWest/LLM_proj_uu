"""Finite reference/mass controls; authored fixtures and saved worlds only."""
from copy import deepcopy
from math import log

import pytest

from environments.website_world import conditioned_feature_generation as api
from environments.website_world.test_feature_offer_task import fixture


def request(requirements=None, **task_options):
    return {'schema': 'website-world-generation-v2', 'seed': 73,
        'world': {'concept_ids': ['footwear.walking_shoes']},
        'task': {'kind': 'cheapest_matching_available',
            'concept_id': 'footwear.walking_shoes',
            'predicates': [{'field': 'sku.size_eu', 'operator': 'eq', 'value': 42}],
            **task_options}, 'requirements': requirements or [],
        'budget': {'max_proposals': 1, 'max_seconds': 10}}


def world_config(monkeypatch, required, **task_options):
    world = fixture()[0]
    for retailer in world['retailers']:
        retailer['scale'] = 'small'
        retailer['initial_form'] = {'provenance': {'autofill': False,
            'incorrect_values': False, 'missing_fields': False, 'wrong_mode': None}}
    # Isolate the mass/reference adapter from unrelated surrounding sampling.
    # Actual producer/sidecar parity has its separate saved-world acceptance.
    monkeypatch.setattr(api.unified_generation.surrounding_config, '_generate_bound',
        lambda world, options, binding: {'source_world_id': world['world_id'],
            'source_world_sha256': binding, 'sites': []})
    return world, api.compile_request(request(required, **task_options))


def winner_reset(values):
    return {'id': 'winner', 'target': {'kind': 'best_matching_retailers'},
            'conditions': {'site.resetPolicy': values}}


def test_all_winning_retailers_and_skus_are_retained_without_world_mutation(monkeypatch):
    world, config = world_config(monkeypatch, [winner_reset(['checkout'])])
    before = deepcopy(world)
    result, task, reference, _ = api.completion(world, config)
    winners = sorted({w['retailer_id'] for w in reference['winners']})
    assert len(reference['winners']) == 4 and len(winners) == 2
    assert result['resolved'] == [{'id': 'winner', 'retailer_ids': winners}]
    assert set(result['conditions']) == set(winners)
    assert result['log_mass'] == pytest.approx(2 * log(config['configuration']['resets']['checkout']))
    assert world == before and 'reference' not in world
    assert task['kind'] == 'cheapest_matching_available'


def test_reference_count_is_distinct_offers_not_models_or_retailers(monkeypatch):
    requirement = {'id': 'count', 'target': {'kind': 'world_reference'},
                   'status': ['match'], 'best_offer_count': {'min': 4, 'max': 4}}
    world, config = world_config(monkeypatch, [requirement])
    result, _, reference, _ = api.completion(world, config)
    assert len({r['product_id'] for r in reference['winners']}) == 1
    assert result['log_mass'] == 0 and result['resolved'] == [{'id': 'count', 'best_offer_count': 4}]
    requirement['best_offer_count'] = {'min': 1, 'max': 2}
    _, wrong = world_config(monkeypatch, [requirement])
    failed, _, _, _ = api.completion(world, wrong)
    assert failed['log_mass'] == float('-inf') and failed['reason'] == 'best_offer_count'


def test_overlapping_requirements_intersect_once(monkeypatch):
    all_sites = {'id': 'all', 'target': {'kind': 'all_retailers'},
                 'conditions': {'site.resetPolicy': ['checkout']}}
    world, config = world_config(monkeypatch,
        [winner_reset(['preserve', 'checkout']), all_sites])
    result, _, _, _ = api.completion(world, config)
    assert result['log_mass'] == pytest.approx(len(world['retailers']) *
        log(config['configuration']['resets']['checkout']))
    assert all(c == {'site.resetPolicy': ['checkout']} for c in result['conditions'].values())


def test_conflicting_overlap_has_zero_completion(monkeypatch):
    world, config = world_config(monkeypatch, [winner_reset(['preserve']),
        {'id': 'all', 'target': {'kind': 'all_retailers'},
         'conditions': {'site.resetPolicy': ['checkout']}}])
    result, _, _, _ = api.completion(world, config)
    assert result['log_mass'] == float('-inf') and result['reason'] == 'zero_completion'


def test_no_match_reference_is_explicit_but_empty_winner_target_fails(monkeypatch):
    required = {'id': 'empty', 'target': {'kind': 'world_reference'},
                'status': ['no_match'], 'best_offer_count': {'min': 0, 'max': 0}}
    world, config = world_config(monkeypatch, [required], max_price_minor=73999)
    result, _, reference, _ = api.completion(world, config)
    assert reference['status'] == 'no_match' and result['log_mass'] == 0
    _, config = world_config(monkeypatch, [winner_reset(['preserve'])], max_price_minor=73999)
    result, _, _, _ = api.completion(world, config)
    assert result['log_mass'] == float('-inf') and result['reason'] == 'empty_target'


def test_winner_address_coverage_checks_each_winning_sku_only(monkeypatch):
    required = {'id': 'home', 'target': {'kind': 'best_matching_retailers'},
                'initial_form': {'home_delivery_available': [True]}}
    world, config = world_config(monkeypatch, [required])
    observed = []
    def checker(actual_world, retailer, selector):
        assert actual_world is world and selector == 'best_matching_retailers'
        assert len(retailer['offers']) == 1
        observed.append(retailer['offers'][0]['offer_id'])
        return True
    result, _, reference, _ = api.completion(world, config, home_delivery_checker=checker)
    assert result['log_mass'] == 0
    assert sorted(observed) == sorted(w['offer_id'] for w in reference['winners'])
    result, _, _, _ = api.completion(world, config, home_delivery_checker=lambda *args: False)
    assert result['log_mass'] == float('-inf') and result['reason'] == 'producer_form'


@pytest.mark.parametrize('requirement', [
    {'id': 'x', 'target': {'kind': 'unknown'}, 'conditions': {'site.resetPolicy': ['preserve']}},
    {'id': 'x', 'target': {'kind': 'world_reference'}, 'status': ['uncertain']},
    {'id': 'x', 'target': {'kind': 'world_reference'}, 'best_offer_count': {'min': -1, 'max': 3}},
    {'id': 'x', 'target': {'kind': 'world_reference'}, 'conditions': {'site.resetPolicy': ['checkout']}},
    {'id': 'x', 'target': {'kind': 'best_matching_retailers'}, 'conditions': {'site.resetPolicy': ['unknown']}}])
def test_invalid_conditioning_rejects_before_factory(requirement):
    calls = []
    with pytest.raises(ValueError):
        api.generate(request([requirement]), world_factory=lambda *a, **k: calls.append(1))
    assert not calls
