from copy import deepcopy

import pytest

from environments.website_world import catalog_relaxation_task as api, catalog_relaxation_generation as generation
from environments.website_world.catalog_relaxation_grading import CatalogRelaxationGrader
from environments.website_world.test_feature_offer_task import fixture as original_fixture
from environments.website_world.test_listed_offer_grading import answer


MASS = 'product.facts.reference_mass_g'
SIZE = {'field': 'sku.size_eu', 'operator': 'eq', 'value': 42}
def mass(value): return {'field': MASS, 'operator': 'le', 'value': value, 'unit': 'g'}


def fixture(strict=200, alternatives=None, **options):
    w, _, _, b, i = original_fixture()
    spec = {'kind': api.KIND, 'concept_id': i.concept_id, 'availability': 'positive_stock',
        'predicates': [SIZE, mass(strict)], 'relaxations': alternatives if alternatives is not None else [
            {'label': 'Allow up to 350 g', 'replacements': [mass(350)]}], **options}
    t = api.make(w, spec, inventory=i)
    r = api.reference(w, t, inventory=i)
    return w, t, r, b, i


def claims(label='Allow up to 350 g', **options):
    text, c = answer(**options)
    text += ' Criteria used: '+label+'.'
    c['criteria_used'] = {'value': label, 'evidence': 'Criteria used: '+label}
    return text, c


def test_first_available_set_and_all_minimum_ties():
    w, t, r, b, i = fixture()
    assert r['selected_index'] == 1 and r['selected_label'] == 'Allow up to 350 g'
    assert r['minimum_price_minor'] == 74000
    assert len(r['scenario_references'][1]['winners']) == 4
    g = CatalogRelaxationGrader(w, t, r, b, inventory=i)
    for store, url in [('Veska','https://a.test/#/product/olive'), ('Tied Shop','https://d.test/#/product/olive')]:
        text, c = claims(name=store, url=url)
        assert g.grade(c, text)['structured_claims_correct']
    assert 'do not combine different alternatives' in t['user_message']
    assert 'If no available option has specifications establishing all requirements, say so' not in t['user_message']


def test_original_set_beats_cheaper_later_set():
    w, _, _, b, i = original_fixture()
    for retailer in w['retailers']:
        for o in retailer['offers']:
            if o['sku_id'].endswith('-43'): o['price_minor'] = 40000
    spec = {'kind': api.KIND, 'concept_id': i.concept_id, 'predicates': [SIZE], 'relaxations': [
        {'label': 'Allow EU43 too', 'replacements': [{'field': 'sku.size_eu','operator':'in','value':[42,43]}]}]}
    t = api.make(w, spec, inventory=i); r = api.reference(w, t, inventory=i)
    assert r['selected_index'] == 0 and r['minimum_price_minor'] == 74000
    assert r['scenario_references'][1]['minimum_price_minor'] == 40000
    g = CatalogRelaxationGrader(w, t, r, b, inventory=i)
    text, c = claims(label=api.ORIGINAL)
    assert g.grade(c, text)['structured_claims_correct']
    text, c = claims(label='Allow EU43 too', size='43', price='400')
    assert not g.grade(c, text)['structured_claims_correct']


def test_ordered_relaxations_are_not_reordered_by_price():
    w, t, r, b, i = fixture(alternatives=[
        {'label':'Allow 250 g','replacements':[mass(250)]},
        {'label':'Allow 350 g','replacements':[mass(350)]}])
    assert r['selected_index'] == 2
    text, c = claims(label='Allow 350 g')
    assert CatalogRelaxationGrader(w,t,r,b,inventory=i).grade(c,text)['structured_claims_correct']


def test_alternatives_start_from_original_not_accumulated():
    w, _, _, b, i = original_fixture()
    spec = {'kind':api.KIND,'concept_id':i.concept_id,
        'predicates':[SIZE,mass(200),{'field':'product.facts.cushioning','operator':'eq','value':'firm'}],
        'relaxations':[{'label':'Ignore mass','drop_fields':[MASS]},
                       {'label':'Ignore cushioning','drop_fields':['product.facts.cushioning']}]}
    t=api.make(w,spec,inventory=i);r=api.reference(w,t,inventory=i)
    assert r['status']=='no_match' and r['selected_index'] is None
    assert all(not ref['candidates'] for ref in r['scenario_references'])
    g=CatalogRelaxationGrader(w,t,r,b,inventory=i)
    text,c=claims(label='Ignore cushioning')
    assert not g.grade(c,text)['structured_claims_correct']


