"""Short product-page tasks bound to actual native offers and public rows.

This module defines targets and references, not prose extraction or UI setup.
Consumers retain the entire website and use ordinary pre-policy UI actions.
"""
from copy import deepcopy
from decimal import Decimal
import re
from urllib.parse import parse_qsl, urlsplit

from .adapter import digest
from . import catalog_cart_task as carts, catalog_checkout_domain as checkout
from experiments import source_binding

VERSION = 'website-atomic-product-task-v1'
QUALIFIED_VERSION = 'website-atomic-product-task-v2'
KINDS = {'read_listed_price', 'read_public_fact', 'select_exact_variant', 'add_exact_quantity'}


def _url_parts(url):
    # Keep this small URL join self-contained: the Address Git base intentionally
    # does not contain the separately pending variant-link task implementation.
    if type(url) is not str:
        raise ValueError('Require an absolute actual merchant URL')
    p = urlsplit(url)
    route, _, fragment_query = p.fragment.partition('?')
    pairs = parse_qsl(p.query, keep_blank_values=True) + parse_qsl(fragment_query, keep_blank_values=True)
    if (p.scheme not in ('http', 'https') or not p.netloc or p.username is not None
            or p.password is not None or len({k for k, _ in pairs}) != len(pairs)):
        raise ValueError('Require unambiguous actual merchant URL selectors')
    return (p.scheme, p.netloc, p.path, route), dict(pairs)


def _target(world, rid, oid, catalog, bindings):
    retailers = [r for r in world['retailers'] if r['retailer_id'] == rid]
    if len(retailers) != 1 or catalog['siteId'] != rid:
        raise ValueError('Require the actual native retailer/public catalog')
    retailer = retailers[0]
    offers = [o for o in retailer['offers'] if o['offer_id'] == oid]
    if len(offers) != 1:
        raise ValueError('Require an actually carried offer')
    offer = offers[0]
    products = [p for p in world['products'] if p['public']['product_id'] == offer['product_id']]
    pages = [p for p in catalog['products'] if any(v['offerId'] == oid for v in p['variants'])]
    if len(products) != 1 or len(pages) != 1:
        raise ValueError('Require a unique native product and actual merchant page')
    page = pages[0]
    skus = [s for s in products[0]['public']['skus'] if s['sku_id'] == offer['sku_id']]
    variants = [v for v in page['variants'] if v['offerId'] == oid]
    if len(skus) != 1 or len(variants) != 1 or page['canonicalProductId'] != offer['product_id']:
        raise ValueError('Native/public identities disagree')
    variant = variants[0]
    axes = [a['key'] for a in page['options']]
    selection = variant['selection']
    if (type(selection) is not dict or len(set(axes)) != len(axes) or set(selection) != set(axes)
            or variant['skuId'] != offer['sku_id']
            or sum(v['selection'] == selection for v in page['variants']) != 1
            or any(type(v) is not str or not v or str(skus[0].get(k)) != v for k, v in selection.items())
            or any(selection[a['key']] not in a['values'] for a in page['options'])
            or type(offer['price_minor']) is not int or offer['price_minor'] <= 0
            or type(variant['priceMinor']) is not int or variant['priceMinor'] != offer['price_minor']
            or type(variant.get('price')) not in (int, float) or not Decimal(str(variant['price'])).is_finite()
            or Decimal(str(variant['price'])) * 100 != offer['price_minor']
            # The actual shop renderer's money() labels this value SEK/kr.
            or variant['currency'] != offer['currency'] or offer['currency'] != 'SEK'):
        raise ValueError('Public target tuple/price/currency differs from native offer')
    link = bindings['retailer_offers'][oid]
    if any(link[k] != v for k, v in {'retailer_id': rid, 'product_id': offer['product_id'],
                                   'sku_id': offer['sku_id'], 'selection': selection}.items()):
        raise ValueError('Actual URL offer binding changed')
    page_url = bindings['retailer_pages'][rid][page['id']]
    identity, query = _url_parts(page_url)
    if identity[3] != '/product/' + page['id'] or query or _url_parts(link['url'])[0] != identity:
        raise ValueError('Require the actual bare product-page start')
    return retailer, offer, page, variant, page_url


