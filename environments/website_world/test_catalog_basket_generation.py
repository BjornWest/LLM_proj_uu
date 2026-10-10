"""Pre-world validation and unchanged supplied-world task attachment."""
from copy import deepcopy

import pytest

from experiments.footwear_world_pilot.test_basket_quote import world
from environments.website_world import catalog_basket_generation as generation
from environments.website_world.test_catalog_basket_task import fixture


def request(task):
    return {'schema': 'website-world-generation-v2', 'seed': 80,
            'world': {'concept_ids': ['footwear.walking_shoes', 'tops.t_shirts']},
            'task': {k: task[k] for k in ('kind', 'requirements', 'domain')},
            'basket_search': {'max_work': 50000, 'max_seconds': 10}}


def test_generated_task_keeps_whole_world_and_explicit_shared_domain(world, monkeypatch):
    w, t, p, d, _, _ = fixture(world)
    calls = []
    def saved(proxy, *, world_factory):
        calls.append(proxy)
        return {'world': w, 'basket_plan': p, 'checkout_domain': d, 'episode': {},
                'audit': {'request_sha256': 'original'}, 'resolved_configuration': {}}
    monkeypatch.setattr(generation.unified, 'generate', saved)
    before = deepcopy(w)
    result = generation.generate(request(t))
    assert result['world'] == before and len(calls) == 1
    assert calls[0]['world']['tasks'] == ['footwear.walking_shoes', 'tops.t_shirts']
    assert result['checkout_domain'] == d and result['catalog_basket_reference']['result']['complete']
    assert result['catalog_basket_binding'] == {'status': 'bound_exact_reference', 'world_repaired': False}
    assert result['episode']['manual_task']['user_message'] == result['catalog_basket_task']['user_message']


def test_budget_exhaustion_retained_without_world_repair(world, monkeypatch):
    w, t, p, d, _, _ = fixture(world)
    monkeypatch.setattr(generation.unified, 'generate', lambda proxy, *, world_factory:
        {'world': w, 'basket_plan': p, 'checkout_domain': d, 'episode': {},
         'audit': {'request_sha256': 'original'}, 'resolved_configuration': {}})
    r = request(t); r['basket_search']['max_work'] = 1
    before = deepcopy(w)
    result = generation.generate(r)
    assert result['world'] == before and result['catalog_basket_binding']['status'] == 'inconclusive_search'
    assert not result['catalog_basket_reference']['result']['complete']


@pytest.mark.parametrize('bad', ['field', 'budget'])
def test_invalid_predeclared_task_rejects_before_world_factory(world, monkeypatch, bad):
    _, t, _, _, _, _ = fixture(world)
    r = request(t)
    if bad == 'field':
        r['task']['requirements'][0]['predicates'] = [{'field': 'product.facts.secret_nonexistent', 'operator': 'eq', 'value': True}]
    else:
        r['basket_search']['max_seconds'] = float('inf')
    def forbidden(*args, **kwargs): raise AssertionError('Generation must not start')
    monkeypatch.setattr(generation.unified, 'generate', forbidden)
    with pytest.raises(ValueError): generation.generate(r)