@pytest.mark.parametrize('status',['unknown','not_applicable'])
def test_unknown_and_na_cannot_satisfy_retained_feature(status):
    w, t, _, b, i = fixture()
    w['products'][0]['catalog_status'][MASS]=status
    spec={k:t[k] for k in ('kind','concept_id','predicates','availability','relaxations')}
    t=api.make(w,spec,inventory=i);r=api.reference(w,t,inventory=i)
    assert r['status']=='no_match'
    spec['relaxations']=[{'label':'No mass restriction','drop_fields':[MASS]}]
    t=api.make(w,spec,inventory=i);r=api.reference(w,t,inventory=i)
    assert r['selected_index']==1  # Dropped unknown field is not asserted false.


@pytest.mark.parametrize('change',['missing_label','wrong_label','unstated_variant','wrong_price','foreign_url'])
def test_answer_is_not_repaired_from_task_or_reference(change):
    w,t,r,b,i=fixture();g=CatalogRelaxationGrader(w,t,r,b,inventory=i)
    text,c=claims()
    if change=='missing_label':c['criteria_used']={'value':None,'evidence':None}
    elif change=='wrong_label':text,c=claims(label=api.ORIGINAL)
    elif change=='unstated_variant':c['variant']['size_eu']={'value':None,'evidence':None}
    elif change=='wrong_price':text,c=claims(price='730')
    else:text,c=claims(url='https://foreign.test/#/product/olive')
    assert not g.grade(c,text)['structured_claims_correct']


def test_label_needs_literal_answer_evidence():
    w,t,r,b,i=fixture();g=CatalogRelaxationGrader(w,t,r,b,inventory=i)
    text,c=claims();c['criteria_used']['evidence']='Not in the answer'
    with pytest.raises(ValueError):g.grade(c,text)


def test_natural_empty_and_uncertain():
    w,t,r,b,i=fixture(max_price_minor=1);assert r['status']=='no_match'
    g=CatalogRelaxationGrader(w,t,r,b,inventory=i)
    text='None match any permitted set.'
    c={k:{'value':None,'evidence':None} for k in ('product_name','retailer_name','offer_url','sku_id','criteria_used')}
    c.update(interpretation='extracted',issues=[],status={'value':'no_match','evidence':text},
        variant={k:{'value':None,'evidence':None} for k in ('colour','size_eu','width')},total=None,source_urls=[])
    assert g.grade(c,text)['structured_claims_correct']
    c['status']['value']='uncertain';assert not g.grade(c,text)['structured_claims_correct']
    text+=' Criteria used: Original requirements.'
    c['status']['value']='no_match';c['criteria_used']={'value':api.ORIGINAL,'evidence':api.ORIGINAL}
    assert not g.grade(c,text)['structured_claims_correct']


@pytest.mark.parametrize('bad',[
    {'label':'Strengthening','replacements':[mass(100)]},
    {'label':'No change','replacements':[mass(200)]},
    {'label':'Wrong units','replacements':[{**mass(350),'unit':'kg'}]},
    {'label':'Foreign field','drop_fields':['product.facts.unregistered']},
    {'label':'All fields','drop_fields':['sku.size_eu',MASS]},
    {'label':'Double','drop_fields':[MASS],'replacements':[mass(350)]},
    {'label':'Duplicate','replacements':[mass(350),mass(400)]},
    {'label':'Unauthorized stock','availability':'purchasable'},
    {'label':api.ORIGINAL,'drop_fields':[MASS]},
    {'label':'Empty'},
    {'label':'Pretend superset','replacements':[{'field':'sku.size_eu','operator':'in','value':[42,42]}]},
])
def test_invalid_changes_reject_before_sampling(bad,monkeypatch):
    request={'schema':'website-world-generation-v2','seed':81,
        'world':{'concept_ids':['footwear.walking_shoes']},
        'task':{'kind':api.KIND,'concept_id':'footwear.walking_shoes','predicates':[SIZE,mass(200)],'relaxations':[bad]}}
    def forbidden(*a,**kw):raise AssertionError('No world sampling')
    monkeypatch.setattr(generation.feature_generation,'generate',forbidden)
    with pytest.raises(ValueError):generation.generate(request)


