from copy import deepcopy
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import urlopen,Request
from urllib.error import HTTPError
from urllib.parse import urljoin,urlsplit,urlencode
import json
import os
import pytest
from .runtime import Runtime
from .pins import load_pin
from .index import Catalog,tokens
from environments.product_world.generator import digest

# These are frozen-world acceptance checks, not portable generated unit fixtures.
PIN=os.environ.get('CONNECTED_SHOPPING_PIN')


@pytest.fixture(scope='module')
def scenario():
    if not PIN:
        pytest.skip('Set CONNECTED_SHOPPING_PIN to an explicitly selected compatible frozen world')
    # An explicitly requested missing/stale pin remains an error, never a skip.
    return load_pin(Path(PIN))[0]
@pytest.fixture(scope='module')
def rt(scenario):
    with Runtime(scenario,consent=False) as x:yield x


class Links(HTMLParser):
    def __init__(self,html):super().__init__();self.links=[];self.feed(html)
    def handle_starttag(self,tag,attrs):
        if tag=='a':self.links.append(dict(attrs).get('href',''))


def test_identity_and_index_no_task_or_private_values(rt,scenario):
    assert digest(rt.world)==digest(scenario['bundle'])
    assert rt.merchant_reviews==scenario['merchant_reviews']
    assert len(rt.site_records)==15 and len(rt.origins)==16
    assert not hasattr(rt,'task')
    public=json.dumps(rt.public_manifest)+json.dumps(rt.documents)
    for marker in ('reference_price_minor','resolved_task','overlap_anchors','hidden_user_specifications','world_requirements','winner'):assert marker not in public
    for sid in rt.stores:
        listed={o['product_id'] for o in rt.offers.values() if o['retailer_id']==sid}
        assert {p['product_id'] for p in rt.catalog(sid)['products']}==listed
        assert not any('reference_price_minor' in p for p in rt.catalog(sid)['products'])
    for sku,bound in rt.bindings['retailer_products'].items():
        sid=next(s for s in rt.stores if bound.startswith(rt.origins[s]+'/'))
        assert (sid,sku) in rt.offer_by_store


def test_all_indexed_routes_and_one_level_links_resolve(rt):
    origins={urlsplit(o).netloc for o in rt.origins.values()};seen=set()
    # Every indexed page once; surrounding distinct links from each site's first page.
    for d in rt.documents:
        u=rt.origins[d['site_id']]+d['path']
        with urlopen(u) as r:assert r.status==200;html=r.read().decode()
        seen.add(u)
        if d['path']=='/':
            for href in Links(html).links:
                link=urljoin(u,href)
                if urlsplit(link).fragment:continue
                assert urlsplit(link).netloc in origins,link
                if link not in seen:
                    assert urlopen(link).status==200;seen.add(link)


def test_quote_identity_and_store_isolation(rt):
    for sid in rt.stores:
        offer=next(o for o in rt.offers.values() if o['retailer_id']==sid)
        q=rt.quote(offer['offer_id']);url=rt.origins[sid]+'/quote?'+urlencode({'offer_id':offer['offer_id']})
        html=urlopen(url).read().decode()
        assert 'Delivery quote' in html and offer['product_id'] in html
        if q['eligible']:assert f'{q["total_minor"]/100:.2f} SEK' in html
        other=next(s for s in rt.stores if s!=sid)
        with pytest.raises(HTTPError) as error:urlopen(rt.origins[other]+'/quote?'+urlencode({'offer_id':offer['offer_id']}))
        assert error.value.code==404


def test_index_filters_lexical_search_and_no_oracle_ranking(rt):
    item=rt.comparisons[0];sku=item['id'];name=item['name']
    rows=rt.index.catalog.search(sku,kind='aggregator');assert len(rows)==1 and rows[0]['path'].endswith(sku)
    assert rt.index.catalog.search(name)
    assert not rt.index.catalog.search('zzzz不存在')
    assert all(rt.index.catalog.by_id[d['site_id']]['kind']=='product_reviews' for d in rt.index.catalog.search('',kind='product_reviews'))
    assert tokens('ABC-test_name')==['abc','test','name']


def test_nonmutation_and_private_routes(rt):
    before=digest(rt.world)
    for sid in ['store-001','aggregator','merchant-reviews']:
        for path in ['/api/state','/scenario.private.json','/reference.private.json','/task']:
            with pytest.raises(HTTPError) as error:urlopen(rt.origins[sid]+path)
            assert error.value.code==404
        with pytest.raises(HTTPError) as error:urlopen(Request(rt.origins[sid]+'/checkout',data=b'{}'))
        assert error.value.code==405
    assert digest(rt.world)==before and rt.snapshot()['orders']==[]


def test_partial_invalid_unlisted_and_soldout_variants(rt):
    sid='store-001';o=next(o for o in rt.offers.values() if o['retailer_id']==sid);sku=o['product_id'];group=rt.group_for[sku]
    partial=urlencode({'option_'+group['axes'][0]['field']:''})
    assert 'Choose all product options' in urlopen(rt.origins[sid]+'/products/'+sku+'?'+partial).read().decode()
    unlisted=next((v['product_id'] for v in group['variants'] if (sid,v['product_id']) not in rt.offer_by_store),None)
    assert unlisted and 'store does not list' in urlopen(rt.origins[sid]+'/products/'+unlisted).read().decode()
    out=next(o for o in rt.offers.values() if o['stock_quantity']==0)
    assert 'Availability: <strong>Unavailable' in urlopen(rt.origins[out['retailer_id']]+'/products/'+out['product_id']).read().decode()
    foreign=next(p for p in rt.products if rt.group_for[p]['group_id'] not in rt.groups_by_store[sid])
    with pytest.raises(HTTPError) as error:urlopen(rt.origins[sid]+'/products/'+foreign)
    assert error.value.code==404


def test_other_tasks_cannot_change_composition(scenario):
    changed=deepcopy(scenario);changed['task']={'private':'NEVER-EXPOSE-CANARY'}
    with Runtime(changed,consent=False) as rt:
        assert rt.product_reviews['private_provenance']['source_catalog_sha256']
        assert 'NEVER-EXPOSE-CANARY' not in json.dumps(rt.documents)
        assert 'NEVER-EXPOSE-CANARY' not in urlopen(rt.index_origin).read().decode()
