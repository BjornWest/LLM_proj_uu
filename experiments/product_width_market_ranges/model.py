"""A separately sampled product-width world with declared commercial ranges."""
from collections import Counter

from environments.product_world.market_range import augment_product
from experiments.product_width_preview.model import generate as base_generate


def generate(seed=0, **kwargs):
    """Uses existing acceptance-gated domain sampler, adding only the new feature.

    Allocation is currently range-agnostic. The independent augmentation commutes
    with that allocation; future range-aware retailer profiles must draw it first.
    """
    world = base_generate(seed, **kwargs)
    world['schema_version'] = 'product-width-market-ranges-preview-v1'
    world['products'] = [augment_product(item, seed=seed) for item in world['products']]
    counts = Counter(item['public']['facts'].get('market_range',
                     item['public']['fact_status']['market_range']) for item in world['products'])
    world['summary']['market_ranges'] = dict(counts)
    world['limitations'].append('Opt-in product range declarations; production department/task/memory integration pending.')
    return world
