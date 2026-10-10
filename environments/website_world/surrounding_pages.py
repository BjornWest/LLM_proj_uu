"""Native surrounding pages: explicit public view models, no commercial oracle."""
from html import escape
from copy import deepcopy
from urllib.parse import quote, unquote, urlencode

from environments.connected_shopping.index import STYLE
from environments.product_world.public_field_rules import is_public_field

REVIEW_STYLE = '''<style>
body{font:16px/1.6 system-ui,sans-serif;margin:0;color:#21332c;background:#f6f8f5}
header{background:#193c31;color:white;padding:22px max(24px,calc((100vw - 1100px)/2))}
header a{color:white}header p{margin:0;font-size:.9rem}header>a{font-size:1.6rem;font-weight:700}
nav{display:flex;gap:20px;flex-wrap:wrap;margin-top:12px}main,footer{max-width:1100px;margin:24px auto;padding:0 24px}
a{color:#166749}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:20px}
article,.rating-panel{background:white;border:1px solid #d8e0d8;padding:20px;margin:16px 0;border-radius:8px}
article h2,article h3{margin-top:0}form{display:flex;gap:14px;flex-wrap:wrap;align-items:end;margin:18px 0}
label{display:flex;flex-direction:column;gap:5px}input,select,button{font:inherit;padding:8px}button{background:#193c31;color:white;border:0}
table{border-collapse:collapse;width:100%;max-width:440px}th,td{padding:7px;text-align:left;border-bottom:1px solid #e1e7e1}
form{min-width:0}label{min-width:0;max-width:100%}input,select{min-width:0;max-width:100%;box-sizing:border-box}main{overflow-wrap:anywhere}
blockquote{border-left:3px solid #7b9d85;margin:12px 0;padding:8px 18px}dt{font-weight:bold}dd{margin:0 0 10px}
footer{border-top:1px solid #d8e0d8;padding-top:20px}.rating-value{font-size:1.6rem;font-weight:bold}
</style>'''


def e(value):
    return escape(str(value), quote=True)


def link(url, text):
    return f'<a href="{e(url)}">{e(text)}</a>'


def path(prefix, identity):
    return '/' + prefix + '/' + quote(identity, safe='')


def pretty(value):
    if isinstance(value, dict):
        return '; '.join(f'{k.replace("_", " ")}: {pretty(v)}' for k, v in value.items())
    if isinstance(value, list):
        return ', '.join(map(pretty, value))
    if isinstance(value, bool):
        return 'Yes' if value else 'No'
    return str(value)


def public_facts(values):
    """Normalize optional display inputs without inventing unavailable values."""
    if values is None:return {}
    if not isinstance(values,dict):raise TypeError('Public facts must be a mapping')
    def present(value):
        if value is None:return False
        if isinstance(value,str):return bool(value.strip())
        if isinstance(value,(list,dict)):return bool(value)
        return True  # False and zero remain legitimate facts.
    return {key:value for key,value in values.items() if present(value) and is_public_field(key)}


def facts(values):
    values=public_facts(values)
    if not values:return ''
    return '<dl>' + ''.join(f'<dt>{e(k.replace("_", " ").capitalize())}</dt><dd>{e(pretty(v))}</dd>'
                           for k, v in values.items()) + '</dl>'


def fact_section(title, values):
    content=facts(values)
    return '<section><h2>'+e(title)+'</h2>'+content+'</section>' if content else ''


def products_with_optional_facts(products):
    result=deepcopy(products)
    for product in result.values():
        statuses=product.get('fact_status',{})
        product['facts']={k:v for k,v in public_facts(product.get('facts')).items()
                          if statuses.get(k) not in ('unknown','not_applicable')}
        if 'fact_status' in product:
            product['fact_status']={k:v for k,v in statuses.items() if k in product['facts']}
    return result


def money(minor):
    return f'{minor / 100:,.2f} SEK'


