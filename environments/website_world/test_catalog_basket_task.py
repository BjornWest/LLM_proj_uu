"""Authored finite mixed-family fixtures; no genuine world or policy sampling."""
from copy import deepcopy

import pytest

from experiments.accepted_catalog_commerce import basket_quote
from experiments.accepted_catalog_commerce.test_basket_quote import bridged
from experiments.footwear_world_pilot.test_basket_quote import world
from environments.website_world import catalog_basket_task as task, catalog_basket_grading as grading, catalog_checkout_domain


def fixture(world, *, overlap=False, extras=True, budget=None):
    w = bridged(world)
    w['seed'] = 0
    w['config'] = {'concept_ids': ['footwear.walking_shoes', 'tops.t_shirts']}
    for p in w['products'][:2]:
        p['public']['concept_id'] = 'footwear.walking_shoes'
        p['variant_fields'] = {k: {} for k in ('colour', 'width', 'size_eu')}
    shirt = w['products'][2]
    shirt['public']['concept_id'] = 'tops.t_shirts'
    shirt['public']['facts']['market_range'] = 'women'
    shirt['catalog_status'] = {'product.facts.market_range': 'known'}
    shirt['variant_fields'] = {'size_label': {}}
    shirt['sku_status'] = {}
    for s in shirt['public']['skus']:
        s['size_label'] = 'M'
        shirt['sku_status'][s['sku_id']] = {'sku.size_label': 'known'}
    for r in w['retailers']:
        r['catalog'] = [{'pages': [{'listings': [{'sku_id': o['sku_id']} for o in r['offers']]}]}]
    reqs = [{'requirement_id': 'shoes', 'quantity': 1, 'concept_id': 'footwear.walking_shoes', 'predicates': []},
            {'requirement_id': 'shirt', 'quantity': 1, 'concept_id': 'tops.t_shirts',
             'predicates': [{'field': 'product.facts.market_range', 'operator': 'eq', 'value': 'women'},
                            {'field': 'sku.size_label', 'operator': 'eq', 'value': 'M'}]}]
    if overlap:
        reqs[1] = {**deepcopy(reqs[0]), 'requirement_id': 'second-shoes'}
    spec = {'kind': task.KIND, 'requirements': reqs,
            'domain': {'destination': 'user_home', 'allowed_destination_types': ['home'], 'allow_extras': extras}}
    domain = catalog_checkout_domain.make(w, {'max_quantity_per_offer': 2, 'max_lines_per_order': 3})
    inventory = task.Inventory()
    t = task.make(w, spec, checkout_domain=domain, inventory=inventory)
    p = basket_quote.make_plan(w)
    ref = task.reference(w, t, plan=p, checkout_domain=domain, inventory=inventory,
                         budget=budget or {'max_work': 50000, 'max_seconds': 10})
    bindings = {'retailer_offers': {o['offer_id']: {'retailer_id': r['retailer_id'],
        'product_id': o['product_id'], 'sku_id': o['sku_id'],
        'url': 'https://shop.test/#/products/' + o['offer_id'], 'selection': {},
        'required_selection': {}, 'url_behavior': 'none'} for r in w['retailers'] for o in r['offers']}}
    return w, t, p, domain, ref, bindings


def answer(ref, bindings):
    solution = ref['result']['solutions'][0]
    orders = []
    for order in solution['orders']:
        orders.append({'retailer_id': order['retailer_id'],
            'lines': [{'offer_id': l['offer_id'], 'quantity': l['quantity'],
                       'url': bindings['retailer_offers'][l['offer_id']]['url']} for l in order['lines']],
            'selections': order['quote']['selection'], 'split': order['quote']['split']})
    return {'schema_version': grading.VERSION, 'status': 'plan', 'orders': orders,
            'total_minor': solution['total_minor']}


def test_mixed_family_matching_and_requoted_complete_plan(world):
    w, t, p, d, r, b = fixture(world)
    assert r['result']['complete'] and r['result']['status'] == 'optimal'
    assert len(r['matching']['requirements'][0]['offer_ids']) == 2
    assert len(r['matching']['requirements'][1]['offer_ids']) == 1
    result = grading.grade(w, t, answer(r, b), reference=r, plan=p, domain=d, url_bindings=b)
    assert result['verdict'] == 'pass'
    assert 'Arrival speed does not affect ranking' in t['user_message']
    assert 'Extra unrequested products' in t['user_message']


