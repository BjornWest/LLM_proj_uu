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


# Plan version 2: draws keyed on the seed, the retailer and its real route universe, not the finished world.
V1_ROWS_SEEDS_0_TO_11 = '693514e681a7f05716b80d78cca4ac8fbfd91cd65924ad67d977a1cdfbf3fe0b'
V2 = admission.STRUCTURAL_PLAN_VERSION


def rebound(w):
    """A world after an edit of a leaf: a new identity, as generation gives every changed world."""
    w['world_id'] = 'fixture/' + native.model.digest({k: v for k, v in w.items() if k != 'world_id'})
    return w


def leaf_edits(w):
    """Each a change that leaves the retailer's routes and home-anchor capability as they were."""
    retailer = w['retailers'][0]
    def price(): retailer['offers'][0]['price_minor'] += 700
    def stock():
        for offer in retailer['offers']:
            offer['stock_by_source'] = {source: 0 for source in offer['stock_by_source']}
    def wait(): retailer['offers'][1]['supplier_order'] = {'enabled': True, 'wait_days': 9, 'disclosure': 'shown'}
    def fee():
        retailer['contracts'][0]['collection_fee_minor'] += 1000; retailer['contracts'][0]['home_delta_minor'] += 1000
    def threshold(): retailer['free_shipping_threshold_minor'] = 50000
    def dispatch():
        for source in retailer['source_locations']: source['dispatch_days'] = 2
    return {'price': price, 'stock': stock, 'supplier_wait': wait, 'fee': fee, 'threshold': threshold, 'dispatch': dispatch}


def test_v1_rows_and_formula_are_unchanged(commerce):
    w, _, plan, rid = commerce
    plans = [admission.make_plan(w, plan, seed=seed) for seed in range(12)]
    assert native.model.digest([p['retailers'] for p in plans]) == V1_ROWS_SEEDS_0_TO_11
    assert all(p['schema_version'] == admission.PLAN_VERSION == 'retailer-delivery-admission-plan-v1' for p in plans)
    # The formula written out: every draw is a digest of the seed, the finished world's id, the retailer, a stage and a key.
    rank = lambda seed, stage, key: native.model.digest(
        {'seed': seed, 'world_id': w['world_id'], 'retailer_id': rid, 'stage': stage, 'key': key})
    homes = {r['route_key'] for r in admission.enumerate_routes(w, plan, rid) if r['destination_type'] == 'home'}
    for seed, p in enumerate(plans):
        row = p['retailers'][0]
        anchor = min(homes, key=lambda key: rank(seed, 'home', key))
        ordered = [anchor] + sorted((key for key in row['initial_route_keys'] if key != anchor),
                                    key=lambda key: rank(seed, 'membership', key))
        assert row['home_anchor_key'] == anchor and row['admitted_route_keys'] == sorted(ordered[:row['sampled_count']])
        assert admission.make_plan(w, plan, seed=seed, plan_version=admission.PLAN_VERSION) == p


@pytest.mark.parametrize('edit', ['price', 'stock', 'supplier_wait', 'fee', 'threshold', 'dispatch', 'all'])
def test_v2_menus_do_not_move_with_leaves_and_v1_menus_do(commerce, edit):
    w, backend, plan, rid = commerce
    before = {version: [admission.make_plan(w, plan, seed=seed, plan_version=version) for seed in range(12)]
              for version in admission.PLAN_VERSIONS}
    changed = deepcopy(w)
    for name, change in leaf_edits(changed).items():
        if edit in (name, 'all'):
            change()
    rebound(changed)
    assert changed['world_id'] != w['world_id']
    new_plan = backend.make_plan(changed)
    after = {version: [admission.make_plan(changed, new_plan, seed=seed, plan_version=version) for seed in range(12)]
             for version in admission.PLAN_VERSIONS}
    rows = lambda plans: [p['retailers'] for p in plans]
    assert rows(after[V2]) == rows(before[V2])
    assert rows(after[admission.PLAN_VERSION]) != rows(before[admission.PLAN_VERSION])
    for old, new in zip(before[V2], after[V2]):
        # The plan itself is new and bound to the changed world; the old one is stale for it.
        assert admission.validate_plan(changed, new_plan, new)['valid']
        assert (new['world_id'], new['world_sha256']) != (old['world_id'], old['world_sha256'])
        with pytest.raises(ValueError, match='Stale delivery'):
            admission.validate_plan(changed, new_plan, old)
        with pytest.raises(ValueError, match='Stale delivery'):
            admission.Oracle(changed, new_plan, old)
    menu = lambda world, base, sidecar: [admission.route_key(c) for c in admission.quote(
        world, rid, lines(world), plan=base, admission_plan=sidecar)['delivery_choices']]
    if edit not in ('stock', 'all'):
        assert menu(changed, new_plan, after[V2][5]) == menu(w, plan, before[V2][5])