class Page:
    def __init__(self, name, index_origin, layout):
        self.name, self.index_origin, self.layout = name, index_origin, layout

    def document(self, title, body):
        navigation = link('/', self.name) + ' · ' + link('/search', 'Browse all') + ' · ' + link('/about', 'About this site')
        footer = link('/about', 'Sources and scope')
        if self.index_origin:
            footer += ' · ' + link(self.index_origin + '/', 'Search stores and independent publications')
        return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width,initial-scale=1">'
                f'<title>{e(title)} | {e(self.name)}</title>{STYLE}</head><body>'
                f'<header><nav aria-label="Main navigation">{navigation}</nav></header>'
                f'<main id="main"><h1>{e(title)}</h1>{body}</main>'
                f'<footer><nav>{footer}</nav></footer></body></html>')

    def response(self, title, body):
        return 200, self.document(title, body), 'text/html; charset=utf-8'


class ComparisonPage(Page):
    """Only the site's published model/listing membership enters any surface."""
    def __init__(self, site, products, bindings, retailer_names, index_origin, review_links):
        super().__init__(site['name'], index_origin, site['layout'])
        self.site = site
        self.products = products_with_optional_facts(products)
        self.bindings, self.retailer_names, self.review_links = bindings, retailer_names, review_links

    def documents(self):
        return [{'path': path('models', pid), 'title': p['name'],
                 'description': 'Compare tracked retailer item prices; selected options and delivery are confirmed at the store.',
                 'keywords': pid + ' ' + pretty(p['facts'])} for pid, p in self.products.items()]

    def listing(self, row):
        binding = self.bindings[row['entry_offer_id']]
        return (link(binding['model_url'], self.retailer_names[row['retailer_id']]), money(row['advertised_price_minor']),
                'Choose your exact size, colour and width, and check availability at the retailer. '
                'Delivery is additional where applicable.')

    def price(self, p):
        return min((r['advertised_price_minor'] for r in p['listings']), default=None)

    def card(self, pid, p):
        price = self.price(p)
        return (f'<article><h2>{link(path("models", pid), p["name"])}</h2>'
                + facts(dict(list(p['facts'].items())[:3]))
                + '<p>' + (f'Listed from {money(price)}' if price is not None else 'No tracked retailer offers')
                + f'</p><p>{len(p["listings"])} tracked retailers</p></article>')

    def page(self, route, q):
        if route == '/about' and not q:
            return self.response('How these comparisons work',
                '<p>Product and retailer coverage is partial. An absent listing does not mean a product is unavailable.</p>'
                f'<p>Minimum listed item price for the model at each retailer. Price reference date: {e(self.site["as_of"])}.</p>'
                '<p>Model prices may cover different configurations. Confirm your exact selected option, stock, '
                'shipping and final total at the retailer. This site does not calculate checkout charges.</p>')
        if route in ('/', '/search'):
            if set(q) - {'q', 'sort'} or q.get('sort', 'name') not in ('name', 'price'):
                raise ValueError('Invalid comparison search')
            terms = q.get('q', '').casefold().split()
            rows = [(pid, p) for pid, p in self.products.items()
                    if all(t in (p['name'] + ' ' + pretty(p['facts'])).casefold() for t in terms)]
            rows.sort(key=lambda pair: ((self.price(pair[1]) is None, self.price(pair[1]) or 0, pair[0])
                      if q.get('sort') == 'price' else (pair[1]['name'], pair[0])))
            form = (f'<form action="/search"><label>Find a model<input name="q" value="{e(q.get("q", ""))}"></label>'
                    '<label>Sort<select name="sort"><option value="name">Model name</option>'
                    f'<option value="price"{" selected" if q.get("sort") == "price" else ""}>Lowest tracked item price</option>'
                    '</select></label><button>Search</button></form>')
            if self.layout == 'ledger':
                content = '<table><caption>Tracked model prices</caption><thead><tr><th>Model</th><th>Item price from</th><th>Tracked retailers</th></tr></thead><tbody>'
                content += ''.join(f'<tr><td>{link(path("models", pid), p["name"])}</td><td>'
                    + (money(self.price(p)) if self.price(p) is not None else 'No tracked offers')
                    + f'</td><td>{len(p["listings"])}</td></tr>' for pid, p in rows) + '</tbody></table>'
            else:
                content = '<section class="grid" aria-label="Model comparisons">' + ''.join(self.card(pid, p) for pid, p in rows) + '</section>'
            note = '<p>Partial coverage of model item-price snapshots. Choose size and check delivery at the store.</p>'
            return self.response('Compare footwear prices', note + form + f'<p>{len(rows)} models</p>' + content)
        if route.startswith('/models/') and not q:
            pid = unquote(route[len('/models/'):])
            p = self.products[pid]
            rows = sorted(p['listings'], key=lambda r: (r['advertised_price_minor'], r['retailer_id']))
            body = '<p>Listed item-price snapshots for this model. Select and verify your exact configuration at the store.</p>'
            if self.layout == 'ledger':
                body += facts(p['facts'])
            body += '<section><h2>Retailer listings</h2>'
            for row in rows:
                store, price, note = self.listing(row)
                body += f'<article><h3>{store}</h3><p>{price}</p><p>{e(note)}</p></article>'
            if not rows:
                body += '<p>No retailer offers are tracked for this model.</p>'
            body += '</section>'
            if self.layout != 'ledger':
                body += fact_section('Model specifications',p['facts'])
            if pid in self.review_links:
                body += '<section><h2>Customer opinions</h2>' + link(self.review_links[pid], 'Read attributed product reviews') + '</section>'
            return self.response(p['name'], body)
        raise KeyError('Unknown or untracked comparison page')


