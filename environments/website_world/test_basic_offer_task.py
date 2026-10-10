"""Generic listed-price task boundaries; no inference or new world draws."""
from copy import deepcopy
import json
from pathlib import Path

import pytest
from environments.website_world import basic_offer_task as basic
from experiments.accepted_catalog_commerce import package_export


@pytest.fixture(scope='module')
def world():
    return json.loads(Path('.local/website-basic-offer-medium-20261006-v1/pin/world.private.json').read_text())


@pytest.mark.parametrize('cid', package_export.CONCEPTS)
def test_every_supported_type_ranks_the_complete_available_sku_domain(world, cid):
    before = deepcopy(world)
    spec = basic.resolve({'kind': basic.KIND, 'concept_id': cid}, seed=world['seed'],
                         concept_ids=world['config']['concept_ids'])
    task = basic.make(world, spec)
    result = basic.reference(world, task)
    pids = {p['public']['product_id'] for p in world['products'] if p['public']['concept_id'] == cid}
    eligible = [o for r in world['retailers'] for o in r['offers'] if o['product_id'] in pids and
                (sum(o['stock_by_source'].values()) or o['supplier_order']['enabled'])]
    assert {row['offer_id'] for row in result['candidates']} == {o['offer_id'] for o in eligible}
    assert result['minimum_price_minor'] == min(o['price_minor'] for o in eligible)
    assert {row['offer_id'] for row in result['winners']} == {
        o['offer_id'] for o in eligible if o['price_minor'] == result['minimum_price_minor']}
    assert basic.LABELS[cid] in task['user_message']
    for term in ('whole pack', 'supplier orders', 'any shop', 'shipping, coupons and cart deals', 'none are available'):
        assert term in task['user_message']
    assert world == before


def test_sampled_x_is_seed_stable_slice_order_invariant_and_price_independent(world):
    concepts = world['config']['concept_ids']
    selected = basic.resolve({'kind': basic.KIND}, seed=57, concept_ids=concepts)
    assert selected == basic.resolve({'kind': basic.KIND}, seed=57, concept_ids=list(reversed(concepts)))
    assert {basic.resolve({'kind': basic.KIND}, seed=i, concept_ids=concepts)['concept_id']
            for i in range(100)} == set(concepts)
    singleton = ['tops.t_shirts']
    assert basic.resolve({'kind': basic.KIND}, seed=1, concept_ids=singleton)['concept_id'] == singleton[0]


@pytest.mark.parametrize('value', [None, {}, {'kind': 'cheapest_delivered'},
    {'kind': basic.KIND, 'concept_id': 'unknown'}, {'kind': basic.KIND, 'concept_id': True},
    {'kind': basic.KIND, 'predicate': {'colour': 'red'}}])
def test_unsupported_templates_fail_before_sampling(world, value):
    with pytest.raises(ValueError):
        basic.resolve(value, seed=57, concept_ids=world['config']['concept_ids'])
    with pytest.raises(ValueError):
        basic.resolve({'kind': basic.KIND, 'concept_id': 'tops.t_shirts'}, seed=57,
                      concept_ids=['tablets.everyday_media_tablets'])


def rebind(world):
    value = {k: v for k, v in world.items() if k != 'world_id'}
    from experiments.footwear_world_pilot.model import digest
    world['world_id'] = digest(value)


def test_all_ties_backorders_and_no_match_without_repair(world):
    value = deepcopy(world)
    cid = 'tablets.everyday_media_tablets'
    pids = {p['public']['product_id'] for p in value['products'] if p['public']['concept_id'] == cid}
    offers = [o for r in value['retailers'] for o in r['offers'] if o['product_id'] in pids]
    for o in offers:
        o['price_minor'] = 100
        o['stock_by_source'] = dict.fromkeys(o['stock_by_source'], 0)
        o['supplier_order']['enabled'] = False
    offers[0]['supplier_order'].update(enabled=True, wait_days=5, disclosure='product_page')
    offers[1]['stock_by_source'][next(iter(offers[1]['stock_by_source']))] = 1
    rebind(value)
    task = basic.make(value, {'kind': basic.KIND, 'concept_id': cid})
    reference = basic.reference(value, task)
    assert len(reference['winners']) == 2
    assert {row['availability'] for row in reference['winners']} == {'backorder', 'in_stock'}
    assert len(reference['unavailable_offer_ids']) == len(offers) - 2
    offers[0]['supplier_order']['enabled'] = False
    offers[1]['stock_by_source'] = dict.fromkeys(offers[1]['stock_by_source'], 0)
    rebind(value)
    with pytest.raises(ValueError, match='binding'):basic.reference(value, task)
    empty = basic.reference(value, basic.make(value, {'kind': basic.KIND, 'concept_id': cid}))
    assert empty['status'] == 'no_match' and empty['minimum_price_minor'] is None and empty['winners'] == []


