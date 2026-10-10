"""Independent native/public projection, HTTP and stale-response acceptance."""
from copy import deepcopy
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import json
import subprocess

import pytest

from experiments.footwear_world_pilot import basket_quote, model
from environments.website_world.adapter import PublicAdapter
from environments.website_world.basket import Baskets
from environments.website_world.runtime import Runtime
from environments.website_world.generation import compile_request, VERSION

ROOT = Path(__file__).resolve().parents[2]
PACKET = ROOT/'.local/coordination/website-basket-shipping-oracle/callable-v1'


@pytest.fixture
def fixture():
    receipt = json.loads((PACKET/'receipt.json').read_text())
    world = json.loads((ROOT/receipt['world']['path']).read_text())
    plan = json.loads((PACKET/'plan.json').read_text())
    original = json.loads((PACKET/'request.json').read_text())
    sid = original.pop('retailer_id')
    baskets = Baskets(PublicAdapter(world), plan)
    request = {'revision': 7, 'world_id': world['world_id'], 'plan_id': baskets.plan_id,
        'address': baskets.adapter.initial_address, 'coupon_code': None, **original}
    return world, baskets, sid, request


def test_every_public_complete_option_preserves_native_totals_groups_and_allocations(fixture):
    world, baskets, sid, request = fixture
    before = deepcopy(world)
    got = baskets.quote(sid, request)
    raw = basket_quote.quote(world, sid, request['lines'], plan=baskets.plan,
        destination=world['user_location'], selections=got['selected']['selection'])
    assert got['quoteId'] == raw['quote_id']
    assert len(got['options']) == len(raw['options'])
    for public, native in zip(got['options'], raw['options']):
        assert [public[k] for k in ('subtotalMinor','discountMinor','shippingMinor','totalMinor')] == [
            native[k] for k in ('subtotal_minor','discount_minor','shipping_minor','total_minor')]
        assert public['selection'] == native['selection']
        assert public['lineDiscountAllocations'] == native['line_discount_allocations']
        assert [s['lineIds'] for s in public['shipments']] == [s['line_ids'] for s in native['shipments']]
        assert [s['qualification'] for s in public['shipments']] == [s['qualification'] for s in native['shipments']]
        assert [s['arrival'] for s in public['shipments']] == [s['arrival'] for s in native['shipments']]
    forbidden = {'latitude','longitude','local_east_km','local_north_km','route','precision','task','reference','private','price_trace'}
    def inspect(value):
        if isinstance(value,dict):
            assert not forbidden.intersection(value)
            for child in value.values(): inspect(child)
        elif isinstance(value,list):
            for child in value: inspect(child)
    inspect(got)
    assert world == before and model.solve(world) == world['reference']


def test_service_change_and_quantity_revision_recompute_full_quote(fixture):
    world, baskets, sid, request = fixture
    first = baskets.quote(sid, request)
    choice = next(o for o in first['options'] if o['id'] != first['selected']['id'])
    changed = baskets.quote(sid, {**request,'revision':8,'selections':choice['selection']})
    assert changed['selected']['totalMinor'] == choice['totalMinor']
    assert changed['quoteId'] != first['quoteId']
    assert changed['requestId'] != first['requestId']
    more = deepcopy(request);more['revision']=9;more['lines'][0]['quantity']=2
    result = baskets.quote(sid, more)
    assert result['selected'] is not None
    assert result['selected']['subtotalMinor'] == first['selected']['subtotalMinor'] + 117900
    duplicate = deepcopy(request)
    duplicate['lines'] = [{'line_id':'a','offer_id':request['lines'][0]['offer_id'],'quantity':100000},
                          {'line_id':'b','offer_id':request['lines'][0]['offer_id'],'quantity':100000}]
    result = baskets.quote(sid,duplicate)
    assert result['selected'] is None and result['status']=='unavailable'


def test_stale_plan_selection_and_unknown_destination_are_explicit(fixture):
    _, baskets, sid, request = fixture
    for field in ('world_id','plan_id'):
        with pytest.raises(ValueError):baskets.quote(sid,{**request,field:'stale'})
    with pytest.raises(ValueError):baskets.quote(sid,{**request,'address':{**request['address'],'postcode':'99999'}})
    reset = baskets.quote(sid,{**request,'selections':{'not-a-line':'not-a-service'}})
    assert reset['selectionReset'] and reset['selected'] is not None


