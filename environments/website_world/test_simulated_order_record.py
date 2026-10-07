"""Tiny native quote/receipt controls, without Runtime/browser/provider startup."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from experiments.footwear_world_pilot import basket_quote as footwear_quote
from experiments.accepted_catalog_commerce import basket_quote as catalog_quote
from environments.website_world.adapter import PublicAdapter
from environments.website_world.basket import Baskets
from environments.website_world import checkout_domain, catalog_checkout_domain, simulated_order_record as native


@pytest.fixture
def world():
    # Detached authored arithmetic fixture, no sampler/model/world draw.
    return json.loads(Path(__file__).with_name('fixtures').joinpath('simulated_order_quote_world_v1.json').read_text())


@pytest.fixture(params=['footwear', 'catalog'])
def fixture(world, request):
    w = deepcopy(world)
    if request.param == 'catalog':
        w['schema_version'] = 'accepted-catalog-commerce-world-v1'
        for product in w['products']:
            product['commerce'] = {'shipping_class': 'regular',
                'classification_basis': 'closed_ordinary_parcel_concept_slice_v1'}
    oracle = catalog_quote if request.param == 'catalog' else footwear_quote
    domain_provider = catalog_checkout_domain if request.param == 'catalog' else checkout_domain
    w["brands"] = []  # Basket fixture has no rendering/brand population.
    if request.param == 'catalog':
        for retailer in w['retailers']:
            retailer['catalog'] = [{'pages': [{'listings': [
                {'sku_id': o['sku_id']} for o in retailer['offers']]}]}]
    plan = oracle.make_plan(w)
    adapter = PublicAdapter(w, basket_plan=plan, oracle=oracle)
    domain = domain_provider.make(w)
    baskets = Baskets(adapter, plan, domain=domain, oracle=oracle, domain_provider=domain_provider)
    rid = w['retailers'][0]['retailer_id'];offer = w['retailers'][0]['offers'][0]
    quote_request = {'revision': 1, 'world_id': w['world_id'], 'plan_id': baskets.plan_id,
        'domain_id': baskets.domain_id,
        'lines': [{'line_id': 'actual-cart-line', 'offer_id': offer['offer_id'], 'quantity': 1}],
        'address': deepcopy(adapter.initial_address), 'coupon_code': None, 'selections': None, 'split': False}
    preview = baskets.quote(rid, quote_request)
    quote_request['selections'] = preview['options'][0]['selection']
    quoted = baskets.quote(rid, quote_request)
    submission = {'idempotency_key': 'actual-checkout-1', 'quote_request': quote_request,
        'displayed_quote': {'request_id': quoted['requestId'], 'quote_id': quoted['quoteId'],
            'option_id': quoted['selected']['id'], 'total_minor': quoted['selected']['totalMinor'], 'currency': 'SEK'},
        'delivery_instructions': 'Ring twice.', 'terms_accepted': True}
    return baskets, rid, submission


def test_record_replays_actual_native_quote_without_mutation(fixture):
    baskets, rid, submission = fixture
    original = deepcopy((baskets.adapter.world, submission))
    record = native.make(baskets, rid, submission, order_id='order-1')
    assert native.validate(baskets, rid, record)
    assert record['simulated'] is True and record['status'] == 'confirmed'
    assert record['total_minor'] == submission['displayed_quote']['total_minor']
    assert record['address'] == submission['quote_request']['address']
    assert record['items'][0]['offer_id'] == submission['quote_request']['lines'][0]['offer_id']
    assert (baskets.adapter.world, submission) == original
    record['address']['name'] = 'Foreign'
    assert submission['quote_request']['address'] == original[1]['quote_request']['address']


@pytest.mark.parametrize('case', ['no_selection', 'stale_quote', 'stale_request',
    'stale_option', 'wrong_total', 'boolean_total', 'no_consent', 'foreign_address',
    'unknown_choice', 'card_field', 'card_in_address', 'unknown_offer'])
def test_bad_or_stale_submission_never_yields_receipt(fixture, case):
    baskets, rid, submission = fixture
    if case == 'no_selection': submission['quote_request']['selections'] = None
    elif case == 'stale_quote': submission['displayed_quote']['quote_id'] = 'stale'
    elif case == 'stale_request': submission['displayed_quote']['request_id'] = 'stale'
    elif case == 'stale_option': submission['displayed_quote']['option_id'] = 'stale'
    elif case == 'wrong_total': submission['displayed_quote']['total_minor'] += 1
    elif case == 'boolean_total': submission['displayed_quote']['total_minor'] = True
    elif case == 'no_consent': submission['terms_accepted'] = 1
    elif case == 'foreign_address': submission['quote_request']['address']['postcode'] = '99999'
    elif case == 'unknown_choice': submission['quote_request']['selections'] = {'actual-cart-line': 'foreign'}
    elif case == 'card_field': submission['cardNumber'] = 'not-retained'
    elif case == 'card_in_address': submission['quote_request']['address']['securityCode'] = 'not-retained'
    else: submission['quote_request']['lines'][0]['offer_id'] = 'foreign'
    with pytest.raises(ValueError): native.make(baskets, rid, submission, order_id='order-1')


@pytest.mark.parametrize('field', ['items', 'address', 'selection', 'shipments', 'total_minor', 'world_sha256'])
def test_receipt_content_cannot_be_rebound_after_commit(fixture, field):
    baskets, rid, submission = fixture
    record = native.make(baskets, rid, submission, order_id='order-1')
    record[field] = 'foreign'
    with pytest.raises(ValueError): native.validate(baskets, rid, record)
