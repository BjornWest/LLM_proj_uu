import pytest

from environments.website_world import hidden_offer_generation as generation
from environments.website_world.test_memory_offer_generation import request as memory_request
from environments.website_world.test_hidden_offer_task import slot


def request():
    r = memory_request(); r['seed'] = 77
    r['task'] = {'kind':'cheapest_matching_after_clarification','concept_id':'footwear.walking_shoes','hidden_requirement':slot()}
    return r


def test_compile_resolves_hidden_meaning_before_sampling_without_public_value():
    r = request(); c = generation.compile_request(r)
    assert c['proxy_request']['task']['predicates'][0]['value'] == 42
    assert r['task']['hidden_requirement'] == slot()


@pytest.mark.parametrize('change', ['field','unit','slice','world'])
def test_invalid_task_cannot_enter_sampling(change,monkeypatch):
    r = request()
    if change == 'field': r['task']['hidden_requirement']['predicate']['field'] = 'sku.not_declared'
    elif change == 'unit': r['task']['hidden_requirement']['predicate']['unit'] = 'cm'
    elif change == 'slice': r['world']['concept_ids'] = ['tops.t_shirts']
    else: r['world'] = None
    def forbidden(*args,**kwargs): raise AssertionError('Sampling forbidden')
    monkeypatch.setattr(generation.feature_offer_generation,'generate',forbidden)
    with pytest.raises(ValueError): generation.generate(r)