def test_basket_coupon_projection_preserves_one_discount_and_line_allocations(fixture):
    from types import SimpleNamespace
    from experiments.footwear_world_pilot import coupon_quote
    world,baskets,sid,request=fixture
    plan=coupon_quote.make_plan(world,[{'retailer_id':sid,'signed_in':True,'coupons':[
        {'coupon_id':'basket-test','code':'SAVE','kind':'fixed','value':10000,
         'minimum_subtotal_minor':0,'concept_ids':[],'valid_from':'2026-09-01',
         'valid_until':'2026-12-31','redeemed':False,'currency':'SEK'}]}])
    baskets.coupons=SimpleNamespace(plan=plan,account=lambda rid:coupon_quote.public_account(plan,rid))
    before=deepcopy(plan)
    got=baskets.quote(sid,{**request,'coupon_code':'SAVE'})['selected']
    assert got['discountMinor']==10000 and got['totalMinor']==319700
    assert sum(got['lineDiscountAllocations'].values())==10000
    assert got['coupon']['status']=='applied' and plan==before


def test_http_read_only_json_quote_and_legacy_runtime_preserved(fixture):
    _, baskets, sid, request = fixture
    pin = ROOT/'.local/website-surrounding-integration-v2/connected/pin'
    with Runtime(pin,basket_plan=baskets.plan) as runtime:
        origin = runtime.origins[sid]
        req = Request(origin+'/api/basket-quote',data=json.dumps(request).encode(),headers={'Content-Type':'application/json'})
        result=json.load(urlopen(req));assert result['selected']['totalMinor']==329700
        assert runtime.manifest['automatic_grader_supported'] is False
        source=urlopen(origin+'/shop.js').read().decode()
        assert 'worldBinding?.basket?20' in source
        for path in ('/purchase','/basket-plan.private.json'):
            with pytest.raises(HTTPError) as e:urlopen(Request(origin+path,data=b'{}',headers={'Content-Type':'application/json'}))
            assert e.value.code==405
        with pytest.raises(HTTPError) as e:
            urlopen(Request(origin+'/api/basket-quote',data=b'{"revision":1,"revision":2}',headers={'Content-Type':'application/json'}))
        assert e.value.code==400
        assert runtime.snapshot()['orders']==[] and runtime.snapshot()['commerce_mutations']==[]
    with Runtime(pin) as legacy:
        origin=legacy.origins[sid]
        assert urlopen(origin+'/shop.js').read()==(ROOT/'environments/website_drafts/shop.js').read_bytes()
        with pytest.raises(HTTPError) as e:urlopen(Request(origin+'/api/basket-quote',data=b'{}'))
        assert e.value.code==405


@pytest.mark.parametrize('option',[True,{}, {'enabled':1}, {'enabled':True,'policy':{}}])
def test_generation_rejects_unsupported_basket_configuration(option):
    with pytest.raises(ValueError):compile_request({'schema':VERSION,'seed':2,'basket_shipping':option})


def test_browser_quote_cache_does_not_promote_stale_response_and_covers_all_inputs():
    source=(ROOT/'environments/website_world/basket_quote.js').read_text()
    source='\n'.join(line for line in source.splitlines() if not line.startswith(('import ','export {')))
    setup="""
const data={basket:{worldId:'world',planId:'plan'}};
const itemBinding={};const validateAddress=()=>[];
const byVariant=key=>({variant:{offerId:key},product:{name:key}});
const pending=[];globalThis.fetch=(url,args)=>new Promise(resolve=>pending.push({resolve,args}));
"""
    checks="""
const assert=(value)=>{if(!value)throw Error('cache assertion failed');};
const draft={revision:1,cart:[{id:'a',key:'offer',quantity:1}],address:{name:'N'},addressStatus:'valid',coupon:'',split:false};
const key=worldBinding.inquiryKey(draft);
for(const mutate of [d=>d.cart[0].quantity++,d=>d.address.name='Other',d=>d.coupon='CODE',d=>d.split=true,d=>d.basketSelection={a:'service'}]){
 const changed=structuredClone(draft);mutate(changed);assert(worldBinding.inquiryKey(changed)!==key);
}
const old=worldBinding.ensureQuote(draft);assert(pending.length===1);
draft.revision=2;draft.cart[0].quantity=2;
const fresh=worldBinding.ensureQuote(draft);assert(pending.length===2);
const packet={revision:2,selected:{shipments:[],subtotalMinor:200,discountMinor:0,shippingMinor:50,totalMinor:250,coupon:{status:'not_requested'}},options:[],canSplit:false};
pending[1].resolve({ok:true,json:async()=>packet});assert(await fresh);
pending[0].resolve({ok:true,json:async()=>({...packet,revision:1,selected:{...packet.selected,totalMinor:99999}})});assert(!(await old));
assert(quote(draft.cart,draft,{},2).total===2.5);
assert(!(await worldBinding.ensureQuote(draft)));
"""
    subprocess.run(['node','--input-type=module'],input=setup+source+checks,text=True,check=True,capture_output=True)
