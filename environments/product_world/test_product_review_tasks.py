from copy import deepcopy
from types import SimpleNamespace

import pytest

from environments.product_review_sites.evidence import VERSION,generate_evidence,digest
from environments.shopping_intent.world import fingerprint
from environments.shopping_intent.product_reviews import requirement_result
from .scenario import generate_scenario,sample_task
from .product_review_tasks import summaries_for,sample_count_task,grade_count_task
from .outcomes import candidates_for,evaluate
from .episode import Episode


@pytest.fixture(scope='module')
def scenario():
    return generate_scenario({'seed':0,'family':'footwear','memory':'mixed','requirements':1,'hidden':'none',
        'world_preferences':'none','product_review_preferences':'majority','destination_city':'malmo'},
        {'seed':42,'models_per_store':3},{},product_review_options={'seed':42,'as_of':'2026-09-26'})


@pytest.mark.parametrize('memory',['none','profile','episodic','mixed'])
def test_typed_preferences_match_request_or_memory_and_fingerprint(memory):
    task=sample_task(family='footwear',memory=memory,product_review_preferences='majority',hidden='none')
    req=task['resolved_task']['product_review_requirements'][0]
    assert req['rule']=='strict_majority' and req['context_id']=='long_walks'
    assert task['semantic_sha256']==fingerprint(task)
    assert ''.join(s['text'] for s in task['authoring']['message_segments'])==task['public']['user_message']
    if memory=='none':assert task['request']['explicit_product_review_requirements'] and not task['product_review_memory_facts']
    else:assert task['product_review_memory_facts'] and req['source']['kind']=='memory'


def test_world_and_opinion_seed_changes_do_not_rewrite_preferences(scenario):
    other=generate_scenario({'seed':0,'family':'footwear','memory':'mixed','requirements':1,'hidden':'none',
        'world_preferences':'none','product_review_preferences':'majority','destination_city':'malmo'},
        {'seed':43,'models_per_store':3},{},product_review_options={'seed':43})
    assert scenario['task']==other['task']


def test_sparse_exact_sku_coverage_stays_unknown_in_global_selection(scenario):
    candidates=candidates_for(scenario);req=scenario['task']['resolved_task']['product_review_requirements'][0]
    results=[requirement_result(req,c['product_review_evidence'].get('comfort@long_walks')) for c in candidates]
    assert None in results
    assert evaluate(scenario)['outcome']['status']=='uncertain'
    absent=deepcopy(scenario);absent.pop('product_review_evidence')
    assert all(c['product_review_evidence']=={} for c in candidates_for(absent))
    assert evaluate(absent)['outcome']['status']=='uncertain'


def test_corrupt_corpus_cannot_supply_grader_facts(scenario):
    bad=deepcopy(scenario);bad['product_review_evidence']['public']['reviews'][0]['stars']=5
    # Guarantee drift regardless of the original draw.
    bad['product_review_evidence']['public']['reviews'][0]['body']='Changed'
    with pytest.raises(ValueError,match='hash'):candidates_for(bad)


def test_count_task_uses_explicit_polarity_and_rejects_wrong_total(scenario):
    world=scenario['bundle'];e=scenario['product_review_evidence'];scope=e['public']['coverage'][0]
    task=sample_count_task(world,sku_id=scope['sku_id'],aspect_id=scope['aspect_id'])
    req=task['requirement'];s=summaries_for(world,e,[req])[task['sku_id']][req['aspect_id']+'@'+req['context_id']]
    answer={'status':'review_counts','review_counts':s['review_counts']}
    assert grade_count_task(world,e,task,answer,effects=[])['structured_claims_correct']
    bad=deepcopy(answer);bad['review_counts']['negative']+=1
    assert not grade_count_task(world,e,task,bad,effects=[])['structured_claims_correct']
    assert not grade_count_task(world,e,task,answer,effects=[{'event':'purchase'}])['structured_claims_correct']
    empty=generate_evidence(world,reviews_per_sku=0,seed=42)
    assert grade_count_task(world,empty,task,{'status':'review_counts','review_counts':dict.fromkeys(s['review_counts'],0)},effects=[])['structured_claims_correct']


def runtime(scenario):
    e=scenario['product_review_evidence']
    return SimpleNamespace(index_origin='http://localhost:5555',public_manifest={'index_url':'http://localhost:5555','sites':[
        {'site_id':s['retailer_id'],'kind':'retailer','origin':'http://localhost:'+str(6000+i)} for i,s in enumerate(scenario['bundle']['public']['retailers'])]},
        product_review_evidence=e,provenance={'world_sha256':scenario['bundle']['world_sha256'],
        'locations_sha256':scenario['locations']['locations_sha256'],'merchant_reviews_public_sha256':digest(scenario['merchant_reviews']['public']),
        'product_review_evidence_sha256':digest(e['public']),'product_review_evidence_version':VERSION})


def test_episode_requires_actual_served_versioned_corpus(scenario):
    r=runtime(scenario);assert Episode.from_runtime(scenario,r).reference()['status']=='uncertain'
    for field in ('product_review_evidence_sha256','product_review_evidence_version'):
        bad=deepcopy(r);bad.provenance[field]='wrong'
        with pytest.raises(ValueError,match='evidence'):Episode.from_runtime(scenario,bad)
    bad=deepcopy(r);del bad.product_review_evidence
    with pytest.raises(ValueError,match='evidence'):Episode.from_runtime(scenario,bad)
