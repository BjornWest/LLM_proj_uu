from copy import deepcopy

import pytest

from environments.website_world import memory_offer_publication as publication
from environments.website_world.catalog_memory import ClarificationRequired
from environments.website_world.test_memory_offer_generation import request
from environments.website_world.test_memory_offer_task import fixture, record


def test_unresolved_memory_cannot_draw(monkeypatch):
    r=request();r['task']['recipient']=None
    def forbidden(*args, **kwargs):raise AssertionError('No world draw')
    monkeypatch.setattr(publication.native.feature_offer_generation,'generate',forbidden)
    with pytest.raises(ClarificationRequired):publication.generate(r)


def test_conflicting_defaults_cannot_draw(monkeypatch):
    r=request();r['task']['memory_records'].append(record(43,id='conflict'))
    def forbidden(*args, **kwargs):raise AssertionError('No world draw')
    monkeypatch.setattr(publication.native.feature_offer_generation,'generate',forbidden)
    with pytest.raises(ClarificationRequired):publication.generate(r)


def test_comparison_home_matches_predeclared_scope():
    r=request();r['episode']={'start':{'kind':'comparison_home','comparison_site_id':'comparison-00'}}
    with pytest.raises(ValueError,match='task scope'):publication.compile_request(r)
    r['task']['comparison_site_id']='comparison-00'
    c=publication.compile_request(r)
    assert c['requested_start']==r['episode']['start']
    assert c['proxy_request']['episode']['start']=={'kind':'directory'}


def test_native_memories_override_and_no_match_survive_one_draw(monkeypatch):
    world, _, _, _, _=fixture();before=deepcopy(world);calls=[]
    def generated(proxy, *, world_factory):
        calls.append(proxy)
        return {'world':world,'surrounding':None,'resolved_configuration':{},
                'audit':{'request_sha256':'proxy'},'episode':{}}
    monkeypatch.setattr(publication.native.feature_offer_generation.unified_generation,'generate',generated)
    r=request();r['task']['memory_records'][0]['predicates'][0]['value']=43
    r['task']['predicates']=[{'field':'sku.size_eu','operator':'eq','value':99}]
    result=publication.generate(r);t=result['memory_offer_task']
    assert len(calls)==1 and world==before
    assert result['memory_offer_reference']['status']=='no_match'
    assert result['episode']['manual_task']=={'user_message':t['user_message'],'memories':t['memories']}
    assert '43' in t['memories'][0] and '43' not in t['user_message']
    assert '99' in t['user_message'] and t['memory_records']==r['task']['memory_records']
    assert t['memory_resolution']['provenance'][0]['status']=='overridden_by_request'
    assert result['memory_field_inventory']['source_hashes']==t['selection_task']['field_source_sha256']
