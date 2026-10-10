"""Shared quantity domain and canonical money bindings; no model calls."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import json
import subprocess

import pytest

from experiments.footwear_world_pilot import basket_quote, coupon_quote, order_set_optimizer
from experiments.footwear_world_pilot.test_basket_quote import world, bind, plan, coupon
from environments.website_world import checkout_domain as domains
from environments.website_world.adapter import PublicAdapter
from environments.website_world.basket import Baskets, basket_shop_source
from environments.website_world.generation import compile_request, VERSION


def adapter(world, p=None, cp=None, options=None):
    domain = domains.make(world, options)
    coupons = SimpleNamespace(plan=cp, account=lambda rid: coupon_quote.public_account(cp, rid)) if cp else None
    from environments.website_world.adapter import browser_address
    base = SimpleNamespace(world=world, retailers={r['retailer_id']: r for r in world['retailers']},
        initial_address=browser_address(next(a for a in world['address_context']['addresses'] if a['address_id']=='user-home')))
    value = Baskets(base, p or plan(world), coupons, domain)
    return value, domain


def request(value, world, rows, coupon=None):
    return {'revision': 1, 'world_id': world['world_id'], 'plan_id': value.plan_id,
            'domain_id': value.domain_id, 'lines': rows, 'address': value.adapter.initial_address,
            'selections': None, 'split': False, 'coupon_code': coupon}


def test_canonical_money_reordering_aliases_and_duplicate_rows(world):
    # A one-cent allocation across equal-price groups exposes rounding identity.
    r = world['retailers'][0]
    for o in r['offers'][:2]:
        o['price_minor'] = 101
    r['free_shipping_threshold_minor'] = 101
    bind(world)
    cp = coupon(world, value=1)
    p = plan(world, consolidate_sources=False, qualification_scope='shipment')
    value, domain = adapter(world, p, cp)
    a, b = [o['offer_id'] for o in r['offers'][:2]]
    rows = [{'line_id': '2', 'offer_id': a, 'quantity': 1}, {'line_id': '1', 'offer_id': b, 'quantity': 1}]
    first = value.quote(r['retailer_id'], request(value, world, rows, 'SAVE'))
    reversed_rows = [{'line_id': '90', 'offer_id': b, 'quantity': 1}, {'line_id': '3', 'offer_id': a, 'quantity': 1}]
    second = value.quote(r['retailer_id'], request(value, world, reversed_rows, 'SAVE'))
    assert first['quoteId'] == second['quoteId']
    assert first['selected'] == second['selected']
    canonical, _ = domains.canonical_lines(world, domain, r['retailer_id'], rows)
    native = basket_quote.quote(world, r['retailer_id'], canonical, plan=p, coupon_plan=cp,
        coupon_code='SAVE', signed_in=True, selections=first['selected']['selection'])
    assert first['selected']['lineDiscountAllocations'] == native['selected']['line_discount_allocations']
    combined = rows + [{'line_id': '4', 'offer_id': a, 'quantity': 1}]
    merged = value.quote(r['retailer_id'], request(value, world, combined, 'SAVE'))
    direct = value.quote(r['retailer_id'], request(value, world,
        [{'line_id': a, 'offer_id': a, 'quantity': 2}, {'line_id': b, 'offer_id': b, 'quantity': 1}], 'SAVE'))
    assert merged['quoteId'] == direct['quoteId']


def test_shared_quantity_domain_permits_above_twenty_and_rejects_aggregate_excess(world):
    r = world['retailers'][0]
    value, domain = adapter(world, options={'max_quantity_per_offer': 25, 'max_lines_per_order': 2})
    a, b, c = [o['offer_id'] for o in r['offers']]
    rows = [{'line_id': 'ui', 'offer_id': a, 'quantity': 21}]
    assert value.quote(r['retailer_id'], request(value, world, rows))['selected'] is not None
    for invalid in (rows + [{'line_id': 'other', 'offer_id': a, 'quantity': 5}],
                    [{'line_id': oid, 'offer_id': oid, 'quantity': 1} for oid in (a, b, c)]):
        with pytest.raises(ValueError):
            value.quote(r['retailer_id'], request(value, world, invalid))
    stale = request(value, world, rows);stale['domain_id'] = 'old-domain'
    with pytest.raises(ValueError):
        value.quote(r['retailer_id'], stale)
    raw = domains.public(world, domain, r['retailer_id'])
    assert raw['quantityLimits'][a] == 25 and raw['maxLinesPerOrder'] == 2


def test_explicit_line_domain_changes_optimum_without_hidden_truncation(world):
    r = world['retailers'][0]
    ids = [o['offer_id'] for o in r['offers'][:2]]
    requirements = [{'requirement_id': str(i), 'quantity': 1, 'offer_ids': [o]} for i, o in enumerate(ids)]
    domain = domains.make(world, {'max_lines_per_order': 1})
    result = order_set_optimizer.solve(world, requirements, plan=plan(world), allow_extras=True,
        quantity_limits=domain['quantity_limits'], max_lines_per_order=domain['options']['max_lines_per_order'],
        allowed_destination_types=['home'])
    assert result['status'] == 'optimal' and result['total_minor'] == 101800
    assert all(len(o['lines']) == 1 for s in result['solutions'] for o in s['orders'])
    assert result['domain']['max_lines_per_order'] == 1


@pytest.mark.parametrize('invalid', [None, True, {'max_quantity_per_offer': 0}, {'max_lines_per_order': 65}])
def test_generation_rejects_invalid_explicit_domains(invalid):
    with pytest.raises(ValueError):
        compile_request({'schema': VERSION, 'seed': 1, 'basket_shipping': {'enabled': True}, 'checkout_domain': invalid})
    with pytest.raises(ValueError):
        compile_request({'schema': VERSION, 'seed': 1, 'checkout_domain': {}})


def test_domain_has_complete_offer_limits_and_rejects_stale_world(world):
    domain = domains.make(world)
    assert domains.validate(world, domain)
    changed = deepcopy(world);changed['retailers'][0]['offers'][0]['price_minor'] += 1
    with pytest.raises(ValueError):domains.validate(changed, domain)
    missing = deepcopy(domain);missing['quantity_limits'].pop(next(iter(missing['quantity_limits'])))
    with pytest.raises(ValueError):domains.validate(world, missing)


def test_canonical_browser_payload_uses_money_ids_and_preserves_ui_ids():
    source = Path(__file__).with_name('basket_quote.js').read_text()
    source = '\n'.join(l for l in source.splitlines() if not l.startswith(('import ', 'export {')))
    setup = """
