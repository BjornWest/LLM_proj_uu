from copy import deepcopy
from types import SimpleNamespace
import json

import pytest

from environments.website_world import catalog_comparison_task as api
from environments.website_world.catalog_comparison_grading import CatalogComparisonGrader
from environments.website_world.test_catalog_shortlist_task import fixture as models


def fixture(fields=None, model_limit=2):
    world, _, _, bindings, inventory = models()
    for product, value in zip(world['products'], [300, 250, 260, 280], strict=True):
        product['public']['facts']['reference_mass_g'] = value
    spec = {'kind': api.KIND, 'concept_id': inventory.concept_id,
        'fields': fields or ['product.facts.cushioning', 'product.facts.reference_mass_g'],
        'model_limit': model_limit}
    task = api.make(world, spec, inventory=inventory)
    return world, task, api.reference(world, task, inventory=inventory), bindings, inventory


def answer(world, task, reference, bindings):
    paragraphs, rows = [], []
    null = {'value': None, 'evidence': None}
    for model in reference['models']:
        url = next(b['url'] for b in bindings['retailer_offers'].values()
                   if b['product_id'] == model['product_id']).split('?')[0]
        paragraph = model['name']+' '+url
        row = {'product_name': {'value': model['name'], 'evidence': paragraph},
            'product_url': {'value': url, 'evidence': paragraph}, 'facts': {}}
        for field, fact in model['facts'].items():
            if fact['status'] == 'known':
                value = str(fact['value']).lower() if type(fact['value']) is bool else str(fact['value'])
                quote = field+': '+value+((' '+fact['unit']) if fact['unit'] else '')
                quote += ((' ('+fact['basis']+')') if fact['basis'] else '')
                cell = {'status': {'value': 'known', 'evidence': quote},
                    'value': {'value': value, 'evidence': quote},
                    'unit': {'value': fact['unit'], 'evidence': quote} if fact['unit'] else deepcopy(null),
                    'basis': {'value': fact['basis'], 'evidence': quote} if fact['basis'] else deepcopy(null)}
            else:
                quote = field+': '+('unknown' if fact['status'] == 'unknown' else 'not applicable')
                cell = {'status': {'value': fact['status'], 'evidence': quote},
                    **{k: deepcopy(null) for k in ('value', 'unit', 'basis')}}
            row['facts'][field] = cell
            paragraph += '\n'+quote
        paragraphs.append(paragraph)
        rows.append(row)
    text = '\n\n'.join(paragraphs) if paragraphs else 'This catalog carries no models for comparison.'
    return text, {'interpretation': 'extracted', 'issues': [],
        'status': {'value': reference['status'], 'evidence': text}, 'rows': rows, 'source_urls': []}


def test_model_facts_do_not_require_variant_or_stock_or_minimum_price():
    w,t,r,b,i = fixture()
    for retailer in w['retailers']:
        for offer in retailer['offers']:
            offer['stock_by_source'] = {key: 0 for key in offer['stock_by_source']}
            offer['supplier_order']['enabled'] = False
            offer['price_minor'] += 1000000
    spec = {k:t[k] for k in ('kind', 'concept_id', 'fields', 'model_limit')}
    t2 = api.make(w,spec,inventory=i)
    r2 = api.reference(w,t2,inventory=i)
    assert t2['models'] == t['models'] and t2['user_message'] == t['user_message']
    assert r2['models'] == r['models']
    text,c = answer(w,t2,r2,b)
    assert CatalogComparisonGrader(w,t2,r2,b,inventory=i).grade(c,text)['structured_claims_correct']


def test_correct_complete_models_and_reference_measurement_basis():
    w,t,r,b,i = fixture()
    text,c = answer(w,t,r,b)
    g = CatalogComparisonGrader(w,t,r,b,inventory=i)
    assert g.grade(c,text)['structured_claims_correct']
    assert len(r['models']) == 2
    assert 'one item, EU 40 reference configuration' in t['user_message']
    assert all(len(a['offer_ids']) > 1 for a in g.grade(c,text)['selected_candidate_assessment']['rows'])


@pytest.mark.parametrize('change', ['missing_model', 'duplicate_model', 'wrong_value',
    'missing_unit', 'missing_basis', 'wrong_name', 'foreign_link', 'homepage_link'])
def test_wrong_or_missing_facts_and_independent_identity_fail(change):
    w,t,r,b,i = fixture()
    text,c = answer(w,t,r,b)
    row = c['rows'][0]
    mass = row['facts']['product.facts.reference_mass_g']
    if change == 'missing_model': c['rows'].pop()
    elif change == 'duplicate_model': c['rows'][1] = deepcopy(row)
    elif change == 'wrong_value':
        text += '\n999'
        mass['value'] = {'value': '999', 'evidence': '999'}
    elif change in ('missing_unit', 'missing_basis'):
        mass[change.removeprefix('missing_')] = {'value': None, 'evidence': None}
    elif change == 'wrong_name':
        text += '\nForeign model'
        row['product_name'] = {'value': 'Foreign model', 'evidence': 'Foreign model'}
    else:
        url = 'https://foreign.test/product' if change == 'foreign_link' else 'https://a.test/'
        text += '\n'+url
        row['product_url'] = {'value': url, 'evidence': url}
    assert not CatalogComparisonGrader(w,t,r,b,inventory=i).grade(c,text)['structured_claims_correct']


