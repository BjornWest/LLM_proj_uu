"""Pinned, public checkout limits shared by renderer, API and exact references."""
from copy import deepcopy

from experiments.footwear_world_pilot import model

VERSION = 'website-native-checkout-domain-v1'
DEFAULTS = {'max_quantity_per_offer': 20, 'max_lines_per_order': 64}


def options(value=None):
    if value is not None and (type(value) is not dict or set(value) - set(DEFAULTS)):
        raise ValueError('Checkout domain accepts quantity and line limits only')
    result = {**DEFAULTS, **(value or {})}
    if (type(result['max_quantity_per_offer']) is not int or not 1 <= result['max_quantity_per_offer'] <= 1000000 or
            type(result['max_lines_per_order']) is not int or not 1 <= result['max_lines_per_order'] <= 64):
        raise ValueError('Declare quantity1..1000000 and line1..64 checkout limits')
    return result


def make(world, value=None):
    config = options(value)
    limits = {o['offer_id']: config['max_quantity_per_offer']
              for r in world['retailers'] for o in r['offers']}
    # Browser projections use JSON numeric minor units. Reject unsupported money
    # magnitudes rather than losing cents in a differently bounded UI domain.
    amounts = sorted((o['price_minor'] * limits[o['offer_id']]
                      for r in world['retailers'] for o in r['offers']), reverse=True)
    if sum(amounts[:config['max_lines_per_order']]) > (2**53 - 1) // 4:
        raise ValueError('Checkout domain exceeds supported exact browser monetary magnitudes')
    return {'schema_version': VERSION, 'world_id': world['world_id'],
            'world_sha256': model.digest(world), 'origin': 'explicit_shared_checkout_domain',
            'options': config, 'quantity_limits': limits}


def validate(world, domain):
    if type(domain) is not dict or set(domain) != {
            'schema_version', 'world_id', 'world_sha256', 'origin', 'options', 'quantity_limits'}:
        raise ValueError('Invalid checkout domain')
    expected = make(world, domain['options'])
    if domain != expected:
        raise ValueError('Checkout domain/world binding or limits changed')
    return model.digest(domain)


def public(world, domain, retailer_id):
    identifier = validate(world, domain)
    retailer = next(r for r in world['retailers'] if r['retailer_id'] == retailer_id)
    return {'id': identifier, 'monetaryLineId': 'offer_id',
            'maxLinesPerOrder': domain['options']['max_lines_per_order'],
            'quantityLimits': {o['offer_id']: domain['quantity_limits'][o['offer_id']] for o in retailer['offers']}}


def canonical_lines(world, domain, retailer_id, lines):
    """Merge exact-SKU additions; caller UI IDs cannot affect monetary rounding."""
    validate(world, domain)
    retailer = next(r for r in world['retailers'] if r['retailer_id'] == retailer_id)
    allowed = {o['offer_id'] for o in retailer['offers']}
    if type(lines) is not list or not 1 <= len(lines) <= 64:
        raise ValueError('Supply1..64 input cart rows')
    quantities, aliases = {}, {}
    for line in lines:
        if type(line) is not dict or set(line) != {'line_id', 'offer_id', 'quantity'}:
            raise ValueError('Invalid cart row')
        lid, oid, q = line['line_id'], line['offer_id'], line['quantity']
        if (type(lid) is not str or not lid or type(oid) is not str or oid not in allowed or
                type(q) is not int or q < 1):
            raise ValueError('Invalid cart identity or quantity')
        if lid in aliases and aliases[lid] != oid:
            raise ValueError('UI line identity aliases two different offers')
        aliases[lid] = oid
        quantities[oid] = quantities.get(oid, 0) + q
    if (len(quantities) > domain['options']['max_lines_per_order'] or
            any(q > domain['quantity_limits'][oid] for oid, q in quantities.items())):
        raise ValueError('Cart exceeds the declared shared checkout domain')
    return [{'line_id': o, 'offer_id': o, 'quantity': q} for o, q in sorted(quantities.items())], aliases


def canonical_selections(selections, aliases):
    if selections is None:
        return None
    result = {}
    for lid, cid in selections.items():
        oid = aliases.get(lid, lid)
        if oid in result and result[oid] != cid:
            # Producer invalidation will reset the selection rather than quietly
            # committing one of two services for a repeated exact SKU.
            return {'conflicting_duplicate_selection': 'invalid'}
        result[oid] = cid
    return deepcopy(result)
