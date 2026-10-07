"""One preloaded exact-SKU order, using the current admitted basket oracle.

Concrete public wording/memories are authored by Evaluation. Task construction
never appends hints, prohibitions, samples a replacement world or changes stock.
"""
from copy import deepcopy

from .adapter import browser_address, digest
from . import simulated_order_record as records

VERSION = 'website-simulated-order-task-v1'
REFERENCE_VERSION = 'website-simulated-order-reference-v1'
KIND = 'place_preloaded_order'
DELIVERY_TYPES = {'home', 'staffed_counter', 'parcel_locker', 'retailer_branch'}


def context(baskets):
    coupons = baskets.coupons
    return {'world_id': baskets.adapter.world['world_id'],
            'world_sha256': digest(baskets.adapter.world),
            'plan_id': baskets.plan_id, 'domain_id': baskets.domain_id,
            'coupon_plan_sha256': digest(coupons.plan) if coupons else None}


def make(baskets, spec):
    fields = {'kind', 'retailer_id', 'offer_id', 'quantity', 'delivery_types',
              'coupon_code', 'public_request', 'memories'}
    if (type(spec) is not dict or set(spec) != fields or spec['kind'] != KIND
            or type(spec['retailer_id']) is not str
            or spec['retailer_id'] not in baskets.adapter.retailers
            or type(spec['offer_id']) is not str
            or type(spec['quantity']) is not int or spec['quantity'] < 1
            or type(spec['public_request']) is not str or not spec['public_request'].strip()
            or len(spec['public_request']) > 10000
            or type(spec['memories']) is not list
            or any(type(m) is not str or not m.strip() for m in spec['memories'])
            or (spec['coupon_code'] is not None and
                (type(spec['coupon_code']) is not str or not spec['coupon_code']))):
        raise ValueError('Declare one preloaded order and its actual authored request/memories')
    types = spec['delivery_types']
    if types is not None and (type(types) is not list or not types
            or any(type(t) is not str or t not in DELIVERY_TYPES for t in types)
            or len(set(types)) != len(types)):
        raise ValueError('Use all admitted methods or an explicit nonempty delivery-type restriction')
    rid = spec['retailer_id']
    lines = [{'line_id': spec['offer_id'], 'offer_id': spec['offer_id'], 'quantity': spec['quantity']}]
    native_items = records.items(baskets, rid, lines)
    # Validate quantity against the existing canonical shared domain, not a new cap.
    if baskets.domain is None:
        raise ValueError('Order tasks require the shared checkout quantity domain')
    baskets.domain_provider.canonical_lines(baskets.adapter.world, baskets.domain, rid, lines)
    homes = [a for a in baskets.adapter.world['address_context']['addresses'] if a['address_id'] == 'user-home']
    if len(homes) != 1:
        raise ValueError('Require the actual current user-home address')
    task = {'schema_version': VERSION, 'spec': deepcopy(spec), 'kind': KIND,
            'context': context(baskets), 'retailer_id': rid, 'items': native_items,
            'delivery_address': deepcopy(homes[0]['address']),
            'address_fields': browser_address(homes[0]),
            'delivery_types': deepcopy(types), 'coupon_code': spec['coupon_code'],
            'user_message': spec['public_request'], 'memories': deepcopy(spec['memories']),
            'setup': {'kind': 'preloaded_cart_before_checkout', 'retailer_id': rid, 'lines': lines}}
    task['task_id'] = 'simulated-order-' + digest(task)[:24]
    return task


def reference(baskets, task):
    if digest(task) != digest(make(baskets, task['spec'])):
        raise ValueError('Original task, request, address or native basket context changed')
    rid = task['retailer_id']
    splits = (False, True) if baskets.policy(rid)['optional_split'] else (False,)
    options = []
    for split in splits:
        request = {'revision': 0, 'world_id': task['context']['world_id'],
            'plan_id': baskets.plan_id, 'domain_id': baskets.domain_id,
            'lines': deepcopy(task['setup']['lines']), 'address': deepcopy(task['address_fields']),
            'selections': None, 'split': split, 'coupon_code': task['coupon_code']}
        quoted = baskets.quote(rid, request)
        for option in quoted['options']:
            methods = {s['delivery']['type'] for s in option['shipments']}
            if task['delivery_types'] is None or methods <= set(task['delivery_types']):
                options.append({'split': split, **deepcopy(option)})
    minimum = min((o['shippingMinor'] for o in options), default=None)
    return {'schema_version': REFERENCE_VERSION, 'task_sha256': digest(task),
            'context': context(baskets), 'status': 'ready' if options else 'no_match',
            'delivery_fee_basis': 'shippingMinor for the fixed preloaded SKU/quantity and coupon context',
            'options': options, 'minimum_shipping_minor': minimum,
            'winners': [deepcopy(o) for o in options if o['shippingMinor'] == minimum],
            'limitations': ['One fixed SKU/quantity at one retailer; no cross-retailer, extra-item or coupon optimization.',
                'Cheapest delivery includes admitted branch/pickup/home methods; arrival speed is not ranked.',
                'A native reference does not establish public discoverability or capture authority.']}
