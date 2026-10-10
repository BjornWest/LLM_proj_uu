"""Finite consumer parameters and ordering for centrally admitted delivery routes.

This module does not admit/hide routes or compute charges. Product's oracle owns
route membership and count draws; these helpers validate their weights and sort actual
public projections. They never receive a task or winning offer.
"""
from datetime import date

from environments.website_drafts.component_sampling import probabilities

VERSION = 'website-delivery-options-v1'
COUNT_WEIGHTS = {
    '1': 6, '2': 18, '3': 23, '4': 20, '5': 12, '6': 8, '7': 4,
    '8': 2.5, '9': 1.5, '10': 2, '11': .6, '12': .6,
    '13': .4, '14': .4, '15': .4, '16': .6,
}
ORDER_WEIGHTS = {'arrival': 1, 'cost': 1}


def options(value):
    if (not isinstance(value, dict) or set(value) - {'enabled', 'count_weights', 'order_weights'}
            or type(value.get('enabled')) is not bool):
        raise ValueError('Delivery alternatives require an explicit enabled flag')
    if not value['enabled']:
        if set(value) != {'enabled'}:
            raise ValueError('Disabled delivery sampling cannot contain weights')
        return None
    counts = value.get('count_weights', COUNT_WEIGHTS)
    if (not isinstance(counts, dict) or not counts or any(
            type(k) is not str or not k.isascii() or not k.isdecimal() or
            str(int(k)) != k or not 1 <= int(k) <= 10000 for k in counts)):
        raise ValueError('Count weights require canonical integer strings 1..10000')
    probabilities(counts)
    order = value.get('order_weights', ORDER_WEIGHTS)
    if not isinstance(order, dict) or set(order) != set(ORDER_WEIGHTS):
        raise ValueError('Declare both arrival and cost ordering weights')
    probabilities(order)
    return {'schema': VERSION,
            'count_weights': {k: counts[k] for k in sorted(counts, key=int)},
            'order_weights': {k: order[k] for k in ORDER_WEIGHTS}}


def validate_settings(settings):
    if not isinstance(settings, dict) or settings.get('schema') != VERSION:
        raise ValueError('Invalid normalized delivery settings')
    if set(settings) != {'schema', 'count_weights', 'order_weights'}:
        raise ValueError('Invalid normalized delivery settings')
    settings = options({'enabled': True, 'count_weights': settings['count_weights'],
                        'order_weights': settings['order_weights']})
    return settings


def producer_weights(settings):
    """Convert canonical JSON count keys for Product's integer-keyed API."""
    validated = validate_settings(settings)
    return {int(k): value for k, value in validated['count_weights'].items()}


def _arrival(value):
    if not isinstance(value, dict) or value.get('status') != 'estimated':
        return (1, '', '')
    latest, earliest = value['latest_date'], value['earliest_date']
    date.fromisoformat(latest)
    date.fromisoformat(earliest)
    return (0, latest, earliest)


def _key(mode, amount, arrival, identity):
    if mode not in ORDER_WEIGHTS:
        raise ValueError('Unknown delivery ordering')
    if type(amount) is not int or amount < 0:
        raise ValueError('Delivery ordering requires authoritative integer costs')
    timing = _arrival(arrival)
    return (timing, amount, identity) if mode == 'arrival' else (amount, timing, identity)


def _selection_key(selection):
    return tuple(sorted(selection.items()))


def sorted_projection(value, mode):
    """Order an owned public quote without changing eligibility or its default.

    Arrival means the full basket/group's upper estimated arrival date; unknown
    estimates sort last in arrival mode. Cost means the conditional complete
    basket amount, which includes coupon and shipping effects. The other criterion
    and actual service selection provide deterministic ties. This does not change
    the oracle's selected/default option or hashes.
    """
    result = dict(value)
    result['options'] = sorted(value['options'], key=lambda o: _key(
        mode, o['totalMinor'], o['arrival'], _selection_key(o['selection'])))
    groups = {}
    for offer in value['groupOffers']:
        groups.setdefault(offer['selection_group_id'], []).append(offer)
    result['groupOffers'] = [offer for rows in groups.values() for offer in sorted(rows, key=lambda o: _key(
        mode, o['complete_basket_total_minor'], o['arrival'], _selection_key(o['selection'])))]
    return result


def sorted_item_rows(rows, mode):
    def key(row):
        estimate = ({'status': 'estimated', 'earliest_date': row['arrival'], 'latest_date': row['arrival']}
                    if row['arrival'] else {'status': 'unknown'})
        return _key(mode, row['totalMinor'], estimate, row['id'])
    return sorted(rows, key=key)
