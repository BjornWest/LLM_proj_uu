from copy import deepcopy

import pytest

from environments.website_world import catalog_priority_task as api
from environments.website_world.catalog_priority_grading import CatalogPriorityGrader
from environments.website_world.test_catalog_shortlist_task import fixture as models, row


def fixture(priorities=None, **options):
    w,_,_,b,i = models()
    for item,mass in zip(w['products'],[300,250,250,280],strict=True):
        item['public']['facts']['reference_mass_g'] = mass
    spec = {'kind':api.KIND,'concept_id':i.concept_id,
        'predicates':[{'field':'sku.size_eu','operator':'eq','value':42}],
        'priorities':priorities or [{'field':'product.facts.reference_mass_g','direction':'min','unit':'g'}],
        **options}
    t=api.make(w,spec,inventory=i)
    return w,t,api.reference(w,t,inventory=i),b,i


def test_feature_priority_precedes_cheaper_price_and_preserves_ties():
    w,t,r,b,i = fixture()
    assert r['best_priority_values'] == [250] and r['tie_price_minor'] == 80000
    assert {o['product_id'] for o in r['winners']} == {'q','r'}
    assert len(r['winners']) == 12
    assert 'Find the cheapest available' not in t['user_message']
    g=CatalogPriorityGrader(w,t,r,b,inventory=i)
    for pid,correct in [('q',True),('r',True),('p',False),('s',False)]:
        text,c = row(pid)
        c = {**c,'interpretation':'extracted','issues':[],
            'status':{'value':'selection','evidence':text},'source_urls':[]}
        assert g.grade(c,text)['structured_claims_correct'] is correct


def test_max_direction_and_price_only_after_all_feature_ties():
    w,t,r,b,i=fixture([{'field':'product.facts.reference_mass_g','direction':'max','unit':'g'}])
    assert {o['product_id'] for o in r['winners']} == {'p'}
    assert r['best_priority_values'] == [300]
    spec={k:t[k] for k in ('kind','concept_id','predicates','priorities')}
    for ret in w['retailers']:
        for o in ret['offers']:
            if o['product_id']=='p':o['price_minor']=99000
    t=api.make(w,spec,inventory=i);r=api.reference(w,t,inventory=i)
    assert {o['product_id'] for o in r['winners']} == {'p'}
    assert r['tie_price_minor']==99000


def test_two_priorities_are_ordered_not_a_weighted_compromise():
    w,t,_,b,i=fixture()
    spec={k:t[k] for k in ('kind','concept_id','predicates','priorities')}
    spec['predicates']=[{'field':'sku.size_eu','operator':'ge','value':42}]
    spec['priorities'].append({'field':'sku.size_eu','direction':'max'})
    t=api.make(w,spec,inventory=i);r=api.reference(w,t,inventory=i)
    assert r['best_priority_values']==[250,43]
    assert {o['product_id'] for o in r['winners']}=={'q','r'}
    assert all(o['sku_id'].endswith('-43') for o in r['winners'])
    g=CatalogPriorityGrader(w,t,r,b,inventory=i)
    text,c=row('q')  # right model/price, but lower-priority size42 loses
    c={**c,'interpretation':'extracted','issues':[],
       'status':{'value':'selection','evidence':text},'source_urls':[]}
    assert not g.grade(c,text)['structured_claims_correct']


@pytest.mark.parametrize('status',['unknown','not_applicable'])
def test_unknown_na_rank_value_excluded_without_inference(status):
    w,t,_,b,i=fixture()
    spec={k:t[k] for k in ('kind','concept_id','predicates','priorities')}
    for item in w['products']:
        item['catalog_status']['product.facts.reference_mass_g']=status
    t=api.make(w,spec,inventory=i);r=api.reference(w,t,inventory=i)
    assert r['status']=='no_match' and not r['winners']
    g=CatalogPriorityGrader(w,t,r,b,inventory=i)
    text='No qualifying option has established ranking features.'
    claims={'interpretation':'extracted','issues':[],
        'status':{'value':'no_match','evidence':text},'product_name':{'value':None,'evidence':None},
        'retailer_name':{'value':None,'evidence':None},'offer_url':{'value':None,'evidence':None},
        'sku_id':{'value':None,'evidence':None},'variant':{},'total':None,'source_urls':[]}
    assert g.grade(claims,text)['structured_claims_correct']


