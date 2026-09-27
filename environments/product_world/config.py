"""Explicit authored priors, not measured retail frequencies or outcome quotas."""
import copy
import math
from environments.shopping_intent.catalog import FAMILIES
from environments.shopping_intent.semantics import RELATIONS

FAMILY_IDS = ('footwear', 'laptops', 'dog_food', 'cat_food', 'beer', 'wine')
WINE_DARK_GRAPES = {'Pinot Noir', 'Cabernet Sauvignon'}


def wine_colours(grapes):
    """Allowed colours for a COMPLETE composition in this four-variety vocabulary.

    White-from-dark-grape wine remains valid. A partial `contains` requirement
    is not a complete composition and must not use this as an implication.
    """
    return ('white', 'red', 'rosé') if WINE_DARK_GRAPES.intersection(grapes) else ('white',)


AXES = {
    'footwear': {'size_eu': 3, 'colour': 2, 'width': 2},
    'laptops': {'ram_gb': 2, 'storage_gb': 2, 'keyboard_layout': 1},
    'dog_food': {'net_weight_kg': 2, 'recipe': 2},
    'cat_food': {'net_weight_kg': 2, 'recipe': 2},
    'beer': {'pack_count': 2, 'volume_ml': 2},
    'wine': {'pack_count': 2, 'volume_ml': 2, 'vintage': 2},
}


def token(value):
    if type(value) is bool: return 'true' if value else 'false'
    return str(value)


def domains():
    result = {}
    for family in FAMILY_IDS:
        for attr in FAMILIES[family].attributes:
            if attr.key == 'ingredients': continue  # Composition is generated from recipe, below.
            values = (False, True) if attr.value_type == 'boolean' else attr.values
            result[family + '.' + attr.key] = list(values)
    return result


def defaults():
    weights = {key: {token(v): 1.0 for v in values} for key, values in domains().items()}
    weights['footwear.waterproof'] = {'false': .65, 'true': .35}
    # New explicit footwear blueprints opt into these activities. Preserve legacy
    # default sampling until a typed assortment requests the additional styles.
    weights['footwear.activity'].update(formal=0.0, beach=0.0)
    weights['wine.sparkling'] = {'false': .75, 'true': .25}
    weights['beer.unfiltered'] = {'false': .6, 'true': .4}
    for family in ('dog_food', 'cat_food'):
        weights[family + '.complete_food'] = {'false': .1, 'true': .9}
    return {'family_weights': {f: 1.0 for f in FAMILY_IDS}, 'field_weights': weights,
            'axis_option_counts': {f + '.' + k: v for f, axes in AXES.items() for k, v in axes.items()},
            'variant_omission_probability': .15, 'extra_protein_probability': .2,
            'wheat_probability': .3, 'reference_price_multiplier': 1.0}


def _number(value, label, *, probability=False, positive=False):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(label + ' must be a finite number')
    if value < 0 or (positive and value == 0) or (probability and value > 1):
        raise ValueError('Out-of-range ' + label)


def _weights(base, patch, label):
    if not isinstance(patch, dict) or set(patch) - set(base):
        raise ValueError('Unknown weights in ' + label)
    result = {**base, **patch}
    for value in result.values(): _number(value, label)
    # Normalize during sampling, avoiding overflow for large but finite relative weights.
    if not any(result.values()): raise ValueError(label + ' needs a positive weight')
    return result


def resolve_config(patch=None):
    result = defaults()
    if patch is None: return result
    if not isinstance(patch, dict) or set(patch) - set(result): raise ValueError('Unknown config field')
    result['family_weights'] = _weights(result['family_weights'], patch.get('family_weights', {}), 'family_weights')
    fields = patch.get('field_weights', {})
    if not isinstance(fields, dict) or set(fields) - set(result['field_weights']): raise ValueError('Unknown field_weights field')
    for key, value in fields.items():
        result['field_weights'][key] = _weights(result['field_weights'][key], value, key)
    if not any(weight > 0 and result['field_weights']['wine.wine_colour'][colour] > 0
               for grape, weight in result['field_weights']['wine.grapes'].items()
               for colour in wine_colours([grape])):
        raise ValueError('Wine grape/colour weights allow no coherent composition')
    if not any(result['field_weights']['beer.origin_country'][country] > 0 and
               result['field_weights']['beer.production_region'][region] > 0
               for country, region in RELATIONS['beer'][0]['rows']):
        raise ValueError('Beer location weights allow no coherent country/region combination')
    counts = patch.get('axis_option_counts', {})
    if not isinstance(counts, dict) or set(counts) - set(result['axis_option_counts']): raise ValueError('Unknown axis_option_counts field')
    for key, value in counts.items():
        if type(value) is not int or not 1 <= value <= len(domains()[key]): raise ValueError('Invalid option count: ' + key)
        result['axis_option_counts'][key] = value
    for key in ('variant_omission_probability', 'extra_protein_probability', 'wheat_probability'):
        if key in patch:
            _number(patch[key], key, probability=True); result[key] = patch[key]
    if 'reference_price_multiplier' in patch:
        value = patch['reference_price_multiplier']; _number(value, 'reference_price_multiplier', positive=True)
        if not .01 <= value <= 100: raise ValueError('reference_price_multiplier must be in [0.01, 100]')
        result['reference_price_multiplier'] = value
    return copy.deepcopy(result)
