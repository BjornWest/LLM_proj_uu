from copy import deepcopy
from fractions import Fraction
import json
from types import SimpleNamespace

import pytest

from environments.website_world import catalog_unit_price_task as api
from environments.website_world.catalog_unit_price_grading import CatalogUnitPriceGrader
from environments.website_world import catalog_unit_price_generation as generation
from environments.website_world.feature_offer_task import FieldInventory
from environments.website_world.test_listed_offer_grading import fixture as base_fixture


def fixture(**options):
    world, _, _, old = base_fixture()
    item = world['products'][0]
    item['public'].update(name='Fixture Cat Kibble', concept_id='cat_food.dry_food',
        skus=[{'sku_id': 'pack-'+str(m), 'product_id': 'p', 'net_mass_g': m} for m in (1000,2000)])
    item['variant_fields'] = {'net_mass_g': {}}
    item['catalog_status'] = {}
    item['sku_status'] = {s['sku_id']: {'sku.net_mass_g': 'known'} for s in item['public']['skus']}
    world['config']['concept_ids'] = ['cat_food.dry_food']
    links = {}
    for retailer in world['retailers']:
        rid = retailer['retailer_id']
        retailer['offers'] = []
        for mass, price in ((1000,40000),(2000,60000)):
            oid = rid+'/pack-'+str(mass)
            offer = {'offer_id': oid, 'sku_id': 'pack-'+str(mass), 'product_id': 'p',
                'price_minor': price + (10000 if rid == 'b' else -10000 if rid == 'c' else 0),
                'currency': 'SEK', 'stock_by_source': {rid: 0 if rid == 'c' else 7},
                'supplier_order': {'enabled': False}}
            retailer['offers'].append(offer)
            links[oid] = {'offer_id': oid, 'sku_id': offer['sku_id'], 'product_id':'p', 'retailer_id':rid,
                'url': f'https://{rid}.test/#/product/food?net_mass_g={mass}',
                'selection': {'net_mass_g':str(mass)}, 'required_selection':{}}
    inventory = FieldInventory('cat_food.dry_food')
    return bind(world, {'retailer_offers':links}, inventory, **options)


def bind(world, bindings, inventory, **options):
    spec = {'kind':api.KIND, 'concept_id':inventory.concept_id, 'unit_basis':api.BASIS, **options}
    task = api.make(world, spec, inventory=inventory)
    ref = api.reference(world, task, inventory=inventory)
    return world, task, ref, bindings, inventory


def answer(mass=2000, price='600', unit='300', rid='a', name='Veska', url=None):
    url = url or f'https://{rid}.test/#/product/food'
    text = f'Choose Fixture Cat Kibble at {name}, net food {mass} g, pack price {price} SEK; {unit} SEK per kg. {url}'
    c = lambda v: {'value':v, 'evidence':text if v is not None else None}
    return text, {'interpretation':'extracted', 'issues':[], 'status':c('selection'),
        'product_name':c('Fixture Cat Kibble'), 'retailer_name':c(name), 'offer_url':c(url), 'sku_id':c(None),
        'variant':{'net_mass_g':c(str(mass))}, 'total':{'amount':price,'currency':'SEK','evidence':text},
        'source_urls':[], 'quantity_g':c(mass), 'quantity_unit':c('g'),
        'unit_price':{'amount':unit,'currency':'SEK','evidence':text}, 'unit_price_unit':c('kg')}


def test_whole_pack_price_and_exact_unit_price_are_different_objectives():
    w,t,r,b,i = fixture()
    assert r['feature_reference']['minimum_price_minor'] == 40000
    assert r['minimum_unit_price_exact'] == {'numerator':30000, 'denominator':1}
    assert {o['offer_id'] for o in r['winners']} == {'a/pack-2000','d/pack-2000'}
    g = CatalogUnitPriceGrader(w,t,r,b,inventory=i)
    for rid,name in [('a','Veska'),('d','Tied Shop')]:
        text,c = answer(rid=rid,name=name)
        assert g.grade(c,text)['structured_claims_correct']
    text,c = answer(mass=1000,price='400',unit='400')
    grade = g.grade(c,text)
    assert grade['oracle_grade']['requirements']['reported_price']
    assert not grade['oracle_grade']['requirements']['lowest_exact_unit_price']
    assert 'cheapest_listed_offer' not in grade['oracle_grade']['requirements']


def test_exact_ranking_does_not_create_a_tie_from_rounded_display():
    w,_,_,b,i = fixture()
    # Both show100.00SEK/kg; the second is genuinely slightly cheaper.
    for item in w['products']:
        item['public']['skus'][1]['net_mass_g'] = 100001
    for retailer in w['retailers']:
        for index,o in enumerate(retailer['offers']):
            o['price_minor'] = 10000 if index == 0 else 1000009
    w,t,r,b,i = bind(w,b,i)
    assert {o['unit_price_minor'] for o in r['candidates']} == {10000}
    assert {o['sku_id'] for o in r['winners']} == {'pack-2000'}
    assert len(r['winners']) == 3


