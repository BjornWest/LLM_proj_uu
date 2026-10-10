"""Opt-in, persistent retailer delivery menus over unchanged native quote bodies.

Admission precedes stock, price and basket feasibility. No global rebinding,
renderer-side truncation, stock repair or changes to the historical basket plans.
"""
from copy import deepcopy
import math
from types import FunctionType

from experiments.footwear_world_pilot import basket_quote as native, model
from . import basket_quote as catalog

VERSION = 'retailer-delivery-admission-quote-v1'
PLAN_VERSION = 'retailer-delivery-admission-plan-v1'
DEFAULT_COUNT_WEIGHTS = {
    1: 50, 2: 180, 3: 220, 4: 200, 5: 130, 6: 100, 7: 40,
    8: 25, 9: 20, 10: 15, 11: 4, 12: 4, 13: 3, 14: 3, 15: 3, 16: 3,
}


def _require(ok, message):
    if not ok:
        raise ValueError(message)


def _backend(world):
    schema = world.get('schema_version') if type(world) is dict else None
    if schema == 'accepted-catalog-commerce-world-v1':
        return catalog
    if schema == native.model.VERSION:
        return native
    raise ValueError('Unsupported delivery admission world')


def route_key(choice):
    """Home identity survives address edits; collection identities stay distinct."""
    if choice['destination_type'] == 'retailer_branch':
        identity = {'branch_id': choice['branch_id']}
    else:
        identity = {key: choice[key] for key in
                    ('carrier_id', 'tier', 'destination_type', 'point_id')}
    return 'route/' + model.digest(identity)


def _potential(backend, world, retailer, policy, destination):
    choices = backend._choices(world, retailer, policy, destination)
    services = {(s['carrier_id'], s['shipping_class'])
                for s in world['address_context']['services']}
    countries = retailer['geography']['fulfilment_policy']['delivery_countries']
    terms = {t['carrier_id']: t for t in policy['carrier_terms']}
    output = []
    for choice in choices:
        if choice['destination_type'] == 'retailer_branch':
            output.append(choice)
            continue
        cid = choice['carrier_id']
        supported = ((cid, 'regular') in services or
                     choice['destination_type'] == 'home' and
                     terms[cid]['bulky_supported'] and (cid, 'bulky') in services)
        if supported and choice['destination']['country'] in countries and any(
            source['shipping_enabled'] and
            model.travel(source['location'], choice['destination'])['status'] == 'estimated'
            for source in retailer['source_locations']
        ):
            output.append(choice)
    _require(len({route_key(c) for c in output}) == len(output),
             'Duplicate canonical delivery route')
    return output


def enumerate_routes(world, basket_plan, retailer_id, *, destination=None):
    """Return real source/geographic capabilities without conditioning on stock."""
    backend = _backend(world)
    backend.validate_plan(world, basket_plan)
    retailers, _ = backend._world(world)
    _require(retailer_id in retailers, 'Unknown delivery retailer')
    location = world['user_location'] if destination is None else backend._location(destination)
    _require(backend._within_region(world, location), 'Unsupported initial address region')
    policy = next(p for p in basket_plan['retailer_policies'] if p['retailer_id'] == retailer_id)
    return [{**backend._public_choice(c), 'route_key': route_key(c)} for c in
            _potential(backend, world, retailers[retailer_id], policy, location)]


def _weights(value):
    _require(type(value) is dict and bool(value), 'Count weights must be a nonempty mapping')
    _require(all(type(k) is int and 1 <= k <= 10000 and
                 type(v) in (int, float) and math.isfinite(v) and v >= 0
                 for k, v in value.items()), 'Invalid finite count weights')
    total = sum(value.values())
    _require(math.isfinite(total) and total > 0, 'Count weights need positive finite mass')
    return [{'count': k, 'weight': v} for k, v in sorted(value.items())]


def _rank(seed, world_id, retailer_id, stage, key):
    return model.digest({'seed': seed, 'world_id': world_id, 'retailer_id': retailer_id,
                         'stage': stage, 'key': key})


