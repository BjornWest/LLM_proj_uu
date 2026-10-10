"""Saved native commerce fixtures; no world generation, model calls or purchases."""
from copy import deepcopy
import json
import math

import pytest

from experiments.footwear_world_pilot.test_basket_quote import world, lines, bulky_policy, coupon
from .test_basket_quote import bridged
from . import delivery_admission as admission, basket_quote as catalog
from experiments.footwear_world_pilot import basket_quote as native


@pytest.fixture(params=['native', 'catalog'])
def commerce(world, request):
    backend = native if request.param == 'native' else catalog
    w = world if backend is native else bridged(world)
    return w, backend, backend.make_plan(w), w['retailers'][0]['retailer_id']


def admitted(commerce, count):
    w, _, plan, rid = commerce
    return admission.make_plan(w, plan, seed=7, retailer_counts={rid: count})


def test_full_menu_exact_formula_and_option_parity(commerce):
    w, backend, plan, rid = commerce
    before = deepcopy((w, plan)); globals_before = dict(backend.quote.__globals__)
    routes = admission.enumerate_routes(w, plan, rid)
    sidecar = admitted(commerce, len(routes))
    old = backend.quote(w, rid, lines(w), plan=plan)
    new = admission.quote(w, rid, lines(w), plan=plan, admission_plan=sidecar)
    for key in ('lines', 'delivery_choices', 'options', 'group_delivery_offers', 'line_availability'):
        assert new[key] == old[key]
    assert new['quote_id'] != old['quote_id']
    assert new['schema_version'] == admission.VERSION
    assert (w, plan) == before and backend.quote.__globals__ == globals_before


def test_one_route_keeps_real_home_and_excluded_selection_is_invalid(commerce):
    w, backend, plan, rid = commerce
    oracle = admission.Oracle(w, plan, admitted(commerce, 1))
    result = oracle.quote(w, rid, lines(w), plan=plan)
    assert len(result['delivery_choices']) == len(result['options']) == 1
    assert result['delivery_choices'][0]['destination_type'] == 'home'
    selected = result['options'][0]['selection']
    q = oracle.quote(w, rid, lines(w), plan=plan, selections=selected)
    assert q['status'] == 'quoted' and q['selected'] == result['options'][0]
    excluded = next(c['choice_id'] for c in backend.quote(w, rid, lines(w), plan=plan)['delivery_choices']
                    if c['choice_id'] not in selected.values())
    q = oracle.quote(w, rid, lines(w), plan=plan,
                     selections={line['line_id']: excluded for line in lines(w)})
    assert q['status'] == 'invalid_plan'


def test_count_pmf_bounded_replay_and_explicit_override(commerce):
    w, _, plan, rid = commerce
    bound = len(admission.enumerate_routes(w, plan, rid))
    draws = [admission.make_plan(w, plan, seed=i, count_weights={1: 1, 2: 1, bound+1: 100})
             for i in range(30)]
    assert {p['retailers'][0]['sampled_count'] for p in draws} == {1, 2}
    assert draws[7] == admission.make_plan(w, plan, seed=7, count_weights={1: 1, 2: 1, bound+1: 100})
    p = admission.make_plan(w, plan, seed=7, count_weights={bound+1: 1}, retailer_counts={rid: 1})
    assert admission.validate_plan(w, plan, p)['valid']
    with pytest.raises(ValueError, match='mass within'):
        admission.make_plan(w, plan, seed=7, count_weights={bound+1: 1})


def test_address_changes_intersect_menu_without_redraw(commerce):
    w, _, plan, rid = commerce
    bound = len(admission.enumerate_routes(w, plan, rid))
    oracle = admission.Oracle(w, plan, admitted(commerce, bound))
    initial = oracle.quote(w, rid, lines(w), plan=plan)
    destination = {**w['user_location'], 'location_id': 'edited-address',
                   'local_east_km': w['user_location']['local_east_km'] + 4}
    edited = oracle.quote(w, rid, lines(w), plan=plan, destination=destination)
    assert edited['status'] == 'offers_available'
    assert len(edited['delivery_choices']) < len(initial['delivery_choices'])
    assert {admission.route_key(c) for c in edited['delivery_choices']} <= {
        admission.route_key(c) for c in initial['delivery_choices']}
    first = next(c for c in initial['delivery_choices'] if c['destination_type'] == 'home')
    second = next(c for c in edited['delivery_choices'] if admission.route_key(c) == admission.route_key(first))
    assert first['choice_id'] != second['choice_id']
    assert edited == oracle.quote(w, rid, lines(w), plan=plan, destination=destination)


