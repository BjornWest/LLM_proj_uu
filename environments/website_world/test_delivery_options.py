"""Finite delivery parameters/order; central membership is a separate boundary."""
from copy import deepcopy

import pytest

from environments.website_world.delivery_options import options, producer_weights, sorted_projection, sorted_item_rows, COUNT_WEIGHTS


def test_json_weights_are_canonical_and_converted_for_the_producer():
    settings = options({'enabled': True})
    assert sum(settings['count_weights'].values()) == 100
    assert sum(v for k, v in settings['count_weights'].items() if int(k)>10)/100 == pytest.approx(.03)
    converted = producer_weights(settings)
    assert all(type(k) is int for k in converted)
    assert converted[2] == 18
    reversed_keys = options({'enabled': True, 'count_weights': dict(reversed(list(COUNT_WEIGHTS.items())))})
    assert settings == reversed_keys
    assert options({'enabled': False}) is None


@pytest.mark.parametrize('value', [None, {'enabled': 1}, {'enabled': False, 'count_weights': {}},
    {'enabled': True, 'count_weights': {}}, {'enabled': True, 'count_weights': {'01': 1}},
    {'enabled': True, 'count_weights': {'0': 1}}, {'enabled': True, 'count_weights': {'10001': 1}},
    {'enabled': True, 'count_weights': {'2': True}}, {'enabled': True, 'count_weights': {'2': float('nan')}},
    {'enabled': True, 'order_weights': {'cost': 1}}, {'enabled': True, 'order_weights': {'arrival': 0, 'cost': 0}},
])
def test_bad_parameters_reject(value):
    with pytest.raises(ValueError):options(value)


def estimate(day):
    return {'status': 'estimated', 'earliest_date': f'2026-10-{day:02d}', 'latest_date': f'2026-10-{day:02d}'}


def fixture():
    entries = [dict(id='fast', selection={'line': 'fast'}, arrival=estimate(7), totalMinor=900),
               dict(id='cheap', selection={'line': 'cheap'}, arrival=estimate(9), totalMinor=800),
               dict(id='unknown', selection={'line': 'unknown'}, arrival={'status': 'unknown'}, totalMinor=850),
               dict(id='cheap-tie', selection={'line': 'cheap-tie'}, arrival=estimate(9), totalMinor=800)]
    offers = [{'selection_group_id': 'g', 'option_id': o['id'], 'selection': o['selection'],
               'arrival': o['arrival'], 'complete_basket_total_minor': o['totalMinor']} for o in entries]
    return {'options': entries, 'groupOffers': offers, 'selected': entries[1], 'quoteId': 'native-id'}


def test_order_uses_real_quote_amounts_unknown_dates_and_stable_service_ties():
    value = fixture();before = deepcopy(value)
    cost = sorted_projection(value, 'cost');arrival = sorted_projection(value, 'arrival')
    assert [o['id'] for o in cost['options']] == ['cheap', 'cheap-tie', 'unknown', 'fast']
    assert [o['id'] for o in arrival['options']] == ['fast', 'cheap', 'cheap-tie', 'unknown']
    assert [o['option_id'] for o in cost['groupOffers']] == [o['id'] for o in cost['options']]
    assert value == before and arrival['selected'] is value['selected']
    assert arrival['quoteId'] == value['quoteId']
    assert set(o['id'] for o in cost['options']) == set(o['id'] for o in value['options'])
    value['options'][0]['totalMinor'] = 700
    value['groupOffers'][0]['complete_basket_total_minor'] = 700
    assert sorted_projection(value, 'cost')['options'][0]['id'] == 'fast'


def test_group_order_stays_contiguous_and_item_rows_use_same_criteria():
    value = fixture();extra = {**value['groupOffers'][0], 'selection_group_id': 'g2'}
    value['groupOffers'].insert(1, extra)
    result = sorted_projection(value, 'arrival')
    assert [o['selection_group_id'] for o in result['groupOffers']] == ['g']*4+['g2']
    rows = [{'id': o['id'], 'totalMinor': o['totalMinor'], 'arrival': o['arrival'].get('latest_date')} for o in value['options']]
    assert [r['id'] for r in sorted_item_rows(rows, 'cost')] == ['cheap', 'cheap-tie', 'unknown', 'fast']


