"""One-page variant-link tasks over actual carried tuples and published URLs.

Navigation capability is private accepted consumer evidence, never an answer
claim or inferred from Runtime's syntactic ``required_selection`` alone.
"""
from copy import deepcopy
from hashlib import sha256
import json
from urllib.parse import parse_qsl, urlsplit
from experiments import source_binding

VERSION = 'website-variant-link-task-v1'
KIND = 'link_exact_variant'
NAVIGATION_PROTOCOL = 'explicit-url-fields-first-v1'


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def url_parts(url):
    """Read only selectors consumed by shop.js's hash router.

    Outer query fields are not product selectors. Reject them rather than
    crediting values the actual recipient cannot recover from the route.
    """
    if type(url) is not str:
        raise ValueError('Product URL must be a string')
    parts = urlsplit(url)
    route, separator, fragment_query = parts.fragment.partition('?')
    pairs = parse_qsl(fragment_query, keep_blank_values=True) if separator else []
    if (parts.scheme not in ('http', 'https') or not parts.netloc or
            parts.username is not None or parts.password is not None or
            parts.query or
            len({k for k, _ in pairs}) != len(pairs)):
        raise ValueError('Require an absolute merchant URL with unique hash-route selectors and no outer query')
    return (parts.scheme, parts.netloc, parts.path, route), dict(pairs)


def make(world, spec, *, catalog, bindings, navigation_capability):
    """Bind one target to trusted native and independently accepted UI exports.

    The consumer supplies its Product-accepted capability for this exact page,
    catalog and asset bundle. A source-only candidate cannot enable a task.
    """
    if (type(spec) is not dict or set(spec) != {'kind', 'retailer_id', 'offer_id'}
            or spec['kind'] != KIND or
            any(type(spec[k]) is not str or not spec[k] for k in ('retailer_id', 'offer_id'))):
        raise ValueError('Declare link_exact_variant, retailer_id and offer_id')
    rid, oid = spec['retailer_id'], spec['offer_id']
    retailers = [r for r in world['retailers'] if r['retailer_id'] == rid]
    if len(retailers) != 1 or catalog['siteId'] != rid:
        raise ValueError('Target retailer must match the native world and public catalog')
    offers = [o for o in retailers[0]['offers'] if o['offer_id'] == oid]
    if len(offers) != 1:
        raise ValueError('Target must be an actually carried native offer')
    offer = offers[0]
    products = [p for p in world['products'] if p['public']['product_id'] == offer['product_id']]
    if len(products) != 1:
        raise ValueError('Native product identity is ambiguous')
    skus = [s for s in products[0]['public']['skus'] if s['sku_id'] == offer['sku_id']]
    pages = [p for p in catalog['products'] if any(v['offerId'] == oid for v in p['variants'])]
    if len(skus) != 1 or len(pages) != 1:
        raise ValueError('Require a unique native SKU and actual merchant page')
    page = pages[0]
    variants = [v for v in page['variants'] if v['offerId'] == oid]
    if len(variants) != 1 or page['canonicalProductId'] != offer['product_id']:
        raise ValueError('Public page/offer identity differs from the native target')
    variant = variants[0]
    target = variant['selection']
    axes = [o['key'] for o in page['options']]
    if (len(axes) != len(set(axes)) or set(target) != set(axes) or
            variant['skuId'] != offer['sku_id'] or
            sum(v['selection'] == target for v in page['variants']) != 1 or
            any(type(v) is not str or not v for v in target.values()) or
            any(str(skus[0].get(k)) != v for k, v in target.items()) or
            any(target[o['key']] not in o['values'] for o in page['options'])):
        raise ValueError('Target options must be the complete carried native tuple')
    link = bindings['retailer_offers'][oid]
    if any(link[k] != value for k, value in {
            'retailer_id': rid, 'product_id': offer['product_id'],
            'sku_id': offer['sku_id'], 'selection': target}.items()):
        raise ValueError('Actual offer URL binding differs from the native target')
    behavior = catalog['configuration']['url']
    if behavior not in ('all', 'colour', 'none') or link['url_behavior'] != behavior:
        raise ValueError('Require the actual renderer URL mode')
    encoded = {k: v for k, v in target.items()
               if behavior == 'all' or behavior == 'colour' and k == 'colour'}
    omitted = {k: v for k, v in target.items() if k not in encoded}
    identity, query = url_parts(link['url'])
    page_url = bindings['retailer_pages'][rid][page['id']]
    page_identity, page_query = url_parts(page_url)
    if (identity != page_identity or identity[3] != '/product/' + page['id'] or
            page_query or query != encoded or link['required_selection'] != omitted):
        raise ValueError('Actual page URL/selector binding changed')
    cap = navigation_capability
    if (type(cap) is not dict or cap.get('protocol') != NAVIGATION_PROTOCOL or
            cap.get('owner') != 'Product' or cap.get('status') != 'accepted' or
            cap.get('retailer_id') != rid or cap.get('page_id') != page['id'] or
            cap.get('catalog_sha256') != digest(catalog) or
            cap.get('recipient_states') != 'fresh_and_all_carried_tuples' or
            type(cap.get('asset_sha256')) is not dict or not cap['asset_sha256'] or
            any(type(v) is not str or len(v) != 64 or
                any(c not in '0123456789abcdef' for c in v) for v in cap['asset_sha256'].values())):
        raise ValueError('Require privately accepted exact recipient navigation capability')
    labels = {o['key']: o['label'] for o in page['options']}
    options_text = ', '.join(f'{labels[k]} {v}' for k, v in target.items())
    task = {'schema_version': VERSION, **deepcopy(spec),
            'world_id': world['world_id'], 'world_sha256': digest(world),
            'catalog_sha256': digest(catalog), 'bindings_sha256': digest(bindings),
            'navigation_capability': deepcopy(cap), 'page_id': page['id'],
            'product_id': offer['product_id'], 'sku_id': offer['sku_id'],
            'product_name': page['name'], 'selection': deepcopy(target),
            'option_labels': labels, 'url': link['url'], 'url_behavior': behavior,
            'encoded_selection': encoded, 'manual_selection': omitted,
            'start': {'kind': 'product', 'page_id': page['id'], 'url': page_url},
            'memories': [], 'user_message':
                f'On this product page at {retailers[0]["name"]}, give me a link to '
                f'{page["name"]} with {options_text}. Tell me whether the link opens '
                'that exact variant, and explain any options the recipient still needs '
                'to select. Stay on this retailer; do not add items, start checkout or buy anything.'}
    task['task_id'] = 'variant-link-' + digest(task)[:24]
    return task


def reference(world, task, *, catalog, bindings, navigation_capability):
    spec = {k: task[k] for k in ('kind', 'retailer_id', 'offer_id')}
    if not source_binding.compatible(task, make(world, spec, catalog=catalog, bindings=bindings,
                    navigation_capability=navigation_capability)):
        raise ValueError('Original variant-link task, menu or navigation binding changed')
    return {'schema_version': 'website-variant-link-reference-v1',
            'task_sha256': digest(task), 'offer_id': task['offer_id'],
            'url': task['url'], 'selection': deepcopy(task['selection']),
            'link_encodes_full_selection': not bool(task['manual_selection']),
            'recipient_must_select': bool(task['manual_selection']),
            'manual_selection': deepcopy(task['manual_selection']),
            'scope': 'Link and recipient-selection explanation only; availability, reading, navigation and effects require separate evidence.'}
