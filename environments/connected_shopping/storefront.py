"""Public home merchandising, collection routes and compact customer information.

Sampling and commercial claims belong to product_world.storefront_content. This
module projects its frozen rows; it never chooses a winner or invents a discount.
"""
from urllib.parse import quote
from . import pages as p


def content(owner, site):
    return getattr(owner, 'storefront_by_store', {}).get(site)


def collection_path(row):
    return '/collections/' + quote(row['collection_id'], safe='')


def section_path(row):
    return '/highlights/' + quote(row['section_id'], safe='')


def catalog_fields(owner, site):
    row = content(owner, site)
    if row is None:
        return {}
    return {
        'storefront_search_form': search_form(owner, site, {}),
        'storefront_links': [{'title': c['title'], 'href': collection_path(c)} for c in row['collections']],
        'customer_service_links': [
            {'title': title, 'href': path} for title, path in (
                ('Delivery', '/policy'), ('Returns', '/returns'),
                ('Purchase information', '/terms'), ('Contact & stores', '/contact'))],
    }


def search_form(owner, site, query):
    row = content(owner, site)
    if row is None:
        return p.layout._search_form(site, owner.origins, owner.catalog(site)['products'], query, label='Search products')
    choices = '<option value="">All collections</option>' + ''.join(
        '<option value="' + p.e(c['collection_id']) + '"' +
        (' selected' if query.get('collection') == c['collection_id'] else '') + '>' + p.e(c['title']) + '</option>'
        for c in row['collections'])
    return '<form class="search-form" method="get" action="/search"><label>Search products<input type="search" name="q" value="' + p.e(query.get('q', '')) + '"></label><label>Collection<select name="collection">' + choices + '</select></label><button>Search</button></form>'


def model_products(owner, site, ids):
    """Expand featured model representatives to carried variants for honest From prices."""
    carried = owner.catalog(site)['products']
    by_group = {}
    for product in carried:
        by_group.setdefault(owner.group_for[product['product_id']]['group_id'], []).append(product)
    result = []; seen = set()
    for sku in ids:
        product = owner.products[sku]
        if product['category'] == 'footwear':
            group = owner.group_for[sku]['group_id']
            if group not in seen:
                result.extend(by_group[group]); seen.add(group)
        else:
            result.append(product)
    return result


def home(owner, site):
    row = content(owner, site)
    body = '<h1>Welcome to ' + p.e(owner.stores[site]['name']) + '</h1>'
    body += '<section aria-label="Explore our collection"><h2>Find your next favourite</h2><p>Browse our collections or search for a model.</p>' + p.link('/search', 'Shop the collection') + '</section>'
    body += search_form(owner, site, {})
    # Category navigation belongs to the selected shell: horizontal boutique,
    # dense disclosure or technical sidebar. Avoid repeating it in the main tree.
    for section in row['sections']:
        body += '<section aria-labelledby="home-' + p.e(section['section_id']) + '"><h2 id="home-' + p.e(section['section_id']) + '">' + p.e(section['title']) + '</h2><p>' + p.e(section['body']) + '</p>'
        selected = p.display_products(owner, model_products(owner, site, section['product_ids']))
        body += p.cards(owner, site, selected[:4], force_cards=True)
        body += p.link(section_path(section), 'Explore ' + section['title'].lower())
        if section['collection_id'] is not None:
            collection = next(c for c in row['collections'] if c['collection_id'] == section['collection_id'])
            body += ' · ' + p.link(collection_path(collection), 'Shop ' + collection['title'].lower())
        body += '</section>'
    return p.shell(owner, site, owner.stores[site]['name'], body)


def listing(owner, site, path, query):
    row = content(owner, site)
    if row is None:
        raise KeyError('No storefront collection')
    if set(query) - {'page'}:
        raise ValueError('Unknown collection field')
    kind, identity = path.strip('/').split('/')
    rows = row['collections'] if kind == 'collections' else row['sections']
    key = 'collection_id' if kind == 'collections' else 'section_id'
    item = next((r for r in rows if r[key] == identity), None)
    if item is None:
        raise KeyError('Unknown collection')
    products = ([owner.products[sku] for sku in item['product_ids']] if kind == 'collections'
                else model_products(owner, site, item['product_ids']))
    products = p.display_products(owner, products)
    page = p.page_number(query); total = max(1, (len(products) + 11) // 12); page = min(page, total)
    body = '<nav aria-label="Breadcrumbs">' + p.link('/', 'Home') + ' / ' + p.e(item['title']) + '</nav><h1>' + p.e(item['title']) + '</h1>'
    if item.get('body'):
        body += '<p>' + p.e(item['body']) + '</p>'
    body += search_form(owner, site, {'collection': identity} if kind == 'collections' else {})
    body += '<section aria-label="Product results"><p>' + str(len(products)) + ' product listings</p>'
    body += p.cards(owner, site, products[(page-1)*12:page*12]) + p.pagination(path, query, page, total) + '</section>'
    return p.shell(owner, site, item['title'], body)


def information(owner, site, path):
    # No invented return periods, promises, emails or live customer-service forms.
    if path == '/returns':
        title = 'Returns'; body = '<p>Return periods and return shipping charges are not listed in this catalog. Check the applicable terms before placing an order.</p>'
    elif path == '/terms':
        title = 'Purchase information'; body = '<p>Prices are shown in SEK. The selected product option, quantity, destination and delivery method determine the full quote. Availability may differ between product options and branches.</p><p>Online ordering is not available in this catalog.</p>'
    elif path == '/contact':
        title = 'Contact & stores'; merchant = owner.merchants[site]
        body = '<p>' + p.e(owner.stores[site]['name']) + ' · ' + p.e(merchant['warehouse']['city']) + ', ' + p.e(merchant['warehouse']['country']) + '</p><p>Contact details and opening hours are not listed. See our branch locations for available pickup and inspection options.</p>' + p.link('/branches', 'Find our stores')
    else:
        raise KeyError('Unknown information page')
    return p.shell(owner, site, title, '<h1>' + p.e(title) + '</h1>' + body + '<p>' + p.link('/policy', 'Delivery and store information') + '</p>')