@pytest.mark.parametrize('cost,rounded',[(Fraction(10001,2),5001),(Fraction(10000,3),3333),(Fraction(0),0)])
def test_half_up_display_uses_integer_ratio(cost,rounded):
    assert api.rounded_minor(cost) == rounded


@pytest.mark.parametrize('status',['unknown','not_applicable'])
def test_unknown_na_quantity_excludes_even_a_lower_listed_price(status):
    w,_,_,b,i = fixture()
    w['products'][0]['sku_status']['pack-2000']['sku.net_mass_g'] = status
    _,_,r,_,_ = bind(w,b,i)
    assert {o['sku_id'] for o in r['candidates']} == {'pack-1000'}
    assert r['minimum_unit_price_minor'] == 40000


def test_missing_quantity_status_is_not_inferred_from_a_variant_number():
    w,_,_,b,i = fixture()
    w['products'][0]['sku_status'] = {}
    w,t,r,b,i = bind(w,b,i)
    assert r['status'] == 'no_match'
    g = CatalogUnitPriceGrader(w,t,r,b,inventory=i)
    c = {'interpretation':'extracted','status':{'value':'no_match','evidence':'No known available match.'}}
    assert g.grade(c,'No known available match.')['structured_claims_correct']
    text,c = answer()
    assert not g.grade(c,text)['structured_claims_correct']


def canonical_provenance(world, inventory):
    for item in world['products']:
        item['private'] = {'sample': {'schema_version':'product-package-v1',
            'concept_id':inventory.concept_id,'entities':{'product':{'product_id':item['public']['product_id'],
                'skus':deepcopy(item['public']['skus'])}}},
            'commerce_source_gate':{'capability':'accepted_package_sampler','source_hashes':{
                n:h for n,h in inventory.source_hashes.items()
                if n.startswith('environments/product_world/data/product_width/')}}}
        item['sku_status'] = {}


def test_closed_canonical_quantity_capability_preserves_world_and_inventory():
    w,_,_,b,i = fixture();canonical_provenance(w,i)
    original,paths = deepcopy(w),i.known_paths
    w,t,r,b,i = bind(w,b,i)
    assert t['quantity_provenance']['mode']=='exact_source_bound_canonical_manufacture'
    assert r['minimum_unit_price_minor']==30000
    assert w==original and i.known_paths==paths
    text,c=answer()
    assert CatalogUnitPriceGrader(w,t,r,b,inventory=i).grade(c,text)['structured_claims_correct']


@pytest.mark.parametrize('fault',['menu_mass','schema','concept','product_id','source_hash','missing_source','capability','boolean_mass'])
def test_unproven_quantity_does_not_get_a_status_upgrade(fault):
    w,_,_,b,i=fixture();canonical_provenance(w,i)
    private=w['products'][0]['private'];sample=private['sample'];gate=private['commerce_source_gate']
    if fault=='menu_mass':sample['entities']['product']['skus'][0]['net_mass_g']=1001
    elif fault=='schema':sample['schema_version']='foreign'
    elif fault=='concept':sample['concept_id']='dog_food.dry_food'
    elif fault=='product_id':sample['entities']['product']['product_id']='foreign'
    elif fault=='source_hash':gate['source_hashes'][next(iter(gate['source_hashes']))]='wrong'
    elif fault=='missing_source':gate['source_hashes']={}
    elif fault=='capability':gate['capability']='foreign'
    else:sample['entities']['product']['skus'][0]['net_mass_g']=True
    w,t,r,b,i=bind(w,b,i)
    assert t['quantity_provenance']['mode']=='explicit_status_only'
    assert r['status']=='no_match'


@pytest.mark.parametrize('status',['unknown','not_applicable'])
def test_canonical_proof_cannot_override_explicit_unknown_na(status):
    w,_,_,b,i=fixture();canonical_provenance(w,i)
    w['products'][0]['sku_status']['pack-2000']={api.FIELD:status}
    w,t,r,b,i=bind(w,b,i)
    assert t['quantity_provenance']['mode']=='exact_source_bound_canonical_manufacture'
    assert {o['sku_id'] for o in r['candidates']}=={'pack-1000'}


def test_one_unproven_model_cannot_borrow_another_models_manufacture():
    w,_,_,b,i=fixture();canonical_provenance(w,i)
    p=deepcopy(w['products'][0]);p['public']['product_id']='second'
    for s in p['public']['skus']:s.update(product_id='second',sku_id='second-'+s['sku_id'])
    w['products'].append(p)
    _,t,r,_,_=bind(w,b,i)
    assert t['quantity_provenance']['mode']=='explicit_status_only' and r['status']=='no_match'


