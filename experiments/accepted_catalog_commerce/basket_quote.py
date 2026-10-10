"""Versioned central basket formula for accepted-catalog commerce.

Derived from the accepted native basket source; monetary/source/route formulas
are unchanged. Only the world/plan envelope and explicit commerce metadata differ.
No renderer implements family-specific shipping arithmetic.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from datetime import date, timedelta
import math

from experiments.footwear_world_pilot import coupon_quote, model

VERSION = 'accepted-catalog-basket-quote-v1'
PLAN_VERSION = 'accepted-catalog-basket-plan-v1'
POLICY_KEYS = {'retailer_id', 'dispatch_policy', 'consolidate_sources',
               'optional_split', 'mixed_destinations', 'qualification_scope',
               'bulky_treatment', 'membership_active', 'carrier_terms'}
TERM_KEYS = {'carrier_id', 'bulky_supported', 'bulky_surcharge_minor',
             'bulky_extra_days', 'arrival_window_days'}
LOCATION_KEYS = {'city_id', 'country', 'location_id', 'latitude', 'longitude',
                 'local_east_km', 'local_north_km'}


def _int(value, minimum=0):
    return type(value) is int and value >= minimum


def _text(value):
    return type(value) is str and bool(value.strip()) and len(value) <= 500


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _location(value):
    _require(type(value) is dict and LOCATION_KEYS <= set(value),
             'Destination must be a resolved native location')
    _require(all(_text(value[k]) for k in ('city_id', 'country', 'location_id')),
             'Destination identity is invalid')
    _require(all(type(value[k]) in (int, float) and math.isfinite(value[k])
                 for k in ('latitude', 'longitude', 'local_east_km', 'local_north_km')),
             'Destination coordinates must be finite numbers')
    return value


def _world(world):
    _require(type(world) is dict and world.get('schema_version') == 'accepted-catalog-commerce-world-v1',
             'Expected the source-bound accepted-catalog commerce envelope')
    _require(_text(world.get('world_id')), 'World identity is missing')
    date.fromisoformat(world['quote_as_of'])
    _location(world['user_location'])
    retailers = {r['retailer_id']: r for r in world['retailers']}
    products = {p['public']['product_id']: p['public'] for p in world['products']}
    _require(len(retailers) == len(world['retailers']) and
             len(products) == len(world['products']), 'Duplicate retailer/product identity')
    # Shipping is explicitly classified by the commerce producer. A transient
    # internal view feeds the unchanged formulas; manufacturer facts stay intact.
    products = {pid: deepcopy(product) for pid, product in products.items()}
    classifications = {p['public']['product_id']: p['commerce'] for p in world['products']}
    for pid, product in products.items():
        classification = classifications[pid]
        _require(classification.get('classification_basis') == 'closed_ordinary_parcel_concept_slice_v1'
                 and classification.get('shipping_class') == 'regular',
                 'Unsupported commerce freight classification')
        _require('shipping_class' not in product['facts'] or
                 product['facts']['shipping_class'] == classification['shipping_class'],
                 'Commerce shipping class conflicts with manufacturer declaration')
        product['facts'] = {**product['facts'], 'shipping_class': classification['shipping_class']}
    for product in products.values():
        from .package_export import SUPPORTED_CONCEPTS
        _require(product['concept_id'] in SUPPORTED_CONCEPTS, 'Concept is outside the adopted commerce slice')
        _require(product['facts'].get('shipping_class') in ('regular', 'bulky'),
                 'Manufactured product requires explicit regular/bulky shipping class')
        _require(_text(product.get('brand_id')) and _text(product.get('concept_id')),
                 'Manufactured brand/concept identity is missing')
        _require(len({s['sku_id'] for s in product['skus']}) == len(product['skus']),
                 'Duplicate manufactured SKU identity')
    return retailers, products


def make_plan(world, *, retailer_policies=None):
    """Bind explicit policy rows; omitted rows use documented regular defaults.

    Defaults preserve threshold values and existing carrier contracts, use
    lowest-tariff/then-ready dispatch, and do not activate optional split, mixed
    destinations, membership or bulky freight. This is not natural policy sampling.
    """
    retailers, products = _world(world)
    supplied = {} if retailer_policies is None else deepcopy(retailer_policies)
    _require(type(supplied) is dict and set(supplied) <= set(retailers),
             'Policy overrides must map known retailer IDs to declared policy fields')
    policies = []
    for rid, retailer in retailers.items():
        override = supplied.get(rid, {})
        _require(type(override) is dict and set(override) <= POLICY_KEYS - {'retailer_id'},
                 'Unknown retailer policy override')
        policy = {'retailer_id': rid, 'dispatch_policy': 'lowest_tariff_then_ready',
                  'consolidate_sources': True, 'optional_split': False,
                  'mixed_destinations': False, 'qualification_scope': 'checkout',
                  'bulky_treatment': 'exclude_bulky', 'membership_active': False,
                  'carrier_terms': [
                      {'carrier_id': c['carrier_id'], 'bulky_supported': False,
                       'bulky_surcharge_minor': 0, 'bulky_extra_days': 0,
                       'arrival_window_days': 0} for c in retailer['contracts']]}
        policy.update(override)
        policies.append(policy)
    plan = {'schema_version': PLAN_VERSION, 'world_id': world['world_id'],
            'world_sha256': model.digest(world), 'origin': 'explicit_policy_fixture',
            'retailer_policies': policies}
    # Nothing between preparation and validation mutates the supplied world.
    # Reuse only these local records/hash; public validation stays independent.
    _validate_plan(world, plan, retailers, products, world_sha256=plan['world_sha256'])
    return plan


def validate_plan(world, plan):
    retailers, products = _world(world)
    return _validate_plan(world, plan, retailers, products)


def _validate_plan(world, plan, retailers, products, *, world_sha256=None):
    """Shared policy checks; a precomputed binding is private to construction."""
    _require(type(plan) is dict and set(plan) == {
        'schema_version', 'world_id', 'world_sha256', 'origin', 'retailer_policies'},
        'Invalid basket plan shape')
    _require(plan['schema_version'] == PLAN_VERSION and
             plan['world_id'] == world['world_id'] and
             plan['world_sha256'] == (model.digest(world) if world_sha256 is None else world_sha256),
             'Stale basket plan/world binding')
    _require(plan['origin'] == 'explicit_policy_fixture', 'Unsupported policy provenance')
    _require(type(plan['retailer_policies']) is list, 'Policies must be a list')
    seen = set()
    carrier_windows, bulky_transit = {}, {}
    services = {(s['carrier_id'], s['shipping_class']) for s in world['address_context']['services']}
    for policy in plan['retailer_policies']:
        _require(type(policy) is dict and set(policy) == POLICY_KEYS, 'Invalid policy shape')
        rid = policy['retailer_id']
        _require(rid in retailers and rid not in seen, 'Unknown/duplicate policy retailer')
        seen.add(rid)
        for key in ('consolidate_sources', 'optional_split', 'mixed_destinations', 'membership_active'):
            _require(type(policy[key]) is bool, 'Policy flags must be boolean: ' + key)
        _require(not policy['mixed_destinations'] or policy['optional_split'],
                 'Mixed destinations require optional split capability')
        _require(policy['dispatch_policy'] in ('lowest_tariff_then_ready', 'earliest_ready_then_tariff'),
                 'Unsupported deterministic dispatch policy')
        _require(policy['qualification_scope'] in ('checkout', 'shipment'), 'Invalid qualification scope')
        _require(policy['bulky_treatment'] in ('waive_all', 'waive_base_only', 'exclude_bulky'),
                 'Invalid bulky promotion treatment')
        retailer = retailers[rid]
        _require(retailer['free_shipping_threshold_minor'] is None or
                 _int(retailer['free_shipping_threshold_minor']), 'Invalid shipping threshold')
        contract_ids = [c['carrier_id'] for c in retailer['contracts']]
        _require(len(set(contract_ids)) == len(contract_ids), 'Duplicate carrier contract')
        terms = policy['carrier_terms']
        _require(type(terms) is list and len(terms) == len(contract_ids), 'One term row per actual contract required')
        _require(all(type(t) is dict and set(t) == TERM_KEYS for t in terms), 'Invalid carrier term shape')
        _require(len({t['carrier_id'] for t in terms}) == len(terms) and
                 {t['carrier_id'] for t in terms} == set(contract_ids), 'Term/contract identities differ')
        for term in terms:
            _require(type(term['bulky_supported']) is bool and all(
                _int(term[k]) for k in ('bulky_surcharge_minor', 'bulky_extra_days', 'arrival_window_days')),
                'Invalid class fee/time terms')
            cid = term['carrier_id']
            _require(cid not in carrier_windows or carrier_windows[cid] == term['arrival_window_days'],
                     'Carrier arrival-window terms must be consistent across retailers')
            carrier_windows[cid] = term['arrival_window_days']
            if term['bulky_supported']:
                _require(cid not in bulky_transit or bulky_transit[cid] == term['bulky_extra_days'],
                         'Carrier bulky transit terms must be consistent across retailers')
                bulky_transit[cid] = term['bulky_extra_days']
            _require(not term['bulky_supported'] or (term['carrier_id'], 'bulky') in services,
                     'Bulky capability requires an actual carrier service')
        listed = set()
        source_ids = {s['source_id'] for s in retailer['source_locations']}
        _require(len(source_ids) == len(retailer['source_locations']), 'Duplicate source identity')
        _require(all(s['kind'] in ('warehouse', 'branch') and
                     type(s['shipping_enabled']) is bool and _int(s['dispatch_days'])
                     for s in retailer['source_locations']), 'Invalid source capability/dispatch')
        _require(retailer['source_locations'] and retailer['source_locations'][0]['kind'] == 'warehouse',
                 'Native primary warehouse must be explicit')
        bulky = False
        for offer in retailer['offers']:
            _require(_text(offer['offer_id']) and offer['offer_id'] not in listed, 'Duplicate/invalid offer ID')
            listed.add(offer['offer_id'])
            _require(offer['product_id'] in products, 'Listed product is not manufactured')
            product = products[offer['product_id']]
            _require(any(s['sku_id'] == offer['sku_id'] and s['product_id'] == offer['product_id']
                         for s in product['skus']), 'Listed SKU is not manufactured')
            _require(offer['currency'] == 'SEK' and _int(offer['price_minor']), 'Unsupported currency/price')
            _require(type(offer['stock_by_source']) is dict and set(offer['stock_by_source']) == source_ids
                     and all(_int(q) for q in offer['stock_by_source'].values()), 'Invalid complete source stock')
            supplier = offer['supplier_order']
            _require(type(supplier['enabled']) is bool and
                     (supplier['wait_days'] is None or _int(supplier['wait_days'])), 'Invalid supplier timing')
            bulky |= product['facts']['shipping_class'] == 'bulky'
        if bulky:
            carriers = {c['carrier_id']: c for c in world['address_context']['carriers']}
            _require(any(t['bulky_supported'] and carriers[t['carrier_id']]['home_delivery']
                         for t in terms), 'Every bulky-selling retailer needs actual bulky-home capability')
    _require(seen == set(retailers), 'Complete retailer policy coverage required')
    return {'valid': True, 'plan_sha256': model.digest(plan)}


def public_policy(plan, retailer_id):
    policy = next((p for p in plan['retailer_policies'] if p['retailer_id'] == retailer_id), None)
    _require(policy is not None, 'Unknown policy retailer')
    return {**deepcopy(policy), 'charged_branch_transfers': 'unsupported_pending_fee_aggregation_decision',
            'branch_transfer_fee': 'retailer_absorbed',
            'stock_pooling': False, 'quantity_source_splitting': False,
            'natural_policy_sampling': False, 'natural_choice_count_sampling': False}


def _within_region(world, destination):
    region = world['address_context']['region']; centre = region['centre']
    return (destination['city_id'] == centre['city_id'] and destination['country'] == centre['country']
            and math.hypot(destination['local_east_km'] - centre['local_east_km'],
                           destination['local_north_km'] - centre['local_north_km']) <= region['radius_km'])


def _choices(world, retailer, policy, destination):
    context = world['address_context']
    carriers = {c['carrier_id']: c for c in context['carriers']}
    points = {p['point_id']: p for p in context['collection_points']}
    choices = []
    for contract in retailer['contracts']:
        cid = contract['carrier_id']; carrier = carriers[cid]
        targets = [('home', destination, None)] if carrier['home_delivery'] else []
        for pid in carrier['collection_point_ids']:
            point = points[pid]; target = point['location']
            if (target['country'] == destination['country'] and target['city_id'] == destination['city_id']
                    and math.hypot(target['local_east_km'] - destination['local_east_km'],
                                   target['local_north_km'] - destination['local_north_km']) <= 3):
                targets.append((point['type'], target, point))
        for tier in contract['tiers']:
            for kind, target, point in targets:
                identity = {'carrier_id': cid, 'tier': tier, 'destination_type': kind,
                            'point_id': point['point_id'] if point else None,
                            'destination': target}
                choices.append({**identity, 'choice_id': 'delivery/' + model.digest(identity),
                                'carrier_name': carrier['name'], 'contract': contract,
                                'collection_hours': point['weekly_hours'] if point else None})
    for branch in retailer['geography']['branches']:
        if branch['pickup_enabled']:
            identity = {'branch_id': branch['branch_id'], 'destination': branch['location']}
            choices.append({**identity, 'choice_id': 'branch/' + model.digest(identity),
                            'carrier_id': None, 'carrier_name': None, 'tier': None,
                            'destination_type': 'retailer_branch', 'point_id': None,
                            'collection_hours': deepcopy(branch.get('weekly_hours')),
                            'branch_name': branch['name']})
    _require(len({c['choice_id'] for c in choices}) == len(choices), 'Duplicate service/destination choice')
    return choices


def _arrival(world, days, width=0):
    if days is None:
        return {'status': 'unknown', 'earliest_date': None, 'latest_date': None}
    start = date.fromisoformat(world['quote_as_of']) + timedelta(days=days)
    return {'status': 'estimated', 'earliest_date': start.isoformat(),
            'latest_date': (start + timedelta(days=width)).isoformat()}


def _carrier_candidates(world, retailer, policy, product, offer, quantity, choice):
    if choice['destination']['country'] not in retailer['geography']['fulfilment_policy']['delivery_countries']:
        return []
    kind = product['facts']['shipping_class']
    term = next(t for t in policy['carrier_terms'] if t['carrier_id'] == choice['carrier_id'])
    if kind == 'bulky' and (not term['bulky_supported'] or choice['destination_type'] != 'home'):
        return []
    service = next(s for s in world['address_context']['services']
                   if s['carrier_id'] == choice['carrier_id'] and s['shipping_class'] == kind)
    sources = [(s, 0, 'on_hand') for s in retailer['source_locations']
               if s['shipping_enabled'] and offer['stock_by_source'][s['source_id']] >= quantity]
    if (not sources and offer['supplier_order']['enabled']
            and retailer['source_locations'][0]['shipping_enabled']):
        sources = [(retailer['source_locations'][0], offer['supplier_order']['wait_days'], 'supplier_order')]
    out = []
    proposals = world['shipping_policy']; contract = choice['contract']; tier = choice['tier']
    relation = proposals['service_relations'][tier]
    for source, wait, supply in sources:
        route = model.travel(source['location'], choice['destination'])
        if route['status'] != 'estimated':
            continue
        distance = proposals['distance_surcharge']; supplement = proposals['geographic_supplements']
        distance_fee = math.ceil(max(0, route['distance_km'] - distance['first_km_included']) / 500) * distance['each_additional_commenced_500km_minor']
        foreign = source['location']['country'] != choice['destination']['country']
        geography = ((supplement['cross_border_minor'] if foreign else 0) +
                     (supplement['non_air_crossing_minor'] if any(k != 'air_cargo' for k in route['crossing_kinds']) else 0) +
                     (supplement['air_cargo_minor'] if 'air_cargo' in route['crossing_kinds'] else 0))
        relative = relation['base_fee_relative_to_standard_minor']
        collection = contract['collection_fee_minor'] + min(0, relative)
        if tier == 'economy':
            collection = max(relation['minimum_base_fee_minor'], collection)
        ordinary = max(0, collection + (contract['home_delta_minor'] if choice['destination_type'] == 'home' else 0))
        components = {'ordinary_minor': ordinary, 'distance_minor': distance_fee,
                      'geographic_minor': geography, 'express_minor': max(0, relative),
                      'bulky_minor': term['bulky_surcharge_minor'] if kind == 'bulky' else 0,
                      'transfer_minor': 0}
        travel_days = model.transit(source['location'], choice['destination'], service['transit_offset_days'], tier)
        ready = None if wait is None else wait + source['dispatch_days'] + travel_days + (term['bulky_extra_days'] if kind == 'bulky' else 0)
        out.append({'source_id': source['source_id'], 'source_kind': source['kind'],
                    'supply': supply, 'supplier_wait_days': wait, 'requires_transfer': False,
                    'service_id': service['service_id'], 'shipping_class': kind,
                    'scheduling': service['scheduling'], 'route': route,
                    'ready_days': ready, 'arrival': _arrival(world, ready, term['arrival_window_days']),
                    'foreign': foreign, 'tariff_components': components,
                    'raw_shipping_minor': sum(components.values())})
    return out


def _branch_candidates(world, retailer, product, offer, quantity, choice):
    bid = choice['branch_id']; branch = next(b for b in retailer['geography']['branches'] if b['branch_id'] == bid)
    if offer['stock_by_source'][bid] >= quantity:
        source, ready, route, transfer = bid, 0, None, False
    else:
        warehouse = retailer['source_locations'][0]
        if (not retailer['geography']['fulfilment_policy']['warehouse_transfer_enabled'] or
                offer['stock_by_source'][warehouse['source_id']] < quantity):
            return []
        route = model.travel(warehouse['location'], branch['location'])
        days = model.transit(warehouse['location'], branch['location'])
        if days is None:
            return []
        source, ready, transfer = warehouse['source_id'], warehouse['dispatch_days'] + days, True
    return [{'source_id': source, 'source_kind': 'warehouse' if transfer else 'branch',
             'supply': 'on_hand', 'supplier_wait_days': 0, 'requires_transfer': transfer,
             'service_id': 'retailer-branch/' + bid, 'shipping_class': product['facts']['shipping_class'],
             'scheduling': 'collection_after_ready', 'route': route, 'ready_days': ready,
             'arrival': _arrival(world, ready), 'foreign': False,
             'tariff_components': {k: 0 for k in ('ordinary_minor', 'distance_minor', 'geographic_minor',
                                                'express_minor', 'bulky_minor', 'transfer_minor')},
             'raw_shipping_minor': 0}]


def _rank(candidate, policy):
    arrival = candidate['ready_days'] if candidate['ready_days'] is not None else math.inf
    if policy['dispatch_policy'] == 'lowest_tariff_then_ready':
        return candidate['raw_shipping_minor'], arrival, candidate['source_id']
    return arrival, candidate['raw_shipping_minor'], candidate['source_id']


def _aggregate_arrival(items):
    if any(item['arrival']['status'] == 'unknown' for item in items):
        return {'status': 'unknown', 'earliest_date': None, 'latest_date': None}
    return {'status': 'estimated',
            'earliest_date': max(i['arrival']['earliest_date'] for i in items),
            'latest_date': max(i['arrival']['latest_date'] for i in items)}


def _discount(lines, groups, world, policy, *, coupon_plan, code, signed_in):
    feedback = {'status': 'not_requested', 'reason': None, 'coupon_id': None, 'code': code,
                'eligible_basis_minor': 0, 'qualifying_group_ids': []}
    allocations = {line['line_id']: 0 for line in lines}
    if code is None:
        return feedback, allocations
    if coupon_plan is None:
        feedback.update(status='unsupported', reason='coupon_plan_required')
        return feedback, allocations
    account = next((a for a in coupon_plan['accounts'] if a['retailer_id'] == policy['retailer_id']), None)
    active = (account['signed_in'] if account else False) if signed_in is None else signed_in
    coupon = next((c for c in (account['coupons'] if account else []) if c['code'] == code), None)
    reason = None
    if not active:
        reason = 'coupon_sign_in_required'
    elif coupon is None:
        reason = 'coupon_not_found'
    elif coupon['redeemed']:
        reason = 'coupon_already_redeemed'
    elif not coupon['valid_from'] <= world['quote_as_of'] <= coupon['valid_until']:
        reason = 'coupon_not_active'
    if reason:
        feedback.update(status='rejected', reason=reason)
        return feedback, allocations
    eligible = {line['line_id']: line for line in lines
                if not coupon['concept_ids'] or line['concept_id'] in coupon['concept_ids']}
    if not eligible:
        feedback.update(status='rejected', reason='coupon_wrong_concept')
        return feedback, allocations
    qualified = set()
    if policy['qualification_scope'] == 'checkout':
        basis = sum(line['subtotal_minor'] for line in eligible.values())
        if basis >= coupon['minimum_subtotal_minor']:
            qualified.update(eligible)
            feedback['qualifying_group_ids'] = [g['group_id'] for g in groups if set(g['line_ids']) & set(eligible)]
    else:
        for group in groups:
            ids = set(group['line_ids']) & set(eligible)
            if ids and sum(eligible[k]['subtotal_minor'] for k in ids) >= coupon['minimum_subtotal_minor']:
                qualified.update(ids); feedback['qualifying_group_ids'].append(group['group_id'])
    if not qualified:
        feedback.update(status='rejected', reason='coupon_minimum_not_met')
        return feedback, allocations
    basis = sum(eligible[k]['subtotal_minor'] for k in qualified)
    total = min(basis, coupon['value'] if coupon['kind'] == 'fixed' else (basis * coupon['value'] + 50) // 100)
    # Integer largest remainders. Stable canonical line IDs resolve exact ties.
    remainders = []
    if basis:
        for key in sorted(qualified):
            allocations[key], remainder = divmod(total * eligible[key]['subtotal_minor'], basis)
            remainders.append((-remainder, key))
        for _, key in sorted(remainders)[:total - sum(allocations.values())]:
            allocations[key] += 1
    feedback.update(status='applied', coupon_id=coupon['coupon_id'], eligible_basis_minor=basis)
    return feedback, allocations


def _applied_tariff(item, qualified, policy):
    components = deepcopy(item['tariff_components']); raw = sum(components.values())
    if qualified and item['destination_type'] == 'retailer_branch':
        components['transfer_minor'] = 0
    elif qualified and not item['foreign']:
        kind = item['shipping_class']; treatment = policy['bulky_treatment']
        if kind == 'regular' or treatment != 'exclude_bulky':
            for key in ('ordinary_minor', 'distance_minor', 'geographic_minor'):
                components[key] = 0
            if kind == 'bulky' and treatment == 'waive_all':
                components['bulky_minor'] = 0
    return {'before_minor': raw, 'after_minor': sum(components.values()),
            'waived_minor': raw - sum(components.values()), 'components': components}


def _prepare_lines(world, retailer, products, lines):
    _require(type(lines) is list and bool(lines), 'Basket must contain nonempty canonical lines')
    offers = {o['offer_id']: o for o in retailer['offers']}
    output, seen, quantities = [], set(), defaultdict(int)
    for line in lines:
        _require(type(line) is dict and set(line) == {'line_id', 'offer_id', 'quantity'}, 'Invalid basket line shape')
        _require(_text(line['line_id']) and line['line_id'] not in seen and
                 _text(line['offer_id']) and _int(line['quantity'], 1), 'Invalid/duplicate line identity or quantity')
        _require(line['offer_id'] in offers, 'Basket offer is not listed by this retailer')
        seen.add(line['line_id']); quantities[line['offer_id']] += line['quantity']
        offer = offers[line['offer_id']]; product = products[offer['product_id']]
        output.append({**deepcopy(line), 'sku_id': offer['sku_id'], 'product_id': offer['product_id'],
                       'brand_id': product['brand_id'], 'concept_id': product['concept_id'],
                       'shipping_class': product['facts']['shipping_class'], 'currency': 'SEK',
                       'unit_price_minor': offer['price_minor'],
                       'subtotal_minor': offer['price_minor'] * line['quantity']})
    return sorted(output, key=lambda x: x['line_id']), offers, quantities


def _public_choice(choice):
    return {k: deepcopy(v) for k, v in choice.items() if k != 'contract'}


def _build_option(world, retailer, policy, lines, offers, products, quantities,
                  choices_by_id, selected, split, coupon_plan, coupon_code, signed_in):
    items, resolved = [], {}
    for line in lines:
        offer = offers[line['offer_id']]; product = products[line['product_id']]
        choice = choices_by_id[selected[line['line_id']]]
        pair = (offer['offer_id'], choice['choice_id'])
        if pair not in resolved:
            candidates = (_branch_candidates(world, retailer, product, offer, quantities[offer['offer_id']], choice)
                          if choice['destination_type'] == 'retailer_branch' else
                          _carrier_candidates(world, retailer, policy, product, offer, quantities[offer['offer_id']], choice))
            if not candidates:
                return None, {'line_id': line['line_id'], 'reason': 'no_sufficient_supported_source_or_service'}
            resolved[pair] = min(candidates, key=lambda c: _rank(c, policy))
        item = {**deepcopy(line), **deepcopy(resolved[pair]),
                'choice_id': choice['choice_id'], 'destination_type': choice['destination_type'],
                'destination': deepcopy(choice['destination']), 'carrier_id': choice['carrier_id'],
                'tier': choice['tier'], 'point_id': choice['point_id']}
        item['supply_group'] = ('stock' if item['supply'] == 'on_hand' else 'backorder/' + line['brand_id'])
        items.append(item)
    # Duplicate input lines for an SKU must not select different sources/services.
    per_offer = defaultdict(set)
    for item in items:per_offer[item['offer_id']].add((item['source_id'], item['choice_id']))
    if any(len(v) != 1 for v in per_offer.values()):
        return None, {'reason': 'repeated_offer_cannot_split_requested_quantity'}
    scope_choices = defaultdict(set)
    for item in items:
        key = (item['supply_group'], item['shipping_class'] if policy['mixed_destinations'] else None)
        scope_choices[key].add(item['choice_id'])
    if any(len(v) > 1 for v in scope_choices.values()):
        return None, {'reason': 'incompatible_services_within_required_group'}
    # Only the declared regular/bulky mixed plan permits different destinations.
    destinations = {model.digest(i['destination']) for i in items}
    if len(destinations) > 1 and not policy['mixed_destinations']:
        return None, {'reason': 'mixed_destinations_not_supported'}
    required = defaultdict(list)
    for item in items:
        key = (item['supply_group'], item['choice_id'],
               None if policy['consolidate_sources'] else item['source_id'])
        required[key].append(item)
    groups, required_groups = [], []
    for key, members in sorted(required.items(), key=lambda x: repr(x[0])):
        base_id = 'required/' + model.digest({'key': key, 'line_ids': sorted(i['line_id'] for i in members)})
        required_arrival = _aggregate_arrival(members)
        required_groups.append({'group_id': base_id, 'line_ids': [i['line_id'] for i in members],
                                'supply_group': key[0], 'choice_id': key[1],
                                'arrival': required_arrival})
        divided = defaultdict(list)
        for item in members:
            arrival_key = tuple(item['arrival'].values()) if split else ('consolidated',)
            divided[arrival_key].append(item)
        for arrival_key, subset in sorted(divided.items(), key=lambda x: repr(x[0])):
            gid = 'shipment/' + model.digest({'required': base_id, 'arrival_key': arrival_key,
                                             'line_ids': sorted(i['line_id'] for i in subset)})
            arrival = _aggregate_arrival(subset)
            earlier = (split and arrival['status'] == required_arrival['status'] == 'estimated'
                       and arrival['latest_date'] < required_arrival['earliest_date'])
            groups.append({'group_id': gid, 'required_group_id': base_id,
                           'line_ids': [i['line_id'] for i in subset], 'items': subset,
                           'choice_id': key[1], 'arrival': arrival,
                           'guaranteed_earlier_than_consolidated_estimate': earlier})
    coupon, allocation = _discount(lines, groups, world, policy, coupon_plan=coupon_plan,
                                   code=coupon_code, signed_in=signed_in)
    subtotal = sum(line['subtotal_minor'] for line in lines)
    discount = sum(allocation.values()); net = subtotal - discount
    threshold = retailer['free_shipping_threshold_minor']
    for group in groups:
        merchandise = sum(i['subtotal_minor'] - allocation[i['line_id']] for i in group['items'])
        basis = net if policy['qualification_scope'] == 'checkout' else merchandise
        qualified = policy['membership_active'] or threshold is not None and basis >= threshold
        tariffs = []
        for item in group['items']:
            item['discount_minor'] = allocation[item['line_id']]
            item['merchandise_minor'] = item['subtotal_minor'] - item['discount_minor']
            item['tariff'] = _applied_tariff(item, qualified, policy)
            tariffs.append(item['tariff']['after_minor'])
        group.update(merchandise_minor=merchandise,
                     discount_minor=sum(allocation[i['line_id']] for i in group['items']),
                     qualification={'scope': policy['qualification_scope'], 'basis_minor': basis,
                                    'threshold_minor': threshold, 'threshold_met': threshold is not None and basis >= threshold,
                                    'membership_active': policy['membership_active'], 'qualified': qualified},
                     shipping_minor=max(tariffs),
                     shipping_tariff_basis_line_ids=[i['line_id'] for i in group['items'] if i['tariff']['after_minor'] == max(tariffs)],
                     delivery={**_public_choice(choices_by_id[group['choice_id']]),
                               'service_ids': sorted({i['service_id'] for i in group['items']})})
    shipping = sum(g['shipping_minor'] for g in groups)
    option = {'selection': dict(selected), 'split': split, 'required_groups': required_groups,
              'shipments': groups, 'subtotal_minor': subtotal, 'discount_minor': discount,
              'merchandise_minor': net, 'shipping_minor': shipping, 'total_minor': net + shipping,
              'currency': 'SEK', 'coupon': coupon, 'line_discount_allocations': allocation,
              'arrival': _aggregate_arrival(items),
              'optional_split_effective': len(groups) > len(required_groups)}
    option['option_id'] = 'basket/' + model.digest(option)
    return option, None


def _group_delivery_offers(result, world, retailer, policy, canonical, offers, products,
                           quantities, by_id, split, coupon_plan, coupon_code, signed_in):
    """One group-choice perturbation at a time; never a Cartesian plan search.

    Costs are conditional on an explicitly returned complete context option.
    Changes to coupon qualification/groups are recomputed, not local fee guesses.
    """
    result['group_delivery_offers'] = []
    context = result['selected'] or next(iter(result['options']), None)
    if context is None:
        result['offer_context_option_id'] = None
        return
    result['offer_context_option_id'] = context['option_id']
    groups = defaultdict(list)
    for shipment in context['shipments']:
        for item in shipment['items']:
            key = (item['supply_group'], item['shipping_class'] if policy['mixed_destinations'] else None)
            groups[key].append(item['line_id'])
    option_ids = {o['option_id'] for o in result['options']}
    for key, ids in sorted(groups.items(), key=lambda x: repr(x[0])):
        ids = sorted(ids)
        gid = 'selection/' + model.digest({'scope': key, 'line_ids': ids})
        for choice in result['delivery_choices']:
            if not set(ids) <= set(choice['eligible_line_ids']):
                continue
            selection = {**context['selection'], **{line_id: choice['choice_id'] for line_id in ids}}
            option, failure = _build_option(world, retailer, policy, canonical, offers, products, quantities,
                                           by_id, selection, split, coupon_plan, coupon_code, signed_in)
            if failure:
                continue
            if option['option_id'] not in option_ids:
                result['options'].append(option); option_ids.add(option['option_id'])
            relevant = [g for g in option['shipments'] if set(g['line_ids']) & set(ids)]
            result['group_delivery_offers'].append({
                'selection_group_id': gid, 'line_ids': ids, 'choice_id': choice['choice_id'],
                'option_id': option['option_id'], 'conditional_context_option_id': context['option_id'],
                'selection': selection, 'shipment_ids': [g['group_id'] for g in relevant],
                'shipping_minor': sum(g['shipping_minor'] for g in relevant),
                'complete_basket_total_minor': option['total_minor'],
                'arrival': _aggregate_arrival([i for g in relevant for i in g['items']]),
                'pricing_scope': 'complete_recomputed_plan_conditional_on_other_group_choices'})


def quote(world, retailer_id, lines, *, plan, destination=None, selections=None,
          split=False, coupon_plan=None, coupon_code=None, signed_in=None,
          expected_quote_id=None):
    """Return finite complete common-service offers or one explicit selected plan.

    `selections` maps every canonical input line ID to a published choice_id. This
    is a transport representation of group choices: within each stock/backorder
    brand group (or declared regular/bulky mixed subgroup), all lines must select
    the same service. It is not arbitrary item partitioning or source selection.
    With None, complete uniform-service plans are enumerated, not a Cartesian
    service product. No default service is secretly selected.
    """
    validation = validate_plan(world, plan)
    retailers, products = _world(world)
    _require(retailer_id in retailers, 'Unknown retailer')
    retailer = retailers[retailer_id]
    policy = next(p for p in plan['retailer_policies'] if p['retailer_id'] == retailer_id)
    _require(type(split) is bool, 'Split must be boolean')
    _require(signed_in is None or type(signed_in) is bool, 'Signed-in override must be boolean')
    _require(coupon_code is None or _text(coupon_code), 'Coupon code must be nonempty text')
    _require(coupon_plan is None and coupon_code is None, 'Accepted-catalog account/coupon bridge is not adopted')
    location = deepcopy(world['user_location'] if destination is None else _location(destination))
    canonical, offers, quantities = _prepare_lines(world, retailer, products, lines)
    identity = {'version': VERSION, 'world_sha256': plan['world_sha256'],
                'policy_sha256': validation['plan_sha256'], 'retailer_id': retailer_id,
                'lines': canonical, 'destination': location, 'selections': selections, 'split': split,
                'coupon_plan_sha256': model.digest(coupon_plan) if coupon_plan is not None else None,
                'coupon_code': coupon_code, 'signed_in': signed_in}
    quote_id = model.digest(identity)
    result = {'schema_version': VERSION, 'quote_id': quote_id, 'world_id': world['world_id'],
              'world_sha256': plan['world_sha256'], 'plan_sha256': validation['plan_sha256'],
              'retailer_id': retailer_id, 'currency': 'SEK', 'lines': canonical,
              'destination': location, 'policy': public_policy(plan, retailer_id),
              'status': 'offers_available', 'reasons': [], 'delivery_choices': [], 'options': [],
              'selected': None, 'group_delivery_offers': [], 'offer_context_option_id': None, 'line_availability': [
                  {'line_id': line['line_id'], 'sku_id': line['sku_id'],
                   'combined_requested_quantity': quantities[line['offer_id']],
                   'shipping_stock_source_ids': [source['source_id'] for source in retailer['source_locations']
                        if source['shipping_enabled'] and offers[line['offer_id']]['stock_by_source'][source['source_id']] >= quantities[line['offer_id']]],
                   'branch_stock_ids': [branch['branch_id'] for branch in retailer['geography']['branches']
                        if branch['pickup_enabled'] and offers[line['offer_id']]['stock_by_source'][branch['branch_id']] >= quantities[line['offer_id']]],
                   'supplier_order_offered': offers[line['offer_id']]['supplier_order']['enabled']}
                  for line in canonical], 'limitations': [
                  'Explicit policy fixtures; natural policy and bounded-choice population are separate.',
                  'No quantity stock pooling/splitting or branch-to-branch transfers.',
                  'Charged warehouse-to-branch transfers await numeric/aggregation policy.',
                  'No basket task/reference/response-grader adoption.',
                  'Group offers are conditional complete-plan recalculations, not a global basket optimum.',
                  'Optional arrival groups share their required group service in this first version.',
                  'No delivery appointment or purchase mutation; timing is an estimate.']}
    if expected_quote_id is not None and expected_quote_id != quote_id:
        result.update(status='stale_quote', reasons=[{'reason': 'quote_input_identity_changed'}]);return result
    if not _within_region(world, location):
        result.update(status='invalid_destination', reasons=[{'reason': 'outside_supported_native_address_region'}]);return result
    if split and not policy['optional_split']:
        result.update(status='unsupported_plan', reasons=[{'reason': 'optional_split_not_supported'}]);return result
    choices = _choices(world, retailer, policy, location); by_id = {c['choice_id']: c for c in choices}
    # Availability rows are class/source/quantity checked even when no complete
    # uniform-service plan exists (a supported mixed home/collection may work).
    eligible = defaultdict(list)
    for line in canonical:
        offer, product = offers[line['offer_id']], products[line['product_id']]
        for choice in choices:
            candidates = (_branch_candidates(world, retailer, product, offer, quantities[line['offer_id']], choice)
                          if choice['destination_type'] == 'retailer_branch' else
                          _carrier_candidates(world, retailer, policy, product, offer, quantities[line['offer_id']], choice))
            if candidates:eligible[choice['choice_id']].append(line['line_id'])
    result['delivery_choices'] = [{**_public_choice(c), 'eligible_line_ids': eligible[c['choice_id']]}
                                  for c in choices if eligible[c['choice_id']]]
    failures = []
    for choice in choices:
        if len(eligible[choice['choice_id']]) != len(canonical):continue
        selected = {line['line_id']: choice['choice_id'] for line in canonical}
        option, failure = _build_option(world, retailer, policy, canonical, offers, products, quantities,
                                        by_id, selected, split, coupon_plan, coupon_code, signed_in)
        if failure:failures.append(failure)
        else:result['options'].append(option)
    if selections is not None:
        if (type(selections) is not dict or set(selections) != {l['line_id'] for l in canonical}
                or any(type(v) is not str or v not in by_id for v in selections.values())):
            result.update(status='invalid_plan', reasons=[{'reason': 'unknown_stale_or_incomplete_delivery_selection'}]);return result
        option, failure = _build_option(world, retailer, policy, canonical, offers, products, quantities,
                                        by_id, selections, split, coupon_plan, coupon_code, signed_in)
        if failure:
            result.update(status='unavailable', reasons=[failure]);return result
        result.update(status='quoted', selected=option)
        if not any(o['option_id'] == option['option_id'] for o in result['options']):
            result['options'].append(option)
        _group_delivery_offers(result, world, retailer, policy, canonical, offers, products, quantities, by_id, split, coupon_plan, coupon_code, signed_in)
        return result
    if not result['options']:
        all_covered = all(any(line['line_id'] in ids for ids in eligible.values()) for line in canonical)
        if all_covered and policy['mixed_destinations']:
            result.update(status='selection_required', reasons=[{'reason': 'explicit_supported_mixed_plan_required'}])
        else:
            result.update(status='unavailable', reasons=failures or [{'reason': 'no_compatible_complete_basket_delivery'}])
    _group_delivery_offers(result, world, retailer, policy, canonical, offers, products, quantities, by_id, split, coupon_plan, coupon_code, signed_in)
    return result