def test_quote_identity_and_isolated_bound_plan(commerce):
    w, _, plan, rid = commerce
    sidecar = admitted(commerce, 1); oracle = admission.Oracle(w, plan, sidecar)
    first = oracle.quote(w, rid, lines(w), plan=plan)
    sidecar['retailers'][0]['admitted_route_keys'].clear()
    assert oracle.quote(w, rid, lines(w), plan=plan) == first
    stale = oracle.quote(w, rid, lines(w), plan=plan, expected_quote_id='old')
    assert stale['status'] == 'stale_quote' and not stale['options']
    two = admission.quote(w, rid, lines(w), plan=plan, admission_plan=admitted(commerce, 2),
                          expected_quote_id=first['quote_id'])
    assert two['status'] == 'stale_quote'
    w['retailers'][0]['offers'][0]['price_minor'] += 1
    changed = admission._backend(w).make_plan(w)
    with pytest.raises(ValueError, match='Stale delivery'):
        oracle.quote(w, rid, lines(w), plan=changed)


def test_json_roundtrip_and_retailer_iteration_independence(world):
    extra = deepcopy(world['retailers'][0]); extra['retailer_id'] = 'second-retailer'
    world['retailers'].append(extra)
    plan = native.make_plan(world)
    first = admission.make_plan(world, plan, seed=8)
    assert admission.validate_plan(world, plan, json.loads(json.dumps(first)))['valid']
    # Digest is order-dependent, but unrelated traversal order cannot change a
    # retailer's count/subset: membership uses stable identities, not shared RNG.
    world['retailers'].reverse()
    second = admission.make_plan(world, native.make_plan(world), seed=8)
    assert first['retailers'] == second['retailers']


def test_carrier_without_home_support_can_keep_collection(world):
    world['address_context']['carriers'][0]['home_delivery'] = False
    plan = native.make_plan(world); rid = world['retailers'][0]['retailer_id']
    p = admission.make_plan(world, plan, seed=8, retailer_counts={rid: 1})
    assert p['retailers'][0]['home_anchor_key'] is None
    assert len(p['retailers'][0]['admitted_route_keys']) == 1
    assert admission.validate_plan(world, plan, p)['valid']


def test_no_refill_when_new_collection_becomes_geographically_possible(world):
    carrier = world['address_context']['carriers'][0]
    point = next(p for p in world['address_context']['collection_points']
                 if p['point_id'] in carrier['collection_point_ids'])
    point['location']['local_east_km'] += 5
    plan = native.make_plan(world); rid = world['retailers'][0]['retailer_id']
    initial = admission.enumerate_routes(world, plan, rid)
    p = admission.make_plan(world, plan, seed=8, retailer_counts={rid: len(initial)})
    oracle = admission.Oracle(world, plan, p)
    moved = {**world['user_location'], 'local_east_km': world['user_location']['local_east_km']+4}
    potential = admission.enumerate_routes(world, plan, rid, destination=moved)
    assert any(c['point_id'] == point['point_id'] for c in potential)
    q = oracle.quote(world, rid, lines(world), plan=plan, destination=moved)
    assert not any(c['point_id'] == point['point_id'] for c in q['delivery_choices'])


def test_quantity_stock_does_not_repair_membership(commerce):
    w, backend, plan, rid = commerce
    oracle = admission.Oracle(w, plan, admitted(commerce, 1))
    q = oracle.quote(w, rid, [{**line, 'quantity': 100000} for line in lines(w)], plan=plan)
    assert q['status'] == 'unavailable' and not q['options']
    q = oracle.quote(w, rid, lines(w), plan=plan)
    assert len(q['options']) == 1
    assert backend.quote(w, rid, lines(w), plan=plan)['schema_version'] == backend.VERSION