def test_stock_supplier_and_whole_pack_cap_remain_hard():
    w,_,_,b,i = fixture(max_price_minor=50000)
    assert bind(w,b,i,max_price_minor=50000)[2]['minimum_unit_price_minor'] == 40000
    for retailer in w['retailers']:
        for o in retailer['offers']:
            if o['sku_id'] == 'pack-2000':
                o['stock_by_source'] = {retailer['retailer_id']:0}
                o['supplier_order']['enabled'] = True
    assert bind(w,b,i)[2]['minimum_unit_price_minor'] == 25000  # sold-out shop supplier is also available
    assert bind(w,b,i,availability='positive_stock')[2]['minimum_unit_price_minor'] == 40000


@pytest.mark.parametrize('change',['missing_quantity','missing_unit_price','wrong_quantity','wrong_unit_price','foreign_url','ambiguous_pack'])
def test_missing_and_wrong_claims_are_not_repaired(change):
    w,t,r,b,i = fixture()
    g = CatalogUnitPriceGrader(w,t,r,b,inventory=i)
    text,c = answer()
    if change == 'missing_quantity': c['quantity_g']={'value':None,'evidence':None}
    elif change == 'missing_unit_price': c['unit_price']=None
    elif change == 'wrong_quantity':
        text += ' Other pack1000 g.'; c['quantity_g']={'value':1000,'evidence':'1000 g'}
    elif change == 'wrong_unit_price':
        text += ' Wrong unit299 SEK.'; c['unit_price']={'amount':'299','currency':'SEK','evidence':'299 SEK'}
    elif change == 'foreign_url':
        text += ' https://foreign.test/'; c['offer_url']={'value':'https://foreign.test/','evidence':'https://foreign.test/'}
    else: c['variant']['net_mass_g']={'value':None,'evidence':None}
    assert not g.grade(c,text)['structured_claims_correct']


@pytest.mark.parametrize('options',[{'unit_basis':'reference_shoe_mass'}, {'predicates':False},
    {'quantity_field':'sku.net_mass_g'}, {'max_price_minor':True},
    {'predicates':[{'field':'sku.net_mass_g','operator':'ge','value':1000,'unit':'kg'}]}])
def test_bad_inputs_reject_before_world_sampling(options):
    request={'schema':'website-world-generation-v2','seed':82,
        'world':{'concept_ids':['cat_food.dry_food']},
        'task':{'kind':api.KIND,'concept_id':'cat_food.dry_food','unit_basis':api.BASIS,**options}}
    def never(*a,**k): raise AssertionError('World generation happened before rejection')
    with pytest.raises(ValueError): generation.generate(request,world_factory=never)


def test_unsupported_concept_cannot_use_arbitrary_weight_denominator():
    i=FieldInventory('footwear.walking_shoes')
    with pytest.raises(ValueError): api.resolve({'kind':api.KIND,'concept_id':i.concept_id,
        'unit_basis':api.BASIS},inventory=i,concept_ids=[i.concept_id])


def test_literal_ratio_rejects_boolean_zero_negative_quantities():
    for price,mass in ((True,1000),(100,True),(100,0),(100,-1),(-1,1000)):
        with pytest.raises(ValueError):api.ratio(price,mass)


@pytest.mark.parametrize('target',['reference','task','inventory'])
def test_task_reference_quantity_binding_tampering_rejects(target):
    w,t,r,b,i=fixture()
    if target=='reference':r['minimum_unit_price_minor']=1
    elif target=='task':t['quantity_basis']='body weight'
    else:i.fields['sku.net_mass_g']['unit']='kg'
    with pytest.raises(ValueError):CatalogUnitPriceGrader(w,t,r,b,inventory=i)


def test_task_neutral_extraction_has_no_private_ratio_and_does_no_arithmetic(tmp_path):
    from experiments.answer_grading import task_answer
    w,t,r,b,i=fixture();g=CatalogUnitPriceGrader(w,t,r,b,inventory=i)
    text,c=answer();calls=[]
    class Backend:
        def complete(self,messages):
            calls.append(messages)
            assert 'minimum_unit_price_exact' not in messages[1]['content']
            assert '30000' not in messages[0]['content']
            out=json.dumps(c)
            return SimpleNamespace(text=out,request={'messages':messages},raw={
                'model':'scripted','provider':'offline','usage':{},
                'choices':[{'finish_reason':'stop','message':{'content':out}}]})
    grade=task_answer.extract_and_grade(g,{'user_message':t['user_message'],'memories':[]},text,tmp_path/'extract',Backend())
    assert grade['structured_claims_correct'] and len(calls)==1
    assert type(grade['derivations']) is list
