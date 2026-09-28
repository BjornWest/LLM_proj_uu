"""Retailers must not expose privileged discovery shortcuts or a size-per-card home."""
from urllib.parse import urlsplit,urlencode
from .test_interaction_patterns import rt,fetch
from .conformance import Document
from . import pages
from environments.product_world.generator import digest


def test_home_is_bounded_collections_not_search_pagination(rt):
    before=digest(rt.world)
    for sid in rt.stores:
        html=fetch(rt,sid,'/');root=Document(html).root
        assert 'Shop the collection' in root.text()
        assert not root.find('nav',**{'aria-label':'Pagination'})
        assert not root.find('caption')  # Home stays a curated display even with list-mode search.
        assert root.find('nav',**{'aria-label':'Shop by category'})
        assert 'product listings' not in root.text()
    assert digest(rt.world)==before


def test_footwear_search_groups_sizes_and_prices_correctly(rt):
    for sid in rt.stores:
        products=[p for p in rt.catalog(sid)['products'] if p['category']=='footwear']
        if not products:continue
        models={rt.group_for[p['product_id']]['group_id'] for p in products}
        grouped=pages.display_products(rt,products)
        assert len(grouped)==len(models)
        for p in grouped:
            g=rt.group_for[p['product_id']]
            assert p['name']==g['name']
            assert not set(p['attributes'])&{a['field'] for a in g['axes']}
            offers=[rt.offer_by_store[(sid,sku)] for sku in p['_browse_variants']]
            html=pages.cards(rt,sid,[p])
            assert 'From '+pages.money(min(o['price_minor'] for o in offers)) in html
            for sku in p['_browse_variants']:
                # Every exact option remains reachable; grouping removes no product page.
                assert 'id="selected-sku">'+sku in fetch(rt,sid,'/products/'+sku)
        assert str(len(models))+' product listings' in fetch(rt,sid,'/search?category=footwear')


def test_retailers_have_no_external_discovery_shortcuts(rt):
    forbidden={urlsplit(origin).netloc for sid,origin in rt.origins.items()
               if sid=='aggregator' or sid=='index' or sid=='merchant-reviews' or sid.startswith('reviews-')}
    for sid in rt.stores:
        offer=next(o for o in rt.offers.values() if o['retailer_id']==sid)
        p=rt.products[offer['product_id']]
        for path in ('/','/search?'+urlencode({'q':p['name']}),'/products/'+p['product_id'],'/quote?'+urlencode({'offer_id':offer['offer_id']}),'/policy'):
            root=Document(fetch(rt,sid,path)).root
            assert 'Other websites' not in root.text()
            assert not any(urlsplit(a.attrs.get('href','')).netloc in forbidden for a in root.find('a'))


def test_exact_size_query_still_leads_to_matching_sku(rt):
    o=next(o for o in rt.offers.values() if rt.products[o['product_id']]['category']=='footwear')
    html=fetch(rt,o['retailer_id'],'/search?'+urlencode({'q':o['product_id']}))
    assert '/products/'+o['product_id'] in html
    assert '1 product listings' in html
