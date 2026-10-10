from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from urllib.request import urlopen
from urllib.parse import urlencode
from urllib.error import HTTPError
import json
import pytest
from experiments.accepted_catalog_commerce import pin_v2,basket_quote
from environments.website_world import unified_generation
from environments.website_world.runtime import Runtime


@pytest.fixture(scope='module')
def fixture(tmp_path_factory):
    root=tmp_path_factory.mktemp('lazy-world')
    old=Path('.local/generation-scaling-20261005-v1/scale1-unconditioned')
    world=json.loads((old/'pin/world.private.json').read_text())
    request=json.loads((old/'request.json').read_text())
    result=unified_generation.generate(request,world_factory=lambda *a,**kw:world)
    pin_v2.freeze(world,root/'pin',source_store=root/'store')
    with Runtime(root/'pin',source_store=root/'store',lazy_publication=True,
                 presentation=result['presentation'],surrounding=result['surrounding'],
                 basket_plan=result['basket_plan'],checkout_domain=result['checkout_domain']) as runtime:
        yield runtime,result


def test_bootstrap_is_pending_not_unavailable(fixture):
    runtime,result=fixture
    assert runtime.prepared.binding['world_id']==runtime.world['world_id']
    assert runtime.manifest['publication']['mode']=='lazy_selected_sku'
    for rid,catalog in runtime.public_catalogs.items():
        assert next(s['offers'] for s in runtime.manifest['sites'] if s['retailer_id']==rid)==len(runtime.adapter.retailers[rid]['offers'])
        assert catalog['lazyFulfilment'] and catalog['fulfilment']['pending']
        assert catalog['fulfilment']['optionsBySku']=={}
        assert len([v for p in catalog['products'] for v in p['variants']])==len(runtime.adapter.retailers[rid]['offers'])


def test_selected_sku_http_and_address_validation(fixture):
    runtime,result=fixture;rid=next(iter(runtime.origins));v=runtime.public_catalogs[rid]['products'][0]['variants'][0]
    address=runtime.public_catalogs[rid]['rememberedAddress']
    url=runtime.origins[rid]+'/api/fulfilment?'+urlencode(address)
    with urlopen(url) as response:pending=json.load(response)
    assert pending['pending'] and pending['optionsBySku']=={}
    with urlopen(url+'&sku_id='+v['skuId']) as response:selected=json.load(response)
    assert set(selected['optionsBySku'])=={v['skuId']}
    assert selected==runtime.adapter.fulfilment(rid,address,sku_ids=[v['skuId']])
    with pytest.raises(HTTPError) as error:urlopen(url+'&sku_id=foreign')
    assert error.value.code==400


def test_parallel_selected_projections_match_complete_public_projection(fixture):
    runtime,result=fixture;rid=next(iter(runtime.origins));catalog=runtime.public_catalogs[rid]
    address=catalog['rememberedAddress'];skus=[v['skuId'] for p in catalog['products'] for v in p['variants']]
    with ThreadPoolExecutor(max_workers=3) as pool:
        partial=list(pool.map(lambda sku:runtime.adapter.fulfilment(rid,address,sku_ids=[sku]),skus[:6]))
    full=runtime.adapter.fulfilment(rid,address)
    for value in partial:
        for sku,rows in value['optionsBySku'].items():assert rows==full['optionsBySku'][sku]
    for sku,rows in full['optionsBySku'].items():
        offer=next(o for o in runtime.adapter.retailers[rid]['offers'] if o['sku_id']==sku)
        raw=basket_quote.quote(runtime.world,rid,[{'line_id':offer['offer_id'],'offer_id':offer['offer_id'],'quantity':1}],plan=result['basket_plan'])
        assert sorted((r['totalMinor'],r['shippingMinor']) for r in rows)==sorted((o['total_minor'],o['shipping_minor']) for o in raw['options'])


def test_basket_quote_exact_public_requote_and_binding_rejection(fixture):
    runtime,result=fixture;rid=next(iter(runtime.origins));catalog=runtime.public_catalogs[rid]
    variants=[v for p in catalog['products'] for v in p['variants'] if v['state']!='unavailable']
    selected=variants[:2];lines=[{'line_id':v['offerId'],'offer_id':v['offerId'],'quantity':1} for v in selected]
    request={'revision':1,'world_id':runtime.world['world_id'],'plan_id':runtime.baskets.plan_id,
        'domain_id':runtime.baskets.domain_id,'lines':lines,'address':catalog['rememberedAddress'],
        'selections':None,'split':False,'coupon_code':None}
    actual=runtime.baskets.quote(rid,request)
    if actual['selected']:
        expected=basket_quote.quote(runtime.world,rid,lines,plan=result['basket_plan'],selections=actual['selected']['selection'])
        assert actual['quoteId']==expected['quote_id']
        assert actual['selected']['totalMinor']==expected['selected']['total_minor']
    with pytest.raises(ValueError,match='binding changed'):runtime.baskets.quote(rid,{**request,'plan_id':'foreign'})


def test_bound_domain_reuses_validation_without_weakening_public_checks(fixture,monkeypatch):
    from environments.website_world import catalog_checkout_domain as domain
    runtime,result=fixture
    original=domain.validate
    calls=[]
    def recording(world,value):
        calls.append(value)
        return original(world,value)
    monkeypatch.setattr(domain,'validate',recording)
    bound=domain._BoundDomain(runtime.world,result['checkout_domain'])
    assert len(calls)==1
    for retailer in runtime.world['retailers']:
        rid=retailer['retailer_id']
        value=bound.public(rid)
        assert value==runtime.baskets.public_domain(rid)
        limits=deepcopy(value['quantityLimits'])
        value['quantityLimits'].clear()
        assert bound.public(rid)['quantityLimits']==limits
        if not retailer['offers']:continue
        oid=retailer['offers'][0]['offer_id']
        lines=[{'line_id':'first','offer_id':oid,'quantity':1},
               {'line_id':'second','offer_id':oid,'quantity':2}]
        assert bound.canonical_lines(rid,lines)[0]==[{'line_id':oid,'offer_id':oid,'quantity':3}]
        active_rid=rid
    assert len(calls)==1
    broken=deepcopy(result['checkout_domain']);broken['world_sha256']='stale'
    with pytest.raises(ValueError,match='binding'):domain.public(runtime.world,broken,active_rid)
    with pytest.raises(ValueError,match='binding'):domain.canonical_lines(runtime.world,broken,active_rid,lines)
    assert len(calls)==3
    with pytest.raises(ValueError,match='identity or quantity'):
        bound.canonical_lines(active_rid,[{'line_id':'x','offer_id':oid,'quantity':True}])
