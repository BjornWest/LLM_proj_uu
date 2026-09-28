"""Frozen merchandising projection; commercial facts and default pages are independent."""
from urllib.error import HTTPError
from urllib.parse import urlencode
import pytest
from environments.product_world.storefront_content import attach_storefront_content
from environments.product_world.generator import digest
from .test_interaction_patterns import specimen, fetch
from .runtime import Runtime
from .conformance import Document
from . import pages, storefront


@pytest.fixture(scope='module')
def merch():
    scenario=attach_storefront_content(specimen(),seed=17)
    with Runtime(scenario,consent=False) as rt:yield rt


def links(root):
    return {a.attrs.get('href') for a in root.find('a')}


def test_sections_and_shell_navigation_use_export(merch):
    before=digest(merch.world)
    for sid,row in merch.storefront_by_store.items():
        root=Document(fetch(merch,sid,'/')).root
        nav=root.one('nav',**{'aria-label':'Shop by category'})
        assert [a.text() for a in nav.find('a')]==[c['title'] for c in row['collections']]
        for section in row['sections']:
            rendered=root.one('section',**{'aria-labelledby':'home-'+section['section_id']})
            assert rendered.one('h2').text()==section['title']
            assert section['body'] in rendered.text()
            assert storefront.section_path(section) in links(rendered)
        assert not root.find('nav',**{'aria-label':'Other websites'})
        assert not root.find('nav',**{'aria-label':'Pagination'})
        assert root.one('nav',**{'aria-label':'Customer service'})
    assert digest(merch.world)==before
    assert merch.provenance['storefront_content_sha256']==digest(merch.storefront_content)


def test_collection_search_and_navigation_do_not_leak_other_members(merch):
    for sid,row in merch.storefront_by_store.items():
        for collection in row['collections']:
            path=storefront.collection_path(collection)
            expected=pages.display_products(merch,[merch.products[sku] for sku in collection['product_ids']])
            for route in (path,'/search?'+urlencode({'collection':collection['collection_id']})):
                root=Document(fetch(merch,sid,route)).root
                results=root.one('section',**{'aria-label':'Product results'})
                actual={a.attrs['href'].split('/products/')[-1] for a in results.find('a') if '/products/' in a.attrs.get('href','')}
                assert actual <= set(collection['product_ids'])
                def identity(sku):
                    return merch.group_for[sku]['group_id'] if merch.products[sku]['category']=='footwear' else sku
                assert {identity(sku) for sku in actual}=={identity(p['product_id']) for p in expected[:12]}
                assert str(len(expected))+' product listings' in results.text()
            sku=collection['product_ids'][0]
            exact=Document(fetch(merch,sid,'/search?'+urlencode({'collection':collection['collection_id'],'q':sku}))).root
            assert '1 product listings' in exact.text()
            assert exact.find('a',href=merch.origins[sid]+'/products/'+sku)


def test_model_sections_use_all_carried_variants_for_price(merch):
    for sid,row in merch.storefront_by_store.items():
        for section in row['sections']:
            root=Document(fetch(merch,sid,storefront.section_path(section))).root
            expected=pages.display_products(merch,storefront.model_products(merch,sid,section['product_ids']))
            for product in expected[:12]:
                if product.get('_browse_variants'):
                    expected_min=min(merch.offer_by_store[(sid,sku)]['price_minor'] for sku in product['_browse_variants'])
                    assert 'From '+pages.money(expected_min) in root.text()


def test_compact_service_pages_work_without_fabricated_promises(merch):
    for sid in merch.stores:
        assert 'not listed' in fetch(merch,sid,'/returns')
        assert 'not available' in fetch(merch,sid,'/terms')
        root=Document(fetch(merch,sid,'/contact')).root
        assert '/branches' in links(root)
        for path in ('/collections/missing','/highlights/missing','/collections/x/extra','/search?collection=missing','/returns?period=30'):
            with pytest.raises(HTTPError) as error:fetch(merch,sid,path)
            assert error.value.code in (400,404)


def test_invalid_sidecar_rejected_before_opening_pages():
    s=attach_storefront_content(specimen(),seed=17)
    s['storefront_content']['source_world_sha256']='bad'
    with pytest.raises(ValueError):Runtime(s,consent=False)
