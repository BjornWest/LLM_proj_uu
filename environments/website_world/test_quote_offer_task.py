"""Finite ranking/identity controls; scripted quotes isolate the task contract.

Actual prepared-quote parity is checked separately on a saved/generated world.
No duplicate shipping arithmetic is introduced into production.
"""
from copy import deepcopy

import pytest

from experiments.accepted_catalog_commerce import basket_quote
from environments.website_world import feature_offer_task, quote_offer_task as api
from environments.website_world.quote_offer_grading import QuoteOfferGrader
from environments.website_world.test_listed_offer_grading import fixture as base_fixture, answer


class Quotes:
    def __init__(self, world, *, unknown=False, admitted=None, supplier=False):
        self.binding = {'world_id': world['world_id'], 'world_sha256': basket_quote.model.digest(world),
            'source_sha256': {}, 'quote_plan_sha256': 'explicit-scripted-fixture',
            'admission_plan_sha256': admitted}
        self.world, self.unknown, self.calls = deepcopy(world), unknown, []
        self.supplier = supplier

    def quote(self, rid, lines, *, destination, split):
        assert len(lines) == 1 and lines[0]['line_id'] == lines[0]['offer_id']
        assert lines[0]['quantity'] == 1 and split is False
        oid = lines[0]['offer_id']; self.calls.append(oid)
        offer = next(o for r in self.world['retailers'] if r['retailer_id'] == rid for o in r['offers'] if o['offer_id'] == oid)
        options = []
        for tier in ('standard', 'express'):
            if self.binding['admission_plan_sha256'] and tier == 'standard':
                continue
            for point in (None, 'locker1', 'locker2'):
                cid = tier+'/'+str(point)
                fee = (0 if rid == 'b' or point else 10000) + (1000 if tier == 'express' else 0)
                day = ('2026-10-08' if rid == 'b' else '2026-10-05') if tier == 'standard' else ('2026-10-04' if rid == 'b' else '2026-10-03')
                unknown = self.unknown and rid == 'b' and tier == 'standard'
                options.append({'option_id': 'basket/'+oid+'/'+cid, 'selection': {oid: cid},
                    'total_minor': offer['price_minor']+fee, 'shipping_minor': fee,
                    'subtotal_minor': offer['price_minor'], 'currency': 'SEK',
                    'arrival': {'status': 'unknown' if unknown else 'estimated',
                        'earliest_date': None if unknown else day, 'latest_date': None if unknown else day},
                    'shipments': [{'items': [{'supply': 'supplier_order' if self.supplier else 'on_hand'}],
                        'delivery': {'carrier_id': 'courier', 'tier': tier,
                        'destination_type': 'home' if point is None else 'parcel_locker', 'point_id': point}}]})
        return {'quote_id': 'quote/'+oid, 'status': 'available', 'options': options}


def fixture(*, unknown=False, admitted=None, supplier=False, **options):
    world, _, _, links = base_fixture()
    world['products'][0]['public']['facts'] = {}
    world['products'][0]['catalog_status'] = {}; world['products'][0]['sku_status'] = {}
    world['quote_as_of'] = '2026-09-30'; world['user_location'] = {'location_id': 'user-home'}
    world['address_context'] = {'carriers': [{'carrier_id': 'courier', 'name': 'Courier'}],
        'collection_points': [{'point_id': 'locker1', 'name': 'North Locker'}, {'point_id': 'locker2', 'name': 'South Locker'}],
        'addresses': [{'address_id': 'user-home', 'location': deepcopy(world['user_location']),
            'address': {'recipient': 'Alex', 'street': 'Street',
            'house_number': '12', 'unit': '', 'postcode': '12345', 'city': 'Uppsala'}}]}
    inventory = feature_offer_task.FieldInventory('footwear.walking_shoes')
    context = Quotes(world, unknown=unknown, admitted=admitted, supplier=supplier)
    spec = {'kind': api.KIND, 'concept_id': inventory.concept_id,
        'predicates': [{'field': 'sku.size_eu', 'operator': 'eq', 'value': 42}], **options}
    task = api.make(world, spec, inventory=inventory, quote_context=context)
    ref = api.reference(world, task, inventory=inventory, quote_context=context)
    grader = QuoteOfferGrader(world, task, ref, links, inventory=inventory, quote_context=context)
    return world, task, ref, context, inventory, grader


