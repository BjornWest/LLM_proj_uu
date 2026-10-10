from copy import deepcopy
from hashlib import sha256
import json
import pytest
from environments.website_world import catalog_unit_price_publication as publication
from environments.website_world.test_catalog_unit_price_task import fixture, canonical_provenance


def request():
    return {'schema':'website-world-generation-v2','seed':82,
        'world':{'concept_ids':['cat_food.dry_food']},
        'task':{'kind':'cheapest_matching_unit_price','concept_id':'cat_food.dry_food',
                'unit_basis':'net_food_mass_kg','predicates':[]}}


@pytest.mark.parametrize('bad',['basis','quantity_predicate','start_scope'])
def test_invalid_request_rejects_before_sampling(monkeypatch,bad):
    r=request()
    if bad=='basis':r['task']['unit_basis']='packaging_mass_kg'
    if bad=='quantity_predicate':r['task']['predicates']=[{'field':'sku.net_mass_g','operator':'gt','value':True,'unit':'g'}]
    if bad=='start_scope':
        r['task']['comparison_site_id']='comparison-00'
        r['episode']={'start':{'kind':'comparison_home','comparison_site_id':'comparison-01'}}
    def forbidden(*a,**kw):raise AssertionError('No draw allowed')
    monkeypatch.setattr(publication.native.feature_generation,'generate',forbidden)
    with pytest.raises(ValueError):publication.generate(r)


def test_comparison_home_is_predeclared_and_request_is_immutable():
    r=request();r['task']['comparison_site_id']='comparison-00'
    r['episode']={'start':{'kind':'comparison_home','comparison_site_id':'comparison-00'}}
    before=deepcopy(r);config=publication.compile_request(r)
    assert r==before and config['requested_start']==r['episode']['start']
    assert config['feature_request']['episode']['start']=={'kind':'directory'}
    assert config['selection']['comparison_site_id']=='comparison-00'


@pytest.mark.parametrize('empty',[False,True])
def test_unit_price_ties_full_population_and_natural_empty_retained(monkeypatch,empty):
    world,_,_,_,_=fixture();before=deepcopy(world);calls=[]
    def supplied(proxy,*,world_factory):
        calls.append(proxy)
        return {'world':world,'surrounding':None,'episode':{},'resolved_configuration':{},'audit':{'request_sha256':'feature'}}
    monkeypatch.setattr(publication.native.feature_generation,'generate',supplied)
    r=request()
    if empty:r['task']['max_price_minor']=1
    result=publication.generate(r);task=result['catalog_unit_price_task'];ref=result['catalog_unit_price_reference']
    assert len(calls)==1 and result['world']==before
    assert result['unit_price_binding']=={'status':'bound','world_repaired':False}
    assert result['episode']['manual_task']=={'user_message':task['user_message'],'memories':[]}
    assert task['schema_version']=='website-catalog-unit-price-task-v2'
    assert result['unit_price_field_inventory']['concept_id']==task['concept_id']
    if empty:
        assert ref['status']=='no_match' and not ref['winners'] and ref['minimum_unit_price_exact'] is None
    else:
        assert ref['feature_reference']['minimum_price_minor']==40000
        assert ref['minimum_unit_price_exact']=={'numerator':30000,'denominator':1}
        assert {r['offer_id'] for r in ref['winners']}=={'a/pack-2000','d/pack-2000'}


@pytest.mark.parametrize('status',['absent','unknown','not_applicable'])
def test_native_canonical_quantity_proof_never_repairs_explicit_status(monkeypatch,status):
    world,_,_,_,inventory=fixture();canonical_provenance(world,inventory)
    if status!='absent':world['products'][0]['sku_status']['pack-2000']={'sku.net_mass_g':status}
    before=deepcopy(world)
    def supplied(*a,**kw):
        return {'world':world,'surrounding':None,'episode':{},'resolved_configuration':{},'audit':{'request_sha256':'feature'}}
    monkeypatch.setattr(publication.native.feature_generation,'generate',supplied)
    result=publication.generate(request());task=result['catalog_unit_price_task'];ref=result['catalog_unit_price_reference']
    assert world==before and task['quantity_provenance']['mode']=='exact_source_bound_canonical_manufacture'
    if status=='absent':assert {r['sku_id'] for r in ref['winners']}=={'pack-2000'}
    else:assert {r['sku_id'] for r in ref['candidates']}=={'pack-1000'}
    assert result['unit_price_field_inventory']['known_paths']==inventory.known_paths


@pytest.mark.parametrize('status',['match','no_match'])
def test_freeze_exact_ratio_provenance_winners_and_inventory(tmp_path,monkeypatch,status):
    task={'kind':publication.native.native.KIND,'quantity_provenance':{
        'mode':'exact_source_bound_canonical_manufacture','source_bound_models':[{'product_id':'p','canonical_sku_menu_sha256':'frozen-proof'}]}}
    reference={'status':status,'minimum_unit_price_exact':None if status=='no_match' else {'numerator':30000,'denominator':1},
        'winners':[] if status=='no_match' else [{'offer_id':'a/pack-2000'},{'offer_id':'d/pack-2000'}]}
    result={'catalog_unit_price_task':task,'catalog_unit_price_reference':reference,
        'unit_price_field_inventory':{'source_hashes':{}},'unit_price_binding':{'status':'bound','world_repaired':False}}
    monkeypatch.setattr(publication,'generate',lambda *a,**kw:result)
    def freeze(request,output,**kw):
        sampled=generate(request);output.mkdir();files={}
        for name,key in [('feature-offer-task.private.json','feature_offer_task'),
                ('feature-offer-reference.private.json','feature_offer_reference'),
                ('feature-field-inventory.private.json','feature_field_inventory')]:
            (output/name).write_text(json.dumps(sampled[key]));files[name]=sha256((output/name).read_bytes()).hexdigest()
        return {'files':files}
    monkeypatch.setattr(publication.feature,'prepare',freeze)
    output=tmp_path/'new';manifest=publication.prepare(request(),output)
    assert json.loads((output/'catalog-unit-price-task.private.json').read_text())==task
    assert json.loads((output/'catalog-unit-price-reference.private.json').read_text())==reference
    assert json.loads((output/'unit-price-field-inventory.private.json').read_text())==result['unit_price_field_inventory']
    assert manifest['unit_price_binding_status']=='bound' and not list(output.glob('feature-*'))
    for name,h in manifest['files'].items():assert sha256((output/name).read_bytes()).hexdigest()==h