def test_v2_count_pmf_replay_override_and_roundtrip(commerce):
    w, _, plan, rid = commerce
    bound = len(admission.enumerate_routes(w, plan, rid))
    make = lambda seed, **kw: admission.make_plan(w, plan, seed=seed, plan_version=V2, **kw)
    draws = [make(seed, count_weights={1: 1, 2: 1, bound + 1: 100}) for seed in range(30)]
    assert {p['retailers'][0]['sampled_count'] for p in draws} == {1, 2}
    assert draws[7] == make(7, count_weights={1: 1, 2: 1, bound + 1: 100})
    counts = [make(seed)['retailers'][0]['sampled_count'] for seed in range(300)]
    assert len(set(counts)) > 5 and max(counts) <= bound
    homes = {make(seed)['retailers'][0]['home_anchor_key'] for seed in range(60)}
    assert len(homes) > 1
    for p in (make(7), make(7, retailer_counts={rid: 1}), make(7, count_weights={bound + 1: 1}, retailer_counts={rid: bound})):
        assert p['schema_version'] == V2
        row = p['retailers'][0]
        assert set(row['admitted_route_keys']) <= set(row['initial_route_keys']) and row['home_anchor_key'] in row['admitted_route_keys']
        assert len(row['admitted_route_keys']) == row['sampled_count']
        assert admission.validate_plan(w, plan, json.loads(json.dumps(p)))['valid']
    with pytest.raises(ValueError, match='mass within'):
        make(7, count_weights={bound + 1: 1})


def test_v2_structural_change_draws_afresh_and_stays_real(world):
    rid = world['retailers'][0]['retailer_id']; plan = native.make_plan(world)
    before = [admission.make_plan(world, plan, seed=seed, plan_version=V2)['retailers'][0] for seed in range(20)]
    changes = {}
    tiers = deepcopy(world); tiers['retailers'][0]['contracts'][0]['tiers'] = ['standard']; changes['a tier dropped'] = tiers
    point = deepcopy(world); carrier = point['address_context']['carriers'][0]
    carrier['collection_point_ids'] = carrier['collection_point_ids'][1:]; changes['a collection point dropped'] = point
    branch = deepcopy(world); branch['retailers'][0]['geography']['branches'][0]['pickup_enabled'] = False
    changes['a pickup branch closed'] = branch
    for name, changed in changes.items():
        rebound(changed); new_plan = native.make_plan(changed)
        universe = {r['route_key'] for r in admission.enumerate_routes(changed, new_plan, rid)}
        assert universe < set(before[0]['initial_route_keys']), name
        after = [admission.make_plan(changed, new_plan, seed=seed, plan_version=V2) for seed in range(20)]
        for p in after:
            row = p['retailers'][0]
            assert set(row['admitted_route_keys']) <= universe == set(row['initial_route_keys']), name
            assert row['home_anchor_key'] in row['admitted_route_keys'] and len(row['admitted_route_keys']) == row['sampled_count']
            assert admission.validate_plan(changed, new_plan, p)['valid']
        # Not the old draws restricted to the routes that remain: the count draw itself is new.
        assert [p['retailers'][0]['sampled_count'] for p in after] != [
            min(row['sampled_count'], len(universe)) for row in before], name
    # A change of home-anchor capability alone, with the routes as they were, is structural too; this fixture's one
    # carrier cannot lose it and stay a valid basket plan, so the draw's identity is read directly.
    keys = before[0]['initial_route_keys']
    homes = [r['route_key'] for r in admission.enumerate_routes(world, plan, rid) if r['destination_type'] == 'home']
    draw = lambda *identity: [admission._ranker(V2, *identity)(stage, key) for stage, key in
                              (('count', None), ('home', keys[0]), ('membership', keys[0]), ('membership', keys[1]))]
    same = draw(3, 'one-world', rid, keys, homes)
    assert len(set(same)) == 4 and len(homes) > 1
    assert same == draw(3, 'another-world', rid, list(reversed(keys)), list(reversed(homes)))
    for other in ((4, 'one-world', rid, keys, homes), (3, 'one-world', 'other-retailer', keys, homes),
                  (3, 'one-world', rid, keys[1:], homes), (3, 'one-world', rid, keys, homes[1:]),
                  (3, 'one-world', rid, keys, [])):
        assert not set(same) & set(draw(*other))
    # Version 1 reads the world's id and nothing of the routes.
    v1 = lambda *identity: admission._ranker(admission.PLAN_VERSION, *identity)('membership', keys[0])
    assert v1(3, 'one-world', rid, keys, homes) == v1(3, 'one-world', rid, keys[1:], []) != v1(3, 'another-world', rid, keys, homes)


