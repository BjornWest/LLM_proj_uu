"""Native, page-scoped colour/size gaps for isolated short shopping tasks.

This predicate reads the merchant's carried menu, including zero-stock rows.
It neither removes SKUs nor changes stock, grouping or presentation. A match
is an unavailable requested combination, never a fabricated available target.
"""
from copy import deepcopy
from hashlib import sha256
import json

VERSION = 'native-variant-menu-gap-v1'


def digest(value):
    # Match the existing adapter's stable merchant page IDs.
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def compile_condition(condition):
    allowed = {'schema', 'colour_key', 'size_key', 'target_colour',
               'retailer_id', 'product_id', 'concept_id', 'require_dispatch_stock'}
    if (type(condition) is not dict or condition.get('schema') != VERSION
            or set(condition) - allowed):
        raise ValueError('Declare a native variant-menu-gap condition')
    result = {'colour_key': 'colour', 'size_key': 'size_eu',
              'target_colour': 'black', 'require_dispatch_stock': False, **deepcopy(condition)}
    for key in allowed - {'schema', 'require_dispatch_stock'}:
        if key in result and (type(result[key]) is not str or not result[key].strip()):
            raise ValueError('Menu axes, values and scope IDs must be nonempty strings')
    if (result['colour_key'] == result['size_key']
            or type(result['require_dispatch_stock']) is not bool):
        raise ValueError('Use distinct colour/size axes and an explicit stock flag')
    return result


def witnesses(world, condition):
    """Return existing source tuples plus the absent requested combination.

    Absence is across every carried target-colour SKU on this one page, not
    across in-stock rows alone. Additional selector values are held constant
    for the start/fallback pair, isolating a size change from other changes.
    Optional dispatch stock requires positive stock at a shipping-enabled
    native source for both tuples; supplier eligibility does not satisfy it.
    """
    c = compile_condition(condition)
    colour, size, target = c['colour_key'], c['size_key'], c['target_colour']
    products = {p['public']['product_id']: p['public'] for p in world['products']}
    result = []
    for retailer in world['retailers']:
        rid = retailer['retailer_id']
        if 'retailer_id' in c and rid != c['retailer_id']:
            continue
        offers = {o['sku_id']: o for o in retailer['offers']}
        dispatch = {s['source_id'] for s in retailer['source_locations'] if s['shipping_enabled']}
        for entry in retailer['catalog']:
            pid = entry['product_id']
            public = products[pid]
            if ('product_id' in c and pid != c['product_id'] or
                    'concept_id' in c and public['concept_id'] != c['concept_id']):
                continue
            canonical = {s['sku_id']: s for s in public['skus']}
            for page in entry['pages']:
                axes = list(page['selectors'])
                if not {colour, size} <= set(axes):
                    continue  # A separate product page is not a colour selector.
                rows = []
                for listing in page['listings']:
                    sid = listing['sku_id']
                    sku, offer = canonical[sid], offers[sid]
                    if offer['product_id'] != pid:
                        raise ValueError('Carried menu and native offer product disagree')
                    selection = {a: str(sku[a]) for a in axes}
                    stock = any(offer['stock_by_source'][s] > 0 for s in dispatch)
                    rows.append({'sku_id': sid, 'offer_id': offer['offer_id'],
                                 'selection': selection, 'has_dispatch_stock': stock})
                black = [r for r in rows if r['selection'][colour] == target]
                for before in rows:
                    if (before['selection'][colour] == target or
                            any(r['selection'][size] == before['selection'][size] for r in black)):
                        continue
                    fallback = [r for r in black if all(r['selection'][a] == before['selection'][a]
                                for a in axes if a not in {colour, size})]
                    if c['require_dispatch_stock']:
                        fallback = [r for r in fallback if r['has_dispatch_stock']]
                        if not before['has_dispatch_stock']:
                            continue
                    if not fallback:
                        continue
                    result.append({'retailer_id': rid, 'product_id': pid,
                        'page_id': 'page-' + digest([pid, page['page_key']])[:24],
                        'native_axis_order': axes, 'before': deepcopy(before),
                        'requested_selection': {**before['selection'], colour: target},
                        'requested_tuple_present': False,
                        'existing_fallbacks': deepcopy(fallback),
                        'page_menu_sha256': digest(page),
                        'outcome': 'requested_combination_unavailable'})
    return result


def completion(world, condition):
    """Binary native event for bounded proposal conditioning; no SAT or repair.

    A generator must separately bind its finite proposal/time budget and
    presentation mass. This function alone does not launch generation.
    """
    matches = witnesses(world, condition)
    return {'schema': VERSION, 'condition': compile_condition(condition),
            'world_sha256': digest(world), 'eligible': bool(matches),
            'log_mass': 0.0 if matches else float('-inf'), 'witnesses': matches,
            'qualification': 'Native carried-menu event only; presentation, browser and model evidence separate.'}