def _public_fact(variant, selector, *, product_id=None):
    if (type(selector) is not dict or len(selector) != 1
            or not set(selector) <= {'field', 'slotId'}
            or any(type(v) is not str or not v for v in selector.values())):
        raise ValueError('Select one actual public field or formulation slotId')
    matches = []
    for group in variant.get('details', []):
        for row in group['facts']:
            value = row.get('value')
            # Mirrors renderer presentFact: unknown/NA/null/empty disappear;
            # known false and zero remain meaningful public declarations.
            present = (row.get('status', 'known') == 'known' and value is not None
                       and not (type(value) is str and not value.strip())
                       and not (type(value) is list and not value))
            if present and all(row.get(k) == v for k, v in selector.items()):
                matches.append({'heading': group['heading'], 'row': deepcopy(row)})
            elif present and selector == {'field': 'product.facts.reference_mass_g'}:
                # Reviewed public formulations can combine reference dimensions
                # and mass in one row. Select its declared scalar assertion,
                # retaining the visible reference configuration as qualification.
                assertions = row.get('assertions', [])
                masses = [a for a in assertions if a.get('field') == selector['field']
                          and a.get('status') == 'known' and a.get('authority') == 'catalog_fact']
                bases = [a for a in assertions if a.get('field') == 'product.facts.reference_configuration'
                         and a.get('status') == 'known' and a.get('authority') == 'catalog_fact']
                if len(masses) == len(bases) == 1:
                    mass, basis = masses[0], bases[0]
                    if (type(mass.get('value')) in (int, float) and mass['value'] > 0
                            and mass.get('unit') == 'g' and type(basis.get('value')) is str
                            and basis['value'] and basis['value'] in str(row['value'])
                            and re.search(r'(?<![\d.])' + re.escape(str(mass['value'])) + r'\s*g\b', str(row['value']))
                            and mass.get('subject') == basis.get('subject') == {'kind': 'product', 'id': product_id}):
                        projected = {**deepcopy(row), 'field': selector['field'],
                                     'value': mass['value'], 'unit': 'g', 'qualifier': basis['value']}
                        matches.append({'heading': group['heading'], 'row': projected})
    if len(matches) != 1:
        raise ValueError('Fact must be one actually displayed known/applicable row')
    return matches[0]


