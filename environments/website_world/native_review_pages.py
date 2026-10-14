"""Authored three-design review presentation over the current native corpus.

No legacy Catalog, comment sampler, chronology or comment-only rating arithmetic.
"""
from urllib.parse import urlencode, unquote
from environments.product_review_sites.render import STYLE
from .surrounding_pages import ReviewPage, e, link, path, pretty, fact_section, facts

LAYOUTS = ('lab-directory', 'editorial-magazine', 'community-feed')
VERSION = 'native-review-presentation-v1'
EXTRA_STYLE = '<style>form,label{min-width:0}label{max-width:100%}input,select{min-width:0;max-width:100%}.rating-panel table{width:100%;max-width:440px}blockquote{border-left:3px solid #78988b;margin:12px 0;padding:8px 16px}.contents{position:sticky;top:20px}dl{overflow-wrap:anywhere}.score-panel{padding:16px;background:#e8efeb}.publication-scope{max-width:70ch}</style>'


def url(route, query=None):
    query = {k: v for k, v in (query or {}).items() if v != ''}
    return route + ('?' + urlencode(query) if query else '')


def select(name, label, values, current=''):
    return '<label>' + e(label) + '<select name="' + e(name) + '">' + ''.join(
        '<option value="' + e(value) + '"' + (' selected' if str(value) == current else '') + '>' + e(text) + '</option>'
        for value, text in values) + '</select></label>'


