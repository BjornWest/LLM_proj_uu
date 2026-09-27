import copy
import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import pytest
from .stores import generate_store_world, validate_store_world, generate_world_task, PROFILES
from .generator import digest


def test_store_first_and_shared_canonical_products():
    w=generate_store_world(42)
    assert w==generate_store_world(42)
    assert w['private_provenance']['generation_order'][0]=='stores'
    p=w['public'];stores={s['retailer_id']:s for s in p['retailers']};products={x['product_id']:x for x in p['products']}
    for o in p['offers']:
        assert products[o['product_id']]['category'] in PROFILES[stores[o['retailer_id']]['profile_id']]['families']
    anchor=w['private_provenance']['overlap_anchors']['footwear']
    offers=[o for o in p['offers'] if o['product_id']==anchor['product_id']]
    assert len({o['retailer_id'] for o in offers})>=2
    assert len({o['offer_id'] for o in offers})==len(offers)
    assert len({i['url'] for i in p['web_index']})==6
    assert {i['site_id'] for i in p['web_index']}==set(stores)
    for entry in p['web_index']:
        assert set(entry)=={'site_id','kind','url','title','description','product_families'}
    for forbidden in ('family_scope','overlap_anchors','relevance_contract'):
        assert forbidden not in json.dumps(p)


def test_generalists_rare_capped_and_specialists_do_not_mix_unrelated_goods():
    for probability in (0,1):
        w=generate_store_world(9,store_config={'generalist_probability':probability})
        assert sum(s['profile_id']=='marketplace' for s in w['public']['retailers'])==probability
        for s in w['public']['retailers']:
            if s['profile_id']!='marketplace': assert not {'footwear','laptops'}<=set(s['families'])


def test_stock_changes_do_not_change_stores_catalog_or_task():
    a=generate_store_world(7,store_config={'stockout_probability':0})
    b=generate_store_world(7,store_config={'stockout_probability':1})
    assert a['catalog']==b['catalog']
    for key in ('retailers','assortments','web_index'):assert a['public'][key]==b['public'][key]
    assert all(o['stock_quantity']>0 for o in a['public']['offers'])
    assert all(o['stock_quantity']==0 for o in b['public']['offers'])
    for x,y in zip(a['public']['offers'],b['public']['offers']):
        assert {k:v for k,v in x.items() if k!='stock_quantity'}=={k:v for k,v in y.items() if k!='stock_quantity'}
    ta,tb=[generate_world_task(w,seed=4,target='model',budget_sek=1) for w in (a,b)]
    assert ta['semantic_sha256']==tb['semantic_sha256']
    assert ta['resolved_task']['constraints']['budget_minor']==100


def test_overlap_and_variant_probability_boundaries():
    for probability in (0,1):
        w=generate_store_world(10,store_count=2,models_per_store=4,
            store_config={'model_overlap_probability':probability,'variant_carry_probability':probability})
        groups={g['group_id']:g for g in w['public']['product_groups']}
        for a in w['public']['assortments']:
            assert len(a['product_ids'])==(len(groups[a['model_id']]['variants']) if probability else 1)
        first,second=[{a['model_id'] for a in w['public']['assortments'] if a['retailer_id']==s['retailer_id']} for s in w['public']['retailers']]
        assert len(first&second)==(4 if probability else 1)


def test_multiple_scoped_families_and_one_store_mode():
    w=generate_store_world(4,focus_families=['footwear','laptops','dog_food'])
    task=generate_world_task(w,seed=3,family='footwear',query='split_basket')
    assert {l['family_id'] for l in task['request']['lines']}=={'footwear','laptops','dog_food'}
    for f,anchor in w['private_provenance']['overlap_anchors'].items():assert len(anchor['retailer_ids'])==2
    single=generate_store_world(5,1,focus_families=['beer'],store_config={'relevant_stores_per_family':1})
    assert len(single['public']['retailers'])==1 and single['public']['retailers'][0]['profile_id']=='drinks'
    with pytest.raises(ValueError):generate_world_task(single,query='basket')
    with pytest.raises(ValueError):generate_world_task(single,family='laptops')


@pytest.mark.parametrize('kwargs',[
    {'store_count':1}, {'store_count':True}, {'models_per_store':0}, {'focus_families':['unknown']},
    {'focus_families':['footwear'],'config':{'family_weights':{'footwear':0}}},
    {'focus_families':['dog_food','cat_food'],'models_per_store':1},
    {'store_config':{'generalist_probability':1.1}},
    {'store_config':{'profile_weights':{'footwear':0}}},
])
def test_invalid_world_configuration(kwargs):
    with pytest.raises(ValueError):generate_store_world(**kwargs)


def test_corrupt_world_rejected():
    w=generate_store_world(3)
    for kind in ('missing-offer','wrong-family','missing-index','negative-stock','lost-anchor'):
        bad=copy.deepcopy(w)
        if kind=='missing-offer':bad['public']['offers'].pop()
        if kind=='wrong-family':bad['public']['retailers'][0]['families']=['laptops','footwear']
        if kind=='missing-index':bad['public']['web_index'].pop()
        if kind=='negative-stock':bad['public']['offers'][0]['stock_quantity']=-1
        if kind=='lost-anchor':bad['private_provenance']['overlap_anchors']={}
        bad['world_sha256']=digest(bad['public'])
        with pytest.raises(ValueError):validate_store_world(bad)


def test_bounded_store_world_audit():
    def check(seed):
        w=generate_store_world(seed,focus_families=[('footwear','laptops','dog_food','cat_food','beer','wine')[seed%6]])
        validate_store_world(w)
        assert sum(s['profile_id']!='marketplace' for s in w['public']['retailers'])>=5
        return True
    with ThreadPoolExecutor(max_workers=4) as pool:assert all(pool.map(check,range(48)))