def test_delivery_order_condition_mass_is_part_of_world_conditioning():
    from math import exp
    from environments.website_world import unified_generation, requirements, presentation
    request = {'schema': unified_generation.VERSION, 'seed': 1,
        'realism': {'delivery_options': {'enabled': True, 'order_weights': {'arrival': 3, 'cost': 1}},
                    'page_variations': {'enabled': True}},
        'requirements': [{'id': 'cost', 'target': {'kind': 'retailer_id', 'retailer_id': 'r'},
            'conditions': {'site.deliveryOrder': ['cost'], 'variation.site.navigationGrouping': ['shopping-services']}}]}
    config = unified_generation.compile_request(request)
    conditions = config['requirements'][0]['conditions']
    mass = requirements.site_log_mass('typical', config['priors'], config['resets'], config['policies'],
        conditions, config['variation_priors'], config['delivery_options'])
    assert exp(mass) == pytest.approx(.25/6)
    world = {'world_id': 'w', 'seed': 1, 'retailers': [{'retailer_id': 'r', 'scale': 'medium'}]}
    spec = {'schema': presentation.VERSION, 'world_id': 'w', 'component_priors': config['priors'],
        'delivery_options': config['delivery_options'], 'variation_priors': config['variation_priors'],
        'sites': {'r': {'conditions': conditions}}}
    plan = presentation.site_plan(world, world['retailers'][0], spec)
    assert plan['config']['deliveryOrder'] == 'cost'
    assert plan['presentation']['condition_mass'] == pytest.approx(exp(mass))
    spec['sites']['r']['conditions']['site.deliveryOrder'] = ['arrival']
    assert presentation.site_plan(world, world['retailers'][0], spec)['config']['deliveryOrder'] == 'arrival'


def test_delivery_order_without_its_recipe_and_native_reference_adoption_are_rejected():
    from environments.website_world import generation, unified_generation
    with pytest.raises(ValueError):
        unified_generation.compile_request({'schema': unified_generation.VERSION, 'seed': 1,
            'requirements': [{'id': 'cost', 'target': {'kind': 'all_retailers'},
                              'conditions': {'site.deliveryOrder': ['cost']}}]})
    def forbidden(*args, **kwargs):pytest.fail('Native producer must not be called')
    with pytest.raises(ValueError, match='native reference'):
        generation.generate({'schema': generation.VERSION, 'seed': 1,
            'realism': {'delivery_options': {'enabled': True}}}, world_factory=forbidden)


@pytest.fixture(scope='module')
def saved_world():
    import json
    from pathlib import Path
    return json.loads(Path('.local/website-variation-sampling-20261006-v1/world-1/pin/world.private.json').read_text())


def test_admitted_oracle_adapter_and_transport_share_routes_order_and_stale_binding(saved_world):
    from experiments.accepted_catalog_commerce import basket_quote, delivery_admission
    from environments.website_world.catalog_adapter import PublicAdapter
    from environments.website_world.basket import Baskets
    from environments.website_world.adapter import browser_address, digest
    base = basket_quote.make_plan(saved_world)
    admission = delivery_admission.make_plan(saved_world, base, seed=1, count_weights={2: 1})
    oracle = delivery_admission.Oracle(saved_world, base, admission)
    adapter = PublicAdapter(saved_world, base, oracle=oracle)
    rid = saved_world['retailers'][0]['retailer_id']
    adapter.delivery_orders[rid] = 'arrival'
    transport = Baskets(adapter, base, oracle=oracle, delivery_plan=admission)
    assert transport.plan_id != digest(base)
    address = adapter.catalog(rid, {'url': 'all'})['rememberedAddress']
    fulf = adapter.fulfilment(rid, address)
    assert all(len(v) <= 2 for v in fulf['optionsBySku'].values())
    r = adapter.retailers[rid]
    offer = next(o for o in r['offers'] if fulf['optionsBySku'][o['sku_id']])
    lines = [{'line_id': offer['offer_id'], 'offer_id': offer['offer_id'], 'quantity': 1}]
    request = {'revision': 1, 'world_id': saved_world['world_id'], 'plan_id': transport.plan_id,
        'lines': lines, 'address': address, 'selections': None, 'split': False, 'coupon_code': None}
    result = transport.quote(rid, request)
    assert result['selected'] and len(result['options']) <= 2
    assert result == sorted_projection(result, 'arrival')
    actual = set(v for o in result['options'] for v in o['selection'].values())
    assert actual == {v['id'] for v in fulf['optionsBySku'][offer['sku_id']]}
    old = basket_quote.quote(saved_world, rid, lines, plan=base)
    excluded = next(o for o in old['options'] if any(v not in actual for v in o['selection'].values()))
    reset = transport.quote(rid, {**request, 'revision': 2, 'selections': excluded['selection']})
    assert reset['selectionReset'] and reset['selected']
    assert all(v in actual for v in reset['selected']['selection'].values())
    with pytest.raises(ValueError, match='policy binding'):
        transport.quote(rid, {**request, 'plan_id': digest(base)})
    adapter.delivery_orders[rid] = 'cost'
    cost = transport.quote(rid, {**request, 'revision': 3})
    assert cost == sorted_projection(cost, 'cost')
    assert cost['selected'] == result['selected']
    assert cost['quoteId'] == result['quoteId']
    assert sorted(cost['options'], key=lambda x: x['id']) == sorted(result['options'], key=lambda x: x['id'])


