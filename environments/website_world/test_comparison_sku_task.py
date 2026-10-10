from copy import deepcopy
from hashlib import sha256
import json
import pytest
from environments.website_world.comparison_sku_task import make, reference, bind_public


def fixture():
    skus=[{'sku_id':'p-black-42','product_id':'p','colour':'black','size_eu':42},
          {'sku_id':'p-blue-42','product_id':'p','colour':'blue','size_eu':42}]
    world={'world_id':'w','quote_as_of':'2026-09-30','products':[
        {'public':{'product_id':'p','name':'Example Luma','skus':skus},
         'variant_fields':{'colour':{},'size_eu':{}}}], 'retailers':[]}
    for rid,price,stock,supplier in [('a',50000,0,True),('b',60000,4,False)]:
        world['retailers'].append({'retailer_id':rid,'name':rid.upper(),
            'source_locations':[{'source_id':rid+'-shop','shipping_enabled':False}],
            'offers':[{'offer_id':rid+'/p-black-42','sku_id':'p-black-42',
                'price_minor':price,'stock_by_source':{rid+'-shop':stock},
                'supplier_order':{'enabled':supplier}}]})
    sidecar={'source_world_id':'w','source_world_sha256':sha256(
        json.dumps(world,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),
        'sites':[{'site_id':'comparison-00','kind':'aggregator','name':'Compare',
            'product_ids':['p'],'listings':[{'product_id':'p','retailer_id':'a','price_minor':50000},
                                         {'product_id':'p','retailer_id':'b','price_minor':60000}]}]}
    return world,sidecar


def test_backorder_cheapest_retained_instead_of_replacing_with_available_store():
    w,s=fixture();task=make(w,s,comparison_site_id='comparison-00',sku_id='p-black-42')
    result=reference(w,s,task)
    assert result['minimum_advertised_price_minor']==50000
    assert [r['retailer_id'] for r in result['winners']]==['a']
    assert result['winners'][0]['availability']=='backorder'
    assert result['winners'][0]['in_stock'] is False
    assert task['selectors']=={'colour':'black','size_eu':42}
    assert 'retailer with the lowest' in task['user_message']
    assert 'A' not in task['user_message'].split('Open the retailer')[0]


def test_any_tie_and_branch_stock_not_shipping_stock():
    w,s=fixture();s['sites'][0]['listings'][1]['price_minor']=50000
    task=make(w,s,comparison_site_id='comparison-00',sku_id='p-black-42')
    result=reference(w,s,task)
    assert [r['retailer_id'] for r in result['winners']]==['a','b']
    assert result['winners'][1]['in_stock'] is True
    assert result['winners'][1]['stock'][0]['shipping_enabled'] is False
    assert result['winners'][1]['live_price_minor']==60000


def test_exact_variant_absent_is_not_inferred_from_other_variant():
    w,s=fixture();task=make(w,s,comparison_site_id='comparison-00',sku_id='p-blue-42')
    result=reference(w,s,task)
    assert result['winners'][0]['availability']=='variant_not_sold'
    assert result['winners'][0]['offer_id'] is None


@pytest.mark.parametrize('change',['task','source','model_membership','ambiguous_variants'])
def test_changed_bindings_rejected(change):
    w,s=fixture();task=make(w,s,comparison_site_id='comparison-00',sku_id='p-black-42')
    if change=='task':task['selectors']['size_eu']=40
    if change=='source':w['retailers'][0]['offers'][0]['price_minor']+=1
    if change=='model_membership':s['sites'][0]['product_ids']=[]
    if change=='ambiguous_variants':
        w['products'][0]['public']['skus'].append(deepcopy(w['products'][0]['public']['skus'][0]))
    with pytest.raises(ValueError):reference(w,s,task)


def test_public_task_starts_at_comparison_and_omits_private_winners():
    from types import SimpleNamespace
    w,s=fixture();task=make(w,s,comparison_site_id='comparison-00',sku_id='p-black-42')
    runtime=SimpleNamespace(world=w,site_registry=[{'site_id':'comparison-00','name':'Compare','origin':'https://compare.test'}])
    public=bind_public(runtime,task)
    assert public['start_url']=='https://compare.test/'
    assert 'winners' not in public and 'requirements' not in public
    assert public['environment_context']['shopping_scope'].startswith('Price comparison on Compare')
