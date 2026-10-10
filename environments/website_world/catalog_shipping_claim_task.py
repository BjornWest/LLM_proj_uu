"""Audit an advertised shipping threshold against a real single-SKU basket quote.

The scalar subtotal test is not a promise of free shipping. Actual admitted
options retain carrier, destination, upgrade and membership qualifications.
"""
from copy import deepcopy

from . import catalog_checkout_domain as checkout, quote_offer_task
from .adapter import browser_address, digest

VERSION = 'website-catalog-shipping-claim-task-v1'
KIND = 'audit_free_shipping_claim'
TYPES = quote_offer_task.TYPES


def resolve(value):
    allowed = {'kind', 'retailer_index', 'offer_index', 'quantity', 'delivery_types'}
    if type(value) is not dict or set(value) - allowed or value.get('kind') != KIND:
        raise ValueError('Declare audit_free_shipping_claim and finite identity selectors')
    result = {'kind': KIND, 'retailer_index': value.get('retailer_index', 0),
              'offer_index': value.get('offer_index', 0), 'quantity': value.get('quantity', 1),
              'delivery_types': deepcopy(value.get('delivery_types', list(TYPES)))}
    for key in ('retailer_index', 'offer_index'):
        if type(result[key]) is not int or not 0 <= result[key] <= 10000:
            raise ValueError('Selectors must be integer identity indices, not outcome targets')
    if type(result['quantity']) is not int or not 1 <= result['quantity'] <= 1000000:
        raise ValueError('Quantity must be positive integer retail sale units')
    types = result['delivery_types']
    if (type(types) is not list or not types or any(type(t) is not str or t not in TYPES for t in types)
            or len(types) != len(set(types))):
        raise ValueError('Declare unique home/parcel_locker/staffed_counter methods; shop pickup is separate')
    result['delivery_types'] = sorted(types)
    return result


def selected_offer(world, selection):
    retailers = sorted(world['retailers'], key=lambda r: r['retailer_id'])
    if selection['retailer_index'] >= len(retailers):
        return None
    retailer = retailers[selection['retailer_index']]
    offers = sorted(retailer['offers'], key=lambda o: o['offer_id'])
    if selection['offer_index'] >= len(offers):
        return None
    offer = offers[selection['offer_index']]
    product = next(p for p in world['products'] if p['public']['product_id'] == offer['product_id'])
    sku = next(s for s in product['public']['skus'] if s['sku_id'] == offer['sku_id'])
    return retailer, offer, product, sku


def make(world, spec, *, quote_context, checkout_domain):
    selection = resolve(spec)
    checkout.validate(world, checkout_domain)
    quote_binding = quote_offer_task._check_quote_binding(world, quote_context)
    row = selected_offer(world, selection)
    if row is None:
        raise ValueError('Natural population has no selected retailer/offer identity')
    retailer, offer, product, sku = row
    if selection['quantity'] > checkout_domain['quantity_limits'][offer['offer_id']]:
        raise ValueError('Requested quantity exceeds the shared checkout domain')
    variant = {k: deepcopy(sku[k]) for k in product['variant_fields']}
    address = browser_address(quote_offer_task.home_record(world))
    description = ', '.join(k.replace('_', ' ') + ': ' + str(v) for k, v in variant.items())
    message = ('Check '+retailer['name']+'\'s advertised free-shipping terms for '+str(selection['quantity'])+
        ' retail sale unit(s) of '+product['public']['name']+' ('+description+'). '
        'A sale unit is the whole pack when sold as a pack. Use a fresh basket containing only '
        'these units, no coupons, extras or new memberships; preserve any already-active shipping benefit. '
        'Destination: '+', '.join(address.values())+'. Allowed delivery methods: '+
        ', '.join(quote_offer_task.TYPE_LABELS[t] for t in selection['delivery_types'])+'. '
        'Report the listed unit price and merchandise subtotal in SEK; the advertised free-shipping '
        'threshold in SEK, or explicitly say no threshold is offered; and whether the subtotal reaches it. '
        'Reaching the number alone does not guarantee free shipping: retain destination restrictions, '
        'standard-versus-express charges and active benefits. Report how many complete admitted delivery '
        'options are currently available for this exact basket, how many have zero shipping charge, '
        'and the minimum and maximum shipping charge in SEK. Say whether all, some or none of these '
        'options are free; if none are available, say unavailable and leave minimum/maximum undefined. '
        'Shop collection is outside this scope, and shipping here includes all unavoidable delivery fees. '
        'Do not attribute a zero charge to the threshold merely because it is zero. Include the exact '
        'retailer product link and the shipping-policy or checkout link. This is an audit, not a cheapest '
        'product search or an arrival-speed ranking. Do not place an order.')
    task = {**selection, 'schema_version': VERSION, 'world_id': world['world_id'],
        'world_sha256': digest(world), 'checkout_domain_sha256': digest(checkout_domain),
        'quote_binding': quote_binding, 'subject': {'retailer_id': retailer['retailer_id'],
        'retailer_name': retailer['name'], 'offer_id': offer['offer_id'], 'product_id': offer['product_id'],
        'product_name': product['public']['name'], 'concept_id': product['public']['concept_id'],
        'sku_id': offer['sku_id'], 'selection': variant},
        'destination_address': address, 'user_message': message, 'memories': [],
        'quantity_basis': 'retail_sale_units', 'corpus_policy': 'Complete admitted quotes before fee comparisons; no fallback routes.'}
    task['task_id'] = 'shipping-claim-' + digest(task)[:24]
    return task


