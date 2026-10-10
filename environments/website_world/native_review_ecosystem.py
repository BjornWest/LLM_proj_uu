"""Additive rich review choices; historic v1/v2 sidecars replay unchanged."""
from copy import deepcopy
from . import ecosystem, rich_ecosystem
from .native_review_pages import LAYOUTS, VERSION as PRESENTATION

VERSION = 'native-rich-surrounding-v3'
NAMES = ('Review Atlas', 'The Detail Journal', 'Reader Circle', 'Product Notebooks',
         'Everyday Opinions', 'The Choice Desk', 'Owner Notes', 'Model Review')


def options(value=None):
    raw = {} if value is None else deepcopy(value)
    if type(raw) is not dict:
        raise ValueError('Rich review options must be an object')
    allowed = {*rich_ecosystem.DEFAULTS, 'coverage_seed', 'family_weights', 'review_assignment', 'review_page_size', 'comparison_search_probability'}
    if set(raw) - allowed:raise ValueError('Unknown rich review option')
    weights = rich_ecosystem.weights(raw.get('review_layout_weights', dict.fromkeys(LAYOUTS, 1)), dict.fromkeys(LAYOUTS, 1), 'review layouts')
    legacy = {k: v for k, v in raw.items() if k not in ('review_layout_weights', 'review_assignment', 'review_page_size')}
    result = rich_ecosystem.options(legacy)
    assignment = raw.get('review_assignment', 'distinct' if result['review_count'] == 3 and 'review_layout_weights' not in raw else 'independent')
    if assignment not in ('distinct', 'independent'):
        raise ValueError('Unknown rich review assignment')
    if assignment == 'distinct' and result['review_count'] > sum(v > 0 for v in weights.values()):
        raise ValueError('Distinct review assignment exceeds positive layout support')
    size = raw.get('review_page_size', 12)
    if type(size) is not int or not 1 <= size <= 50:raise ValueError('Review page size must be 1..50')
    result.update(review_layout_weights=weights, review_assignment=assignment, review_page_size=size)
    return result


def generate(world, controls=None):
    return _generate_bound(world, controls, ecosystem.digest(world))


def _generate_bound(world, controls, world_sha256):
    controls = options(controls)
    legacy = {k: deepcopy(v) for k, v in controls.items() if k not in ('review_assignment', 'review_page_size', 'review_layout_weights')}
    result = rich_ecosystem._generate_bound(world, legacy, world_sha256)
    remaining = deepcopy(controls['review_layout_weights'])
    names = sorted(NAMES, key=lambda name: ecosystem.draw(world['seed'], VERSION, 'publication-name', name))
    reviews = [s for s in result['sites'] if s['kind'] == 'product_reviews']
    for index, site in enumerate(reviews):
        site['layout'] = rich_ecosystem.choice(world['seed'], site['site_id'], VERSION + '/review-layout', remaining)
        if controls['review_assignment'] == 'distinct':remaining[site['layout']] = 0
        site['name'] = names[index]
        site['review_presentation'] = {'version': PRESENTATION, 'page_size': controls['review_page_size']}
    result.update(schema_version=VERSION, controls=controls)
    return result


def validate(world, sidecar):
    if sidecar.get('schema_version') != VERSION or sidecar.get('source_world_id') != world['world_id'] or sidecar.get('source_world_sha256') != ecosystem.digest(world):
        raise ValueError('Rich review sidecar belongs to another world')
    if sidecar != generate(world, sidecar['controls']):raise ValueError('Rich review sidecar does not replay')
    return sidecar
