"""Opt-in, single-item native coupon quotes; no account or order mutation.

Plans are explicit authored fixtures bound to an immutable world. This module
does not turn the legacy account sampler into a new-width account producer.
"""
from copy import deepcopy
from datetime import date
import math

from . import model

VERSION = 'footwear-coupon-quote-v1'
PLAN_VERSION = 'footwear-coupon-plan-v1'
ACCOUNT_KEYS = {'retailer_id', 'signed_in', 'coupons'}
COUPON_KEYS = {'coupon_id', 'code', 'kind', 'value', 'minimum_subtotal_minor',
               'concept_ids', 'valid_from', 'valid_until', 'redeemed', 'currency'}


def _integer(value, minimum=0):
    return type(value) is int and value >= minimum


def _text(value):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 200


def _day(value):
    if not isinstance(value, str):
        raise ValueError('Date must be ISO calendar text')
    result = date.fromisoformat(value)
    if result.isoformat() != value:
        raise ValueError('Date must be YYYY-MM-DD')
    return result


def validate_plan(world, plan):
    """Reject stale binding, unknown subjects and unsupported monetary terms."""
    if world.get('schema_version') != model.VERSION:
        raise ValueError('Expected native footwear world')
    if not isinstance(plan, dict) or set(plan) != {
            'schema_version', 'world_id', 'world_sha256', 'origin', 'accounts'}:
        raise ValueError('Invalid coupon plan shape')
    if (plan['schema_version'] != PLAN_VERSION or
            plan['world_id'] != world['world_id'] or
            plan['world_sha256'] != model.digest(world)):
        raise ValueError('Coupon plan/world binding mismatch')
    if plan['origin'] != 'authoring_fixture':
        raise ValueError('Only explicitly authored coupon fixtures are supported')
    if not isinstance(plan['accounts'], list):
        raise ValueError('Accounts must be a list')
    retailers = {r['retailer_id']: r for r in world['retailers']}
    concepts = {p['public']['product_id']: p['public']['concept_id'] for p in world['products']}
    seen_accounts, seen_coupons = set(), set()
    for account in plan['accounts']:
        if not isinstance(account, dict) or set(account) != ACCOUNT_KEYS:
            raise ValueError('Invalid account shape')
        rid = account['retailer_id']
        if not _text(rid) or rid not in retailers or rid in seen_accounts:
            raise ValueError('Unknown or duplicate account retailer')
        seen_accounts.add(rid)
        if type(account['signed_in']) is not bool or not isinstance(account['coupons'], list):
            raise ValueError('Invalid account state')
        allowed_concepts = {concepts[o['product_id']] for o in retailers[rid]['offers']}
        codes = set()
        for coupon in account['coupons']:
            if not isinstance(coupon, dict) or set(coupon) != COUPON_KEYS:
                raise ValueError('Invalid coupon shape')
            if not _text(coupon['coupon_id']) or coupon['coupon_id'] in seen_coupons:
                raise ValueError('Invalid or duplicate coupon identity')
            seen_coupons.add(coupon['coupon_id'])
            if not _text(coupon['code']) or coupon['code'] in codes:
                raise ValueError('Invalid or duplicate coupon code')
            codes.add(coupon['code'])
            if (coupon['kind'] not in ('percent', 'fixed') or
                    not _integer(coupon['value'], 1) or
                    coupon['kind'] == 'percent' and coupon['value'] > 100 or
                    not _integer(coupon['minimum_subtotal_minor']) or
                    type(coupon['redeemed']) is not bool or coupon['currency'] != 'SEK'):
                raise ValueError('Unsupported coupon monetary/state terms')
            scope = coupon['concept_ids']
            if (not isinstance(scope, list) or any(not _text(c) for c in scope) or
                    len(scope) != len(set(scope)) or not set(scope) <= allowed_concepts):
                raise ValueError('Invalid coupon concept scope')
            if _day(coupon['valid_from']) > _day(coupon['valid_until']):
                raise ValueError('Inverted coupon dates')
    return {'valid': True, 'plan_sha256': model.digest(plan)}


def make_plan(world, accounts=()):
    """Bind explicit account rows; no stochastic sampling or source-world edits."""
    plan = {'schema_version': PLAN_VERSION, 'world_id': world['world_id'],
            'world_sha256': model.digest(world), 'origin': 'authoring_fixture',
            'accounts': deepcopy(list(accounts))}
    validate_plan(world, plan)
    return plan


def public_account(plan, retailer_id):
    """Public account terms only, without the trusted world/provenance binding."""
    account = next((a for a in plan['accounts'] if a['retailer_id'] == retailer_id), None)
    if account is None:
        return {'signed_in': False, 'coupons': []}
    return {'signed_in': account['signed_in'],
            'coupons': deepcopy(account['coupons']) if account['signed_in'] else []}


