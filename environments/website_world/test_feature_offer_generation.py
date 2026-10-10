from copy import deepcopy

import pytest

from environments.website_world import feature_offer_generation as generation
from environments.website_world.test_feature_offer_task import fixture


def request():
    return {'schema': 'website-world-generation-v2', 'seed': 62,
        'world': {'concept_ids': ['footwear.walking_shoes', 'tops.t_shirts'],
                  'controls': {'world_size': 0.75}},
        'task': {'kind': 'cheapest_matching_available', 'concept_id': 'footwear.walking_shoes',
            'predicates': [{'field': 'sku.size_eu', 'operator': 'eq', 'value': 42}]},
        'budget': {'max_proposals': 1, 'max_seconds': 120}}


def test_task_compiles_before_world_and_preserves_explicit_concentration():
    r = request(); c = generation.compile_request(r)
    assert c['proxy_request']['world']['tasks'] == ['footwear.walking_shoes']
    assert r['task']['kind'] == 'cheapest_matching_available'
    r['world']['tasks'] = ['tops.t_shirts']
    assert generation.compile_request(r)['proxy_request']['world']['tasks'] == ['tops.t_shirts']


@pytest.mark.parametrize('change', ['field', 'type', 'unit', 'concept', 'comparison'])
def test_invalid_task_rejects_before_world_factory(change, monkeypatch):
    r = request()
    if change == 'field': r['task']['predicates'][0]['field'] = 'sku.not_defined'
    elif change == 'type': r['task']['predicates'][0]['value'] = True
    elif change == 'unit': r['task']['predicates'][0]['unit'] = 'cm'
    elif change == 'concept': r['world']['concept_ids'] = ['tops.t_shirts']
    else:
        r['task']['comparison_site_id'] = 'comparison-07'
        r['surrounding_sites'] = {'enabled': False}
    def forbidden(*args, **kwargs): raise AssertionError('No world draw allowed')
    monkeypatch.setattr(generation.unified_generation, 'generate', forbidden)
    with pytest.raises(ValueError): generation.generate(r)


def test_generation_binds_no_match_without_repair_or_another_draw(monkeypatch):
    world, _, _, _, _ = fixture()
    before = deepcopy(world); calls = []
    def existing(proxy, *, world_factory):
        calls.append(proxy)
        return {'world': world, 'surrounding': None, 'resolved_configuration': {},
                'audit': {'request_sha256': 'proxy'}, 'episode': {}}
    monkeypatch.setattr(generation.unified_generation, 'generate', existing)
    r = request(); r['task']['predicates'][0]['value'] = 99
    result = generation.generate(r)
    assert len(calls) == 1 and world == before
    assert result['feature_offer_reference']['status'] == 'no_match'
    assert result['feature_offer_task']['predicates'] == r['task']['predicates']
    assert result['episode']['manual_task']['user_message'] == result['feature_offer_task']['user_message']
