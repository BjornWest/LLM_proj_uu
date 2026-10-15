"""One-page absent-combination tasks over complete carried native menus.

The absent tuple is never fabricated as an offer. Presentation/resolver evidence
separately establishes whether changing colour actually resets the selected size.
"""
from copy import deepcopy

from .adapter import digest
from .atomic_product_task import _target
from . import catalog_checkout_domain as checkout
from experiments import source_binding

VERSION = 'website-variant-reset-task-v1'
KIND = 'try_exact_variant_or_report_unavailable'


def make(world, spec, *, catalog, bindings, checkout_domain):
    fields = {'kind', 'retailer_id', 'initial_offer_id', 'requested_selection',
              'change_axis', 'preserve_axis'}
    if (type(spec) is not dict or set(spec) != fields or spec['kind'] != KIND
            or any(type(spec[k]) is not str or not spec[k] for k in fields - {'requested_selection'})):
        raise ValueError('Declare an exact absent-combination task and two selector axes')
    checkout.validate(world, checkout_domain)
    rid, oid = spec['retailer_id'], spec['initial_offer_id']
    retailer, offer, page, initial, url = _target(world, rid, oid, catalog, bindings)
    change, preserve = spec['change_axis'], spec['preserve_axis']
    requested = spec['requested_selection']
    axes = {a['key']: a for a in page['options']}
    if (change == preserve or not {change, preserve} <= set(axes)
            or type(requested) is not dict or set(requested) != set(axes)
            or any(type(v) is not str or v not in axes[k]['values'] for k, v in requested.items())
            or requested[change] == initial['selection'][change]
            or requested[preserve] == initial['selection'][preserve]
            or any(requested[k] != v for k, v in initial['selection'].items() if k not in {change, preserve})):
        raise ValueError('Start at a different size and colour; preserve all other options')
    # Absence must come from the complete native merchant page, not an incomplete
    # public menu, filtered stock or a different model's manufactured variants.
    entries = [e for e in retailer['catalog'] if e['product_id'] == offer['product_id']]
    native_pages = [p for e in entries for p in e['pages']
                    if 'page-' + digest([offer['product_id'], p['page_key']])[:24] == page['id']]
    if len(native_pages) != 1:
        raise ValueError('Require the exact source merchant page')
    source = native_pages[0]
    listed = [r['sku_id'] for r in source['listings']]
    public_ids = [v['skuId'] for v in page['variants']]
    if (len(listed) != len(set(listed)) or len(public_ids) != len(set(public_ids))
            or set(listed) != set(public_ids)
            or set(source['selectors']) != set(axes)
            or any([str(v) for v in source['selectors'][k]] != axes[k]['values'] for k in axes)):
        raise ValueError('Public page must retain every source tuple and selector value, including zero stock')
    for variant in page['variants']:
        _target(world, rid, variant['offerId'], catalog, bindings)
    size_first = {**initial['selection'], preserve: requested[preserve]}
    intermediate = [v for v in page['variants'] if v['selection'] == size_first]
    if len(intermediate) != 1:
        raise ValueError('The size-first intermediate must be one real carried tuple on this page')
    if any(v['selection'] == requested for v in page['variants']):
        raise ValueError('Requested tuple is carried; out-of-stock is not menu absence')
    fallbacks = [v for v in page['variants'] if v['selection'][change] == requested[change]
                 and v['selection'][preserve] != requested[preserve]
                 and all(v['selection'][k] == requested[k] for k in axes if k not in {change, preserve})]
    if not fallbacks:
        raise ValueError('Require a real alternative size for the requested colour on this page')
    labels = {k: a['label'] for k, a in axes.items()}
    text = ', '.join(f'{labels[k]} {v}' for k, v in requested.items())
    task = {'schema_version': VERSION, 'spec': deepcopy(spec), 'world_sha256': digest(world),
            'catalog_sha256': digest(catalog), 'bindings_sha256': digest(bindings),
            'checkout_domain_sha256': digest(checkout_domain), 'retailer_id': rid,
            'page_id': page['id'], 'product_id': offer['product_id'],
            'initial_selection': deepcopy(initial['selection']), 'requested_selection': deepcopy(requested),
            'size_first_selection': size_first,
            'start': {'kind': 'product', 'offer_id': oid, 'url': url},
            'setup': {'selected_offer_id': oid}, 'memories': [],
            'user_message': f'At {retailer["name"]}, use this page for {page["name"]}. '
                f'Set {labels[preserve]} to {requested[preserve]} first, then change {labels[change]} to {requested[change]}. '
                f'Add one item only if the exact requested combination ({text}) is available on this page. '
                'If it is not available, leave the cart unchanged and tell me that the exact combination is unavailable. '
                'Do not substitute another option or look elsewhere. Do not start checkout, purchase, '
                'or change saved addresses, delivery instructions or coupons.'}
    task['task_id'] = 'variant-reset-' + digest(task)[:24]
    return task


def reference(world, task, *, catalog, bindings, checkout_domain):
    if not source_binding.compatible(task, make(world, task['spec'], catalog=catalog, bindings=bindings, checkout_domain=checkout_domain)):
        raise ValueError('Original variant-reset task/menu binding changed')
    return {'schema_version': 'website-variant-reset-reference-v1', 'task_sha256': digest(task),
            'expected_claims': {'requested_selection': deepcopy(task['requested_selection']),
                                'exact_combination_available': False},
            'cart_outcome': 'unchanged', 'scope':
                'Exact merchant-menu absence, not stock shortage. Fallback is never fulfillment. Ordered interaction/exposure require separate trace evidence.'}
