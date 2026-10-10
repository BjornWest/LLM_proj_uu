"""Regression controls for request-local offer ordering; no hosts or providers."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Event

import pytest

from .comparison_pages import ComparisonPage
from .test_rich_surrounding import view


def comparator(layout):
    site = deepcopy(view((layout, layout, layout)).site)
    rows = [
        {'entry_offer_id': rid + '/shoe', 'retailer_id': rid,
         'price_minor': price, 'advertised_price_minor': price}
        for rid, price in [('r-a', 60000), ('r-b', 10000), ('r-c', 20000)]
    ]
    products = {'shoe': {'name': 'Fixture Shoe', 'family_id': 'footwear',
                         'facts': {'waterproof': True}, 'listings': rows}}
    bindings = {row['entry_offer_id']: {
        'retailer_id': row['retailer_id'], 'product_id': 'shoe',
        'model_url': 'https://' + row['retailer_id'] + '.test/product/shoe'}
        for row in rows}
    return ComparisonPage(site, products, bindings,
                          {'r-a': 'Alpha', 'r-b': 'Zulu', 'r-c': 'Middle'},
                          '', {})


@pytest.mark.parametrize('layout', ['directory', 'specialist'])
def test_model_page_is_independent_of_previous_offer_sort_requests(layout):
    page = comparator(layout)
    design = page.views[layout]
    original = deepcopy(design.items)
    merchant_before = page.page('/models/shoe', {'merchant': 'r-c'})
    catalog_before = page.page('/search', {})
    price = page.page('/models/shoe', {})[1]
    names = page.page('/models/shoe', {'offer_sort': 'retailer'})[1]
    # Check the actual displayed offer order, independently of the merchant form.
    price = price.split('Advertised item prices')[-1] if layout == 'directory' else price.split('<details class="offer">', 1)[-1]
    names = names.split('Advertised item prices')[-1] if layout == 'directory' else names.split('<details class="offer">', 1)[-1]
    assert price.index('View offer at Zulu') < price.index('View offer at Middle') < price.index('View offer at Alpha')
    assert names.index('View offer at Alpha') < names.index('View offer at Middle') < names.index('View offer at Zulu')
    assert page.page('/models/shoe', {'merchant': 'r-c'}) == merchant_before
    assert page.page('/search', {}) == catalog_before
    assert design.items == original


@pytest.mark.parametrize('layout', ['directory', 'specialist'])
def test_catalog_keeps_all_offers_during_an_overlapping_model_sort(layout):
    page = comparator(layout)
    design = page.views[layout]
    item = design.by_id['shoe']
    original = deepcopy(design.items)
    entered, release = Event(), Event()

    class PausedName(dict):
        def __getitem__(self, key):
            if key == 'name' and not entered.is_set():
                entered.set()
                if not release.wait(5):
                    raise RuntimeError('Concurrent-render control timed out')
            return super().__getitem__(key)

    design.stores['r-a'] = PausedName(design.stores['r-a'])
    with ThreadPoolExecutor(max_workers=1) as worker:
        sorting = worker.submit(page.page, '/models/shoe', {'offer_sort': 'retailer'})
        try:
            assert entered.wait(5), 'Offer sort was never reached'
            assert design.price(item) == 10000
            assert len(design.offers(item)) == 3
            status, body, _ = page.page('/search', {'max_price': '150'})
            assert status == 200
            assert 'Fixture Shoe' in body and '100.00 SEK' in body
            assert 'No listed price' not in body
        finally:
            release.set()
        assert sorting.result(timeout=5)[0] == 200
    assert design.items == original