def test_unknown_na_are_distinct_and_never_false():
    w,t,r,b,i = fixture(['product.facts.cushioning'],4)
    w['products'][0]['catalog_status']['product.facts.cushioning'] = 'unknown'
    w['products'][1]['catalog_status']['product.facts.cushioning'] = 'not_applicable'
    t = api.make(w,{k:t[k] for k in ('kind','concept_id','fields','model_limit')},inventory=i)
    r = api.reference(w,t,inventory=i)
    text,c = answer(w,t,r,b)
    assert CatalogComparisonGrader(w,t,r,b,inventory=i).grade(c,text)['structured_claims_correct']
    index = next(n for n,row in enumerate(r['models']) if row['product_id']=='p')
    cell = c['rows'][index]['facts']['product.facts.cushioning']
    text += '\nnot applicable'
    cell['status'] = {'value':'not_applicable','evidence':'not applicable'}
    assert not CatalogComparisonGrader(w,t,r,b,inventory=i).grade(c,text)['structured_claims_correct']


def test_unknown_annotation_cannot_be_claimed_from_a_positive_value_quote():
    w,t,r,b,i = fixture()
    text,c = answer(w,t,r,b)
    c['rows'][0]['facts']['product.facts.cushioning'] = {
        'status': {'value':'unknown', 'evidence':'moderate'},
        **{k:{'value':None,'evidence':None} for k in ('value','unit','basis')}}
    assert not CatalogComparisonGrader(w,t,r,b,inventory=i).grade(c,text)['structured_claims_correct']


def test_natural_empty_carried_population_and_fewer_than_limit():
    w,t,r,b,i = fixture(model_limit=4)
    for retailer in w['retailers']:
        retailer['offers'] = [o for o in retailer['offers'] if o['product_id']=='p']
    b['retailer_offers'] = {oid:link for oid,link in b['retailer_offers'].items() if link['product_id']=='p'}
    spec = {k:t[k] for k in ('kind','concept_id','fields','model_limit')}
    t=api.make(w,spec,inventory=i);r=api.reference(w,t,inventory=i)
    assert len(r['models']) == 1
    text,c = answer(w,t,r,b)
    assert CatalogComparisonGrader(w,t,r,b,inventory=i).grade(c,text)['structured_claims_correct']
    for retailer in w['retailers']:retailer['offers']=[]
    b['retailer_offers']={}
    t=api.make(w,spec,inventory=i);r=api.reference(w,t,inventory=i)
    text,c = answer(w,t,r,b)
    assert r['status']=='no_models'
    assert CatalogComparisonGrader(w,t,r,b,inventory=i).grade(c,text)['structured_claims_correct']


@pytest.mark.parametrize('patch', [
    {'fields':[]}, {'fields':['sku.size_eu']}, {'fields':['private.price_factor']},
    {'fields':['product.facts.cushioning']*2}, {'model_limit':1},
    {'model_limit':True}, {'price_cap':1000},
])
def test_bad_task_rejects_before_factory(patch):
    from environments.website_world import catalog_comparison_generation as generation
    def forbidden(*args,**kwargs):raise AssertionError('World factory called')
    request={'schema':'website-world-generation-v2','seed':84,
        'world':{'concept_ids':['footwear.walking_shoes']},
        'task':{'kind':api.KIND,'concept_id':'footwear.walking_shoes',
            'fields':['product.facts.cushioning'],**patch}}
    with pytest.raises(ValueError):generation.generate(request,world_factory=forbidden)


def test_task_reference_and_complete_public_join_tampering_reject():
    w,t,r,b,i=fixture()
    changed=deepcopy(t);changed['models'][0]['name']='Foreign model'
    with pytest.raises(ValueError):api.reference(w,changed,inventory=i)
    changed=deepcopy(r);changed['models'][0]['facts']['product.facts.cushioning']['value']='firm'
    with pytest.raises(ValueError):CatalogComparisonGrader(w,t,changed,b,inventory=i)
    changed=deepcopy(b);changed['retailer_offers'].pop(next(iter(changed['retailer_offers'])))
    with pytest.raises(ValueError):CatalogComparisonGrader(w,t,r,changed,inventory=i)


def test_shared_formatter_boundary_has_no_native_expected_values(tmp_path):
    from experiments.answer_grading import task_answer
    w,t,r,b,i=fixture(['product.facts.cushioning'])
    text,c = answer(w,t,r,b)
    calls=[]
    class Backend:
        def complete(self,messages):
            calls.append(messages)
            assert 'native_reference' not in messages[1]['content']
            assert 'offer_ids' not in messages[0]['content']
            return SimpleNamespace(text=json.dumps(c),request={'messages':messages},raw={
                'model':'scripted','provider':'offline','usage':{},
                'choices':[{'finish_reason':'stop','message':{'content':json.dumps(c)}}]})
    g=CatalogComparisonGrader(w,t,r,b,inventory=i)
    grade=task_answer.extract_and_grade(g,{'user_message':t['user_message'],'memories':[]},text,
        tmp_path/'extraction',Backend())
    assert grade['structured_claims_correct'] and len(calls)==1


def test_model_selection_does_not_condition_on_requested_fact_values():
    w,t,r,b,i = fixture()
    for item in w['products']:
        item['public']['facts']['cushioning'] = 'firm'
        item['public']['facts']['reference_mass_g'] = 350
    revised = api.make(w,{k:t[k] for k in ('kind','concept_id','fields','model_limit')},inventory=i)
    assert revised['models'] == t['models']


@pytest.mark.parametrize('supplied,expected,typ,correct', [
    ('false',False,'boolean',True),('no',False,'boolean',True),
    ('yes',False,'boolean',False),('-1.25',-1.25,'number',True),
    ('1,25',1.25,'number',True),('NaN',1.25,'number',False),
])
def test_literal_boolean_and_signed_finite_numeric_claims(supplied,expected,typ,correct):
    from environments.website_world.catalog_comparison_grading import _value_matches
    assert _value_matches(supplied,expected,{'type':typ}) is correct
