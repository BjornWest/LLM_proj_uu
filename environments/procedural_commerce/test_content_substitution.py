"""Cheap renderer contract checks; not a substitute for browser/AX acceptance."""
from copy import deepcopy
from html.parser import HTMLParser

import pytest

from .department_variations import CONTRAST
from .generator import generate_world, retailer_view
from .retailer_designs import render_retailer


class Markup(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.nodes = []
        self.text = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.nodes.append((tag, dict(attrs)))

    def handle_data(self, value):
        self.text.append(value)

    def forms(self):
        # Content changes must not alter native commerce form destinations or
        # field identity. Product-specific controls need their own future contract.
        return [(tag, attrs) for tag, attrs in self.nodes
                if tag in {'form', 'input', 'select', 'option', 'button'}]


@pytest.mark.parametrize('design,options', [
    ('department-market', None), ('department-market', CONTRAST),
    ('editorial-boutique', None), ('technical-catalog', None),
])
@pytest.mark.parametrize('payload', ['long-unicode', 'markup', 'sparse'])
@pytest.mark.parametrize('page', ['/', '/search', 'product'])
def test_content_substitution_preserves_page_contract(design, options, payload, page):
    catalog = retailer_view(generate_world(7), 'nordhem')
    changed = deepcopy(catalog)
    product = changed['products'][0]
    if payload == 'long-unicode':
        product['name'] = 'Ångström 東京 — Long descriptive catalog title ' * 40
        product['attributes'] = {f'property_{i}': 'Factual value Å & "quoted" ' * 20
                                 for i in range(30)}
        product['traits'] = ['Long trait ' * 30, 'Unicode 東京']
    elif payload == 'markup':
        product['name'] = '</h2><script>injected()</script><form action="https://invalid.test">'
        product['attributes'] = {'<img onerror="injected()">': '</td><input name="quantity" value="999">'}
        product['traits'] = ['<iframe src="https://invalid.test"></iframe>']
    else:
        product['name'] = 'X'
        product['attributes'] = {}
        product['traits'] = []
    path = f'/products/{product["product_id"]}' if page == 'product' else page
    def render(data, route):
        return Markup(render_retailer('nordhem', route, {},
                      {'catalog': data, 'cart': None}, {'nordhem': '/store'},
                      design, options))
    before, after = render(catalog, path), render(changed, path)
    assert after.forms() == before.forms()
    # A landing page may show collections only; do not force every design to
    # display products there. Results and product pages must retain the name.
    if page != '/' or catalog['products'][0]['name'] in ''.join(before.text):
        assert product['name'] in ''.join(after.text)
    assert sum(tag == 'main' for tag, _ in after.nodes) == 1
    ids = [attrs['id'] for _, attrs in after.nodes if 'id' in attrs]
    assert len(ids) == len(set(ids))
    for tag, attrs in after.nodes:
        assert tag not in {'script', 'iframe'}
        assert not any(key.startswith('on') for key in attrs)
        for ref in attrs.get('aria-labelledby', '').split():
            assert ref in ids
    # Boutique facts intentionally live on a separate route. Other designs may
    # use closed disclosures: source reachability here is NOT policy exposure.
    if page == 'product':
        facts = render(changed, path + '/details') if design == 'editorial-boutique' else after
        text = ''.join(facts.text)
        for value in product['attributes'].values():
            assert value in text