@pytest.mark.parametrize('weights', [{}, {True: 1}, {0: 1}, {1: -1}, {1: 0},
                                    {1: math.inf}, {1: math.nan}, {'1': 1}, {1: True}])
def test_bad_count_weights_rejected(world, weights):
    with pytest.raises(ValueError):
        admission.make_plan(world, native.make_plan(world), seed=1, count_weights=weights)


def test_forged_plan_home_and_count_rejected(world):
    plan = native.make_plan(world); rid = world['retailers'][0]['retailer_id']
    valid = admission.make_plan(world, plan, seed=1, retailer_counts={rid: 1})
    for change in ('foreign_route', 'boolean_count', 'missing_home', 'stale_plan'):
        p = deepcopy(valid)
        if change == 'foreign_route':p['retailers'][0]['admitted_route_keys'] = ['route/foreign']
        if change == 'boolean_count':p['retailers'][0]['sampled_count'] = True
        if change == 'missing_home':p['retailers'][0]['home_anchor_key'] = None
        if change == 'stale_plan':p['basket_plan_sha256'] = 'foreign'
        with pytest.raises(ValueError):admission.validate_plan(world, plan, p)


def test_bulky_home_anchor_uses_real_native_capability(world):
    policy = bulky_policy(world)
    plan = native.make_plan(world, retailer_policies={world['retailers'][0]['retailer_id']: policy})
    rid = world['retailers'][0]['retailer_id']
    p = admission.make_plan(world, plan, seed=3, retailer_counts={rid: 1})
    q = admission.quote(world, rid, lines(world), plan=plan, admission_plan=p)
    assert q['options'] and all(c['destination_type'] == 'home' for c in q['delivery_choices'])


def test_empty_geographic_universe_stays_empty(world):
    for carrier in world['address_context']['carriers']:
        carrier['home_delivery'] = False; carrier['collection_point_ids'] = []
    for branch in world['retailers'][0]['geography']['branches']:branch['pickup_enabled'] = False
    plan = native.make_plan(world); rid = world['retailers'][0]['retailer_id']
    p = admission.make_plan(world, plan, seed=4)
    assert p['retailers'][0]['sampled_count'] == 0
    assert admission.validate_plan(world, plan, p)['valid']
    assert admission.quote(world, rid, lines(world), plan=plan, admission_plan=p)['status'] == 'unavailable'


def test_geographically_unavailable_bulky_home_is_not_invented(world):
    policy = bulky_policy(world)
    world['retailers'][0]['geography']['fulfilment_policy']['delivery_countries'] = []
    rid = world['retailers'][0]['retailer_id']
    plan = native.make_plan(world, retailer_policies={rid: policy})
    p = admission.make_plan(world, plan, seed=3, retailer_counts={rid: 1})
    assert p['retailers'][0]['home_anchor_key'] is None
    assert admission.validate_plan(world, plan, p)['valid']


def test_native_coupon_recalculates_cost_without_changing_menu(world):
    rid = world['retailers'][0]['retailer_id'];plan = native.make_plan(world)
    cp = coupon(world)
    p = admission.make_plan(world, plan, seed=2, retailer_counts={rid: 2})
    oracle = admission.Oracle(world, plan, p)
    plain = oracle.quote(world, rid, lines(world), plan=plan)
    discounted = oracle.quote(world, rid, lines(world), plan=plan, coupon_plan=cp, coupon_code='SAVE')
    assert plain['delivery_choices'] == discounted['delivery_choices']
    assert discounted['options'][0]['discount_minor'] > 0
    legacy = native.quote(world, rid, lines(world), plan=plan, coupon_plan=cp, coupon_code='SAVE')
    expected = {o['option_id']: o for o in legacy['options']}
    assert all(expected[o['option_id']] == o for o in discounted['options'])
