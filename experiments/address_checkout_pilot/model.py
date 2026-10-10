"""Executable local-region resolver and checkout quote fixture; no live integration."""
import copy
from datetime import date, timedelta
from hashlib import sha256
import json
import math
from pathlib import Path

from environments.product_world.geography import cities, location, route
from experiments.carrier_location_pilot.model import generate as carrier_world, rng
from .formats import COUNTRIES, address_lines, folded, make_postcodes, postcode

VERSION = 'address-checkout-pilot-v1'
PLAN = Path(__file__).resolve().parents[2] / 'docs/agents/cross-family-store-theme-review.json'
FIELDS = ('recipient', 'street', 'house_number', 'unit', 'postcode', 'city', 'country')
REQUIRED = tuple(f for f in FIELDS if f != 'unit')
CONFIG = {'autofill_probability': .3, 'incorrect_probability': .2, 'missing_probability': .25}
FIXTURE_PRICES = {
    'SE': ('SEK', 79900, 4900), 'NO': ('NOK', 99900, 7900),
    'DK': ('DKK', 59900, 3900), 'IS': ('ISK', 1299000, 99000),
    'GB': ('GBP', 6999, 499), 'CH': ('CHF', 7990, 590),
}


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def parameters(options=None):
    if options is not None and (not isinstance(options, dict) or set(options) - set(CONFIG)):
        raise ValueError('Unknown autofill sampling parameter')
    result = {**CONFIG, **(options or {})}
    for value in result.values():
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError('Autofill probabilities must be between zero and one')
    return result


def offset(home, id, radius, angle):
    city = cities()[home['city_id']]
    east = home['local_east_km'] + radius * math.cos(angle)
    north = home['local_north_km'] + radius * math.sin(angle)
    return {**home, 'location_id': id,
            'latitude': round(city['latitude'] + north / 111.195, 6),
            'longitude': round(city['longitude'] + east / (111.195 * math.cos(math.radians(city['latitude']))), 6),
            'local_east_km': round(east, 3), 'local_north_km': round(north, 3)}


def building_key(address):
    return digest({k: folded(address[k]) for k in ('country', 'city', 'postcode', 'street', 'house_number')})


