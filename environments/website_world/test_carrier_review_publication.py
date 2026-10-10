from copy import deepcopy
from hashlib import sha256
import json

import pytest

from environments.website_world import carrier_review_publication as publication
from environments.website_world.test_carrier_review_task import fixture


def request():return {'schema':'website-world-generation-v2','seed':85,'world':{'concept_ids':['footwear.walking_shoes']},'task':{'kind':'summarize_carrier_reviews','operation':'topic_counts','shipping_class':'regular','aspect':'punctuality'}}


@pytest.mark.parametrize('bad',['private','class','dates'])
def test_invalid_scope_rejects_before_generation(monkeypatch,bad):
    r=request()
    if bad=='private':r['task']['operation']='hidden_success_rate'
    if bad=='class':r['task']['shipping_class']='home'
    if bad=='dates':r['task'].update(date_from='2026-10-01',date_to='2026-09-01')
    def forbidden(*a,**kw):raise AssertionError('No factory')
    monkeypatch.setattr(publication.native.unified_generation,'generate',forbidden)
    with pytest.raises(ValueError):publication.generate(r)


@pytest.mark.parametrize('missing',[False,True])
def test_exact_publication_and_insufficient_or_unsupported_are_retained(monkeypatch,missing):
    world,_,_,_,_,_=fixture();world['config']={'concept_ids':['footwear.walking_shoes']};before=deepcopy(world)
    def supplied(*a,**kw):return {'world':world,'episode':{},'resolved_configuration':{},'audit':{'request_sha256':'proxy'}}
    monkeypatch.setattr(publication.native.unified_generation,'generate',supplied)
    r=request();r['task']['min_assessed']=4
    if missing:r['task']['carrier_index']=999
    original=deepcopy(r);result=publication.generate(r)
    assert r==original and world==before
    assert result['carrier_review_publication']==publication.native.native.public_projection(world)
    if missing:
        assert result['carrier_review_task'] is None and result['carrier_review_reference'] is None
        assert result['carrier_review_binding']['status']=='unsupported_no_carrier_identity'
    else:
        task=result['carrier_review_task'];assert result['carrier_review_reference']['verdict']=='insufficient_evidence'
        assert result['episode']['manual_task']=={'user_message':task['user_message'],'memories':[]}
        assert result['carrier_review_binding']['status']=='requires_carrier_publication_adoption'


@pytest.mark.parametrize('missing',[False,True])
def test_freeze_original_pending_binding_publication_and_nulls(tmp_path,monkeypatch,missing):
    task=None if missing else {'kind':'summarize_carrier_reviews'};ref=None if missing else {'status':'summary','verdict':'insufficient_evidence'}
    binding={'status':'unsupported_no_carrier_identity' if missing else 'requires_carrier_publication_adoption','world_repaired':False}
    result={'carrier_review_task':task,'carrier_review_reference':ref,'carrier_review_inventory':{'source_hashes':{}},'carrier_review_binding':binding,'carrier_review_publication':{'profiles':[]}}
    monkeypatch.setattr(publication,'generate',lambda *a,**kw:result)
    def freeze(request,output,**kw):
        sampled=generate(request);output.mkdir();files={}
        for name,key in [('feature-offer-task.private.json','feature_offer_task'),('feature-offer-reference.private.json','feature_offer_reference'),('feature-field-inventory.private.json','feature_field_inventory')]:
            (output/name).write_text(json.dumps(sampled[key]));files[name]=sha256((output/name).read_bytes()).hexdigest()
        return {'files':files}
    monkeypatch.setattr(publication.feature,'prepare',freeze)
    output=tmp_path/'new';manifest=publication.prepare(request(),output)
    assert json.loads((output/'carrier-review-task.private.json').read_text())==task
    assert json.loads((output/'carrier-review-reference.private.json').read_text())==ref
    assert json.loads((output/'carrier-review-binding.private.json').read_text())==binding
    assert json.loads((output/'carrier-publication.private.json').read_text())==result['carrier_review_publication']
    assert manifest['automatic_grader_supported'] is not missing and not list(output.glob('feature-*'))
    for name,h in manifest['files'].items():assert sha256((output/name).read_bytes()).hexdigest()==h
