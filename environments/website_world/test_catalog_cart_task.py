"""Finite authored cart captures, not live browser or model evidence."""
from copy import deepcopy
import json

import pytest

from experiments.accepted_catalog_commerce.test_basket_quote import bridged
from experiments.footwear_world_pilot.test_basket_quote import world
from environments.website_world import catalog_cart_task as task, catalog_cart_grading as grading, catalog_checkout_domain
from environments.website_world.adapter import digest


def fixture(world, *, quantities=(1, 1), initial_cart='preserve', domain_options=None):
    w = bridged(world)
    w['config'] = {'concept_ids': ['footwear.walking_shoes']}
    for item in w['products']:
        item['public']['concept_id'] = 'footwear.walking_shoes'
        item['variant_fields'] = {k: {} for k in ('colour', 'width', 'size_eu')}
    # Historical basket fixture has no retail catalogue. Add an explicit
    # authored catalogue containing exactly its retained offers.
    for retailer in w['retailers']:
        retailer['catalog'] = [{'pages': [{'listings': [
            {'sku_id': offer['sku_id']} for offer in retailer['offers']]}]}]
    requirements = [{'requirement_id': f'item-{i}', 'quantity': q,
                     'concept_id': 'footwear.walking_shoes', 'predicates': []}
                    for i, q in enumerate(quantities)]
    d = catalog_checkout_domain.make(w, domain_options)
    t = task.make(w, {'kind': task.KIND, 'requirements': requirements, 'initial_cart': initial_cart},
                  checkout_domain=d)
    ref = task.reference(w, t, checkout_domain=d)
    rid = w['retailers'][0]['retailer_id']
    b = grading.storage_binding(w, {rid: {'origin': 'https://shop.test',
        'storage_key': 'website-drafts.state.' + rid,
        'offer_keys': {o['sku_id']: o['offer_id'] for o in w['retailers'][0]['offers']}}})
    return w, t, d, ref, b


def state(w, amounts):
    offers = {o['offer_id']: o for r in w['retailers'] for o in r['offers']}
    return {'version': 2, 'cart': [{'id': str(i), 'key': offers[oid]['sku_id'], 'quantity': q}
        for i, (oid, q) in enumerate(amounts.items())], 'orders': [],
        'address': {'city': 'Uppsala'}, 'remembered': {'city': 'Uppsala'},
        'instructions': 'Ring twice', 'coupon': '', 'selection': {}}


def capsule(w, t, b, before, after, journal=None):
    row = next(iter(b['retailers'].values()))
    def snapshot(value):
        return {'cookies': [], 'origins': [{'origin': row['origin'], 'localStorage': [
            {'name': row['storage_key'], 'value': json.dumps(value)}]}]}
    return {'schema_version': grading.CAPSULE_VERSION, 'task_sha256': digest(t),
        'binding_sha256': digest(b), 'episode_id': 'authored-episode', 'main_trace_sha256': 'a' * 64,
        'before': {'phase': 'before_policy', 'storage_state': snapshot(before)},
        'after': {'phase': 'after_policy_before_context_close', 'storage_state': snapshot(after)},
        'effect_journal': journal if journal is not None else {
            'authority': 'complete_generated_world_event_journal', 'complete': True, 'events': []}}


def run(values, c, *, completed=True):
    w, t, d, r, b = values
    return grading.grade(w, t, r, checkout_domain=d, binding=b, capsule=c,
        episode_id='authored-episode', main_trace_sha256='a' * 64, policy_completed=completed)


def test_final_matching_units_without_price_objective(world):
    values = fixture(world)
    w, t, d, r, b = values
    oid = w['retailers'][0]['offers'][-1]['offer_id']
    c = capsule(w, t, b, state(w, {}), state(w, {oid: 2}))
    assert run(values, c)['verdict'] == 'pass'
    assert r['empty_initial_cart']['status'] == 'feasible'
    assert 'neither price nor delivery speed ranks' in t['user_message']
    assert r['matching']['requirements'][0]['offer_ids'] == r['matching']['requirements'][1]['offer_ids']


def test_one_unit_cannot_cover_two_requests_and_extra_unit_fails(world):
    values = fixture(world)
    w, t, d, r, b = values
    oid = w['retailers'][0]['offers'][0]['offer_id']
    for quantity in (1, 3):
        assert run(values, capsule(w, t, b, state(w, {}), state(w, {oid: quantity})))['verdict'] == 'fail'


def test_preserve_requires_additions_on_top_of_initial_units(world):
    values = fixture(world)
    w, t, d, r, b = values
    first, second = [o['offer_id'] for o in w['retailers'][0]['offers'][:2]]
    before = state(w, {first: 1})
    assert run(values, capsule(w, t, b, before, state(w, {first: 1, second: 2})))['verdict'] == 'pass'
    assert run(values, capsule(w, t, b, before, state(w, {first: 1, second: 1})))['verdict'] == 'fail'
    assert run(values, capsule(w, t, b, before, state(w, {second: 2})))['verdict'] == 'fail'


def test_replace_permission_is_explicit_and_final_units_are_exact(world):
    values = fixture(world, initial_cart='replace')
    w, t, d, r, b = values
    first, second = [o['offer_id'] for o in w['retailers'][0]['offers'][:2]]
    assert 'replace all existing basket contents' in t['user_message']
    assert run(values, capsule(w, t, b, state(w, {first: 5}), state(w, {second: 2})))['verdict'] == 'pass'


@pytest.mark.parametrize('field', grading.PROTECTED)
def test_protected_persistent_fields_cannot_change(world, field):
    values = fixture(world)
    w, t, d, r, b = values
    oid = w['retailers'][0]['offers'][0]['offer_id']
    after = state(w, {oid: 2})
    after[field] = ['changed'] if field == 'orders' else 'changed'
    assert run(values, capsule(w, t, b, state(w, {}), after))['verdict'] == 'fail'