const data={basket:{worldId:'world',planId:'plan',domain:{id:'domain',quantityLimits:{offer:25},maxLinesPerOrder:2}}};
const itemBinding={}; const validateAddress=()=>[];
const byVariant=key=>({variant:{offerId:key},product:{name:key}});
let posted;globalThis.fetch=async(url,request)=>{posted=JSON.parse(request.body);return {ok:true,json:async()=>({revision:1,selected:null})};};
"""
    checks = """
const assert=v=>{if(!v)throw Error('canonical payload assertion failed');};
const draft={revision:1,cart:[{id:'ui2',key:'offer',quantity:1},{id:'ui1',key:'offer',quantity:2}],address:{},addressStatus:'valid',split:false};
await worldBinding.ensureQuote(draft);
assert(posted.domain_id==='domain'&&posted.lines.length===1);
assert(posted.lines[0].line_id==='offer'&&posted.lines[0].quantity===3);
assert(draft.cart[0].id==='ui2'&&draft.cart[1].id==='ui1');
assert(worldBinding.quantityLimit({offerId:'offer'})===25&&worldBinding.maxLinesPerOrder()===2);
"""
    subprocess.run(['node', '--input-type=module'], input=setup + source + checks,
                   text=True, check=True, capture_output=True)
    shop = basket_shop_source((Path(__file__).resolve().parents[1]/'website_drafts/shop.js').read_text(), canonical_domain=True)
    assert shop.count('worldBinding.quantityLimit(v)') == 2
    assert 'other.quantity+=quantity' in shop and 'worldBinding.maxLinesPerOrder()' in shop
