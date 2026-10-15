"""Concept-only cheapest-listed-offer templates over existing commerce fields.

No attribute matching, delivered-cost optimization, world repair or free-form
grading. The task type is chosen before the world, independently of its prices.
"""
from copy import deepcopy
import random

from experiments.accepted_catalog_commerce import model, package_export
from experiments.accepted_catalog_commerce.catalog_registry import TASK_LABELS
from .adapter import digest
from experiments import source_binding

VERSION = 'website-basic-listed-offer-task-v1'
KIND = 'cheapest_available'
LABELS = {'footwear.walking_shoes': 'walking shoes',
          'footwear.walking_sandals': 'walking sandals',
          'footwear.casual_trainers': 'casual trainers',
          'tops.t_shirts': 'T-shirt',
          'tablets.everyday_media_tablets': 'tablet'}
LABELS.update(TASK_LABELS)


def resolve(value, *, seed, concept_ids):
    """Resolve X before generation; omitted X samples the declared slice equally."""
    if (type(value) is not dict or set(value) - {'kind', 'concept_id', 'comparison_site_id'} or
            value.get('kind') != KIND):
        raise ValueError('Declare a cheapest_available task with an optional concept_id')
    if type(seed) is not int or seed < 0:
        raise ValueError('Task seed must be a nonnegative integer')
    if (type(concept_ids) is not list or not concept_ids or
            any(type(cid) is not str or cid not in package_export.SUPPORTED_CONCEPTS for cid in concept_ids) or
            len(set(concept_ids)) != len(concept_ids)):
        raise ValueError('Declare a unique supported concept slice')
    cid = value.get('concept_id')
    if cid is None:
        rng = random.Random(int(digest([VERSION, seed, 'type']), 16))
        cid = rng.choice(sorted(concept_ids))
    if type(cid) is not str or cid not in concept_ids:
        raise ValueError('Task concept must belong to the declared world slice')
    result = {'kind': KIND, 'concept_id': cid}
    if 'comparison_site_id' in value:
        sid = value['comparison_site_id']
        if type(sid) is not str or sid not in {f'comparison-{i:02d}' for i in range(8)}:
            raise ValueError('Declare a generated comparison_site_id')
        result['comparison_site_id'] = sid
    return result


def make(world, selection, *, surrounding=None):
    """Bind a resolved template without making a product or offer choice."""
    model.validate(world)
    if 'comparison_site_id' in selection:
        from .surrounding_config import validate
        if surrounding is None:
            raise ValueError('Comparison-scoped task requires its surrounding sidecar')
        validate(world, surrounding)
    return _make_bound(world, selection, digest(world), surrounding=surrounding)


def _make_bound(world, selection, world_sha256, *, surrounding=None):
    """Generation-local binding only; public make/reference validate supplied data."""
    spec = resolve(selection, seed=world['seed'], concept_ids=world['config']['concept_ids'])
    cid = spec['concept_id']
    message = (f'Find the cheapest available {LABELS[cid]} across the shops in this world. '
               'Any model, variant or pack is acceptable. '
               'Stock at any shop or warehouse and supplier orders count as available. '
               'Compare the listed price of one sale unit (the whole pack if sold as a pack), '
               'excluding shipping, coupons and cart deals; do not compare normalized per-unit prices. '
               'Tell me the product, selected variant, retailer, price in SEK, and product link. '
               'If none are available, say so. '
               'Do not place an order.')
    task = {'schema_version': VERSION, 'world_id': world['world_id'],
            'world_sha256': world_sha256, 'kind': KIND, 'concept_id': cid,
            'price_basis': 'listed_sku_price', 'quantity': 1,
            'user_message': message, 'memories': []}
    if 'comparison_site_id' in spec:
        sid = spec['comparison_site_id']
        if (surrounding is None or surrounding.get('source_world_id') != world['world_id'] or
                surrounding.get('source_world_sha256') != world_sha256):
            raise ValueError('Comparison-scoped task requires its bound surrounding sidecar')
        sites = [s for s in surrounding['sites'] if s['site_id'] == sid and s['kind'] == 'aggregator']
        if len(sites) != 1:
            raise ValueError('Task comparison site is not generated')
        site = sites[0]
        task['comparison_site_id'] = sid
        task['comparison_scope'] = {'site_name': site['name'], 'surrounding_sha256': digest(surrounding),
            'product_retailer_pairs': [list(pair) for pair in sorted({
                (r['product_id'], r['retailer_id']) for r in site['listings']})]}
        task['user_message'] = message.replace('across the shops in this world.',
            f'among the products and retailer listings shown on the comparison website {site["name"]}. '
            'Only offers from a product–retailer pair listed there qualify. '
            'Check the retailer for the selected variant’s actual price and availability. '
            'You do not need to search retailers absent from that comparison listing.')
    task['task_id'] = 'basic-offer-' + digest(task)[:24]
    return task