def test_terminal_orders_equal_does_not_certify_whole_run_effects(world):
    values = fixture(world)
    w, t, d, r, b = values
    oid = w['retailers'][0]['offers'][0]['offer_id']
    c = capsule(w, t, b, state(w, {}), state(w, {oid: 2}), journal={})
    assert run(values, c)['cart_outcome_correct'] is True
    assert run(values, c)['verdict'] == 'inconclusive'
    c['effect_journal'] = {'authority': 'complete_generated_world_event_journal', 'complete': True,
                           'events': [{'kind': 'purchase'}, {'kind': 'cancel'}]}
    assert run(values, c)['verdict'] == 'fail'
    c['effect_journal']['events'] = []
    assert run(values, c, completed=False)['verdict'] == 'inconclusive'


def test_missing_origin_or_capture_phase_is_unknown_not_empty(world):
    values = fixture(world)
    w, t, d, r, b = values
    c = capsule(w, t, b, state(w, {}), state(w, {}))
    c['before']['storage_state']['origins'] = []
    assert run(values, c)['verdict'] == 'inconclusive'
    c['before']['phase'] = 'after_policy'
    assert run(values, c)['verdict'] == 'inconclusive'


@pytest.mark.parametrize('quantity', [True, 0, -1, 1.5, '2'])
def test_malformed_cart_quantities_fail(world, quantity):
    values = fixture(world)
    w, t, d, r, b = values
    oid = w['retailers'][0]['offers'][0]['offer_id']
    assert run(values, capsule(w, t, b, state(w, {}), state(w, {oid: quantity})))['verdict'] == 'fail'


def test_foreign_and_duplicate_json_state_reject(world):
    values = fixture(world)
    w, t, d, r, b = values
    after = state(w, {})
    after['cart'] = [{'id': 'x', 'key': 'foreign', 'quantity': 2}]
    assert run(values, capsule(w, t, b, state(w, {}), after))['verdict'] == 'fail'
    c = capsule(w, t, b, state(w, {}), state(w, {}))
    raw = c['after']['storage_state']['origins'][0]['localStorage'][0]
    raw['value'] = '{"version":2,"version":2}'
    assert run(values, c)['verdict'] == 'fail'


def test_supplier_only_and_local_only_stock_cannot_fill_cart(world):
    values = fixture(world)
    w, t, d, r, b = values
    for retailer in w['retailers']:
        for source in retailer['source_locations']:
            source['shipping_enabled'] = False
        for offer in retailer['offers']:
            offer['supplier_order'] = {'enabled': True, 'wait_days': 14, 'disclosure': 'product_page'}
    d = catalog_checkout_domain.make(w)
    t = task.make(w, task.selection(t), checkout_domain=d)
    r = task.reference(w, t, checkout_domain=d)
    b = grading.storage_binding(w, b['retailers'])
    values = w, t, d, r, b
    assert r['empty_initial_cart']['status'] == 'no_match'
    assert run(values, capsule(w, t, b, state(w, {}), state(w, {})))['verdict'] == 'pass'
    oid = w['retailers'][0]['offers'][0]['offer_id']
    assert run(values, capsule(w, t, b, state(w, {}), state(w, {oid: 2})))['verdict'] == 'fail'


def test_full_initial_quantity_limit_can_make_addition_infeasible(world):
    values = fixture(world, domain_options={'max_quantity_per_offer': 1})
    w, t, d, r, b = values
    initial = {o['offer_id']: 1 for o in w['retailers'][0]['offers']}
    c = capsule(w, t, b, state(w, initial), state(w, initial))
    assert r['empty_initial_cart']['status'] == 'feasible'
    assert run(values, c)['components']['cart']['feasibility'] == 'no_match'
    assert run(values, c)['verdict'] == 'pass'


def test_line_limit_witness_is_inconclusive_not_a_proof_of_impossibility(world):
    values = fixture(world, quantities=(3,), domain_options={'max_quantity_per_offer': 1, 'max_lines_per_order': 2})
    assert values[3]['empty_initial_cart']['status'] == 'inconclusive_line_limit'


def test_reference_and_capsule_identity_tampering_is_not_success(world):
    values = fixture(world)
    w, t, d, r, b = values
    c = capsule(w, t, b, state(w, {}), state(w, {}))
    c['main_trace_sha256'] = 'b' * 64
    assert run(values, c)['verdict'] == 'inconclusive'
    broken = deepcopy(r)
    broken['empty_initial_cart']['status'] = 'no_match'
    assert run((w, t, d, broken, b), capsule(w, t, b, state(w, {}), state(w, {})))['verdict'] == 'inconclusive'


@pytest.mark.parametrize('change', [lambda s: s.update(initial_cart='append_or_replace'),
    lambda s: s.update(kind='buy'), lambda s: s.update(delivery='express'),
    lambda s: s['requirements'][0].update(quantity=True)])
def test_bad_task_rejects_before_factory(change):
    from environments.website_world import catalog_cart_generation as generation
    spec = {'kind': task.KIND, 'requirements': [{'requirement_id': 'shoes', 'quantity': 1,
        'concept_id': 'footwear.walking_shoes', 'predicates': []}]}
    change(spec)
    request = {'schema': 'website-world-generation-v2', 'seed': 86,
               'world': {'concept_ids': ['footwear.walking_shoes']}, 'task': spec}
    def forbidden(*args, **kwargs):
        raise AssertionError('Factory called for bad task')
    with pytest.raises(ValueError):
        generation.generate(request, world_factory=forbidden)
