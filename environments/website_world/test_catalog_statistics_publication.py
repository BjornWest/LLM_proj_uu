from copy import deepcopy
from hashlib import sha256
import json
import pytest
from environments.website_world import catalog_statistics_publication as publication
from environments.website_world.test_catalog_statistics_task import fixture


def request():
    return {'schema':'website-world-generation-v2','seed':78,
        'world':{'concept_ids':['footwear.walking_shoes']},
        'task':{'kind':'comparison_catalog_statistics','concept_id':'footwear.walking_shoes',
            'comparison_site_id':'comparison-00','operation':'mean','grain':'model'}}


@pytest.mark.parametrize('change',['site','operation'])
def test_invalid_selection_rejects_before_sampling(change,monkeypatch):
    r=request();r['task'].update({'comparison_site_id':'comparison-07'} if change=='site' else {'operation':'historical_change'})
    def forbidden(*a,**kw):raise AssertionError('No draw allowed')
    monkeypatch.setattr(publication.native.unified,'generate',forbidden)
    with pytest.raises(ValueError):publication.generate(r)


@pytest.mark.parametrize('empty',[False,True])
def test_inventory_native_population_and_empty_state_are_preserved(empty,monkeypatch):
    world,sidecar,_,_,_=fixture(empty=empty);before=deepcopy(world);calls=[]
    def generated(proxy,*,world_factory):
        calls.append(proxy)
        return {'world':world,'surrounding':sidecar,'resolved_configuration':{},'audit':{'request_sha256':'proxy'},'episode':{}}
    monkeypatch.setattr(publication.native.unified,'generate',generated)
    result=publication.generate(request());t=result['catalog_statistics_task'];ref=result['catalog_statistics_reference']
    assert len(calls)==1 and world==before
    assert result['episode']['manual_task']=={'user_message':t['user_message'],'memories':[]}
    assert result['statistics_binding']=={'status':'bound','comparison_site_id':'comparison-00','world_repaired':False}
    assert (ref['population_count']==0)==empty
    if empty:assert ref['aggregate_sek'] is None and ref['statistic_defined'] is False
    assert result['statistics_field_inventory']['fields']==publication.native.native.FieldInventory(t['concept_id']).fields


@pytest.mark.parametrize('defined',[True,False])
def test_freeze_retains_exact_reference_without_writer_only_status(tmp_path,monkeypatch,defined):
    task={'kind':publication.native.native.KIND};reference={'statistic_defined':defined,'population_count':1 if defined else 0}
    records={'catalog_statistics_task':task,'catalog_statistics_reference':reference,
        'statistics_field_inventory':{},'statistics_binding':{'status':'bound','world_repaired':False}}
    monkeypatch.setattr(publication,'generate',lambda *a,**kw:records)
    def freeze(request,output,**kw):
        result=generate(request);output.mkdir();files={}
        for name,key in [('feature-offer-task.private.json','feature_offer_task'),('feature-offer-reference.private.json','feature_offer_reference'),('feature-field-inventory.private.json','feature_field_inventory')]:
            (output/name).write_text(json.dumps(result[key]));files[name]=sha256((output/name).read_bytes()).hexdigest()
        return {'files':files}
    monkeypatch.setattr(publication.feature,'prepare',freeze)
    output=tmp_path/'fresh';manifest=publication.prepare(request(),output)
    assert json.loads((output/'catalog-statistics-reference.private.json').read_text())==reference
    for name,h in manifest['files'].items():assert sha256((output/name).read_bytes()).hexdigest()==h
    assert not list(output.glob('feature-*'))
