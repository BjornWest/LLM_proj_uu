from copy import deepcopy
from urllib.error import HTTPError
from urllib.request import urlopen, Request
import json

import pytest

from environments.website_world.adapter import PublicAdapter, browser_address, load_pin, supported_destination
from environments.website_world.runtime import Runtime
from experiments.footwear_world_pilot import model


def test_projection_keeps_all_and_only_carried_skus_and_exact_offer_prices():
    world, pin = load_pin()
    adapter = PublicAdapter(world)
    forbidden = {'private', 'task', 'reference', 'diagnostics', 'sampling_trace', 'price_trace', 'conditions', 'relevance', 'stock_tendency'}
    def inspect(value):
        if isinstance(value, dict):
            assert not forbidden.intersection(value)
            for child in value.values(): inspect(child)
        if isinstance(value, list):
            for child in value: inspect(child)
    for retailer in world['retailers']:
        public = adapter.catalog(retailer['retailer_id'], {})
        inspect(public)
        carried = {o['sku_id']: o for o in retailer['offers']}
        manufactured = {s['sku_id']: s for p in world['products'] for s in p['public']['skus']}
        variants = [v for p in public['products'] for v in p['variants']]
        assert {v['skuId'] for v in variants} == set(carried)
        assert len(variants) == len(carried)
        for variant in variants:
            offer = carried[variant['skuId']]
            assert variant['key'] == variant['skuId']
            assert variant['priceMinor'] == offer['price_minor']
            assert {s['sourceId']: s['quantity'] for s in variant['sourceStock']} == offer['stock_by_source']
            assert all(str(manufactured[variant['skuId']][k]) == v for k,v in variant['selection'].items())


def test_all_home_and_collection_choices_preserve_authoritative_totals():
    world, _ = load_pin()
    adapter = PublicAdapter(world)
    total = 0
    for retailer in world['retailers']:
        public = adapter.fulfilment(retailer['retailer_id'], adapter.initial_address)
        for offer in retailer['offers']:
            original = model.delivery_options(world, retailer, offer)
            projected = public['optionsBySku'][offer['sku_id']]
            assert len(projected) == len(original)
            assert len({q['id'] for q in projected}) == len(projected)
            for q, p in zip(original, projected):
                assert (p['sourceId'],p['carrierId'],p['tier'],p['type'],p['location']['id']) == (q['source_id'],q['carrier_id'],q['tier'],q['destination_type'],q['point_id'] or 'home')
                assert (p['shippingMinor'],p['totalMinor'],p['arrival'],p['readyDays']) == (q['shipping_minor'],q['total_minor'],q['arrival_date'],q['ready_days'])
            total += len(projected)
    assert total == 11272
    assert model.solve(world) == world['reference']


def test_address_resolution_is_explicit_and_recipient_is_not_stale():
    world, _ = load_pin()
    adapter = PublicAdapter(world)
    for known in world['address_context']['addresses']:
        address = browser_address(known)
        assert supported_destination(world, address)['location_id'] == known['location']['location_id']
        result = adapter.fulfilment(world['retailers'][0]['retailer_id'], address)
        assert result['address'] == address
    changed = {**adapter.initial_address, 'name': 'Different Recipient'}
    assert adapter.fulfilment(world['retailers'][0]['retailer_id'], changed)['address'] == changed
    home = adapter.fulfilment(world['retailers'][0]['retailer_id'], adapter.initial_address)
    other = adapter.fulfilment(world['retailers'][0]['retailer_id'], browser_address(world['address_context']['addresses'][1]))
    for sku, options in home['optionsBySku'].items():
        old = {o['id'] for o in options if o['type']=='home'}
        new = {o['id'] for o in other['optionsBySku'][sku] if o['type']=='home'}
        assert old == new
    for changes in ({'street': 'Björkvägen 999'}, {'postcode': '99999'}, {'city': 'Stockholm'}, {'latitude': 0}):
        with pytest.raises(ValueError):
            supported_destination(world, {**adapter.initial_address, **changes})


def test_runtime_routes_never_mount_private_input_or_allow_purchase():
    with Runtime() as runtime:
        assert len(runtime.bindings['retailer_offers']) == 285
        assert sum(len(v) for v in runtime.bindings['retailer_skus'].values()) == 285
        origin = next(iter(runtime.origins.values()))
        for path in ('/world.json','/manifest.json','/policy-input.json','/generated-catalog.js','/reviewer.js','/../world.json'):
            with pytest.raises(HTTPError) as error: urlopen(origin + path)
            assert error.value.code == 404
        with pytest.raises(HTTPError) as error:
            urlopen(Request(origin + '/purchase', data=b'quantity=1'))
        assert error.value.code == 405
        assert runtime.snapshot()['orders'] == []
        assert runtime.snapshot()['commerce_mutations'] == []
        public = json.load(urlopen(origin + '/api/catalog'))
        assert public['siteId'] == next(iter(runtime.origins))