class ReviewPage(Page):
    def __init__(self, site, products, bindings, retailer_names, index_origin):
        super().__init__(site['name'], index_origin, site['layout'])
        self.products, self.bindings, self.retailer_names = products_with_optional_facts(products), bindings, retailer_names
        self.review_scope = 'product' if 'families' in site else 'footwear'

    def document(self, title, body):
        footer = link('/about', 'Review sources and publication scope')
        if self.index_origin:
            footer += ' · ' + link(self.index_origin + '/', 'Find stores and independent publications')
        return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width,initial-scale=1">'
                f'<title>{e(title)} | {e(self.name)}</title>{REVIEW_STYLE}</head><body>'
                f'<header><p>Reader reviews · Customer experiences</p>{link("/", self.name)}'
                f'<nav aria-label="Review publication">{link("/search", "Product review library")}'
                f'{link("/about", "How these reviews are published")}</nav></header>'
                f'<main id="main"><h1>{e(title)}</h1>{body}</main><footer>{footer}</footer></body></html>')

    def documents(self):
        return [{'path': path('reviews', pid), 'title': p['name'] + ' — customer reviews',
                 'description': 'Attributed opinions with exact reviewed configurations, ratings and published model facts.',
                 'keywords': pid + ' ' + pretty(p['facts'])} for pid, p in self.products.items()]

    def configuration(self, sku):
        return {k:v for k,v in sku.items() if k not in ("sku_id","product_id")}

    def summary(self, p, pid=None, query=None):
        s = p['rating_summary']
        if not s['rating_count']:return '<p>No customer ratings are recorded.</p>'
        histogram = ''
        counts = s.get('star_counts')
        if counts is not None:
            if (type(counts) is not dict or set(counts) != set('12345') or
                    any(type(n) is not int or n < 0 for n in counts.values()) or
                    sum(counts.values()) != s['rating_count']):
                raise ValueError('Published rating histogram disagrees with its rating total')
            histogram = '<table><caption>All recorded ratings, including ratings without comments</caption><thead><tr><th>Rating</th><th>Count</th></tr></thead><tbody>'
            for stars in range(5, 0, -1):
                label = f'{stars} stars'
                if pid is not None:
                    fields = {'stars': str(stars)}
                    if query and query.get('sku'):fields['sku'] = query['sku']
                    if query and query.get('part'):fields['part'] = query['part']
                    label = link(path('reviews', pid) + '?' + urlencode(fields), label)
                histogram += f'<tr><th scope="row">{label}</th><td>{counts[str(stars)]}</td></tr>'
            histogram += '</tbody></table>'
        return (f'<section class="rating-panel" aria-label="Customer rating summary"><h2>Customer rating</h2>'
                f'<p class="rating-value">{s["average_rating"]} / 5</p><p>{s["rating_count"]} ratings; '
                f'{s["written_review_count"]} written reviews, {s["rating_only_count"]} ratings without comments.</p>'
                '<p>The average includes ratings without comments.</p>' + histogram + '</section>')

    def page(self, route, q):
        if route == '/about' and not q:
            return self.response('Sources and review scope',
                '<p>This publication shares one customer-review corpus with participating retailer pages. These are the same source '
                'opinions wherever republished, not additional independent tests or endorsements.</p>'
                '<p>Each comment is attributed to its recorded reviewer and reviewed configuration. Customer '
                'experience is distinct from catalog facts. Rating-only entries contribute to summaries, not comments.</p>')
        if route in ('/', '/search'):
            if set(q) - {'q'}:
                raise ValueError('Invalid review search')
            terms = q.get('q', '').casefold().split()
            rows = [(pid, p) for pid, p in self.products.items()
                    if all(t in (p['name'] + ' ' + pretty(p['facts'])).casefold() for t in terms)]
            rows.sort(key=lambda pair: (pair[1]['name'], pair[0]))
            form = f'<form action="/search"><label>Search {e(self.review_scope)} reviews<input name="q" value="{e(q.get("q", ""))}"></label><button>Search</button></form>'
            cards = ''.join(f'<article><h2>{link(path("reviews", pid), p["name"])}</h2>'
                            + self.summary(p) + '</article>' for pid, p in rows)
            return self.response(self.review_scope.capitalize() + ' reader reviews', form + '<section class="grid">' + cards + '</section>')
        if route.startswith('/reviews/'):
            pid = unquote(route[len('/reviews/'):])
            p = self.products[pid]
            if set(q) - {'stars', 'sku'} or q.get('stars', '') not in ('', '1', '2', '3', '4', '5'):
                raise ValueError('Invalid review filter')
            skus = {s['sku_id']: s for s in p['skus']}
            if q.get('sku') and q['sku'] not in skus:
                raise ValueError('Unknown reviewed configuration')
            rows = [r for r in p['reviews'] if r['text'] and
                    (not q.get('stars') or str(r['rating']) == q['stars']) and
                    (not q.get('sku') or r['sku_id'] == q['sku'])]
            filters = (f'<form action="{e(path("reviews", pid))}"><label>Stars<select name="stars">'
                       '<option value="">All ratings</option>' + ''.join(f'<option value="{n}"'
                       + (' selected' if q.get('stars') == str(n) else '') + f'>{n}</option>' for n in range(1, 6))
                       + '</select></label><label>Reviewed configuration<select name="sku"><option value="">All configurations</option>'
                       + ''.join(f'<option value="{e(sid)}"' + (' selected' if q.get('sku') == sid else '')
                                 + f'>{e(pretty(self.configuration(s)))}</option>'
                                 for sid, s in skus.items()) + '</select></label><button>Filter comments</button></form>')
            comments = '<section><h2>Written customer reviews</h2>' + filters + f'<p>{len(rows)} matching comments</p>'
            for r in rows:
                sku = skus[r['sku_id']]
                comments += (f'<article id="{e(r["review_id"])}"><h3>{e(r["reviewer"])} — {r["rating"]} / 5</h3>'
                    + f'<p>Reviewed configuration: {e(pretty(self.configuration(sku)))}</p>'
                    + f'<p>SKU: {e(r["sku_id"])}</p><blockquote>{e(r["text"])}</blockquote></article>')
            if not rows:
                comments += '<p>No written comments match these filters.</p>'
            comments += '</section>'
            specifications = fact_section('Published model facts',p['facts'])
            offers = ''
            seen = set()
            for binding in self.bindings.values():
                sid = binding['retailer_id']
                if binding['product_id'] == pid and sid not in seen:
                    seen.add(sid)
                    offers += '<li>' + link(binding['model_url'], self.retailer_names[sid]) + '</li>'
            if offers:offers = '<section><h2>Retailer pages</h2><ul>'+offers+'</ul><p>Select your exact configuration and confirm availability at the retailer.</p></section>'
            sections = (comments + specifications if self.layout == 'community' else specifications + comments)
            fit_text=(p.get('guidance') or {}).get('fit_text')
            guidance = ('<aside><h2>Editorial fit guidance</h2><p>' + e(fit_text) + '</p><p>Editorial guidance, separate from customer votes.</p></aside>') if isinstance(fit_text,str) and fit_text.strip() else ''
            attribution = '<p>Customer opinions are shared with participating retailer pages; publication does not add votes.</p>'
            breadcrumb = '<nav aria-label="Review location">' + link('/search', 'All product reviews') + '</nav>'
            return self.response(p['name'], breadcrumb + self.summary(p, pid, q) + attribution + guidance + sections + offers)
        raise KeyError('Unknown or unpublished review page')
