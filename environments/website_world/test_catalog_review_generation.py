from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from environments.website_world import catalog_review_generation as generation
from environments.website_world.catalog_review_grading import ReviewSummaryGrader
from environments.website_world.test_catalog_review_task import fixture,claims_for


def request():
    return {'schema':'website-world-generation-v2','seed':78,
        'world':{'concept_ids':['footwear.walking_shoes','footwear.casual_trainers'],
                 'controls':{'world_size':.75},'review_count':12},
        'task':{'kind':'summarize_product_reviews','concept_id':'footwear.walking_shoes','operation':'topic_counts',
                'topic':{'aspect':'walking_comfort','context':{'activity':'walking around town','duration':'several hours'}}},
        'surrounding_sites':{'version':'native-rich-surrounding-v3'},
        'budget':{'max_proposals':1,'max_seconds':120}}


def test_compile_preserves_input_concentration_and_review_count():
    r=request();r['world']['tasks']=['footwear.casual_trainers'];before=deepcopy(r)
    c=generation.compile_request(r)
    assert r==before and c['proxy_request']['world']['review_count']==12
    assert c['proxy_request']['world']['tasks']==['footwear.casual_trainers']


@pytest.mark.parametrize('change',['topic','scope','publication','slice','index','operation'])
def test_invalid_task_rejects_before_world_factory(change,monkeypatch):
    r=request()
    if change=='topic':r['task']['topic']['aspect']='undeclared'
    elif change=='scope':r['task']['subject_scope']='all_store_products'
    elif change=='publication':r['surrounding_sites']['review_count']=0
    elif change=='slice':r['world']['concept_ids']=['footwear.casual_trainers']
    elif change=='index':r['task']['product_index']=True
    else:r['task']['operation']='guess_customer_satisfaction_from_price'
    def forbidden(*args,**kwargs):raise AssertionError('No sampling allowed')
    monkeypatch.setattr(generation.unified_generation,'generate',forbidden)
    with pytest.raises(ValueError):generation.generate(r)


@pytest.mark.parametrize('missing',['none','product','sku','publication'])
def test_binding_never_repairs_missing_subject_or_publication(missing,monkeypatch):
    w,t,ref,registry,sidecar,_=fixture();before=deepcopy(w);calls=[]
    r=request()
    if missing=='product':r['task']['product_index']=100
    elif missing=='sku':r['task'].update(subject_scope='sku',sku_index=100)
    elif missing=='publication':sidecar['sites']=[]
    def existing(proxy,*,world_factory):
        calls.append(proxy)
        return {'world':w,'surrounding':sidecar,'resolved_configuration':{},'audit':{'request_sha256':'proxy'},'episode':{}}
    monkeypatch.setattr(generation.unified_generation,'generate',existing)
    out=generation.generate(r)
    assert len(calls)==1 and w==before and out['review_task_binding']['world_repaired'] is False
    assert (out['review_task_binding']['status']=='bound') == (missing=='none')
    if missing in ('product','sku'):assert out['catalog_review_task'] is None


def test_saved_once_formatter_and_shared_publisher_use_only_public_input(tmp_path):
    from experiments.answer_grading.task_answer import grade_saved_once
    from scripts.trace_grades import BOUND_FILES,FILENAME
    w,t,r,registry,sidecar,i=fixture();text,claims=claims_for(t,r)
    trace=tmp_path/'trace';trace.mkdir()
    save=lambda p,x:p.write_text(json.dumps(x)+'\n')
    for name in BOUND_FILES:(trace/name).write_text('' if name.endswith('.jsonl') else '{}')
    save(trace/'natural-answer.json',{'text':text,'stop_reason':'agent_finished','technical_error':None})
    public={'user_message':t['user_message'],'memories':[],'environment_context':{}}
    save(trace/'policy-task.json',public)
    inputs={};values={'world':w,'task':t,'reference':r,'site_registry':registry,'surrounding':sidecar}
    for key,value in values.items():
        inputs[key]=tmp_path/(key+'.json');save(inputs[key],value)
    calls=[]
    class Backend:
        def complete(self,messages):
            payload=json.loads(messages[1]['content'])
            assert payload=={'public_task':public,'final_answer':text}
            assert 'canonical_review_ids' not in messages[0]['content']
            calls.append(messages)
            return SimpleNamespace(text=json.dumps(claims),raw={'model':'scripted-review-formatter','provider':'offline',
                'choices':[{'finish_reason':'stop','message':{'content':json.dumps(claims)}}]},request={'messages':messages})
        def close(self):pass
    kwargs=dict(trace=trace,inputs=inputs,output=tmp_path/'grading',
        grader_factory=lambda **data:ReviewSummaryGrader(**data,inventory=i),
        backend_factory=lambda _:Backend(),source_paths=[Path(generation.__file__)])
    grade=grade_saved_once(**kwargs)
    assert grade['structured_claims_correct'] and len(calls)==1
    assert json.loads((trace/FILENAME).read_text())['grading_version']=='website-catalog-review-grading-v1'
    with pytest.raises(FileExistsError):grade_saved_once(**kwargs)
    assert len(calls)==1