def reference(world, task, *, surrounding=None):
    """Full finite offer domain, including every optimal tie and no-match cases."""
    selection = {'kind': task.get('kind'), 'concept_id': task.get('concept_id')}
    if 'comparison_site_id' in task:
        selection['comparison_site_id'] = task['comparison_site_id']
    if not source_binding.compatible(task, make(world, selection, surrounding=surrounding)):
        raise ValueError('Basic task/world binding changed')
    return _reference_bound(world, task)


def _reference_bound(world, task):
    products = {p['public']['product_id']: p['public'] for p in world['products']}
    candidates, unavailable = [], []
    pairs = ({tuple(pair) for pair in task['comparison_scope']['product_retailer_pairs']}
             if 'comparison_site_id' in task else None)
    for retailer in world['retailers']:
        sources = {s['source_id']: s for s in retailer['source_locations']}
        for offer in retailer['offers']:
            if pairs is not None and (offer['product_id'], retailer['retailer_id']) not in pairs:
                continue
            product = products[offer['product_id']]
            if product['concept_id'] != task['concept_id']:
                continue
            supplier = offer['supplier_order']['enabled']
            if type(supplier) is not bool:
                raise ValueError('Invalid supplier-order eligibility flag')
            available = any(offer['stock_by_source'].values())
            dispatch = any(quantity > 0 and sources[sid]['shipping_enabled']
                           for sid, quantity in offer['stock_by_source'].items())
            # Match the public page priority when branch stock and supplier
            # ordering coexist: dispatch, supplier order, then branch stock.
            supply = 'in_stock' if dispatch else 'backorder' if supplier else 'in_stock' if available else 'unavailable'
            if supply == 'unavailable':
                unavailable.append(offer['offer_id'])
                continue
            candidates.append({key: deepcopy(offer[key]) for key in
                               ('offer_id', 'product_id', 'sku_id', 'price_minor', 'currency')})
            candidates[-1].update(retailer_id=retailer['retailer_id'], retailer_name=retailer['name'],
                                  product_name=product['name'], availability=supply)
    candidates.sort(key=lambda row: (row['price_minor'], row['retailer_id'], row['offer_id']))
    price = candidates[0]['price_minor'] if candidates else None
    return {'schema_version': VERSION, 'task_id': task['task_id'], 'world_id': world['world_id'],
            'world_sha256': task['world_sha256'], 'concept_id': task['concept_id'],
            'status': 'match' if candidates else 'no_match', 'price_basis': task['price_basis'],
            'minimum_price_minor': price, 'currency': 'SEK',
            'winners': [deepcopy(row) for row in candidates if row['price_minor'] == price],
            'candidates': candidates, 'unavailable_offer_ids': sorted(unavailable)}


def bind_reference(value, bindings):
    """Private URL projection; require every candidate's actual offer/SKU join."""
    result = deepcopy(value)
    for key in ('candidates', 'winners'):
        for row in result[key]:
            bound = bindings['retailer_offers'][row['offer_id']]
            if any(bound[k] != row[k] for k in ('retailer_id', 'product_id', 'sku_id')):
                raise ValueError('Basic reference URL binding changed')
            row.update({k: deepcopy(bound[k]) for k in ('url', 'required_selection', 'selection', 'url_behavior')})
    return result
