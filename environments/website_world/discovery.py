"""Public-only native site/document records for the existing Sökväg index."""
from environments.connected_shopping.index import Catalog, KINDS, render
from html import escape
from .site_discovery import DiscoverSites, scope_description


def directory_page(directory, *, search=True):
    rows, offset = [], 0
    while True:
        page = directory.search(limit=20, offset=offset)
        rows.extend(page['sites'])
        if page['next_offset'] is None:
            break
        offset = page['next_offset']
    items = ''.join('<li><a href="' + escape(row['url'], quote=True) + '">' +
                    escape(row['name']) + '</a> <span>' + escape(row['kind']) + '</span><p>' +
                    escape(row['description']) + '</p></li>' for row in rows)
    extra = '<p><a href="/search">Search products and pages</a></p>' if search else ''
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>Shopping directory</title><style>body{font:16px/1.5 system-ui,sans-serif;'
            'max-width:850px;margin:32px auto;padding:0 20px;color:#25313b}ul{list-style:none;padding:0}'
            'li{padding:16px 0;border-top:1px solid #ddd}a{color:#175a8d}li>a{font-weight:600}'
            'span{font-size:.85rem;color:#596673;margin-left:10px}p{margin:5px 0;overflow-wrap:anywhere}'
            '</style></head><body><main><h1>Shopping directory</h1><p>' + str(len(rows)) +
            ' websites · The same names and scopes returned by discover_sites.</p>' + extra +
            '<ul>' + items + '</ul></main></body></html>')


def retailer_records(catalogs, origins):
    sites, documents = [], []
    for sid, catalog in catalogs.items():
        families=sorted({p.get('familyId','footwear') for p in catalog['products']})
        scope=' '.join(families)
        types = sorted({p['type'] for p in catalog['products']})
        description = scope_description(types)
        sites.append({'site_id': sid, 'kind': 'retailer', 'name': catalog['siteName'],
            'origin': origins[sid], 'families': families,
            'types': types, 'description': description})
        documents.extend({'site_id': sid, 'path': path, 'title': title,
            'description': description, 'keywords': keywords} for path, title, description, keywords in (
                ('/', catalog['siteName'], description, scope+' store'),
                ('/#/results', 'Product catalog', 'Browse carried products and their selectable options.', scope+' '+ ' '.join(sorted({p['type'] for p in catalog['products']}))),
                ('/#/info/shipping', 'Delivery policy', 'Retailer delivery and collection terms.', 'shipping charges free delivery'),
                ('/#/info/returns', 'Returns', 'Published return-policy information, where available.', 'return refund'),
                ('/#/info/stores', 'Our shops', 'Branch information and locations.', 'store branches collection'),
            ))
        for product in catalog['products']:
            # Carried retailer pages are indexed regardless of comparator membership.
            # No task predicates, prices, private assertions or winners enter ranking.
            keywords = ' '.join([product['canonicalProductId'], product['brand'], product['type'],
                                 *[v['skuId'] for v in product['variants']]])
            documents.append({'site_id': sid, 'path': '/#/product/' + product['id'],
                'title': product['name'], 'description': product['introduction'], 'keywords': keywords})
    return sites, documents


class Index:
    def __init__(self, sites, documents):
        self.catalog = Catalog([{k: v for k, v in site.items() if k != 'types'} for site in sites], documents)
        self.directory = DiscoverSites(sites)

    def page(self, path, query):
        if path not in ('/', '/search'):
            raise KeyError('Unknown index page')
        if set(query) - {'q', 'kind', 'page'} or len(query.get('q', '')) > 300:
            raise ValueError('Invalid search query')
        if query.get('kind', '') not in ('', *KINDS):
            raise ValueError('Invalid site kind')
        page = query.get('page', '1')
        if not page.isascii() or not page.isdigit() or not 1 <= int(page) <= 10000:
            raise ValueError('Invalid page number')
        body = directory_page(self.directory) if path == '/' and not query else render(self.catalog, path, query)
        return 200, body, 'text/html; charset=utf-8'