def test_unsupported_count_pmf_rejects_proposals_without_clipping_or_fallback(saved_world):
    from environments.website_world import unified_generation, generation
    request = {'schema': unified_generation.VERSION, 'seed': 1,
        'realism': {'delivery_options': {'enabled': True, 'count_weights': {'10000': 1}}},
        'budget': {'max_proposals': 3, 'max_seconds': 10}}
    with pytest.raises(generation.SamplingBudgetExceeded) as result:
        unified_generation.generate(request, world_factory=lambda *args, **kwargs: deepcopy(saved_world))
    audit = result.value.audit
    assert audit['feasibility'] == 'unknown'
    assert len(audit['proposals']) == 3
    assert all(r['reason']=='delivery_count_support' and r['completion_mass']==0 and not r['accepted']
               for r in audit['proposals'])


def test_admission_plan_version_is_opt_in_and_leaves_default_settings_as_they_were():
    from experiments.accepted_catalog_commerce import delivery_admission
    from environments.website_world.delivery_options import (ADMISSION_PLANS, VERSION, producer_plan_version,
                                                             validate_settings)
    assert ADMISSION_PLANS == delivery_admission.PLAN_VERSIONS
    v1, v2 = ADMISSION_PLANS
    default = options({'enabled': True})
    assert set(default) == {'schema', 'count_weights', 'order_weights'} and default['schema'] == VERSION
    assert options({'enabled': True, 'admission_plan': v1}) == default
    assert producer_plan_version(default) == v1
    asked = options({'enabled': True, 'admission_plan': v2})
    assert asked == {**default, 'admission_plan': v2} and validate_settings(asked) == asked
    assert producer_plan_version(asked) == v2 and producer_weights(asked) == producer_weights(default)
    for bad in ('retailer-delivery-admission-plan-v3', '', None, 2, [v2]):
        with pytest.raises(ValueError):
            options({'enabled': True, 'admission_plan': bad})
        with pytest.raises(ValueError):
            validate_settings({**default, 'admission_plan': bad})
    # Normalized settings name a version only when it is not the default, so one request has one normal form.
    with pytest.raises(ValueError):
        validate_settings({**default, 'admission_plan': v1})
    with pytest.raises(ValueError):
        options({'enabled': False, 'admission_plan': v2})


@pytest.mark.parametrize('asked', [None, 'retailer-delivery-admission-plan-v1', 'retailer-delivery-admission-plan-v2'])
def test_the_catalog_generator_asks_the_oracle_for_the_settings_plan_version(saved_world, monkeypatch, asked):
    from experiments.accepted_catalog_commerce import delivery_admission
    from environments.website_world import unified_generation, generation
    made, real = [], delivery_admission.make_plan

    def recording(*args, **kwargs):
        made.append(kwargs.get('plan_version', 'not passed'))
        return real(*args, **kwargs)

    monkeypatch.setattr(delivery_admission, 'make_plan', recording)
    settings = {'enabled': True, 'count_weights': {'10000': 1}, **({} if asked is None else {'admission_plan': asked})}
    # The native generator's call is exercised with an order-set task in test_order_set_delivery.py.
    with pytest.raises(generation.SamplingBudgetExceeded):
        unified_generation.generate({'schema': unified_generation.VERSION, 'seed': 1,
                                     'realism': {'delivery_options': settings},
                                     'budget': {'max_proposals': 2, 'max_seconds': 10}},
                                    world_factory=lambda *args, **kwargs: deepcopy(saved_world))
    assert made == [asked or 'retailer-delivery-admission-plan-v1'] * 2


def test_a_generated_plan_has_the_asked_version_and_the_same_weights(saved_world):
    from experiments.accepted_catalog_commerce import basket_quote, delivery_admission
    from environments.website_world.delivery_options import producer_plan_version
    base = basket_quote.make_plan(saved_world)
    plans = {}
    for version in delivery_admission.PLAN_VERSIONS:
        settings = options({'enabled': True, 'admission_plan': version})
        plans[version] = delivery_admission.make_plan(saved_world, base, seed=saved_world['seed'],
                                                      count_weights=producer_weights(settings),
                                                      plan_version=producer_plan_version(settings))
        assert plans[version]['schema_version'] == version
        assert delivery_admission.validate_plan(saved_world, base, plans[version])['valid']
        oracle = delivery_admission.Oracle(saved_world, base, plans[version])
        rid = saved_world['retailers'][0]['retailer_id']
        assert oracle.public_policy(base, rid)['delivery_admission']['schema_version'] == version
    first, second = plans.values()
    assert first['count_weights'] == second['count_weights']
    assert [r['initial_route_keys'] for r in first['retailers']] == [r['initial_route_keys'] for r in second['retailers']]
    assert first['retailers'] != second['retailers']
