"""Explicit per-page selector ordering over complete native public catalogs.

No layout draw or merchant-menu change. Copy the full catalog once and delegate
each targeted page to the already accepted colour-before-size projection.
"""
from copy import deepcopy

from . import variant_axis_order as projection

VERSION = 'website-page-option-order-v1'
DEFAULT_AXES = {'colour_key': 'colour', 'size_key': 'size_eu'}


def options(value=None):
    if value is None:
        return None
    if type(value) is not dict or not value:
        raise ValueError('Option order requires an explicit nonempty retailer/page mapping')
    result = {}
    for retailer_id, pages in value.items():
        if type(retailer_id) is not str or not retailer_id or type(pages) is not dict or not pages:
            raise ValueError('Declare retailer IDs with nonempty page mappings')
        result[retailer_id] = {}
        for page_id, axes in pages.items():
            if type(page_id) is not str or not page_id or type(axes) is not dict or set(axes)-set(DEFAULT_AXES):
                raise ValueError('Use page IDs and existing colour_key/size_key only')
            chosen = {**DEFAULT_AXES, **axes}
            if (any(type(key) is not str or not key for key in chosen.values()) or
                    chosen['colour_key'] == chosen['size_key']):
                raise ValueError('Declare distinct existing colour and size axis keys')
            result[retailer_id][page_id] = chosen
    return result


def project_catalog(catalog, *, retailer_id, settings=None):
    """Return native input unchanged unless explicitly targeted.

    Full native catalog/other-page hashes surround the per-page inverse proofs.
    Only target-page options change. The result shares no mutable data with the
    source; multiple targets require one full-catalog copy, not one per page.
    """
    settings = options(settings)
    if settings is None or retailer_id not in settings:
        return catalog, None
    if catalog.get('siteId') != retailer_id:
        raise ValueError('Option order must bind the actual public retailer')
    pages = catalog['products']
    index = {}
    for position, page in enumerate(pages):
        if page['id'] in index:
            raise ValueError('Public page identity is ambiguous')
        index[page['id']] = position
    if set(settings[retailer_id])-set(index):
        raise ValueError('Option-order target page is absent from the retailer')
    result = deepcopy(catalog)
    page_evidence = {}
    for page_id, axes in settings[retailer_id].items():
        # Small wrappers keep projection validation/inverse local to this page.
        wrapper = {'siteId': retailer_id, 'products': [pages[index[page_id]]]}
        changed, evidence = projection.project(wrapper, retailer_id=retailer_id,
                                               page_id=page_id, **axes)
        result['products'][index[page_id]] = changed['products'][0]
        page_evidence[page_id] = evidence
    evidence = {'schema': VERSION, 'retailer_id': retailer_id,
        'settings': deepcopy(settings[retailer_id]), 'pages': page_evidence,
        'before_catalog_sha256': projection._digest(catalog),
        'after_catalog_sha256': projection._digest(result),
        'changed_pages': [p for p, row in page_evidence.items() if row['changed']],
        'scope': 'Only declared existing page options order; no tuple, content, stock, price or URL identity changes.'}
    if restore_catalog(result, evidence) != catalog:
        raise ValueError('Option order has no exact complete-catalog inverse')
    return result, evidence


def validate_catalog(catalog, *, retailer_id, settings):
    """Preflight every requested page/tuple before any site host is published."""
    settings = options(settings)
    if settings is None or retailer_id not in settings:
        return
    if catalog.get('siteId') != retailer_id:
        raise ValueError('Option order must bind the actual public retailer')
    identities = [page['id'] for page in catalog['products']]
    if len(identities) != len(set(identities)):
        raise ValueError('Public page identity is ambiguous')
    for page_id, axes in settings[retailer_id].items():
        page = projection._page(catalog, page_id)
        projection.project({'siteId': retailer_id, 'products': [page]},
                           retailer_id=retailer_id, page_id=page_id, **axes)


def restore_catalog(catalog, evidence):
    if (evidence.get('schema') != VERSION or catalog.get('siteId') != evidence['retailer_id']
            or projection._digest(catalog) != evidence['after_catalog_sha256']):
        raise ValueError('Option-order evidence does not bind this copied catalog')
    result = deepcopy(catalog)
    for page in result['products']:
        if page['id'] in evidence['pages']:
            wrapper = {'siteId': result['siteId'], 'products': [page]}
            restored = projection.restore(wrapper, evidence['pages'][page['id']])
            page['options'] = restored['products'][0]['options']
    if projection._digest(result) != evidence['before_catalog_sha256']:
        raise ValueError('Option order cannot recover the complete native catalog')
    return result