def claims_for(row, *, missing_point=False):
    rid = row['retailer_id']; colour = row['sku_id'].split('-')[1]
    name = {'a': 'Veska', 'b': 'Virela', 'd': 'Tied Shop'}[rid]
    total = row['option']['total_minor']; delivery = row['delivery']
    point = row['point_name']
    text, claims = answer(name=name, colour=colour, price=f'{total//100}.{total%100:02d}',
                         url=f'https://{rid}.test/#/product/{colour}')
    text += f' Courier {delivery["tier"]}, '+('home delivery' if point is None else 'pickup locker')
    if point is not None and not missing_point: text += ', '+point
    latest = row['option']['arrival']['latest_date']
    if latest: text += ', latest estimated arrival '+latest
    # Earlier evidence quotes remain actual contiguous substrings of this text.
    c = lambda v: {'value': v, 'evidence': text if v is not None else None}
    claims.update(carrier_name=c('Courier'), tier=c(delivery['tier']),
        delivery_type=c(delivery['destination_type']), point_id=c(None),
        point_name=c(point if not missing_point else None), earliest_arrival_date=c(None),
        latest_arrival_date=c(latest))
    return text, claims


def test_delivered_total_changes_listed_price_winner_and_keeps_ties():
    _, task, ref, _, _, grader = fixture()
    assert ref['optimal_score'] == [80000]
    assert len(ref['winners']) == 2  # colours remain unconstrained
    assert all(row['retailer_id'] == 'b' for row in ref['winners'])
    assert 'Arrival speed is not a preference' in task['user_message']
    for row in ref['winners']:
        assert grader.grade(*reversed(claims_for(row)))['structured_claims_correct']
    inferior = next(r for r in ref['candidates'] if r['retailer_id'] == 'a')
    grade = grader.grade(*reversed(claims_for(inferior)))
    assert grade['oracle_grade']['requirements']['reported_total']
    assert not grade['oracle_grade']['requirements']['optimal_objective']


def test_fastest_uses_latest_estimate_then_total_without_arbitrary_weighting():
    _, _, ref, _, _, grader = fixture(objective='fastest_then_cheapest')
    assert ref['optimal_score'] == ['2026-10-03', 85000]
    assert {r['retailer_id'] for r in ref['winners']} == {'a', 'd'}
    text, c = claims_for(ref['winners'][0])
    assert grader.grade(c, text)['structured_claims_correct']
    c['latest_arrival_date'] = {'value': None, 'evidence': None}
    assert not grader.grade(c, text)['structured_claims_correct']


def test_deadline_inclusive_and_price_cap_include_shipping():
    _, _, ref, _, _, g = fixture(arrival_deadline='2026-10-04', max_total_minor=81000)
    assert ref['optimal_score'] == [81000]
    assert all(r['option']['arrival']['latest_date'] == '2026-10-04' for r in ref['winners'])
    assert g.grade(*reversed(claims_for(ref['winners'][0])))['structured_claims_correct']
    assert fixture(arrival_deadline='2026-10-04', max_total_minor=80999)[2]['status'] == 'no_match'
    assert fixture(arrival_deadline='2026-09-01')[2]['status'] == 'no_match'


def test_unknown_arrival_excluded_only_when_timing_is_required():
    assert fixture(unknown=True)[2]['optimal_score'] == [80000]
    assert fixture(unknown=True, arrival_deadline='2026-10-05')[2]['optimal_score'] == [81000]
    assert fixture(unknown=True, objective='fastest_then_cheapest')[2]['optimal_score'][0] == '2026-10-03'


def test_admitted_menu_is_not_refilled_for_a_cheaper_quote():
    _, task, ref, _, _, _ = fixture(admitted='fixed-express-only')
    assert task['quote_binding']['admission_plan_sha256'] == 'fixed-express-only'
    assert all(r['delivery']['tier'] == 'express' for r in ref['all_options'])
    assert ref['optimal_score'] == [81000]


