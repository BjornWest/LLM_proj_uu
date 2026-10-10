"""Opt-in bounded factual-detail vocabulary; no candidates or expected values."""
from copy import deepcopy
import math

VERSION = 'shopping-factual-details-v1'
PROPERTIES = {
    'arrival_days': {'kind': 'integer', 'description': 'Calendar days until delivery arrives, not dispatch or pickup readiness.'},
    'dispatch_days': {'kind': 'integer', 'description': 'Days before the retailer dispatches the item, not delivery arrival.'},
    'shipping_cost': {'kind': 'money', 'description': 'Explicit shipping charge, with its stated currency; never calculate it from a subtotal.'},
    'quantity': {'kind': 'integer', 'description': 'Explicit number of units in the recommended offer or quote.'},
    'size_eu': {'kind': 'number', 'description': 'Explicit EU shoe size. Do not convert US/UK sizes or fill the size from the request.'},
    'colour': {'kind': 'string', 'description': 'Explicit product colour. Do not infer it from a title, URL or request.'},
}


def compile_details(task):
    config = task.get('response_requirements', {}).get('factual_details')
    if config is None:
        return None
    if not isinstance(config, dict) or set(config) - {'weights', 'penalty_floor', 'negative_cap', 'positive_cap'}:
        raise ValueError('Invalid factual-detail configuration')
    if task['query']['operation'] != 'select' or len(task.get('lines', [None])) != 1:
        raise ValueError('Factual details currently require single-product selection')
    weights = config.get('weights')
    if not isinstance(weights, dict) or not weights or set(weights) - set(PROPERTIES):
        raise ValueError('Unknown or empty factual-detail property set')
    for v in weights.values():
        if type(v) not in (int, float) or not math.isfinite(v) or v < 0 or v > 1:
            raise ValueError('Detail weights must be finite numbers in [0, 1]')
    settings = {'penalty_floor': 0.1, 'negative_cap': 1.0, 'positive_cap': 1.0, **{k: v for k, v in config.items() if k != 'weights'}}
    for v in settings.values():
        if type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1:
            raise ValueError('Detail bounds must be finite numbers in [0, 1]')
    return {'schema_version': VERSION, 'weights': deepcopy(weights), **settings,
            'properties': {p: deepcopy(PROPERTIES[p]) for p in weights},
            'unrelated_facts': 'not_extracted_or_scored'}