def test_missing_runtime_links_and_incomplete_search_are_inconclusive(world):
    w, t, p, d, r, b = fixture(world)
    assert grading.grade(w, t, answer(r, b), reference=r, plan=p, domain=d)['verdict'] == 'inconclusive'
    w, t, p, d, r, b = fixture(world, budget={'max_work': 1, 'max_seconds': 10})
    assert not r['result']['complete']
    result = grading.grade(w, t, {'schema_version': grading.VERSION, 'status': 'no_match'},
                           reference=r, plan=p, domain=d, url_bindings=b)
    assert result['verdict'] == 'inconclusive'


def test_unknown_negative_predicate_cannot_establish_a_match(world):
    w, t, _, d, _, _ = fixture(world)
    shirt = w['products'][2]
    shirt['catalog_status']['product.facts.market_range'] = 'unknown'
    spec = task._selection(t)
    spec['requirements'][1]['predicates'][0].update(operator='ne', value='men')
    bound = task.make(w, spec, checkout_domain=catalog_checkout_domain.make(w, d['options']))
    matches = task.match(w, bound, checkout_domain=catalog_checkout_domain.make(w, d['options']))
    assert matches['requirements'][1]['offer_ids'] == []


def test_zero_stock_kept_in_matching_but_not_fulfillable(world):
    w, t, _, d, _, _ = fixture(world)
    offer = w['retailers'][0]['offers'][2]
    offer['stock_by_source'] = {s: 0 for s in offer['stock_by_source']}
    d = catalog_checkout_domain.make(w, d['options'])
    t = task.make(w, task._selection(t), checkout_domain=d)
    p = basket_quote.make_plan(w)
    r = task.reference(w, t, plan=p, checkout_domain=d)
    assert r['matching']['requirements'][1]['offer_ids'] == [offer['offer_id']]
    assert r['result']['complete'] and r['result']['status'] == 'infeasible'
    assert grading.grade(w, t, {'schema_version': grading.VERSION, 'status': 'no_match'},
                         reference=r, plan=p, domain=d)['verdict'] == 'pass'


def test_overlapping_requirements_use_distinct_purchased_units(world):
    w, t, p, d, r, b = fixture(world, overlap=True)
    response = answer(r, b)
    assert sum(l['quantity'] for o in response['orders'] for l in o['lines']) >= 2
    assert grading.grade(w, t, response, reference=r, plan=p, domain=d, url_bindings=b)['verdict'] == 'pass'
    broken = deepcopy(response)
    broken['orders'][0]['lines'] = broken['orders'][0]['lines'][:1]
    broken['orders'][0]['lines'][0]['quantity'] = 1
    oid = broken['orders'][0]['lines'][0]['offer_id']
    q = basket_quote.quote(w, broken['orders'][0]['retailer_id'],
                          [{'line_id': oid, 'offer_id': oid, 'quantity': 1}], plan=p)
    broken['orders'][0]['selections'] = q['options'][0]['selection']
    broken['total_minor'] = q['options'][0]['total_minor']
    assert grading.grade(w, t, broken, reference=r, plan=p, domain=d, url_bindings=b)['verdict'] == 'fail'


def test_wrong_total_foreign_link_and_stale_checkout_domain_reject(world):
    w, t, p, d, r, b = fixture(world)
    response = answer(r, b)
    response['total_minor'] += 1
    assert grading.grade(w, t, response, reference=r, plan=p, domain=d, url_bindings=b)['verdict'] == 'fail'
    response = answer(r, b)
    response['orders'][0]['lines'][0]['url'] = 'https://foreign.test/'
    assert grading.grade(w, t, response, reference=r, plan=p, domain=d, url_bindings=b)['verdict'] == 'fail'
    changed = deepcopy(d)
    changed['options']['max_quantity_per_offer'] += 1
    assert grading.grade(w, t, answer(r, b), reference=r, plan=p, domain=changed, url_bindings=b)['verdict'] == 'inconclusive'


@pytest.mark.parametrize('change', [lambda s: s['requirements'][0].update(quantity=True),
                                    lambda s: s['requirements'][1].update(requirement_id='shoes'),
                                    lambda s: s['domain'].update(deadline='yesterday')])
def test_bad_requirement_inputs_reject(world, change):
    w, t, _, d, _, _ = fixture(world)
    spec = task._selection(t)
    change(spec)
    with pytest.raises(ValueError):
        task.make(w, spec, checkout_domain=d)
