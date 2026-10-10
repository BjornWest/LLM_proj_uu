from copy import deepcopy

import pytest

from environments.website_world import catalog_memory, memory_offer_generation as generation
from environments.website_world.test_memory_offer_task import fixture, record


def request():
    return {'schema': 'website-world-generation-v2', 'seed': 76,
        'world': {'concept_ids': ['footwear.walking_shoes', 'tops.t_shirts'], 'controls': {'world_size': 0.75}},
        'task': {'kind': 'cheapest_matching_with_memory', 'concept_id': 'footwear.walking_shoes',
                 'recipient': 'self', 'memory_records': [record()]},
        'budget': {'max_proposals': 1, 'max_seconds': 120}}


def test_resolves_before_sampling_and_does_not_change_input_or_concentration():
    r = request(); before = deepcopy(r)
    r['world']['tasks'] = ['tops.t_shirts']; before = deepcopy(r)
    c = generation.compile_request(r)
    assert r == before and c['proxy_request']['world']['tasks'] == ['tops.t_shirts']
    assert c['proxy_request']['task']['predicates'] == record()['predicates']


@pytest.mark.parametrize('change', ['recipient', 'conflict', 'unit', 'world', 'slice', 'comparison', 'unknown_field'])
def test_invalid_or_unresolved_task_cannot_call_sampling(change, monkeypatch):
    r = request()
    if change == 'recipient': r['task']['recipient'] = None
    elif change == 'conflict': r['task']['memory_records'].append(record(43, id='contradiction'))
    elif change == 'unit': r['task']['memory_records'][0]['predicates'][0]['unit'] = 'cm'
    elif change == 'world': r['world'] = []
    elif change == 'slice': r['world']['concept_ids'] = ['tops.t_shirts']
    elif change == 'comparison': r['task']['comparison_site_id'] = 'comparison-07'
    else: r['task']['memory_records'][0]['predicates'][0]['field'] = 'sku.missing'
    def forbidden(*args, **kwargs): raise AssertionError('No sampling permitted')
    monkeypatch.setattr(generation.feature_offer_generation, 'generate', forbidden)
    with pytest.raises(ValueError): generation.generate(r)


def test_one_underlying_call_binds_natural_no_match_without_repair(monkeypatch):
    world, _, _, _, _ = fixture(); before = deepcopy(world); calls = []
    def existing(proxy, *, world_factory):
        calls.append(proxy)
        return {'world': world, 'surrounding': None, 'resolved_configuration': {},
                'audit': {'request_sha256': 'proxy'}, 'episode': {}}
    monkeypatch.setattr(generation.feature_offer_generation.unified_generation, 'generate', existing)
    r = request(); r['task']['memory_records'][0]['predicates'][0]['value'] = 99
    result = generation.generate(r)
    assert len(calls) == 1 and world == before
    assert result['memory_offer_reference']['status'] == 'no_match'
    assert result['memory_offer_task']['memory_records'] == r['task']['memory_records']
    assert result['episode']['manual_task']['memories'] == result['memory_offer_task']['memories']
    assert '99' not in result['episode']['manual_task']['user_message']
    assert result['audit']['request_sha256'] != result['audit']['feature_request_sha256']