def test_reference_keeps_actual_offer_link_and_required_variant_selection(world):
    spec = {'kind': basic.KIND, 'concept_id': 'footwear.walking_shoes'}
    reference = basic.reference(world, basic.make(world, spec))
    bindings = {'retailer_offers': {r['offer_id']: {
        **{k: r[k] for k in ('retailer_id', 'product_id', 'sku_id')},
        'url': 'http://localhost:1234/#/product/model', 'required_selection': {'size': '42'},
        'selection': {'size': '42'}, 'url_behavior': 'none'} for r in reference['candidates']}}
    bound = basic.bind_reference(reference, bindings)
    assert all(row['required_selection'] == {'size': '42'} for row in bound['winners'])
    assert all('url' not in row for row in reference['winners'])
    first = reference['candidates'][0]['offer_id']
    bindings['retailer_offers'][first]['sku_id'] = 'foreign'
    with pytest.raises(ValueError, match='binding'):basic.bind_reference(reference, bindings)


def test_branch_only_stock_and_supplier_label_priority_match_public_state(world):
    value = deepcopy(world)
    retailer = next(r for r in value['retailers'] if r['offers'] and any(s['kind'] == 'branch' for s in r['source_locations']))
    source = next(s for s in retailer['source_locations'] if s['kind'] == 'branch')
    source['shipping_enabled'] = False
    offer = retailer['offers'][0]
    offer['stock_by_source'] = dict.fromkeys(offer['stock_by_source'], 0)
    offer['stock_by_source'][source['source_id']] = 2
    offer['supplier_order'].update(enabled=True, wait_days=5, disclosure='product_page')
    rebind(value)
    cid = next(p['public']['concept_id'] for p in value['products'] if p['public']['product_id'] == offer['product_id'])
    result = basic.reference(value, basic.make(value, {'kind': basic.KIND, 'concept_id': cid}))
    assert next(row for row in result['candidates'] if row['offer_id'] == offer['offer_id'])['availability'] == 'backorder'
    offer['supplier_order']['enabled'] = False
    rebind(value)
    result = basic.reference(value, basic.make(value, {'kind': basic.KIND, 'concept_id': cid}))
    assert next(row for row in result['candidates'] if row['offer_id'] == offer['offer_id'])['availability'] == 'in_stock'
    offer['supplier_order']['enabled'] = 'yes'
    rebind(value)
    with pytest.raises(ValueError, match='eligibility'):
        basic.reference(value, basic.make(value, {'kind': basic.KIND, 'concept_id': cid}))


def test_template_compiles_before_world_and_preserves_explicit_concentration():
    from environments.website_world import unified_generation as generation
    request = {'schema': generation.VERSION, 'seed': 57,
               'world': {'concept_ids': ['tops.t_shirts', 'tablets.everyday_media_tablets']},
               'task': {'kind': basic.KIND}}
    before = deepcopy(request)
    config = generation.compile_request(request)
    cid = config['basic_offer_selection']['concept_id']
    assert config['world']['tasks'] == [cid]
    assert request == before
    request['world']['tasks'] = ['tops.t_shirts']
    request['task']['concept_id'] = 'tablets.everyday_media_tablets'
    config = generation.compile_request(request)
    assert config['world']['tasks'] == ['tops.t_shirts']
    assert config['basic_offer_selection']['concept_id'] == 'tablets.everyday_media_tablets'
    assert 'basic_offer_selection' not in generation.compile_request({'schema': generation.VERSION, 'seed': 57})


def test_generation_binds_private_reference_and_public_message_without_resampling(world, monkeypatch):
    from environments.website_world import unified_generation as generation
    from intent_browser.connected_world_task import public_projection
    from types import SimpleNamespace
    request = {'schema': generation.VERSION, 'seed': world['seed'],
               'budget': {'max_proposals': 1}, 'task': {'kind': basic.KIND}}
    calls = []
    def factory(seed, **kwargs):
        calls.append((seed, kwargs))
        return world
    result = generation.generate(request, world_factory=factory)
    assert len(calls) == 1
    assert result['basic_offer_reference'] == basic.reference(world, result['basic_offer_task'])
    assert calls[0][1]['tasks'] == [result['basic_offer_task']['concept_id']]
    fake = SimpleNamespace(index_origin='http://localhost:1234', world=world)
    public = public_projection(generation.bind_task(fake, result['episode']))
    assert public['task_id'] == result['basic_offer_task']['task_id']
    assert public['user_message'] == result['basic_offer_task']['user_message']
    for key in ('winners', 'candidates', 'minimum_price_minor'):
        assert key not in json.dumps(public)


def test_selected_x_survives_rejected_world_proposals(world, monkeypatch):
    from environments.website_world import unified_generation as generation
    evaluate = generation.requirements.evaluate
    evaluations, calls = [], []
    def conditioned(*args, **kwargs):
        result = evaluate(*args, **kwargs)
        evaluations.append(result)
        if len(evaluations) == 1:
            result.update(log_mass=float('-inf'), reason='test_zero_completion')
        return result
    monkeypatch.setattr(generation.requirements, 'evaluate', conditioned)
    def factory(seed, **kwargs):
        calls.append((seed, kwargs['tasks']))
        value = deepcopy(world)
        value['seed'] = seed
        rebind(value)
        return value
    result = generation.generate({'schema': generation.VERSION, 'seed': world['seed'],
        'budget': {'max_proposals': 2}, 'task': {'kind': basic.KIND}}, world_factory=factory)
    assert len(calls) == 2 and calls[0][0] != calls[1][0]
    assert calls[0][1] == calls[1][1] == [result['basic_offer_task']['concept_id']]
    assert [row['accepted'] for row in result['audit']['proposals']] == [False, True]