class NativeReviewPage(ReviewPage):
    def __init__(self, site, products, bindings, retailer_names, index_origin):
        if site['layout'] not in LAYOUTS:
            raise ValueError('Unknown native review design')
        super().__init__(site, products, bindings, retailer_names, index_origin)
        self.site = site
        self.page_size = site['review_presentation']['page_size']
        self.families = sorted({p['family_id'] for p in self.products.values()})
        self.labels = site['family_labels']
        self.variants = {s['sku_id']: (pid, s) for pid, p in self.products.items() for s in p['skus']}
        self.written = [(pid, r) for pid in sorted(self.products) for r in self.products[pid]['reviews'] if r['text']]

    def document(self, title, body):
        categories = ''.join(link(url('/catalog', {'family': f}), self.labels[f]) for f in self.families)
        search = '<form action="/catalog"><label>Search reviews<input type="search" name="q"></label><button>Search</button></form>'
        if self.layout == 'lab-directory':
            navigation = search + '<nav aria-label="Categories">' + categories + link('/compare', 'Compare products') + link('/methodology', 'Methodology') + '</nav>'
            navigation += '<nav aria-label="Browse review topics">' + ''.join('<details><summary>' + e(self.labels[f]) + ' notebooks</summary>' + link(url('/catalog', {'family': f}), 'All ' + self.labels[f].lower()) + '</details>' for f in self.families) + '</nav>'
        elif self.layout == 'editorial-magazine':
            navigation = '<nav aria-label="Sections">' + link('/catalog', 'Review library') + categories + link('/compare', 'Side by side') + link('/methodology', 'Our approach') + '</nav><details><summary>Search the magazine</summary>' + search + '</details>'
        else:
            navigation = '<nav aria-label="Community">' + link('/catalog', 'Discover products') + categories + link('/activity', 'Community notes') + link('/members', 'Reader directory') + link('/methodology', 'About ratings') + '</nav>' + search
        footer = '<div class="grid"><section><h2>Explore</h2>' + link('/catalog', 'All product reviews') + link('/compare', 'Compare product details') + link('/activity', 'Written reader notes') + '</section><section><h2>Publication</h2>' + link('/members', 'Readers with published comments') + link('/methodology', 'Facts, opinions and coverage') + '</section><section><h2>Categories</h2>' + categories + '</section></div>'
        if self.index_origin:
            footer += link(self.index_origin + '/', 'Find other shopping websites')
        footer += '<p>One syndicated customer-review corpus. Republishing does not add independent votes or tests.</p>'
        return '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>' + e(title) + ' | ' + e(self.name) + '</title>' + STYLE + EXTRA_STYLE + '</head><body class="' + self.layout + '"><header><a class="brand" href="/">' + e(self.name) + '</a>' + navigation + '</header><main id="main">' + body + '</main><footer>' + footer + '</footer></body></html>'

    def paged(self, route, query, rows):
        value = query.get('page', '1')
        if type(value) is not str or not value.isascii() or not value.isdigit() or not 1 <= int(value) <= 10000:
            raise ValueError('Invalid review page number')
        count = max(1, (len(rows) + self.page_size - 1) // self.page_size)
        page = min(int(value), count)
        navigation = '<nav class="pagination" aria-label="Pagination">'
        if page > 1:
            navigation += link(url(route, {**query, 'page': page - 1}), 'Previous')
        navigation += '<span>Page ' + str(page) + ' of ' + str(count) + '</span>'
        if page < count:
            navigation += link(url(route, {**query, 'page': page + 1}), 'Next')
        navigation += '</nav>'
        return rows[(page - 1) * self.page_size:page * self.page_size], navigation

    def card(self, pid):
        p = self.products[pid];s = p['rating_summary']
        rating = str(s['average_rating']) + ' / 5' if s['rating_count'] else 'Not yet rated'
        return '<section class="card"><span class="tag">' + e(self.labels[p['family_id']]) + '</span><h3>' + link(path('reviews', pid), p['name']) + '</h3><p>' + e(rating) + ' · ' + str(s['rating_count']) + ' ratings · ' + str(s['written_review_count']) + ' written comments</p>' + link(url('/compare', {'left': pid}), 'Compare this product') + '</section>'

    def related(self, pid):
        family = self.products[pid]['family_id']
        peers = [other for other in sorted(self.products) if other != pid and self.products[other]['family_id'] == family][:4]
        return '<section><h2>More in this category</h2>' + (''.join(self.card(other) for other in peers) or '<p>No other covered products in this category.</p>') + '</section>'

    def variants_section(self, pid):
        p = self.products[pid]
        return '<details id="options"><summary>Product options (' + str(len(p['skus'])) + ')</summary><p>Comments identify their actual option; the overview and catalog facts are model-wide.</p><ul>' + ''.join('<li>' + link(path('variants', s['sku_id']), pretty(self.configuration(s))) + '</li>' for s in p['skus']) + '</ul></details>'

    def retailer_links(self, pid, sku=None):
        seen = set();rows = []
        for b in self.bindings.values():
            if b['product_id'] != pid or sku is not None and b['sku_id'] != sku:
                continue
            sid = b['retailer_id']
            if sid in seen:
                continue
            seen.add(sid)
            target = b['url'] if sku is not None else b['model_url']
            rows.append('<li>' + link(target, self.retailer_names[sid]) + '</li>')
        return '<section><h2>Retailer pages</h2><ul>' + ''.join(rows) + '</ul><p>Confirm the selected configuration, stock and delivery at the retailer.</p></section>' if rows else ''

    def opinion(self, pid, row):
        p = self.products[pid]
        sku = self.variants[row['sku_id']][1]
        return '<article class="entry" id="' + e(row['review_id']) + '" data-review-id="' + e(row['review_id']) + '"><p><strong>' + link(path('members', row['reviewer']), row['reviewer']) + '</strong> reviewed ' + link(path('reviews', pid), p['name']) + '</p><p role="img" aria-label="' + str(row['rating']) + ' out of 5 stars">' + ('★' * row['rating']) + '</p><blockquote>' + e(row['text']) + '</blockquote><details><summary>Reviewed option</summary>' + link(path('variants', row['sku_id']), pretty(self.configuration(sku))) + '</details>' + link(path('reviews', pid) + '/opinions/' + e_quote(row['review_id']), 'Read this reader note') + '</article>'

    def model_summary(self, pid, query=None):
        query = {k: v for k, v in (query or {}).items() if k != 'sku'}
        return '<div class="score-panel"><p>Model-wide rating summary, including every recorded option and ratings without comments.</p>' + self.summary(self.products[pid], pid, query) + '</div>'

    def reader_section(self, pid, query):
        p = self.products[pid]
        if query.get('sku') and query['sku'] not in {s['sku_id'] for s in p['skus']}:
            raise ValueError('Unknown reviewed configuration')
        rows = [r for r in p['reviews'] if r['text'] and (not query.get('stars') or str(r['rating']) == query['stars']) and (not query.get('sku') or r['sku_id'] == query['sku'])]
        order = query.get('sort', 'identity')
        if order not in ('identity', 'lowest', 'highest'):
            raise ValueError('Unsupported reader sort; source comments have no dates')
        rows.sort(key=lambda r: (r['rating'] if order == 'lowest' else -r['rating'] if order == 'highest' else 0, r['review_id']))
        form = '<form action="' + e(path('reviews', pid)) + '">' + select('stars', 'Rating', [('', 'All ratings')] + [(str(n), str(n) + ' stars') for n in range(1, 6)], query.get('stars', ''))
        form += select('sku', 'Reviewed option', [('', 'All options')] + [(s['sku_id'], pretty(self.configuration(s))) for s in p['skus']], query.get('sku', ''))
        form += select('sort', 'Sort reader notes', [('identity', 'Default order'), ('lowest', 'Lowest rating first'), ('highest', 'Highest rating first')], order)
        if self.layout == 'editorial-magazine':
            form += '<input type="hidden" name="part" value="readers">'
        form += '<button>Filter reader notes</button></form>'
        chosen, pages = self.paged(path('reviews', pid), query, rows)
        option = self.sku_summary(pid, query['sku'], query) if query.get('sku') else ''
        return '<section id="readers"><h2>Reader opinions</h2>' + form + option + '<p>' + str(len(rows)) + ' matching written comments</p><div class="feed">' + (''.join(self.opinion(pid, r) for r in chosen) or '<p>No written comments match.</p>') + '</div>' + pages + '</section>'

    def model_facts(self, pid):
        values = self.products[pid]['facts']
        return '<section id="specifications"><h2>Published model facts</h2><p>Recorded catalog facts, distinct from customer experiences and independent tests.</p>' + facts(values) + '</section>' if values else ''

    def product_page(self, pid, query):
        if set(query) - {'stars', 'sku', 'sort', 'page', 'part'} or query.get('stars', '') not in ('', '1', '2', '3', '4', '5'):
            raise ValueError('Invalid native review filter')
        part = query.get('part', 'overview')
        if part not in ('overview', 'specifications', 'readers') or self.layout != 'editorial-magazine' and 'part' in query:
            raise ValueError('Unsupported review article part')
        p = self.products[pid]
        header = '<nav aria-label="Breadcrumb">' + link('/catalog', 'Reviews') + link(url('/catalog', {'family': p['family_id']}), self.labels[p['family_id']]) + '</nav><h1>' + e(p['name']) + '</h1>'
        summary_query = {**query, **({'part': 'readers'} if self.layout == 'editorial-magazine' else {})}
        summary = self.model_summary(pid, summary_query)
        content = self.model_facts(pid)
        readers = self.reader_section(pid, query)
        options = self.variants_section(pid)
        retailers = self.retailer_links(pid)
        if self.layout == 'lab-directory':
            sections = [('overview', 'Product overview'), *([('specifications', 'Catalog details')] if content else []), ('options', 'Product options'), ('readers', 'Reader opinions')]
            contents = '<aside><nav class="contents" aria-label="Review contents"><h2>Contents</h2><ul>' + ''.join('<li>' + link('#' + k, label) + '</li>' for k, label in sections) + '</ul></nav></aside>'
            article = '<article>' + header + '<section id="overview">' + summary + '</section>' + content + options + readers + '</article>'
            sidebar = '<aside><h2>Compare before choosing</h2>' + link(url('/compare', {'left': pid}), 'Compare product details') + retailers + self.related(pid) + '</aside>'
            body = '<div class="columns">' + contents + article + sidebar + '</div>'
        elif self.layout == 'editorial-magazine':
            nav = '<nav aria-label="Article pages">' + ''.join(link(url(path('reviews', pid), {'part': k}), label) for k, label in [('overview', '1. Overview'), ('specifications', '2. Catalog details'), ('readers', '3. Reader responses')]) + '</nav>'
            if part == 'overview':
                main = summary + '<section><h2>Coverage</h2><p>This overview covers the product. Individual reader comments retain their exact option.</p></section>' + retailers + link(url(path('reviews', pid), {'part': 'specifications'}), 'Continue to catalog details')
            elif part == 'specifications':
                main = (content or '<p>No model facts are published here.</p>') + options + link(url(path('reviews', pid), {'part': 'readers'}), 'Continue to reader responses')
            else:
                main = summary + readers
            body = header + nav + '<div class="two"><article>' + main + '</article><aside>' + self.related(pid) + '</aside></div>'
        else:
            main = header + summary + '<div class="two"><section>' + readers + '</section><aside><h2>Product details</h2><details><summary>Published catalog information</summary>' + content + '</details>' + options + retailers + self.related(pid) + '</aside></div>'
            body = main
        return self.response(p['name'], body)

    def catalog_page(self, query):
        if set(query) - {'q', 'family', 'sort', 'page'} or query.get('family', '') not in ('', *self.families) or query.get('sort', 'name') not in ('name', 'rating'):
            raise ValueError('Invalid native review catalog search')
        terms = query.get('q', '').casefold().split()
        rows = [pid for pid, p in self.products.items() if (not query.get('family') or p['family_id'] == query['family']) and all(t in (p['name'] + ' ' + pretty(p['facts'])).casefold() for t in terms)]
        rows.sort(key=lambda pid: ((self.products[pid]['rating_summary']['average_rating'] is None, -(self.products[pid]['rating_summary']['average_rating'] or 0), pid) if query.get('sort') == 'rating' else (self.products[pid]['name'], pid)))
        form = '<form action="/catalog"><label>Product or keyword<input type="search" name="q" value="' + e(query.get('q', '')) + '"></label>' + select('family', 'Category', [('', 'All categories')] + [(f, self.labels[f]) for f in self.families], query.get('family', '')) + select('sort', 'Sort reviews', [('name', 'Product name'), ('rating', 'Reader rating')], query.get('sort', 'name')) + '<button>Apply filters</button>' + link('/catalog', 'Clear filters') + '</form>'
        chosen, pages = self.paged('/catalog', query, rows)
        cards = ''.join(self.card(pid) for pid in chosen) or '<p>No covered products match.</p>'
        if self.layout == 'lab-directory':
            body = '<div class="catalog"><aside><h2>Filters</h2>' + form + '</aside><section><div class="grid">' + cards + '</div>' + pages + '</section></div>'
        elif self.layout == 'editorial-magazine':
            body = '<details open><summary>Find a review</summary>' + form + '</details><section>' + cards + '</section>' + pages
        else:
            body = form + '<section class="grid">' + cards + '</section>' + pages
        return self.response('Review library', '<h1>Review library (' + str(len(rows)) + ')</h1>' + body)

    def activity_page(self, query, member=None):
        if set(query) - {'family', 'stars', 'page'} or query.get('family', '') not in ('', *self.families) or query.get('stars', '') not in ('', '1', '2', '3', '4', '5'):
            raise ValueError('Invalid community filter')
        rows = [(pid, r) for pid, r in self.written if (member is None or r['reviewer'] == member) and (not query.get('family') or self.products[pid]['family_id'] == query['family']) and (not query.get('stars') or str(r['rating']) == query['stars'])]
        route = path('members', member) if member is not None else '/activity'
        chosen, pages = self.paged(route, query, rows)
        form = '<form action="' + e(route) + '">' + select('family', 'Comment category', [('', 'All categories')] + [(f, self.labels[f]) for f in self.families], query.get('family', '')) + select('stars', 'Comment rating', [('', 'All ratings')] + [(str(n), str(n) + ' stars') for n in range(1, 6)], query.get('stars', '')) + '<button>Filter comments</button></form>'
        return self.response(member or 'Community notes', '<h1>' + e(member or 'Community notes') + '</h1>' + form + '<p>' + str(len(rows)) + ' written notes</p><section class="feed">' + ''.join(self.opinion(pid, r) for pid, r in chosen) + '</section>' + pages)

    def compare_page(self, query):
        if set(query) - {'left', 'right'}:
            raise ValueError('Invalid review comparison')
        for value in query.values():
            if value and value not in self.products:
                raise ValueError('Unknown comparison product')
        choices = [('', 'Choose product')] + [(pid, p['name']) for pid, p in sorted(self.products.items(), key=lambda row: (row[1]['name'], row[0]))]
        form = '<form action="/compare">' + select('left', 'First product', choices, query.get('left', '')) + select('right', 'Second product', choices, query.get('right', '')) + '<button>Compare</button></form>'
        ids = list(dict.fromkeys(query.get(key) for key in ('left', 'right') if query.get(key)))
        table = ''
        if ids:
            keys = sorted({k for pid in ids for k in self.products[pid]['facts']})
            table = '<div class="scroll-table"><table class="facts"><caption>Published model facts; individual comment claims remain option-specific</caption><thead><tr><th>Attribute</th>' + ''.join('<th>' + link(path('reviews', pid), self.products[pid]['name']) + '</th>' for pid in ids) + '</tr></thead><tbody>'
            for key in keys:
                table += '<tr><th scope="row">' + e(key.replace('_', ' ').capitalize()) + '</th>' + ''.join('<td>' + e(pretty(self.products[pid]['facts'][key]) if key in self.products[pid]['facts'] else 'Not published here') + '</td>' for pid in ids) + '</tr>'
            table += '</tbody></table></div>'
        return self.response('Compare product details', '<h1>Compare product details</h1>' + form + table)

    def page(self, route, query):
        if route in ('/about', '/methodology'):
            if query:raise ValueError('Unexpected methodology query')
            return self.response('Facts, opinions and coverage', '<h1>Facts, opinions and coverage</h1><p class="publication-scope">This publication syndicates the existing customer-review corpus. The same source opinions also appear on participating retailer pages; republication does not add votes. Catalog facts are not independent laboratory results. Reader comments have exact product and option scope. Model-wide summaries include ratings without comments. No publication dates, comment titles or independent editorial test scores are supplied.</p>')
        if route in ('/catalog', '/search'):
            return self.catalog_page(query)
        if route == '/activity':
            return self.activity_page(query)
        if route == '/members':
            if set(query) - {'page'}:raise ValueError('Invalid reader-directory query')
            people = sorted({r['reviewer'] for _, r in self.written})
            chosen, pages = self.paged(route, query, people)
            return self.response('Reader directory', '<h1>Readers with published comments</h1><ul>' + ''.join('<li>' + link(path('members', person), person) + '</li>' for person in chosen) + '</ul>' + pages)
        if route.startswith('/members/'):
            person = unquote(route[len('/members/'):])
            if person not in {r['reviewer'] for _, r in self.written}:raise KeyError('Unknown reader')
            return self.activity_page(query, person)
        if route == '/compare':
            return self.compare_page(query)
        if route.startswith('/variants/'):
            if query:raise ValueError('Unexpected option query')
            pid, sku = self.variants[unquote(route[len('/variants/'):])]
            query = {'part': 'readers'} if self.layout == 'editorial-magazine' else {}
            return self.response('Product option', '<h1>' + e(self.products[pid]['name']) + ': product option</h1>' + facts(self.configuration(sku)) + self.sku_summary(pid, sku['sku_id'], query) + link(url(path('reviews', pid), {'sku': sku['sku_id'], **query}), 'Comments on this option') + self.retailer_links(pid, sku['sku_id']))
        if route.startswith('/reviews/'):
            rest = route[len('/reviews/'):]
            if '/opinions/' in rest:
                if query:raise ValueError('Unexpected comment query')
                product_id, review_id = map(unquote, rest.split('/opinions/', 1))
                row = next((r for r in self.products[product_id]['reviews'] if r['review_id'] == review_id and r['text']), None)
                if row is None:raise KeyError('Unknown written review')
                return self.response('Reader note', '<h1>' + e(self.products[product_id]['name']) + ': reader note</h1>' + self.opinion(product_id, row))
            return self.product_page(unquote(rest), query)
        if route == '/':
            if query:raise ValueError('Unexpected home query')
            rows = sorted(self.products, key=lambda pid: (self.products[pid]['name'], pid))
            if self.layout == 'lab-directory':
                body = '<div class="catalog"><aside><h2>Browse a category</h2><ul>' + ''.join('<li>' + link(url('/catalog', {'family': f}), self.labels[f]) + '</li>' for f in self.families) + '</ul>' + link('/compare', 'Compare covered products') + '</aside><section><h2>Product notebooks</h2><div class="grid">' + ''.join(self.card(pid) for pid in rows[:12]) + '</div></section></div>'
            elif self.layout == 'editorial-magazine':
                body = '<section><h2>From the review library</h2>' + ''.join('<article class="card"><h2>' + link(path('reviews', pid), self.products[pid]['name'] + ': details and reader responses') + '</h2><p>Explore catalog details and option-scoped customer experiences.</p></article>' for pid in rows[:8]) + '</section>'
            else:
                body = '<div class="two"><section class="feed"><h2>Community notes</h2>' + (''.join(self.opinion(pid, r) for pid, r in self.written[:16]) or '<p>No written comments are recorded.</p>') + link('/activity', 'All community notes') + '</section><aside><h2>Explore products</h2>' + ''.join(self.card(pid) for pid in rows[:5]) + '</aside></div>'
            return self.response('Home', '<section class="hero"><h1>' + e(self.name) + '</h1><p>' + str(len(rows)) + ' covered products · Catalog details and customer experiences</p>' + link('/catalog', 'Explore reviews') + '</section>' + body)
        raise KeyError('Unknown native review route')


def e_quote(value):
    from urllib.parse import quote
    return quote(value, safe='')