def generate(seed=0, city_id='uppsala', options=None):
    cfg = parameters(options)
    carriers = carrier_world(seed, city_id)
    home = carriers['user_location']
    city = cities()[city_id]
    country = city['country']
    plan = json.loads(PLAN.read_text())
    region = plan['checkout_address_autofill_contract']['destination_and_checkout_update_contract']['region_sampling_proposal']
    postal_count = region['synthetic_postal_area_count']
    codes = make_postcodes(country, rng(seed, VERSION + '/codes'), postal_count + 1)
    areas = []
    for i in range(postal_count):
        r = rng(seed, VERSION + f'/postal/{i}')
        point = copy.deepcopy(home) if i == 0 else offset(home, f'postal-{i}',
                    math.sqrt(r.uniform(.25, (region['maximum_straight_line_radius_km'] * .8) ** 2)), r.uniform(0, math.tau))
        point['location_id'] = f'postal-{i}'
        areas.append({'postal_area_id': f'postal-{i}', 'postcode': codes[i], 'location': point})
    homes = []
    for i in range(region['saved_alternative_address_count'] + 1):
        r = rng(seed, VERSION + f'/address/{i}')
        point = copy.deepcopy(home) if i == 0 else offset(home, f'saved-home-{i}',
                   math.sqrt(r.uniform(region['alternative_home_distance_km']['minimum'] ** 2,
                                       region['alternative_home_distance_km']['maximum'] ** 2)), r.uniform(0, math.tau))
        code = areas[i % postal_count]['postcode']
        unit = 'H0302' if country == 'NO' else '2 tv.' if country == 'DK' else str(24 + i)
        address = dict(recipient='Alex Lind', street=COUNTRIES[country][2], house_number=str(12 + i * 7),
                       unit=unit, postcode=code, city=city['name'], country=country)
        point['location_id'] = 'user-home' if i == 0 else f'saved-home-{i}'
        homes.append({'address_id': point['location_id'], 'address': address, 'location': point,
                      'building_key': building_key(address), 'display_lines': address_lines(address)})
    currency, item_price, base_fee = FIXTURE_PRICES.get(country, ('EUR', 7999, 499))
    service_plan = plan['retailer_population_contract']['geography_and_delivery_policy']['delivery_options_proposal']['home_delivery_terms_backlog']['sampling_proposal']
    service_rows = []
    for carrier in carriers['carriers']:
        cid = carrier['carrier_id']
        modes = ('recipient_opens', 'provided_code_or_intercom', 'authorised_access')
        access = {h['building_key']: rng(seed, VERSION + '/' + cid + '/' + h['building_key']).choices(modes, [.4, .35, .25])[0]
                  for h in homes}
        for kind in ('regular', 'bulky'):
            r = rng(seed, VERSION + '/service/' + cid + '/' + kind)
            weights = service_plan['scheduling_mode_probabilities_by_shipping_class'][kind]
            scheduling = r.choices(list(weights), list(weights.values()))[0]
            service_rows.append({'service_id': cid + '-' + kind, 'carrier_id': cid, 'shipping_class': kind,
                                 'scheduling': scheduling, 'evening_windows': r.random() < .5,
                                 'unattended_allowed': kind == 'regular' and r.random() < .5,
                                 'building_access': access,
                                 'transit_offset_days': rng(seed, VERSION + '/' + cid + '/offset').choices([-1, 0, 1], [.2, .6, .2])[0]})
    domestic = sorted(c['city_id'] for c in cities().values() if c['country'] == country and c['city_id'] != city_id)
    origins = [location(seed, 'fixture-local-warehouse', city_id),
               location(seed, 'fixture-regional-warehouse', domestic[0] if domestic else city_id)]
    stores = []
    for i, origin in enumerate(origins):
        sid = f'fixture-store-{i+1}'
        selected = rng(seed, VERSION + '/' + sid + '/carriers').sample([c['carrier_id'] for c in carriers['carriers']], 3)
        initial = autofill(seed, sid, homes, codes[-1], cfg)
        stores.append({'retailer_id': sid, 'name': ('Local retailer' if i == 0 else 'Regional retailer'),
                       'origin': origin, 'carrier_ids': selected, 'currency': currency,
                       'item_price_minor': item_price, 'base_shipping_minor': base_fee,
                       'dispatch_days': i, 'initial_form': initial})
    world = {'schema_version': VERSION, 'seed': seed, 'city': city, 'parameters': cfg,
             'region': {'city_id': city_id, 'radius_km': region['maximum_straight_line_radius_km'], 'centre': home},
             'postal_areas': areas, 'addresses': homes, 'outside_postcode': codes[-1],
             'carriers': carriers['carriers'], 'collection_points': carriers['collection_points'],
             'services': service_rows, 'retailers': stores,
             'task': {'delivery_address': homes[0]['address'], 'memory': 'Please call instead of ringing the doorbell.',
                      'required_instructions': 'Please call instead of ringing the doorbell.'},
             'quote_as_of': '2026-09-30',
             'limitations': ['Isolated authored two-retailer fixture; not live checkout integration.',
                             'Fictional postcode areas and street addresses; no real geocoding.',
                             'Illustrative local-currency prices, not exchange-rate conversions.',
                             'Standard delivery only; no coupons, memberships or freight quantity scaling.',
                             'Shipping quotes expose schedules, not a simulated appointment reservation.',
                             'Instruction text is retained for manual review; no semantic instruction grader.'],
             'provenance': {'plan_sha256': digest(plan)}}
    world['world_id'] = digest(world)
    return world


def autofill(seed, retailer_id, homes, outside_code, cfg, *, force=None):
    r = rng(seed, VERSION + '/autofill/' + retailer_id)
    enabled = r.random() < cfg['autofill_probability']
    wrong = enabled and r.random() < cfg['incorrect_probability']
    missing = enabled and r.random() < cfg['missing_probability']
    mode = r.choice(('minor_field_mismatch', 'previous_home')) if wrong else None
    if force:
        if force not in ('blank', 'correct', 'old', 'postcode', 'missing_unit', 'old_missing_unit'):
            raise ValueError('Unknown authoring form example')
        enabled = force != 'blank'
        wrong = force in ('old', 'postcode', 'old_missing_unit')
        missing = force in ('missing_unit', 'old_missing_unit')
        mode = 'previous_home' if force in ('old', 'old_missing_unit') else 'minor_field_mismatch' if wrong else None
    address = copy.deepcopy(homes[r.randrange(1, len(homes))]['address'] if mode == 'previous_home' else homes[0]['address'])
    if mode == 'minor_field_mismatch':
        address['postcode'] = outside_code
    masked = []
    if missing:
        # Prototype mask weights are authoring choices, not finalized production priors.
        masked = ['unit'] if force else r.choice([['unit'], ['house_number'], ['recipient', 'unit']])
        for field in masked:
            address[field] = ''
    if not enabled:
        address = {k: '' for k in FIELDS}
        address['country'] = homes[0]['address']['country']
    return {'address': address, 'instructions': '',
            'provenance': {'autofill': enabled, 'incorrect_values': wrong, 'missing_fields': missing,
                           'wrong_mode': mode, 'missing_fields_mask': masked, 'authoring_override': force}}