def test_v2_one_retailers_menu_does_not_depend_on_other_retailers(world):
    rid = world['retailers'][0]['retailer_id']
    alone = [admission.make_plan(world, native.make_plan(world), seed=seed, plan_version=V2)['retailers'][0] for seed in range(12)]
    extra = deepcopy(world['retailers'][0]); extra['retailer_id'] = 'second-retailer'
    extra['contracts'][0]['tiers'] = ['standard']
    world['retailers'].append(extra); rebound(world)
    plan = native.make_plan(world)
    both = [admission.make_plan(world, plan, seed=seed, plan_version=V2) for seed in range(12)]
    assert [next(r for r in p['retailers'] if r['retailer_id'] == rid) for p in both] == alone
    assert any(len({json.dumps({k: v for k, v in r.items() if k != 'retailer_id'}, sort_keys=True) for r in p['retailers']}) == 2
               for p in both)
    world['retailers'].reverse()
    assert admission.make_plan(world, native.make_plan(world), seed=3, plan_version=V2)['retailers'] == both[3]['retailers']


def test_plan_versions_are_explicit_and_not_interchangeable(commerce):
    w, _, plan, rid = commerce
    for bad in ('retailer-delivery-admission-plan-v3', None, 2, ['retailer-delivery-admission-plan-v2'], ''):
        with pytest.raises(ValueError, match='plan version'):
            admission.make_plan(w, plan, seed=1, plan_version=bad)
    swapped = 0
    for seed in range(12):
        plans = {version: admission.make_plan(w, plan, seed=seed, plan_version=version) for version in admission.PLAN_VERSIONS}
        for version, other in zip(admission.PLAN_VERSIONS, reversed(admission.PLAN_VERSIONS)):
            forged = {**deepcopy(plans[version]), 'schema_version': other}
            if plans[version]['retailers'] != plans[other]['retailers']:
                swapped += 1
                with pytest.raises(ValueError, match='Invalid admitted'):
                    admission.validate_plan(w, plan, forged)
        for bad in ('retailer-delivery-admission-plan-v3', None, ['retailer-delivery-admission-plan-v1']):
            with pytest.raises(ValueError, match='Stale delivery'):
                admission.validate_plan(w, plan, {**deepcopy(plans[V2]), 'schema_version': bad})
    assert swapped >= 12


def test_oracle_reports_the_plans_version_and_quotes_alike(commerce):
    w, backend, plan, rid = commerce
    bound = len(admission.enumerate_routes(w, plan, rid))
    for version in admission.PLAN_VERSIONS:
        sidecar = admission.make_plan(w, plan, seed=7, plan_version=version, retailer_counts={rid: bound})
        oracle = admission.Oracle(w, plan, sidecar)
        policy = oracle.public_policy(plan, rid)['delivery_admission']
        assert policy['schema_version'] == version and policy['plan_sha256'] == native.model.digest(sidecar)
        full = oracle.quote(w, rid, lines(w), plan=plan)
        assert full['schema_version'] == admission.VERSION and full['admission_plan_sha256'] == native.model.digest(sidecar)
        old = backend.quote(w, rid, lines(w), plan=plan)
        for key in ('lines', 'delivery_choices', 'options', 'group_delivery_offers', 'line_availability'):
            assert full[key] == old[key]
        one = admission.make_plan(w, plan, seed=7, plan_version=version, retailer_counts={rid: 1})
        shown = admission.quote(w, rid, lines(w), plan=plan, admission_plan=one)['delivery_choices']
        assert [admission.route_key(c) for c in shown] == one['retailers'][0]['admitted_route_keys']