def reference(world, task, *, quote_context, checkout_domain):
    selection = {k: deepcopy(task[k]) for k in ('kind', 'retailer_index', 'offer_index', 'quantity', 'delivery_types')}
    if task != make(world, selection, quote_context=quote_context, checkout_domain=checkout_domain):
        raise ValueError('Shipping claim task/world/quantity/menu binding changed')
    retailer, offer, _, _ = selected_offer(world, selection)
    oid = offer['offer_id']; quantity = task['quantity']
    quote = quote_context.quote(retailer['retailer_id'],
        [{'line_id': oid, 'offer_id': oid, 'quantity': quantity}],
        destination=quote_offer_task.home_record(world)['location'], split=False)
    options = []
    for option in quote['options']:
        if set(option['selection']) != {oid} or len(option['shipments']) != 1:
            raise ValueError('Single-SKU basket quote has another order shape')
        shipment = option['shipments'][0]
        if shipment['delivery']['destination_type'] in task['delivery_types']:
            options.append(deepcopy(option))
    threshold = retailer['free_shipping_threshold_minor']
    subtotal = offer['price_minor'] * quantity
    free = sum(o['shipping_minor'] == 0 for o in options)
    fees = [o['shipping_minor'] for o in options]
    assessment = 'unavailable' if not options else 'all_free' if free == len(options) else 'some_free' if free else 'none_free'
    return {'schema_version': VERSION, 'task_id': task['task_id'], 'world_id': world['world_id'],
        'world_sha256': digest(world), 'subject': deepcopy(task['subject']), 'currency': 'SEK',
        'quantity': quantity, 'unit_price_minor': offer['price_minor'], 'subtotal_minor': subtotal,
        'advertised_threshold_minor': threshold,
        'subtotal_test': 'no_threshold' if threshold is None else 'meets_threshold' if subtotal >= threshold else 'below_threshold',
        'assessment': assessment, 'option_count': len(options), 'free_option_count': free,
        'minimum_shipping_minor': min(fees) if fees else None, 'maximum_shipping_minor': max(fees) if fees else None,
        'quote_id': quote['quote_id'], 'quote_status': quote['status'],
        'all_quote_options': deepcopy(quote['options']), 'scoped_options': options,
        'public_policy': quote_context.public_policy(retailer['retailer_id']),
        'limitations': ['Numeric threshold test is separate from actual route/upgrade/membership qualification.',
                       'No counterfactual claim that the threshold caused any zero fee.',
                       'Native quote truth is not public exposure, cart-state or transaction-effect evidence.']}
