from copy import deepcopy
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen
import json

import pytest

from environments.website_world.adapter import PublicAdapter, load_pin, supported_destination
from environments.website_world.coupons import Coupons, load_coupon_pin
from environments.website_world.presentation import VERSION, site_plan
from environments.website_world.runtime import Runtime
from experiments.footwear_world_pilot import coupon_quote

PIN = Path('.local/coordination/website-hindrance-integration/coupon-stage-v1')


def test_all_carried_coupon_services_project_exact_native_totals_without_private_routes():
    world, _ = load_pin()
    before = deepcopy(world)
    adapter = PublicAdapter(world)
    coupons = Coupons(adapter, PIN)
    address = adapter.initial_address
    destination = supported_destination(world, address)
    for r in world['retailers']:
        for offer in r['offers']:
            public = coupons.quote(r['retailer_id'], {**address, 'offer_id': offer['offer_id'],
                'quantity': '1', 'coupon_code': 'MEMBER10'})
            native = coupon_quote.quote(world, r['retailer_id'], offer['offer_id'],
                plan=coupons.plan, coupon_code='MEMBER10', signed_in=True, destination=destination)
            assert public['quote_id'] == native['quote_id']
            assert public['coupon'] == native['coupon']
            assert len(public['options']) == len(native['options'])
            for p, q in zip(public['options'], native['options']):
                assert (p['shippingMinor'], p['totalMinor'], p['arrival']) == (q['shipping_minor'], q['total_minor'], q['arrival_date'])
                assert not {'route', 'location_id', 'latitude', 'longitude'} & p.keys()
    assert world == before


def test_binding_quantity_address_and_unknown_code_are_not_silently_repaired():
    world, _ = load_pin()
    coupons = Coupons(PublicAdapter(world), PIN)
    r = world['retailers'][0]
    query = {**coupons.adapter.initial_address, 'offer_id': r['offers'][0]['offer_id'], 'quantity': '1'}
    ordinary = coupons.quote(r['retailer_id'], query)
    rejected = coupons.quote(r['retailer_id'], {**query, 'coupon_code': 'UNKNOWN'})
    assert rejected['coupon']['status'] == 'rejected'
    assert rejected['coupon']['reason'] == 'coupon_not_found'
    assert rejected['discount_minor'] == 0 and rejected['options'] == ordinary['options']
    for changes in ({'quantity': '2'}, {'postcode': '99999'}, {'signed_in': 'true'}, {'offer_id': 'other'}):
        with pytest.raises(ValueError):
            coupons.quote(r['retailer_id'], {**query, **changes})
    changed = deepcopy(world); changed['world_id'] = 'stale'
    with pytest.raises(ValueError): load_coupon_pin(PIN, changed)


def test_opacity_is_conditioned_only_when_compatible_with_native_programme():
    world, _ = load_pin(); r = world['retailers'][0]
    req = {'schema': VERSION, 'world_id': world['world_id'], 'sites': {
        r['retailer_id']: {'conditions': {'site.opaque': ['true']}}}}
    with pytest.raises(ValueError): site_plan(world, r, req)
    assert site_plan(world, r, req, coupon_supported=True)['config']['opaque']


def test_opt_in_http_account_and_quotes_are_public_without_mounting_sidecar():
    world, _ = load_pin(); sid = world['retailers'][0]['retailer_id']
    request = {'schema': VERSION, 'world_id': world['world_id'], 'sites': {
        sid: {'initial_form': 'canonical', 'conditions': {'site.opaque': ['true']}}}}
    with Runtime(presentation=request, coupon_pin=PIN) as runtime:
        origin = runtime.origins[sid]
        catalog = json.load(urlopen(origin + '/api/catalog'))
        assert catalog['account']['signed_in'] and catalog['configuration']['opaque']
        query = {**catalog['initialAddress'], 'offer_id': world['retailers'][0]['offers'][0]['offer_id'],
                 'quantity': '1', 'coupon_code': 'MEMBER10'}
        public = json.load(urlopen(origin + '/api/quote?' + urlencode(query)))
        assert public['coupon']['status'] == 'applied'
        for path in ('/coupon-plan.json', '/reference-with-coupons.private.json', '/api/quote?' + urlencode({**query, 'quantity': '2'})):
            with pytest.raises(HTTPError) as error: urlopen(origin + path)
            assert error.value.code in (400, 404)
        assert runtime.snapshot()['commerce_mutations'] == []
