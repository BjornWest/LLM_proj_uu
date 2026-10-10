"""Explicit, isolated merchant-page control order; no tuple or stock changes.

Preparation boundary only. A fresh consumer must adopt the returned catalog
before publishing its data/URL bindings. No existing Runtime or host is patched.
Native menu conditioning and task/grading semantics remain producer-owned.
"""
from copy import deepcopy
from hashlib import sha256
import json

VERSION = 'website-colour-before-size-projection-v1'


def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                             separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _page(catalog, page_id):
    pages = [p for p in catalog['products'] if p['id'] == page_id]
    if len(pages) != 1:
        raise ValueError('Declare exactly one existing merchant page')
    return pages[0]


def project(catalog, *, retailer_id, page_id, colour_key='colour', size_key='size_eu'):
    """Copy one page's options, moving colour immediately before size.

    Other controls retain their relative order. A page already ordered this way
    is unchanged. Missing axes fail rather than adding invented controls.
    Returns (public_catalog, private_projection_evidence), never native truth.
    """
    if not retailer_id or catalog.get('siteId') != retailer_id:
        raise ValueError('Projection must name the actual public retailer')
    if not colour_key or not size_key or colour_key == size_key:
        raise ValueError('Declare distinct colour and size controls')
    page = _page(catalog, page_id)
    axes = [option['key'] for option in page['options']]
    if len(axes) != len(set(axes)) or not {colour_key, size_key} <= set(axes):
        raise ValueError('Page needs unique existing colour and size controls')
    values = {o['key']: o['values'] for o in page['options']}
    identities, tuples = [set(), set(), set()], set()
    for variant in page['variants']:
        selection = variant['selection']
        if set(selection) != set(axes) or any(selection[k] not in values[k] for k in axes):
            raise ValueError('Every tuple must bind the existing merchant controls')
        identity = (variant['key'], variant['skuId'], variant['offerId'])
        selected = tuple(selection[k] for k in axes)
        if any(value in seen for value, seen in zip(identity, identities)) or selected in tuples:
            raise ValueError('Ambiguous native identity or selector tuple')
        for value, seen in zip(identity, identities):seen.add(value)
        tuples.add(selected)
    if not tuples:
        raise ValueError('An empty merchant menu cannot realize this variation')
    result = deepcopy(catalog)
    changed = _page(result, page_id)
    if axes.index(colour_key) > axes.index(size_key):
        colour = changed['options'].pop(axes.index(colour_key))
        changed['options'].insert(axes.index(size_key), colour)
    after = [option['key'] for option in changed['options']]
    # Verify full structural inverse, including prose, tuples, stock and prices.
    inverse = deepcopy(result)
    back = _page(inverse, page_id)
    keyed = {option['key']: option for option in back['options']}
    back['options'] = [keyed[key] for key in axes]
    if inverse != catalog:
        raise ValueError('Projection changed more than the declared options order')
    evidence = {'schema': VERSION, 'retailer_id': retailer_id, 'page_id': page_id,
                'colour_key': colour_key, 'size_key': size_key,
                'before_axis_order': axes, 'after_axis_order': after,
                'before_catalog_sha256': _digest(catalog), 'after_catalog_sha256': _digest(result),
                'tuple_count': len(page['variants']), 'changed': axes != after,
                'scope': 'Only options order; no native menu/stock/price/task change or runtime adoption.'}
    return result, evidence


def restore(catalog, evidence):
    """Require the exact copied projection and recover its semantic inverse."""
    if (evidence.get('schema') != VERSION or catalog.get('siteId') != evidence['retailer_id']
            or _digest(catalog) != evidence['after_catalog_sha256']):
        raise ValueError('Projection evidence differs from the copied catalog')
    result = deepcopy(catalog)
    page = _page(result, evidence['page_id'])
    if [o['key'] for o in page['options']] != evidence['after_axis_order']:
        raise ValueError('Copied axis order changed')
    keyed = {o['key']: o for o in page['options']}
    page['options'] = [keyed[k] for k in evidence['before_axis_order']]
    if _digest(result) != evidence['before_catalog_sha256']:
        raise ValueError('Projection cannot recover the original catalog')
    return result
