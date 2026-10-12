import json
from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1].parent/'common_agent_util'))
from scripts.trace_grades import BOUND_FILES,FILENAME,SCHEMA,sha,read_grade,project_grade
from scripts.trace_hub import Hub,viewer_html
from agent_trace.value_ledger import LedgerReader
from experiments.answer_grading.publish import publish


def fixture(tmp_path,verdict=True):
    trace=tmp_path/'runs/episode';trace.mkdir(parents=True)
    for name in BOUND_FILES:(trace/name).write_text('{}')
    (trace/'metadata.json').write_text('{"browsergym_version":"0.14.3","model":"test","driver":"llm"}')
    (trace/'steps.jsonl').write_text('')
    out=tmp_path/'extraction';out.mkdir()
    files={'plan.json':{'mode':'live','source_trace':str(trace)},
      'completed.json':{'status':'graded','source_hashes_unchanged':True},
      'grade.json':{'source_trace':str(trace),'structured_claims_correct':verdict,
        'oracle_grade':{'requirements':{'reported_total':verdict}},'additional_checks':{'reported_currency':True},
        'oracle_answer':{'total_minor':100},'derivations':[], 'safe_success':None,'full_response_evaluated':False,'extraction_version':'test'},
      'claims.json':{'total':None},'request.json':{},'response.json':{},
      'usage.json':{'model':'extractor','provider':'provider','reported_cost_usd':0.01},
      'source-hashes.json':{str(trace/n):sha(trace/n) for n in BOUND_FILES}}
    for name,value in files.items():(out/name).write_text(json.dumps(value))
    config=tmp_path/'sources.json';config.write_text(json.dumps({'project_root':str(tmp_path),'roots':[str(trace.parent)]}))
    return trace,out,config


@pytest.mark.parametrize('verdict',[True,False,None])
def test_publication_projection_and_original_preservation(tmp_path,verdict):
    trace,out,config=fixture(tmp_path,verdict);before={n:(trace/n).read_bytes() for n in BOUND_FILES}
    p=publish(out);assert publish(out)==p
    grade=read_grade(trace);assert grade['structured_claims_correct'] is verdict
    hub=Hub(config);summary,entries=hub.snapshot()
    assert 'derived grade available' in json.loads(summary)[0]['title']
    group=json.loads(entries[next(iter(entries))][0])
    assert group['derived_evaluation']['structured_claims_correct'] is verdict
    assert group['recorded_evaluation_label']=='outcome unknown'
    assert len([m for m in group['messages'] if m.get('provenance')=='derived_post_episode_evaluation'])==1
    assert before=={n:(trace/n).read_bytes() for n in BOUND_FILES}


def test_stale_episode_invalidates_cached_pass(tmp_path):
    trace,out,config=fixture(tmp_path);publish(out);hub=Hub(config)
    _,entries=hub.snapshot();ident=next(iter(entries));first=json.loads(entries[ident][0])
    assert first['derived_evaluation']['binding_status']=='verified'
    (trace/'natural-answer.json').write_text('{"text":"different"}')
    group=json.loads(hub.load(hub.lookup(ident))[0])
    assert group['derived_evaluation']['binding_status']=='invalid'
    assert 'passed' not in group['evaluation_label']


@pytest.mark.parametrize('bad',['identity','symlink','bool','binding','broader','array','provenance'])
def test_invalid_sidecar_cannot_show_pass(tmp_path,bad):
    trace,out,_=fixture(tmp_path);p=publish(out);v=json.loads(p.read_text())
    if bad=='identity':v['episode_id']='other'
    if bad=='bool':v['structured_claims_correct']='true'
    if bad=='binding':v['episode_artifact_sha256']['../secret']='x'
    if bad=='broader':v['safe_success']=True
    if bad=='provenance':v['extractor']=None
    if bad=='array':v=[]
    if bad=='symlink':
        p.unlink();target=tmp_path/'other';target.write_text(json.dumps(v));p.symlink_to(target)
    else:p.write_text(json.dumps(v))
    assert read_grade(trace)['binding_status']=='invalid'


