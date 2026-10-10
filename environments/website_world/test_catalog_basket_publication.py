from copy import deepcopy
from hashlib import sha256
import json
import pytest
from environments.website_world import catalog_basket_publication as publication
from environments.website_world.test_catalog_basket_generation import request
from environments.website_world.test_catalog_basket_task import fixture
from experiments.footwear_world_pilot.test_basket_quote import world


@pytest.mark.parametrize('incomplete', [False, True])
def test_native_population_inventory_and_incomplete_search_preserved(world, monkeypatch, incomplete):
    w, t, plan, domain, _, _ = fixture(world)
    before = deepcopy(w); calls = []
    def supplied(proxy, *, world_factory):
        calls.append(proxy)
        return {'world': w, 'basket_plan': plan, 'checkout_domain': domain, 'episode': {},
                'audit': {'request_sha256': 'proxy'}, 'resolved_configuration': {}}
    monkeypatch.setattr(publication.native.unified, 'generate', supplied)
    r = request(t)
    if incomplete: r['basket_search']['max_work'] = 1
    result = publication.generate(r)
    assert len(calls) == 1 and result['world'] == before
    assert result['catalog_basket_binding']['world_repaired'] is False
    assert result['catalog_basket_reference']['result']['complete'] == (not incomplete)
    assert result['catalog_basket_binding']['status'] == ('inconclusive_search' if incomplete else 'bound_exact_reference')
    assert set(result['basket_field_inventory']) == {'footwear.walking_shoes', 'tops.t_shirts'}
    assert result['episode']['manual_task'] == {'user_message': result['catalog_basket_task']['user_message'], 'memories': []}


def test_invalid_predicate_rejects_before_sampling(world, monkeypatch):
    _, task, *_ = fixture(world); r = request(task)
    r['task']['requirements'][1]['predicates'] = [{'field': 'product.facts.private_unknown', 'operator': 'eq', 'value': True}]
    def forbidden(*a, **kw): raise AssertionError('No draw allowed')
    monkeypatch.setattr(publication.native.unified, 'generate', forbidden)
    with pytest.raises(ValueError): publication.generate(r)


@pytest.mark.parametrize('status', ['optimal', 'infeasible', 'work_limit'])
def test_freeze_retains_exact_native_reference_and_binding(tmp_path, monkeypatch, status):
    reference = {'result': {'status': status, 'complete': status != 'work_limit'}}
    binding = {'status': 'inconclusive_search' if status == 'work_limit' else 'bound_exact_reference', 'world_repaired': False}
    result = {'catalog_basket_task': {'kind': publication.native.native.KIND},
        'catalog_basket_reference': reference, 'basket_field_inventory': {}, 'catalog_basket_binding': binding}
    monkeypatch.setattr(publication, 'generate', lambda *a, **kw: result)
    def freeze(request, output, **kwargs):
        result = generate(request); output.mkdir(); files = {}
        for name, key in [('feature-offer-task.private.json', 'feature_offer_task'),
                ('feature-offer-reference.private.json', 'feature_offer_reference'),
                ('feature-field-inventory.private.json', 'feature_field_inventory')]:
            (output/name).write_text(json.dumps(result[key])); files[name] = sha256((output/name).read_bytes()).hexdigest()
        return {'files': files}
    monkeypatch.setattr(publication.feature, 'prepare', freeze)
    output = tmp_path/'new'; manifest = publication.prepare({}, output)
    assert json.loads((output/'catalog-basket-reference.private.json').read_text()) == reference
    assert json.loads((output/'catalog-basket-binding.private.json').read_text()) == binding
    assert manifest['basket_binding_status'] == binding['status']
    assert not list(output.glob('feature-*'))
    for name, h in manifest['files'].items(): assert sha256((output/name).read_bytes()).hexdigest() == h
