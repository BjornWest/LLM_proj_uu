"""Episode-local neutral model names, with strict within-brand uniqueness."""
from collections import Counter
import math


def normalized_name(name):
    return ' '.join(name.split()).casefold()


def validate_product_names(config):
    if config.get('schema_version') != 'neutral-product-names-v1':
        raise ValueError('Unsupported product name configuration')
    names = config['names']
    if not names or any(not isinstance(n, str) or not n.strip() for n in names):
        raise ValueError('Product names must be nonempty strings')
    if len({normalized_name(n) for n in names}) != len(names):
        raise ValueError('Duplicate neutral product names')
    strength = config['reuse_penalty']
    if isinstance(strength, bool) or not isinstance(strength, (int, float)) or not math.isfinite(strength) or strength < 0:
        raise ValueError('Invalid product name reuse penalty')


def sample_product_name(config, *, brand_id, existing_products, rng):
    """Existing products are canonical public records from this episode.

    The population owner supplies earlier products. No global mutable registry,
    concept-dependent vocabulary, brand style, or feature-dependent naming.
    """
    validate_product_names(config)
    own = {normalized_name(p['model_name']) for p in existing_products if p['brand_id'] == brand_id}
    others = Counter(normalized_name(p['model_name']) for p in existing_products if p['brand_id'] != brand_id)
    weights = {name: 1 / (1 + config['reuse_penalty'] * others[normalized_name(name)])
               for name in config['names'] if normalized_name(name) not in own}
    if not weights:
        raise ValueError('Neutral product name pool exhausted for brand ' + brand_id)
    selected = rng.choices(list(weights), weights=list(weights.values()))[0]
    total = sum(weights.values())
    return selected, {'selected': selected, 'probabilities': {n: w / total for n, w in weights.items()}}