def test_stock_elsewhere_does_not_qualify_supplier_delivery_as_physical_stock():
    assert fixture(supplier=True)[2]['status'] == 'match'
    assert fixture(supplier=True, availability='positive_stock')[2]['status'] == 'no_match'


def test_missing_point_is_not_repaired_by_price_or_task_filters():
    _, _, ref, _, _, g = fixture(delivery_types=['parcel_locker'])
    row = ref['winners'][0]
    assert g.grade(*reversed(claims_for(row)))['structured_claims_correct']
    grade = g.grade(*reversed(claims_for(row, missing_point=True)))
    assert len(grade['identity_resolution']['option_ids']) == 2
    assert not grade['structured_claims_correct']


def test_missing_sku_and_service_are_not_repaired():
    _, _, ref, _, _, g = fixture()
    text, c = claims_for(ref['winners'][0]); c['variant']['size_eu'] = {'value': None, 'evidence': None}
    assert len(g.grade(c, text)['identity_resolution']['offer_ids']) == 2
    assert not g.grade(c, text)['structured_claims_correct']
    text, c = claims_for(ref['winners'][0]); c['tier'] = {'value': None, 'evidence': None}
    assert not g.grade(c, text)['structured_claims_correct']


def test_wrong_but_publicly_identified_service_is_not_repaired_from_cheapest():
    _, _, ref, _, _, g = fixture()
    row = next(r for r in ref['all_options'] if r['retailer_id'] == 'b' and r['delivery']['tier'] == 'express' and r['delivery']['destination_type'] == 'home')
    grade = g.grade(*reversed(claims_for(row)))
    assert grade['oracle_grade']['requirements']['public_service_identity']
    assert not grade['oracle_grade']['requirements']['optimal_objective']


def test_no_match_requires_no_contradictory_selection():
    _, _, _, _, _, g = fixture(max_total_minor=1)
    c = {'interpretation': 'extracted', 'status': {'value': 'no_match', 'evidence': 'No qualifying option.'}}
    assert g.grade(c, 'No qualifying option.')['structured_claims_correct']
    c['tier'] = {'value': 'standard', 'evidence': 'standard'}
    assert not g.grade(c, 'No qualifying option. standard')['structured_claims_correct']


@pytest.mark.parametrize('extra', [dict(objective='weighted_utility'), dict(destination='old_home'),
    dict(delivery_types=['retailer_branch']), dict(delivery_types=[]), dict(delivery_types=['home', 'home']),
    dict(max_total_minor=True), dict(max_total_minor=-1), dict(max_price_minor=100),
    dict(arrival_deadline='20261005'), dict(arrival_deadline='2026-13-01')])
def test_malformed_or_out_of_scope_requirements_reject(extra):
    with pytest.raises(ValueError): fixture(**extra)


@pytest.mark.parametrize('changed', ['world', 'task', 'reference', 'quote_plan'])
def test_native_binding_tampering_rejects(changed):
    w, t, r, q, i, g = fixture()
    if changed == 'world': w['retailers'][0]['offers'][0]['price_minor'] += 1
    elif changed == 'task': t['objective'] = 'fastest_then_cheapest'
    elif changed == 'reference': r['optimal_score'] = [0]
    else: q.binding['quote_plan_sha256'] = 'foreign'
    with pytest.raises(ValueError):
        QuoteOfferGrader(w, t, r, {'retailer_offers': g.identity.links}, inventory=i, quote_context=q)


def test_address_and_requirements_do_not_select_cheapest_or_autofill():
    w, t, _, q, i, _ = fixture()
    for r in w['retailers']:
        r['initial_form'] = {'address': {'street': 'Wrong Street'}}
        for offer in r['offers']: offer['price_minor'] += 1000
    spec = {k: t[k] for k in ('kind', 'concept_id', 'predicates', 'objective', 'destination', 'delivery_types')}
    updated = api.make(w, spec, inventory=i, quote_context=Quotes(w))
    for key in ('user_message', 'predicates', 'destination_address', 'objective'):
        assert updated[key] == t[key]
    assert 'Wrong Street' not in updated['user_message']
    assert 'building_key' not in updated['destination_address']