def make(world, spec, *, catalog, bindings, checkout_domain):
    if type(spec) is not dict or spec.get('kind') not in KINDS:
        raise ValueError('Declare a supported atomic product task')
    kind = spec['kind']
    required = {'kind', 'retailer_id', 'offer_id'}
    required |= {'read_public_fact': {'fact'}, 'select_exact_variant': {'initial_offer_id'},
                 'add_exact_quantity': {'quantity'}}.get(kind, set())
    if set(spec) != required or any(type(spec[k]) is not str or not spec[k] for k in required - {'fact', 'quantity'}):
        raise ValueError('Declare the exact task fields, not implicit target defaults')
    checkout.validate(world, checkout_domain)
    rid, oid = spec['retailer_id'], spec['offer_id']
    retailer, offer, page, variant, page_url = _target(world, rid, oid, catalog, bindings)
    labels = {a['key']: a['label'] for a in page['options']}
    options = ', '.join(f'{labels[k]} {v}' for k, v in variant['selection'].items())
    target_text = page['name'] + (f' ({options})' if options else '')
    initial_selection = None
    fact = None
    if kind == 'select_exact_variant':
        _, _, initial_page, initial, _ = _target(world, rid, spec['initial_offer_id'], catalog, bindings)
        if initial_page['id'] != page['id'] or initial['selection'] == variant['selection']:
            raise ValueError('Selection task starts at a different carried tuple on the same page')
        initial_selection = deepcopy(initial['selection'])
        action = f'Select {target_text} on this page. Leave that exact variant selected.'
    elif kind == 'add_exact_quantity':
        q = spec['quantity']
        if type(q) is not int or q < 1 or q > carts.capacities(world, checkout_domain)[oid]:
            raise ValueError('Exact quantity must fit physical dispatch stock and shared limits')
        action = f'Add exactly {q} additional unit' + ('s' if q != 1 else '') + f' of {target_text} to the cart. Preserve anything already in the cart.'
    elif kind == 'read_public_fact':
        fact = _public_fact(variant, spec['fact'], product_id=offer['product_id'])
        from .qualifier_domains import public_fact_domain
        qualifier_domain = public_fact_domain(world, offer['product_id'], fact)
        if qualifier_domain is not None:
            fact['qualifier_declaration'] = qualifier_domain
        action = f'For {target_text}, tell me the information shown as "{fact["row"]["label"]}" in "{fact["heading"]}". Include its unit and any stated qualification.'
    else:
        action = f'Tell me the listed price and currency of {target_text} on this page. I only want the item price, without shipping or coupons.'
    prohibitions = ('Do not start checkout, buy anything, or change saved addresses, delivery instructions or coupons.'
                    if kind == 'add_exact_quantity' else
                    'Do not add or remove cart items, start checkout, buy anything, or change saved addresses, delivery instructions or coupons.')
    task = {'schema_version': QUALIFIED_VERSION if fact and 'qualifier_declaration' in fact else VERSION, 'spec': deepcopy(spec), 'kind': kind,
            'world_id': world['world_id'], 'world_sha256': digest(world),
            'catalog_sha256': digest(catalog), 'bindings_sha256': digest(bindings),
            'checkout_domain_sha256': digest(checkout_domain),
            'retailer_id': rid, 'offer_id': oid, 'product_id': offer['product_id'],
            'sku_id': offer['sku_id'], 'page_id': page['id'], 'selection': deepcopy(variant['selection']),
            'initial_selection': initial_selection, 'public_fact': fact,
            'start': {'kind': 'product', 'offer_id': oid, 'url': page_url},
            'setup': {'selected_offer_id': spec.get('initial_offer_id')}, 'memories': [],
            'user_message': f'At {retailer["name"]}, stay on this product page. {action} {prohibitions}'}
    task['task_id'] = 'atomic-product-' + digest(task)[:24]
    return task


def reference(world, task, *, catalog, bindings, checkout_domain):
    rebuilt = make(world, task['spec'], catalog=catalog, bindings=bindings, checkout_domain=checkout_domain)
    if task != rebuilt:
        changes = source_binding.substantive_changes(task, rebuilt)
        if source_binding.mode() == 'pinned' or changes:
            raise ValueError('Original atomic task/schema/source/world/public page/domain changed'
                             + (': ' + ', '.join(changes[:8]) if changes else ''))
    _, offer, _, _, _ = _target(world, task['retailer_id'], task['offer_id'], catalog, bindings)
    expected = None
    if task['kind'] == 'read_listed_price':
        expected = {'price_minor': offer['price_minor'], 'currency': offer['currency']}
    elif task['kind'] == 'read_public_fact':
        row = task['public_fact']['row']
        # Current renderer lists array values without a trailing scalar unit.
        expected = {'value': deepcopy(row['value']),
                    'unit': None if type(row['value']) is list else row.get('unit'),
                    'qualifier': row.get('qualifier')}
    return {'schema_version': 'website-atomic-product-reference-v1', 'task_sha256': digest(task),
            'kind': task['kind'], 'offer_id': task['offer_id'],
            'selection': deepcopy(task['selection']), 'quantity': task['spec'].get('quantity'),
            'expected_claims': expected}
