"""Detached simulated receipt over the existing authoritative basket transport.

The caller owns the locked private ledger and runtime-scoped idempotency. This
module never mutates stock, a cart, an account, a payment or that ledger.
"""
from copy import deepcopy

from .adapter import digest

VERSION = 'website-simulated-order-record-v1'
SUBMISSION_FIELDS = {'idempotency_key', 'quote_request', 'displayed_quote',
                     'delivery_instructions', 'terms_accepted'}
DISPLAY_FIELDS = {'request_id', 'quote_id', 'option_id', 'total_minor', 'currency'}


def _text(value, limit):
    return type(value) is str and bool(value.strip()) and len(value) <= limit


def items(baskets, retailer_id, lines):
    """Native identities and summed quantities; quote validates the input domain."""
    retailer = baskets.adapter.retailers[retailer_id]
    offers = {o['offer_id']: o for o in retailer['offers']}
    totals = {}
    for line in lines:
        oid, quantity = line['offer_id'], line['quantity']
        if type(quantity) is not int or quantity < 1 or oid not in offers:
            raise ValueError('Invalid native order item or quantity')
        totals[oid] = totals.get(oid, 0) + quantity
    return [{'offer_id': oid, 'product_id': offers[oid]['product_id'],
             'sku_id': offers[oid]['sku_id'], 'quantity': quantity}
            for oid, quantity in sorted(totals.items())]


def make(baskets, retailer_id, submission, *, order_id):
    """Requote the exact displayed selection; return a detached native receipt."""
    if (not _text(order_id, 128) or type(submission) is not dict
            or set(submission) != SUBMISSION_FIELDS
            or not _text(submission['idempotency_key'], 200)
            or submission['terms_accepted'] is not True
            or type(submission['delivery_instructions']) is not str
            or len(submission['delivery_instructions']) > 2000):
        raise ValueError('Require an order ID, idempotency key, consent and complete simulated submission')
    request, shown = submission['quote_request'], submission['displayed_quote']
    if (type(request) is not dict or type(request.get('selections')) is not dict
            or not request['selections'] or type(shown) is not dict
            or set(shown) != DISPLAY_FIELDS
            or any(not _text(shown[k], 200) for k in ('request_id', 'quote_id', 'option_id'))
            or type(shown['total_minor']) is not int or shown['total_minor'] < 0
            or shown['currency'] != 'SEK'):
        raise ValueError('Commit needs explicit delivery selection and displayed quote identity/total')
    address = request.get('address')
    if (type(address) is not dict or set(address) not in (
            {'name', 'street', 'postcode', 'city'}, {'name', 'street', 'unit', 'postcode', 'city'})
            or any(type(v) is not str or len(v) > 200 for v in address.values())
            or any(not address[k].strip() for k in ('name', 'street', 'postcode', 'city'))):
        raise ValueError('Require the actual complete recipient and delivery address')
    quoted = baskets.quote(retailer_id, deepcopy(request))
    selected = quoted['selected']
    if (quoted['status'] != 'quoted' or quoted['selectionReset'] or selected is None
            or shown != {'request_id': quoted['requestId'], 'quote_id': quoted['quoteId'],
                'option_id': selected['id'], 'total_minor': selected['totalMinor'], 'currency': 'SEK'}):
        raise ValueError('Displayed quote is stale, unavailable or resolved through a selection fallback')
    native_items = items(baskets, retailer_id, request['lines'])
    offers = {o['offer_id']: o for o in baskets.adapter.retailers[retailer_id]['offers']}
    if any(offers[i['offer_id']]['currency'] != 'SEK' for i in native_items):
        raise ValueError('Current simulated receipt supports native SEK quotes')
    return {'schema_version': VERSION, 'order_id': order_id, 'simulated': True,
        'status': 'confirmed', 'retailer_id': retailer_id,
        'world_id': baskets.adapter.world['world_id'], 'world_sha256': digest(baskets.adapter.world),
        'plan_id': baskets.plan_id, 'domain_id': baskets.domain_id,
        'items': native_items, 'address': deepcopy(address),
        'delivery_instructions': submission['delivery_instructions'],
        'request_id': quoted['requestId'], 'quote_id': quoted['quoteId'],
        'option_id': selected['id'], 'currency': 'SEK',
        'selection': deepcopy(selected['selection']), 'shipments': deepcopy(selected['shipments']),
        'subtotal_minor': selected['subtotalMinor'], 'discount_minor': selected['discountMinor'],
        'shipping_minor': selected['shippingMinor'], 'total_minor': selected['totalMinor'],
        'submission_sha256': digest(submission), 'submission': deepcopy(submission)}


def validate(baskets, retailer_id, record):
    if type(record) is not dict or digest(record) != digest(make(baskets, retailer_id,
            record.get('submission'), order_id=record.get('order_id'))):
        raise ValueError('Simulated order differs from its actual native quote/submission')
    return digest(record)