def normalize(address):
    if not isinstance(address, dict) or set(address) - set(FIELDS):
        raise ValueError('Unknown address fields')
    result = {f: address.get(f, '') for f in FIELDS}
    if any(not isinstance(v, str) or len(v) > 200 for v in result.values()):
        raise ValueError('Address fields must be text of at most 200 characters')
    result = {f: ' '.join(v.split()) for f, v in result.items()}
    result['country'] = result['country'].upper()
    return result


def resolve(world, address):
    address = normalize(address)
    errors = {f: 'Required field' for f in REQUIRED if not address[f]}
    if errors:
        return {'status': 'invalid', 'errors': errors, 'address': address}
    if address['country'] not in COUNTRIES:
        return {'status': 'unavailable', 'reason': 'Shipping not available for this address', 'address': address}
    try:
        code = postcode(address['country'], address['postcode'])
    except ValueError as exc:
        return {'status': 'invalid', 'errors': {'postcode': str(exc)}, 'address': address}
    if address['country'] != world['city']['country']:
        return {'status': 'unavailable', 'reason': 'Shipping not available for this address', 'address': address}
    area = next((p for p in world['postal_areas'] if postcode(address['country'], p['postcode']) == code), None)
    if area is None:
        return {'status': 'unavailable', 'reason': 'Shipping not available for this address', 'address': address}
    if folded(address['city']) != folded(world['city']['name']):
        return {'status': 'invalid', 'errors': {'city': 'City conflicts with this supported postcode'}, 'address': address}
    address['postcode'] = area['postcode']
    address['city'] = world['city']['name']
    key = building_key(address)
    known = next((h for h in world['addresses'] if h['building_key'] == key), None)
    position = copy.deepcopy(known['location'] if known else area['location'])
    precision = 'known_synthetic_building' if known else 'approximate_synthetic_postal_area'
    distance = math.hypot(position['local_east_km'] - world['region']['centre']['local_east_km'],
                          position['local_north_km'] - world['region']['centre']['local_north_km'])
    if distance > world['region']['radius_km']:
        return {'status': 'unavailable', 'reason': 'Shipping not available for this address', 'address': address}
    return {'status': 'supported', 'address': address, 'location': position, 'precision': precision,
            'building_key': key if known else None, 'distance_from_true_home_km': round(distance, 3),
            'display_lines': address_lines(address)}