def _count(weights, bound, seed, world_id, rid):
    if bound == 0:
        return 0
    rows = [r for r in weights if r['count'] <= bound and r['weight'] > 0]
    _require(bool(rows), 'No positive count mass within the real route bound')
    draw = int(_rank(seed, world_id, rid, 'count', None), 16) / 2**256
    target = draw * sum(r['weight'] for r in rows)
    for row in rows:
        target -= row['weight']
        if target < 0:
            return row['count']
    return rows[-1]['count']


def _rows(backend, world, basket_plan, seed, weights, counts, destination):
    retailers, products = backend._world(world)
    _require(type(counts) is dict and set(counts) <= set(retailers),
             'Count overrides must name known retailers')
    rows = []
    for policy in sorted(basket_plan['retailer_policies'], key=lambda p: p['retailer_id']):
        rid = policy['retailer_id']; retailer = retailers[rid]
        choices = _potential(backend, world, retailer, policy, destination)
        count = (counts[rid] if rid in counts else
                 _count(weights, len(choices), seed, world['world_id'], rid))
        _require(type(count) is int and (1 <= count <= len(choices) if choices else count == 0),
                 'Retailer count must fit the real initial route universe')
        keys = sorted(route_key(c) for c in choices)
        bulky = any(products[o['product_id']]['facts']['shipping_class'] == 'bulky'
                    for o in retailer['offers'])
        terms = {t['carrier_id']: t for t in policy['carrier_terms']}
        homes = [route_key(c) for c in choices if c['destination_type'] == 'home' and
                 (not bulky or terms[c['carrier_id']]['bulky_supported'])]
        anchor = min(homes, key=lambda k: _rank(seed, world['world_id'], rid, 'home', k)) if homes else None
        ordered = sorted(keys, key=lambda k: _rank(seed, world['world_id'], rid, 'membership', k))
        selected = ([anchor] if anchor else []) + [k for k in ordered if k != anchor]
        rows.append({'retailer_id': rid, 'initial_route_keys': keys,
                     'sampled_count': count, 'admitted_route_keys': sorted(selected[:count]),
                     'home_anchor_key': anchor})
    return rows


def make_plan(world, basket_plan, *, seed, count_weights=None, retailer_counts=None,
              destination=None):
    """Sample once per retailer; optional exact count fixtures never force stock."""
    backend = _backend(world)
    backend.validate_plan(world, basket_plan)
    _require(type(seed) is int and seed >= 0, 'Delivery seed must be a nonnegative integer')
    weights = _weights(DEFAULT_COUNT_WEIGHTS if count_weights is None else count_weights)
    counts = {} if retailer_counts is None else deepcopy(retailer_counts)
    location = deepcopy(world['user_location'] if destination is None else backend._location(destination))
    _require(backend._within_region(world, location), 'Unsupported initial address region')
    return {'schema_version': PLAN_VERSION, 'world_id': world['world_id'],
            'world_sha256': model.digest(world), 'basket_plan_sha256': model.digest(basket_plan),
            'seed': seed, 'initial_destination': location, 'count_weights': weights,
            'retailer_counts': counts,
            'retailers': _rows(backend, world, basket_plan, seed, weights, counts, location)}