def test_stock_and_price_limits_remain_hard():
    w,t,_,b,i=fixture()
    for retailer in w['retailers']:
        for offer in retailer['offers']:
            offer['stock_by_source']={retailer['retailer_id']:0};offer['supplier_order']['enabled']=True
    spec={k:t[k] for k in ('kind','concept_id','predicates','availability','relaxations')}
    t=api.make(w,spec,inventory=i);r=api.reference(w,t,inventory=i)
    assert r['status']=='no_match'
    spec['availability']='purchasable';t=api.make(w,spec,inventory=i);r=api.reference(w,t,inventory=i)
    assert r['selected_index']==1


@pytest.mark.parametrize('operator,original,weaker', [('ge',350,250),('gt',350,250),('lt',250,350),('le',250,350)])
def test_numeric_bound_directions(operator,original,weaker):
    w,_,_,b,i=original_fixture()
    original_predicate={'field':MASS,'operator':operator,'value':original,'unit':'g'}
    spec={'kind':api.KIND,'concept_id':i.concept_id,'predicates':[SIZE,original_predicate],
        'relaxations':[{'label':'Loosen mass','replacements':[{**original_predicate,'value':weaker}]}]}
    t=api.make(w,spec,inventory=i);r=api.reference(w,t,inventory=i)
    assert r['selected_index']==1 and r['minimum_price_minor']==74000


@pytest.mark.parametrize('operator,original,weaker,selected',[
    ('in',['olive'],['olive','brown'],0),
    ('not_in',['olive','brown'],['brown'],1)])
def test_finite_allowed_and_excluded_sets(operator,original,weaker,selected):
    w,_,_,b,i=original_fixture()
    predicate={'field':'sku.colour','operator':operator,'value':original}
    spec={'kind':api.KIND,'concept_id':i.concept_id,'predicates':[SIZE,predicate],
        'relaxations':[{'label':'More permitted colours','replacements':[{**predicate,'value':weaker}]}]}
    t=api.make(w,spec,inventory=i);r=api.reference(w,t,inventory=i)
    assert r['selected_index']==selected
    assert len(r['scenario_references'][1]['winners'])==(4 if operator=='in' else 2)


@pytest.mark.parametrize('change',['task','reference','inventory'])
def test_changed_bindings_reject(change):
    w,t,r,b,i=fixture()
    if change=='task':t['relaxations'][0]['label']='Different label'
    elif change=='reference':r['selected_index']=0
    else:i.fields['sku.size_eu']['type']='boolean'
    with pytest.raises(ValueError):CatalogRelaxationGrader(w,t,r,b,inventory=i)


def test_generation_preserves_world_and_public_binding(monkeypatch):
    w,_,_,_,_=fixture();before=deepcopy(w);calls=[]
    def saved(*a,**kw):
        calls.append(True)
        return {'world':w,'surrounding':None,'episode':{},'resolved_configuration':{},'audit':{'request_sha256':'original'}}
    monkeypatch.setattr(generation.feature_generation,'generate',saved)
    request={'schema':'website-world-generation-v2','seed':81,'world':{'concept_ids':['footwear.walking_shoes']},
        'task':{'kind':api.KIND,'concept_id':'footwear.walking_shoes','predicates':[SIZE,mass(200)],
                'relaxations':[{'label':'Allow 350 g','replacements':[mass(350)]}]}}
    result=generation.generate(request)
    assert w==before and len(calls)==1
    assert result['catalog_relaxation_reference']['selected_index']==1
    assert result['episode']['task_id']==result['catalog_relaxation_task']['task_id']
    assert result['resolved_configuration']['request']==request


def test_task_neutral_extraction_and_list_derivations(tmp_path):
    import json
    from types import SimpleNamespace
    from experiments.answer_grading import task_answer
    w,t,r,b,i=fixture();g=CatalogRelaxationGrader(w,t,r,b,inventory=i);text,c=claims();events=[]
    class Backend:
        def complete(self,messages):
            payload=json.loads(messages[1]['content'])
            assert set(payload)=={'public_task','final_answer'} and payload['final_answer']==text
            assert 'scenario_references' not in messages[1]['content'] and 'selected_index' not in messages[0]['content']
            events.append(True);content=json.dumps(c)
            return SimpleNamespace(text=content,request={'messages':messages},raw={'model':'scripted','usage':{},
                'choices':[{'finish_reason':'stop','message':{'content':content}}]})
    result=task_answer.extract_and_grade(g,{'user_message':t['user_message'],'memories':[]},text,tmp_path/'extract',Backend())
    assert result['structured_claims_correct'] and isinstance(result['derivations'],list) and len(events)==1