def quote(world, retailer_id, address, *, shipping_class='regular', quantity=1):
    if shipping_class not in ('regular', 'bulky') or type(quantity) is not int or not 1 <= quantity <= 10:
        raise ValueError('Invalid cart configuration')
    store = next((s for s in world['retailers'] if s['retailer_id'] == retailer_id), None)
    if store is None:
        raise ValueError('Unknown retailer')
    destination = resolve(world, address)
    binding = {'world_id': world['world_id'], 'retailer_id': retailer_id, 'address': destination['address'],
               'shipping_class': shipping_class, 'quantity': quantity}
    result = {'quote_id': digest(binding), 'destination': destination, 'options': [],
              'currency': store['currency'], 'subtotal_minor': store['item_price_minor'] * quantity,
              'status': destination['status']}
    if destination['status'] != 'supported':
        return result
    freight = route(store['origin'], destination['location'], 'freight')
    if freight['status'] != 'estimated':
        return {**result, 'status': 'unavailable', 'reason': 'Shipping not available for this address'}
    base_transit = 1 if store['origin']['city_id'] == destination['location']['city_id'] else 1 + math.ceil(freight['distance_km'] / 650)
    currency_unit = store['base_shipping_minor'] / 49
    geographic_fee = math.ceil(max(0, freight['distance_km'] - 500) / 500) * round(25 * currency_unit)
    carriers = {c['carrier_id']: c for c in world['carriers']}
    for service in world['services']:
        if service['carrier_id'] not in store['carrier_ids'] or service['shipping_class'] != shipping_class:
            continue
        cid = service['carrier_id']
        carrier = carriers[cid]
        days = store['dispatch_days'] + max(1, base_transit + service['transit_offset_days']) + (1 if shipping_class == 'bulky' else 0)
        first_date = date.fromisoformat(world['quote_as_of']) + timedelta(days=days)
        slots = [{'date': (first_date + timedelta(days=i)).isoformat(), 'windows_local':
                  (['08:00-12:00', '12:00-16:00'] + (['16:00-20:00'] if service['evening_windows'] else []))
                  if service['scheduling'] == 'choose_day_and_window' else []}
                 for i in range(1 if service['scheduling'] == 'carrier_assigned' else 3)]
        access = service['building_access'].get(destination['building_key'], 'unknown')
        base = store['base_shipping_minor'] + geographic_fee
        home_offset = rng(world['seed'], VERSION + '/' + retailer_id + '/' + cid + '/home-fee').choices(
            [-20, -10, 0, 10, 20], [.1, .1, .2, .4, .2])[0]
        bulky = round(249 * currency_unit) if shipping_class == 'bulky' else 0
        common = {'carrier_id': cid, 'carrier_name': carrier['name'], 'arrival_date': first_date.isoformat(),
                  'timezone': destination['location']['timezone'], 'route': freight}
        fee = max(0, base + round(home_offset * currency_unit)) + bulky
        result['options'].append({**common, 'option_id': service['service_id'] + '-home', 'destination_type': 'home',
            'shipping_minor': fee, 'total_minor': result['subtotal_minor'] + fee,
            'scheduling': service['scheduling'], 'slots': slots, 'building_entry': access,
            'handoff': 'Apartment door when entry is resolved; otherwise recipient comes downstairs.',
            'unattended_allowed': service['unattended_allowed'], 'bulky_surcharge_minor': bulky})
        if shipping_class == 'regular':
            for point in world['collection_points']:
                if cid not in point['carrier_ids']:
                    continue
                km = math.hypot(point['location']['local_east_km'] - destination['location']['local_east_km'],
                                point['location']['local_north_km'] - destination['location']['local_north_km'])
                if km > 3:
                    continue
                travel = {mode: route(destination['location'], point['location'], mode) for mode in ('walking', 'cycling', 'driving')}
                point_freight = route(store['origin'], point['location'], 'freight')
                if point_freight['status'] != 'estimated':
                    continue
                point_days = store['dispatch_days'] + max(1, (1 if store['origin']['city_id'] == point['location']['city_id'] else
                    1 + math.ceil(point_freight['distance_km'] / 650)) + service['transit_offset_days'])
                ready_date = (date.fromisoformat(world['quote_as_of']) + timedelta(days=point_days)).isoformat()
                point_fee = store['base_shipping_minor'] + math.ceil(max(0, point_freight['distance_km'] - 500) / 500) * round(25 * currency_unit)
                result['options'].append({**common, 'arrival_date': ready_date, 'route': point_freight,
                    'option_id': service['service_id'] + '-' + point['point_id'],
                    'destination_type': point['type'], 'point_id': point['point_id'], 'point_name': point['name'],
                    'shipping_minor': point_fee, 'total_minor': result['subtotal_minor'] + point_fee,
                    'ready_date': ready_date, 'distance_from_destination_km': round(km, 3),
                    'travel': travel, 'weekly_hours': point['weekly_hours'], 'access_24_7': point['access_24_7']})
    return result


def save_draft(world, payload):
    allowed = {'retailer_id', 'address', 'shipping_class', 'quantity', 'quote_id', 'option_id', 'instructions'}
    if not isinstance(payload, dict) or set(payload) - allowed:
        raise ValueError('Unknown draft fields')
    instructions = payload.get('instructions', '')
    if not isinstance(instructions, str) or len(instructions) > 2000:
        raise ValueError('Instructions must be text of at most 2000 characters')
    result = quote(world, payload['retailer_id'], payload['address'],
                   shipping_class=payload.get('shipping_class', 'regular'), quantity=payload.get('quantity', 1))
    if result['status'] != 'supported':
        return {'ok': False, 'error': 'Shipping destination is not ready', 'quote': result}
    if payload.get('quote_id') != result['quote_id']:
        return {'ok': False, 'error': 'Shipping quote is stale; update and choose again', 'quote': result}
    option = next((o for o in result['options'] if o['option_id'] == payload.get('option_id')), None)
    if option is None:
        return {'ok': False, 'error': 'Choose an available shipping option', 'quote': result}
    correct = normalize(world['task']['delivery_address'])
    submitted = result['destination']['address']
    differs = [f for f in FIELDS if folded(submitted[f]) != folded(correct[f])]
    return {'ok': True, 'draft': {'world_id': world['world_id'], 'retailer_id': payload['retailer_id'],
            'address': submitted, 'instructions': instructions, 'quote_id': result['quote_id'],
            'shipping_class': payload.get('shipping_class', 'regular'), 'quantity': payload.get('quantity', 1),
            'shipping_option': option},
            'authoring_checks': {'address_matches_task': not differs, 'different_address_fields': differs,
                                 'instructions_present': bool(instructions.strip()),
                                 'instruction_meaning': 'Manual review; no semantic grading implemented'},
            'scope': 'Saved checkout draft only; no purchase, charge or simulated shipment.'}
