"""Approved bounded coverage/syndication projection; no reference or quote reads."""
from copy import deepcopy
from hashlib import sha256
import json
from math import isfinite
import random

VERSION = 'native-footwear-surrounding-v1'
PRICE_BASIS = 'minimum_listed_native_offer_snapshot'
DEFAULTS = {'enabled': True, 'comparison_count': 2, 'review_count': 1,
            'model_probability': .8, 'retailer_pair_probability': .7,
            'comparison_layout_weights': {'directory': 1, 'ledger': 1},
            'review_layout_weights': {'journal': 1, 'community': 1}}


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def options(value=None):
    value = {} if value is None else value
    if not isinstance(value, dict) or set(value) - {*DEFAULTS, 'coverage_seed'}:
        raise ValueError('Unknown surrounding-site control')
    result = {**deepcopy(DEFAULTS), **deepcopy(value)}
    if type(result['enabled']) is not bool:
        raise ValueError('enabled must be boolean')
    for field, maximum in (('comparison_count', 8), ('review_count', 4)):
        if type(result[field]) is not int or not 0 <= result[field] <= maximum:
            raise ValueError('Invalid surrounding-site count: ' + field)
    for field in ('model_probability', 'retailer_pair_probability'):
        p = result[field]
        if type(p) not in (int, float) or not isfinite(p) or not 0 <= p <= 1:
            raise ValueError('Invalid coverage probability: ' + field)
    for field in ('comparison_layout_weights', 'review_layout_weights'):
        weights = result[field]
        if not isinstance(weights, dict) or set(weights) != set(DEFAULTS[field]):
            raise ValueError('Declare the full layout domain: ' + field)
        if any(type(w) not in (int, float) or not isfinite(w) or w < 0 for w in weights.values()) or not sum(weights.values()):
            raise ValueError('Invalid layout weights')
        result[field] = {k: weights[k] for k in DEFAULTS[field]}
    if 'coverage_seed' in result and (type(result['coverage_seed']) is not int or not 0 <= result['coverage_seed'] < 2**31):
        raise ValueError('Invalid coverage seed')
    return result


def draw(seed, *identity):
    return random.Random(int(digest([VERSION, seed, *identity]), 16)).random()


def layout(seed, sid, weights):
    value = draw(seed, sid, 'layout') * sum(weights.values())
    for key, weight in weights.items():
        value -= weight
        if value < 0:
            return key
    raise ArithmeticError('Invalid layout draw')


def generate(world, controls=None):
    return _generate_bound(world, controls, digest(world))


def _generate_bound(world, controls, world_sha256):
    """Internal reuse of a binding computed during this generation call."""
    controls = options(controls)
    seed = controls.get('coverage_seed', world['seed'])
    products = {p['public']['product_id']: p for p in world['products']}
    eligible = {}
    for r in world['retailers']:
        for offer in r['offers']:
            eligible.setdefault((offer['product_id'], r['retailer_id']), []).append(offer)
    sites, provenance = [], {}
    if controls['enabled']:
        for index in range(controls['comparison_count']):
            sid = f'comparison-{index:02d}'
            tracked = [pid for pid in sorted(products)
                       if draw(seed, sid, pid, 'model') < controls['model_probability']]
            pairs = [pair for pair in sorted(eligible) if pair[0] in tracked and
                     draw(seed, sid, *pair, 'pair') < controls['retailer_pair_probability']]
            listings = []
            for pid, rid in pairs:
                offers = sorted(eligible[(pid, rid)], key=lambda o: (o['price_minor'], o['offer_id']))
                minimum = offers[0]['price_minor']
                listings.append({'product_id': pid, 'retailer_id': rid, 'price_minor': minimum,
                    'currency': offers[0]['currency'], 'price_basis': PRICE_BASIS,
                    'entry_offer_id': offers[0]['offer_id']})
                provenance[f'{sid}/{pid}/{rid}'] = {
                    'source_offer_ids': sorted(o['offer_id'] for o in offers),
                    'minimum_offer_ids': sorted(o['offer_id'] for o in offers if o['price_minor'] == minimum)}
            # Membership is settled before the separately keyed layout draw.
            sites.append({'site_id': sid, 'kind': 'aggregator', 'name': ('Prislyktan' if index == 0 else f'Prisradar {index}'),
                          'product_ids': tracked, 'listings': listings,
                          'layout': layout(world['seed'], sid, controls['comparison_layout_weights']),
                          'price_basis': PRICE_BASIS, 'as_of': world['quote_as_of']})
        for index in range(controls['review_count']):
            sid = f'product-reviews-{index:02d}'
            sites.append({'site_id': sid, 'kind': 'product_reviews', 'name': ('Footnote Review' if index == 0 else f'Footwear Reader {index}'),
                          'product_ids': sorted(products),
                          'layout': layout(world['seed'], sid, controls['review_layout_weights']),
                          'corpus_authority': 'syndicated_native_customer_reviews'})
    return {'schema_version': VERSION, 'source_world_id': world['world_id'],
            'source_world_sha256': world_sha256, 'coverage_seed': seed,
            'controls': controls, 'sites': sites, 'provenance_private': provenance}


def public_products(world):
    """Allowlist public facts, original comments and explicitly promoted guidance."""
    result = {}
    for p in world['products']:
        public = p['public']
        pid = public['product_id']
        reviews, seen = [], set()
        for review in p['reviews']:
            if review['review_id'] in seen:
                continue
            seen.add(review['review_id'])
            reviews.append({k: deepcopy(review[k]) for k in
                            ('review_id', 'reviewer', 'product_id', 'sku_id', 'rating', 'text')})
        result[pid] = {'product_id': pid, 'name': public['name'], 'brand_id': public['brand_id'],
                       'facts': deepcopy(public['facts']),
                       'fact_status': deepcopy(public.get('fact_status',{})), 'skus': deepcopy(public['skus']),
                       'reviews': reviews, 'rating_summary': deepcopy(p['rating_summary']),
                       'guidance': deepcopy(p['review_overview'])}
    return result


def validate(world, sidecar):
    if sidecar.get('schema_version') != VERSION or sidecar.get('source_world_id') != world['world_id'] or sidecar.get('source_world_sha256') != digest(world):
        raise ValueError('Surrounding sidecar belongs to another world')
    if sidecar != generate(world, sidecar['controls']):
        raise ValueError('Surrounding sidecar does not replay from its controls')
    return sidecar