def validate_plan(world, basket_plan, admission_plan):
    backend = _backend(world)
    backend.validate_plan(world, basket_plan)
    _require(type(admission_plan) is dict and set(admission_plan) == {
        'schema_version', 'world_id', 'world_sha256', 'basket_plan_sha256', 'seed',
        'initial_destination', 'count_weights', 'retailer_counts', 'retailers'},
        'Invalid delivery admission plan shape')
    _require(admission_plan['schema_version'] == PLAN_VERSION and
             admission_plan['world_id'] == world['world_id'] and
             admission_plan['world_sha256'] == model.digest(world) and
             admission_plan['basket_plan_sha256'] == model.digest(basket_plan),
             'Stale delivery admission world/basket binding')
    _require(type(admission_plan['seed']) is int and admission_plan['seed'] >= 0,
             'Invalid delivery seed')
    weights = admission_plan['count_weights']
    _require(type(weights) is list and all(type(r) is dict and set(r) == {'count', 'weight'}
                                          for r in weights), 'Invalid count weight rows')
    normalized = _weights({r['count']: r['weight'] for r in weights})
    _require(normalized == weights, 'Duplicate or noncanonical count weight rows')
    location = backend._location(admission_plan['initial_destination'])
    _require(backend._within_region(world, location), 'Unsupported initial address region')
    expected = _rows(backend, world, basket_plan, admission_plan['seed'], normalized,
                     admission_plan['retailer_counts'], location)
    _require(type(admission_plan['retailers']) is list and all(
        type(r) is dict and type(r.get('sampled_count')) is int
        for r in admission_plan['retailers']), 'Invalid retailer count rows')
    _require(admission_plan['retailers'] == expected, 'Invalid admitted routes/count/home coverage')
    return {'valid': True, 'plan_sha256': model.digest(admission_plan)}


class Oracle:
    """Existing basket oracle protocol, bound to a privately isolated route plan."""
    VERSION = VERSION

    def __init__(self, world, basket_plan, admission_plan):
        validation = validate_plan(world, basket_plan, admission_plan)
        self._backend = _backend(world)
        self._admission = deepcopy(admission_plan)
        self._digest = validation['plan_sha256']
        self._menus = {r['retailer_id']: frozenset(r['admitted_route_keys'])
                       for r in self._admission['retailers']}

    def validate_plan(self, world, plan):
        base = self._backend.validate_plan(world, plan)
        _require(plan['world_sha256'] == self._admission['world_sha256'] and
                 base['plan_sha256'] == self._admission['basket_plan_sha256'],
                 'Stale delivery admission world/basket binding')
        return {'valid': True, 'plan_sha256': model.digest({
            'basket_plan_sha256': base['plan_sha256'], 'admission_plan_sha256': self._digest})}

    def public_policy(self, plan, retailer_id):
        policy = self._backend.public_policy(plan, retailer_id)
        row = next((r for r in self._admission['retailers'] if r['retailer_id'] == retailer_id), None)
        _require(row is not None, 'Unknown delivery retailer')
        return {**policy, 'natural_choice_count_sampling': retailer_id not in self._admission['retailer_counts'],
                'delivery_admission': {'schema_version': PLAN_VERSION,
                    'plan_sha256': self._digest, 'sampled_count': row['sampled_count'],
                    'initial_route_count': len(row['initial_route_keys']),
                    'fixed_menu': True, 'home_coverage': row['home_anchor_key'] is not None}}

    def quote(self, world, retailer_id, lines, *, plan, **kwargs):
        # Each callable has private globals; unchanged formula helpers still use
        # their original globals. Only entry validation, route admission and the
        # version/public-policy envelope differ.
        def choices(w, retailer, policy, destination):
            return [c for c in self._backend._choices(w, retailer, policy, destination)
                    if route_key(c) in self._menus[retailer['retailer_id']]]
        original = self._backend.quote
        namespace = {**original.__globals__, 'VERSION': VERSION,
                     'validate_plan': self.validate_plan, '_choices': choices,
                     'public_policy': self.public_policy}
        call = FunctionType(original.__code__, namespace, original.__name__,
                            original.__defaults__, original.__closure__)
        call.__kwdefaults__ = original.__kwdefaults__
        result = call(world, retailer_id, lines, plan=plan, **kwargs)
        result['basket_plan_sha256'] = self._admission['basket_plan_sha256']
        result['admission_plan_sha256'] = self._digest
        result['limitations'] += ['Persistent admitted menu; no refill or basket-feasibility repair.']
        return result


def quote(world, retailer_id, lines, *, plan, admission_plan, **kwargs):
    return Oracle(world, plan, admission_plan).quote(world, retailer_id, lines, plan=plan, **kwargs)
