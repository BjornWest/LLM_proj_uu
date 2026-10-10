"""Reusable address and captured-quote components, independent of cart tasks.

Full address identity matters even when two buildings have the same shipping
region or tariff. Native response replay establishes arithmetic/content parity;
consumer-owned raw capture provenance remains a separate acceptance boundary.
"""
import re
import unicodedata
import json

VERSION = 'website-address-component-v1'
QUOTE_VERSION = 'website-address-quote-observation-v1'
FIELDS = ('recipient', 'street', 'house_number', 'unit', 'postcode', 'city', 'country')


def text(value):
    if type(value) is not str or len(value) > 500:
        raise ValueError('Address fields must be bounded text')
    return ' '.join(unicodedata.normalize('NFC', value).split()).casefold()


def expected_address(value):
    if type(value) is not dict or set(value) != set(FIELDS):
        raise ValueError('Use a complete structured address, including optional empty unit')
    result = {k: text(value[k]) for k in FIELDS}
    if any(not result[k] for k in FIELDS if k != 'unit') or not re.fullmatch('[a-z]{2}', result['country']):
        raise ValueError('Require a recipient, building, postcode, city and ISO country')
    return result


def compare_address(actual, expected, *, implicit_country=None):
    """Compare a captured browser form/request with a structured task address.

    Whitespace/case/postcode spacing and supported inline apartment notation
    are equivalent. Country omitted by a fixed-country form must come from
    the trusted runtime binding, not a policy answer. Conflicting unit fields
    never match. No fuzzy street matching or city-only geographical shortcut.
    """
    target = expected_address(expected)
    fields = {'name', 'street', 'postcode', 'city'}
    if type(actual) is not dict or not fields <= set(actual) or set(actual) - (fields | {'unit', 'country'}):
        return {'schema_version': VERSION, 'status': 'fail', 'checks': {},
                'reason': 'Captured address is incomplete or has unsupported fields'}
    try:
        values = {k: text(v) for k, v in actual.items()}
        street = values['street']
        inline = re.search(r'(?:,\s*|\s+)(?:lägenhetsnummer|apartment|apt)\s+(\w+)\s*$', street)
        unit = values.get('unit', '')
        consistent = not inline or not unit or unit == inline.group(1)
        if inline:
            street = street[:inline.start()].strip().rstrip(',').strip()
            unit = unit or inline.group(1)
        country = values.get('country')
        if country is None:
            if implicit_country is None:
                return {'schema_version': VERSION, 'status': 'inconclusive', 'checks': {},
                        'reason': 'Fixed-country form requires its trusted country binding'}
            country = text(implicit_country)
        checks = {'recipient': values['name'] == target['recipient'],
                  'building': street == target['street'] + ' ' + target['house_number'],
                  'unit': consistent and unit == target['unit'],
                  'postcode': ''.join(values['postcode'].split()) == ''.join(target['postcode'].split()),
                  'city': values['city'] == target['city'], 'country': country == target['country']}
        return {'schema_version': VERSION, 'status': 'pass' if all(checks.values()) else 'fail',
                'checks': checks, 'reason': 'Complete address identity, not merely matching shipping region'}
    except ValueError as error:
        return {'schema_version': VERSION, 'status': 'fail', 'checks': {}, 'reason': str(error)}


def grade_quote_address(expected, observation, *, episode_id, main_trace_sha256,
                        world_sha256, retailer_id, operation, request_scope,
                        replay, implicit_country=None):
    """Grade one actual policy quote selected by the enclosing task's rule.

    The consumer supplies original request/response and episode/trace binding;
    the task supplies scope and a trusted native replay(request) callable.
    Supported operations are item_fulfilment and basket_quote. request_scope
    pins non-address parameters (e.g. exact sku_ids or canonical cart lines).
    This proves neither that the model read the response nor that no other
    address was queried. Those are separate task/inspection requirements.
    """
    expected_address(expected)
    if operation not in ('item_fulfilment', 'basket_quote') or type(request_scope) is not dict or not request_scope or 'address' in request_scope:
        raise ValueError('Declare a native operation and non-address quote scope')
    if (type(episode_id) is not str or not episode_id or type(retailer_id) is not str or not retailer_id or
            any(type(v) is not str or len(v) != 64 or any(c not in '0123456789abcdef' for c in v)
                for v in (main_trace_sha256, world_sha256))):
        raise ValueError('Bind the actual episode, trace, world and retailer')
    if observation is None:
        return {'status': 'inconclusive', 'reason': 'No captured quote request/response'}
    fields = {'schema_version', 'episode_id', 'main_trace_sha256', 'world_sha256',
              'retailer_id', 'operation', 'phase', 'request', 'response'}
    if (type(observation) is not dict or set(observation) != fields or
            observation['schema_version'] != QUOTE_VERSION or observation['phase'] != 'policy' or
            any(observation[k] != v for k, v in {'episode_id': episode_id,
                'main_trace_sha256': main_trace_sha256, 'world_sha256': world_sha256,
                'retailer_id': retailer_id, 'operation': operation}.items())):
        return {'status': 'inconclusive', 'reason': 'Missing or stale actual policy quote binding'}
    request, response = observation['request'], observation['response']
    if type(request) is not dict or 'address' not in request or any(request.get(k) != v for k, v in request_scope.items()):
        return {'status': 'fail', 'reason': 'Captured quote differs from the task quote scope'}
    address = compare_address(request['address'], expected, implicit_country=implicit_country)
    if address['status'] != 'pass':
        return {**address, 'reason': 'Quote request did not use the required complete address'}
    if response is None or not callable(replay):
        return {'status': 'inconclusive', 'reason': 'Missing successful response or native replay'}
    try:
        native = replay(request)
    except (ValueError, KeyError, TypeError) as error:
        return {'status': 'fail', 'reason': 'Native quote replay rejected: ' + str(error)}
    if type(native) is dict and native.get('pending'):
        return {'status': 'inconclusive', 'reason': 'Pending fulfilment is not a completed shipping quote'}
    # Preserve JSON scalar types: Python equality alone aliases True with 1.
    try:
        matches = json.dumps(response, sort_keys=True, ensure_ascii=False, allow_nan=False) == json.dumps(native, sort_keys=True, ensure_ascii=False, allow_nan=False)
    except (ValueError, TypeError):
        matches = False
    return {'status': 'pass' if matches else 'fail', 'address': address,
            'native_response_matches': matches,
            'reason': 'Captured request address and exact native response replay; exposure remains unknown'}