def test_stock_and_cap_are_hard_before_priority_ranking():
    w,t,r,b,i=fixture(max_price_minor=75000)
    assert {o['product_id'] for o in r['winners']}=={'p'}
    spec={k:t[k] for k in ('kind','concept_id','predicates','priorities')}
    for ret in w['retailers']:
        for o in ret['offers']:
            if o['product_id'] in ('q','r'):o['stock_by_source']={k:0 for k in o['stock_by_source']}
    t=api.make(w,spec,inventory=i);r=api.reference(w,t,inventory=i)
    assert {o['product_id'] for o in r['winners']}=={'s'}


@pytest.mark.parametrize('priorities',[
    [],[{'field':'sku.colour','direction':'min'}],
    [{'field':'product.facts.reference_mass_g','direction':'min','unit':'kg'}],
    [{'field':'private.price_factor','direction':'min'}],
    [{'field':'sku.size_eu','direction':'min'}]*2,
    [{'field':'sku.size_eu','direction':'lowest'}],
    [{'field':'sku.size_eu','direction':'min','utility':1}],
])
def test_invalid_priority_rejects_before_sampling(priorities,monkeypatch):
    from environments.website_world import catalog_priority_generation as generation
    def forbidden(*args,**kwargs):raise AssertionError('Factory called on bad task')
    r={'schema':'website-world-generation-v2','seed':83,
        'world':{'concept_ids':['footwear.walking_shoes']},
        'task':{'kind':api.KIND,'concept_id':'footwear.walking_shoes',
            'predicates':[{'field':'sku.size_eu','operator':'eq','value':42}],
            'priorities':priorities}}
    with pytest.raises(ValueError):generation.generate(r,world_factory=forbidden)


def test_task_and_reference_tampering_reject():
    w,t,r,b,i=fixture()
    broken=deepcopy(t);broken['priorities'][0]['direction']='max'
    with pytest.raises(ValueError):api.reference(w,broken,inventory=i)
    broken=deepcopy(r);broken['best_priority_values']=[999]
    with pytest.raises(ValueError):CatalogPriorityGrader(w,t,broken,b,inventory=i)


def test_reference_mass_basis_is_the_declared_reference_not_requested_size():
    w,t,r,b,i = fixture()
    declaration = api._measurement_scope('product.facts.reference_mass_g', i)['declaration']
    basis = declaration['constant']
    assert basis == 'one item, EU 40 reference configuration'
    scope = t['priority_measurement_scopes']['product.facts.reference_mass_g']
    assert scope == {'basis': basis, 'origin': 'registered_constant_field',
        'field': 'product.facts.mass_basis',
        'declaration': declaration}
    assert 'Minimize reference mass g in g ('+basis+').' in t['user_message']
    assert t['predicates'][0]['value'] == 42
    broken=deepcopy(t)
    broken['priority_measurement_scopes']['product.facts.reference_mass_g']['basis']='size 42 weight'
    with pytest.raises(ValueError):api.reference(w,broken,inventory=i)


def test_missing_constant_basis_is_rejected_without_world_inference():
    w,t,r,b,i = fixture()
    declarations = getattr(i, '_measurement_basis_declarations', i.fields)
    del declarations['product.facts.mass_basis']['constant']
    spec={k:t[k] for k in ('kind','concept_id','predicates','priorities')}
    with pytest.raises(ValueError,match='declared constant measurement basis'):
        api.make(w,spec,inventory=i)


def test_inline_reviewed_basis_and_unqualified_dimension_remain_distinct():
    w,t,r,b,i = fixture()
    i.fields['product.facts.reference_mass_g']['basis']='one item, declared reference configuration'
    spec={k:t[k] for k in ('kind','concept_id','predicates','priorities')}
    spec['priorities'].append({'field':'sku.size_eu','direction':'max'})
    t=api.make(w,spec,inventory=i)
    assert t['priority_measurement_scopes'] == {'product.facts.reference_mass_g': {
        'basis':'one item, declared reference configuration',
        'origin':'numeric_field_declaration'}}
    assert '(one item, declared reference configuration)' in t['user_message']
    assert 'Maximize size eu.' in t['user_message']
