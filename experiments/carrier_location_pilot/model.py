"""Deterministic, bounded location draft; no shopping-world/runtime integration."""
from datetime import datetime
from hashlib import sha256
import json
import math
from pathlib import Path
from random import Random
from zoneinfo import ZoneInfo

from environments.product_world.areas import city_areas
from environments.product_world.geography import cities, route, user_location

VERSION = 'carrier-location-pilot-v1'
PLAN = Path(__file__).resolve().parents[2] / 'docs/agents/cross-family-store-theme-review.json'
DEFAULTS = dict(radius_km=3.0, point_count=10, locker_probability=.4,
                home_only_probability=.2)
DAYS = ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')
HOSTS = {'fuel_station': 'Service station', 'grocery_store': 'Market',
         'convenience_store': 'Corner shop', 'parcel_locker': 'Parcel lockers'}


def rng(seed, key):
    return Random(int.from_bytes(sha256(f'{VERSION}/{seed}/{key}'.encode()).digest(), 'big'))


def config(patch=None):
    patch = patch or {}
    if not isinstance(patch, dict) or set(patch) - set(DEFAULTS):
        raise ValueError('Unknown sampling parameter')
    c = {**DEFAULTS, **patch}
    for key, low, high in [('radius_km', .5, 8), ('locker_probability', 0, 1),
                           ('home_only_probability', 0, 1)]:
        v = c[key]
        if type(v) not in (int, float) or not math.isfinite(v) or not low <= v <= high:
            raise ValueError(f'{key} must be between {low} and {high}')
    if type(c['point_count']) is not int or not 1 <= c['point_count'] <= 30:
        raise ValueError('point_count must be an integer between 1 and 30')
    return c


def hours(host, seed, point_id):
    if host == 'parcel_locker':
        return {day: [['00:00', '24:00']] for day in DAYS}
    if host == 'fuel_station':
        return {day: [['06:00', '23:00']] for day in DAYS}
    templates = [
        ([['08:00', '20:00']], [['09:00', '18:00']], [['10:00', '16:00']]),
        ([['09:00', '19:00']], [['10:00', '17:00']], []),
        ([['07:00', '22:00']], [['08:00', '21:00']], [['09:00', '20:00']]),
    ]
    weekdays, saturday, sunday = rng(seed, point_id + '/hours').choice(templates)
    return {day: list(weekdays if i < 5 else saturday if i == 5 else sunday)
            for i, day in enumerate(DAYS)}


def accessible_at(point, instant):
    """Access, not parcel readiness; caller supplies an aware datetime."""
    if not isinstance(instant, datetime) or instant.tzinfo is None:
        raise ValueError('An aware datetime is required')
    if point['access_24_7']:
        return True
    local = instant.astimezone(ZoneInfo(point['location']['timezone']))
    minute = local.hour * 60 + local.minute
    def minutes(value):
        h, m = map(int, value.split(':'))
        return h * 60 + m
    return any(minutes(start) <= minute < minutes(end)
               for start, end in point['weekly_hours'][DAYS[local.weekday()]])


def generate(seed=0, city_id='uppsala', options=None):
    if type(seed) is not int or not 0 <= seed <= 2**31 - 1:
        raise ValueError('seed must be an integer between 0 and 2147483647')
    c = config(options)
    if city_id not in cities():
        raise ValueError('Unknown supported city')
    city = cities()[city_id]
    user = user_location(seed, city_id)
    plan = json.loads(PLAN.read_text())['retailer_population_contract']['geography_and_delivery_policy']['shared_shipping_carriers']
    names = rng(seed, 'carrier-names').sample(plan['name_pool'], plan['carriers_per_world'])
    points = []
    for i in range(c['point_count']):
        pid = f'collection-{i + 1:02d}'
        r = rng(seed, pid + '/position')
        # Uniform area in an annulus centred on the user, rather than the city centre.
        distance = math.sqrt(r.uniform(.15**2, c['radius_km']**2))
        angle = r.uniform(0, math.tau)
        east = user['local_east_km'] + distance * math.cos(angle)
        north = user['local_north_km'] + distance * math.sin(angle)
        area = min(city_areas(city), key=lambda a: (a['east_km'] - east)**2 + (a['north_km'] - north)**2)
        is_locker = rng(seed, pid + '/type').random() < c['locker_probability']
        host = 'parcel_locker' if is_locker else rng(seed, pid + '/host').choice(
            ['fuel_station', 'grocery_store', 'convenience_store'])
        position = {**user, 'location_id': pid,
                    'latitude': round(city['latitude'] + north / 111.195, 6),
                    'longitude': round(city['longitude'] + east / (111.195 * math.cos(math.radians(city['latitude']))), 6),
                    'local_east_km': round(east, 3), 'local_north_km': round(north, 3)}
        points.append(dict(point_id=pid, name=f"{city['name']} · {area['name']} · {HOSTS[host]} {i + 1:02d}",
                           type='parcel_locker' if is_locker else 'staffed_counter', host_type=host,
                           access_24_7=is_locker, location=position,
                           distance_from_home_km=round(distance, 3),
                           area_label_basis='nearest approximate area anchor, not verified street address',
                           weekly_hours=hours(host, seed, pid),
                           travel={mode: route(user, position, mode) for mode in ('walking', 'cycling', 'driving')}))
    carriers = []
    modes = ('staffed_counter', 'parcel_locker', 'both')
    for i, name in enumerate(names):
        cid = f'carrier-{i + 1:02d}'
        r = rng(seed, cid + '/access')
        mode = 'home_only' if r.random() < c['home_only_probability'] else r.choices(modes, [.5, .1875, .3125])[0]
        types = [] if mode == 'home_only' else ['staffed_counter', 'parcel_locker'] if mode == 'both' else [mode]
        eligible = [p['point_id'] for p in points if p['type'] in types]
        chosen = []
        if eligible:
            count = r.randint(min(2 if mode == 'both' else 1, len(eligible)), min(3, len(eligible)))
            # If both types are available, keep one of each; sharing across carriers is permitted.
            if mode == 'both':
                for kind in types:
                    pool = [p['point_id'] for p in points if p['type'] == kind]
                    if pool:
                        chosen.append(r.choice(pool))
            chosen += r.sample([pid for pid in eligible if pid not in chosen], count - len(chosen))
        carriers.append(dict(carrier_id=cid, name=name, home_delivery=True,
                             sampled_local_pickup_mode=mode, local_collection_types=types,
                             collection_point_ids=sorted(chosen)))
    for point in points:
        point['carrier_ids'] = [x['carrier_id'] for x in carriers if point['point_id'] in x['collection_point_ids']]
    used = [p for p in points if p['carrier_ids']]
    return dict(schema_version=VERSION, seed=seed, city=city, user_location=user,
                parameters=c, carriers=carriers, collection_points=points,
                summary=dict(carriers=len(carriers), points=len(points), used_points=len(used),
                             shared_points=sum(len(p['carrier_ids']) > 1 for p in points),
                             home_only_carriers=sum(not x['collection_point_ids'] for x in carriers)),
                provenance=dict(status='isolated draft, not live shopping integration',
                                plan_sha256=sha256(PLAN.read_bytes()).hexdigest(),
                                count_and_access_defaults='proposed for inspection, not accepted production probabilities',
                                pickup_mode_given_collection={'staffed_counter': .5, 'parcel_locker': .1875, 'both': .3125},
                                limits='Synthetic nearby positions and approximate local travel; no real map, street addresses, carrier transit times, parcel readiness, retailer service binding or model evaluation.'))