def test_publisher_rejects_changed_inputs_and_conflicting_grade(tmp_path):
    trace,out,_=fixture(tmp_path);publish(out)
    p=out/'grade.json';v=json.loads(p.read_text());v['structured_claims_correct']=False;p.write_text(json.dumps(v))
    with pytest.raises(ValueError,match='different'):publish(out)
    (trace/'natural-answer.json').write_text('changed')
    with pytest.raises(ValueError,match='input changed'):publish(out)


def test_replay_not_published_as_new_model_grade(tmp_path):
    trace,out,_=fixture(tmp_path);p=out/'plan.json';v=json.loads(p.read_text());v['mode']='replay';p.write_text(json.dumps(v))
    with pytest.raises(ValueError,match='replay'):publish(out)
    assert not (trace/FILENAME).exists()


def test_viewer_integration_has_summary_panel():
    html=viewer_html().decode()
    assert 'renderDerivedGrade();list();const query=' in html
    assert 'Post-run answer checks: ' in html
    assert 'createTextNode' in html and 'derived-answer-grade' in html


@pytest.mark.parametrize('meaningful',[False,True])
def test_only_empty_manual_placeholder_replaced(tmp_path,meaningful):
    trace,out,config=fixture(tmp_path)
    value={'verifier':'manual-review','trust':'ungraded','safe_success':None,
           'task_completed': True if meaningful else None}
    (trace/'evaluation.json').write_text(json.dumps(value))
    p=out/'source-hashes.json';v=json.loads(p.read_text());v[str(trace/'evaluation.json')]=sha(trace/'evaluation.json');p.write_text(json.dumps(v))
    publish(out)
    hub=Hub(config);_,entries=hub.snapshot();group=json.loads(entries[next(iter(entries))][0])
    messages=group['messages']
    original=next(m for m in messages if m['title']=='Privileged verifier — not model input')
    replacement=next(m for m in messages if m['title']=='Answer grading — not model input')
    assert original['diagnostic'] is (not meaningful)
    assert not replacement['diagnostic']
    assert LedgerReader(group['value_ledger']).resolve(original['text_ref'])==value
    if not meaningful:assert messages.index(replacement)==messages.index(original)-1
    assert group['visible_message_count']==sum(not m.get('diagnostic') for m in messages)
    # If evidence changes, neither the placeholder nor a known outcome is hidden.
    (trace/'natural-answer.json').write_text('changed')
    group=json.loads(hub.load(hub.lookup(group['id']))[0])
    original=next(m for m in group['messages'] if m['title']=='Privileged verifier — not model input')
    assert not original['diagnostic']


def test_details_binding_and_lazy_cache_invalidation(tmp_path):
    from scripts.trace_grades import DETAILS_FILENAME
    trace,out,config=fixture(tmp_path);summary=publish(out);hub=Hub(config)
    _,entries=hub.snapshot();ident=next(iter(entries));assert 'check_details' not in json.loads(entries[ident][0])['derived_evaluation']
    details={'schema':'browser-answer-check-details-v1','episode_id':trace.name,'grade_sidecar_sha256':sha(summary),
             'checks':{'reported_total':{'expected':'10 SEK','supplied':'11 SEK','explanation':'Quoted total','answer_quote':'11 SEK'}}}
    p=trace/DETAILS_FILENAME;p.write_text(json.dumps(details))
    group=json.loads(hub.load(hub.lookup(ident))[0])
    assert group['derived_evaluation']['check_details']['reported_total']['expected']=='10 SEK'
    details['grade_sidecar_sha256']='wrong';p.write_text(json.dumps(details))
    group=json.loads(hub.load(hub.lookup(ident))[0]);g=group['derived_evaluation']
    assert 'check_details' not in g and 'check_details_error' in g
    assert g['binding_status']=='verified' # explanatory enrichment does not rewrite the original verdict