def quote(world, retailer_id, offer_id, *, plan, coupon_code=None, signed_in=None,
          destination=None, quantity=1):
    """Quote one offer, re-evaluating native shipping after a valid discount.

    A rejected coupon leaves undiscounted options with explicit rejection feedback.
    Session state is input, never mutated. Native destination lookup belongs to
    the caller; a non-None location is never replaced with the user's home.
    """
    if type(quantity) is not int or quantity != 1:
        raise ValueError('Only one line, quantity one is supported')
    if signed_in is not None and type(signed_in) is not bool:
        raise ValueError('Signed-in override must be boolean')
    if coupon_code is not None and not _text(coupon_code):
        raise ValueError('Coupon code must be nonempty text or None')
    validation = validate_plan(world, plan)
    retailer = next((r for r in world['retailers'] if r['retailer_id'] == retailer_id), None)
    if retailer is None:
        raise ValueError('Unknown retailer')
    offer = next((o for o in retailer['offers'] if o['offer_id'] == offer_id), None)
    if offer is None:
        raise ValueError('Offer is not carried by this retailer')
    if offer['currency'] != 'SEK' or not _integer(offer['price_minor']):
        raise ValueError('Unsupported offer currency or price')
    product = next(p for p in world['products'] if p['public']['product_id'] == offer['product_id'])
    if not any(s['sku_id'] == offer['sku_id'] for s in product['public']['skus']):
        raise ValueError('Offer/SKU manufacture mismatch')
    account = next((a for a in plan['accounts'] if a['retailer_id'] == retailer_id), None)
    active_session = (account['signed_in'] if account else False) if signed_in is None else signed_in
    location = world['user_location'] if destination is None else destination
    location_keys = {'city_id', 'country', 'location_id', 'latitude', 'longitude',
                     'local_east_km', 'local_north_km'}
    if (not isinstance(location, dict) or not location_keys <= set(location) or
            any(not _text(location[k]) for k in ('city_id', 'country', 'location_id')) or
            any(type(location[k]) not in (int, float) or not math.isfinite(location[k])
                for k in ('latitude', 'longitude', 'local_east_km', 'local_north_km'))):
        raise ValueError('Destination must be a resolved native location')
    baseline = model.delivery_options(world, retailer, offer, destination=location)
    feedback = {'status': 'not_requested', 'reason': None, 'coupon_id': None, 'code': coupon_code}
    discount = 0
    if coupon_code is not None:
        coupon = next((c for c in (account['coupons'] if account else []) if c['code'] == coupon_code), None)
        reason = None
        if not active_session:
            reason = 'coupon_sign_in_required'
        elif coupon is None:
            reason = 'coupon_not_found'
        elif coupon['redeemed']:
            reason = 'coupon_already_redeemed'
        elif not _day(coupon['valid_from']) <= _day(world['quote_as_of']) <= _day(coupon['valid_until']):
            reason = 'coupon_not_active'
        elif coupon['concept_ids'] and product['public']['concept_id'] not in coupon['concept_ids']:
            reason = 'coupon_wrong_concept'
        elif offer['price_minor'] < coupon['minimum_subtotal_minor']:
            reason = 'coupon_minimum_not_met'
        elif not baseline:
            reason = 'coupon_requires_purchasable_quote'
        if reason:
            feedback.update(status='rejected', reason=reason)
        else:
            discount = (coupon['value'] if coupon['kind'] == 'fixed' else
                        (offer['price_minor'] * coupon['value'] + 50) // 100)
            discount = min(offer['price_minor'], discount)
            feedback.update(status='applied', coupon_id=coupon['coupon_id'])
    net = offer['price_minor'] - discount
    # The native helper owns distance/source/tier/waiver rules. Passing a copied
    # net-price offer changes only its threshold and total inputs, never the pin.
    options = (model.delivery_options(world, retailer, {**offer, 'price_minor': net},
                                     destination=location) if discount else baseline)
    for option in options:
        option.update(subtotal_minor=offer['price_minor'], discount_minor=discount,
                      merchandise_minor=net)
    binding = {'schema_version': VERSION, 'world_sha256': plan['world_sha256'],
               'plan_sha256': validation['plan_sha256'], 'retailer_id': retailer_id,
               'offer_id': offer_id, 'quantity': quantity, 'destination': location,
               'signed_in': active_session, 'coupon_code': coupon_code, 'options': options}
    return {'schema_version': VERSION, 'quote_id': model.digest(binding),
            'retailer_id': retailer_id, 'offer_id': offer_id,
            'product_id': offer['product_id'], 'sku_id': offer['sku_id'],
            'quantity': quantity, 'currency': 'SEK',
            'subtotal_minor': offer['price_minor'], 'discount_minor': discount,
            'merchandise_minor': net, 'coupon': feedback,
            'status': 'quoted' if options else 'unavailable', 'options': options}
