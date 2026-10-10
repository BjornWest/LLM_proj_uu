from copy import deepcopy
import pytest
from environments.website_world import hidden_offer_publication as publication
from environments.website_world.test_hidden_offer_generation import request
from environments.website_world.test_hidden_offer_task import fixture,slot


def test_visible_hidden_field_rejects_before_draw(monkeypatch):
    r=request();r['task']['predicates']=[slot()['predicate']]
    def forbidden(*args,**kwargs):raise AssertionError('No draw permitted')
    monkeypatch.setattr(publication.native.feature_offer_generation,'generate',forbidden)
    with pytest.raises(ValueError,match='visible'):publication.generate(r)


def test_public_initial_task_and_private_reply_bindings_survive(monkeypatch):
    w,_,_,_,_=fixture();before=deepcopy(w);calls=[]
    def generated(proxy,*,world_factory):
        calls.append(proxy)
        return {'world':w,'surrounding':None,'resolved_configuration':{},
                'audit':{'request_sha256':'proxy'},'episode':{}}
    monkeypatch.setattr(publication.native.feature_offer_generation.unified_generation,'generate',generated)
    result=publication.generate(request());t=result['hidden_offer_task']
    assert len(calls)==1 and w==before
    assert result['episode']['manual_task']=={'user_message':t['user_message'],'memories':t['memories']}
    assert '42' not in t['user_message'] and '43' not in t['user_message'] and t['memories']==[]
    assert result['hidden_reply_binding']['audit_id']==publication.catalog_clarification.Responder(t).audit_id
    assert result['hidden_offer_binding']['world_repaired'] is False


def test_no_effect_binding_is_retained_without_repair(monkeypatch):
    w,_,_,_,_=fixture();before=deepcopy(w);calls=[]
    def generated(proxy,*,world_factory):
        calls.append(proxy)
        return {'world':w,'surrounding':None,'resolved_configuration':{},
                'audit':{'request_sha256':'proxy'},'episode':{}}
    monkeypatch.setattr(publication.native.feature_offer_generation.unified_generation,'generate',generated)
    r=request();r['task']['hidden_requirement']['predicate']['value']=54
    r['task']['hidden_requirement']['contrast_values']=[55]
    result=publication.generate(r)
    assert len(calls)==1 and w==before
    assert result['hidden_offer_reference']['status']=='no_match'
    assert result['hidden_offer_binding']['status']=='unsupported_no_effectful_clarification'


def test_comparison_start_scope_matches():
    r=request();r['episode']={'start':{'kind':'comparison_home','comparison_site_id':'comparison-00'}}
    with pytest.raises(ValueError,match='task scope'):publication.compile_request(r)
    r['task']['comparison_site_id']='comparison-00'
    assert publication.compile_request(r)['requested_start']==r['episode']['start']
