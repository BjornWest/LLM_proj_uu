"""Prospective synthetic reader controls. No native grader/backend construction."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest
from scripts.trace_grades import BOUND_FILES, FILENAME, SCHEMA, MISSING_OUTPUT_SCHEMA, read_grade, project_grade


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2))


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':')).encode()).hexdigest()


def hash_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def seal(trace, root, native=None):
    terminal = json.loads((root/'terminal-evidence.json').read_text())
    roles = {'natural_answer':trace/'natural-answer.json',
        'episode_before_finalization':root/'before-finalization/episode.json',
        'evaluation_before_finalization':root/'before-finalization/evaluation.json',
        'policy_result':root/'policy-result.json', 'cleanup_receipt':root/'cleanup-receipt.json'}
    cleanup = json.loads((root/'cleanup-receipt.json').read_text())
    cleanup.update(policy_result_sha256=hash_file(roles['policy_result']),
        episode_before_finalization_sha256=hash_file(roles['episode_before_finalization']))
    save(root/'cleanup-receipt.json', cleanup)
    terminal['artifacts'] = {k:{'path':str(p), 'sha256':hash_file(p)} for k,p in roles.items()}
    save(root/'terminal-evidence.json', terminal)
    if native is None: native = json.loads((root/'native-grade.json').read_text())
    native.update(terminal_evidence=terminal, terminal_evidence_digest=digest(terminal))
    save(root/'native-grade.json', native)
    grade = json.loads((trace/FILENAME).read_text())
    names = ['native-grade.json','terminal-evidence.json','cleanup-receipt.json','policy-result.json',
             'before-finalization/episode.json','before-finalization/evaluation.json']
    grade['source_artifact_sha256'] = {n:hash_file(root/n) for n in names}
    grade['episode_artifact_sha256'] = {n:hash_file(trace/n) for n in BOUND_FILES}
    grade['native_grade_artifact'] = {'name':'native-grade.json','sha256':hash_file(root/'native-grade.json')}
    save(trace/FILENAME, grade)


def fixture(tmp_path, stop='max_steps', messages=None):
    trace=tmp_path/'runs/episode';root=tmp_path/'output';inputs=tmp_path/'inputs'
    for n in BOUND_FILES:save(trace/n, {})
    (trace/'steps.jsonl').write_text('')
    messages=[] if messages is None else messages
    answer={'schema_version':'connected-world-manual-v1','assistant_messages':messages,
        'text':messages[-1] if messages else None, 'stop_reason':stop,
        'initial_chat_messages_excluded':2, 'technical_error':None,
        'source':'BrowserGym chat from executed send_msg_to_user; no extraction or repair'}
    save(trace/'natural-answer.json',answer)
    episode={'trace_complete':True,'stop_reason':stop,'truncated':stop!='agent_finished',
        'error':None,'execution_error':None,'grading_error':None,'cleanup_errors':[]}
    save(trace/'episode.json',episode);save(root/'before-finalization/episode.json',episode)
    save(root/'before-finalization/evaluation.json',{'technical_error':None})
    save(trace/'evaluation.json',{'task_completed':False,'safe_success':False,'technical_error':None})
    save(trace/'metadata.json',{'max_steps':40,'max_input_tokens':100000})
    save(root/'policy-result.json',{'trace':str(trace),'summary':episode})
    pin={}
    for name in ['world','task','reference','surrounding','bindings','site_registry']:
        path=inputs/(name+'.json');save(path,{});pin[name]={'path':str(path),'sha256':hash_file(path)}
    source=inputs/'trusted-callback.py';source.write_text('# synthetic fixture, never executed\n')
    automatic={'task_id':'native','goal_sha256':hashlib.sha256(b'Synthetic public goal').hexdigest(),
        'initial_chat_messages_excluded':2,
        'reference_files':{v['path']:v['sha256'] for v in pin.values()},
        'source_files':{str(source):hash_file(source)}}
    episode['grading']={'schema':'automatic-episode-grading-v1','episode_id':trace.name,
        'contract_id':'synthetic-contract','phase':'external','binding':automatic,
        'binding_sha256':digest(automatic),'status':'pending_external'}
    save(trace/'episode.json',episode);save(root/'before-finalization/episode.json',episode)
    save(root/'policy-result.json',{'trace':str(trace),'summary':episode})
    terminal={'schema':'catalog-compare-review-missing-answer-terminal-v1','episode_id':trace.name,
        'binding':{'native_task_id':'native','public_task_id':'native','contract_id':'synthetic-contract',
            'input_files':pin,'source_files':{str(source):hash_file(source)}},'artifacts':{}}
    save(root/'terminal-evidence.json',terminal)
    save(root/'cleanup-receipt.json',{'schema':'catalog-compare-review-cleanup-v1','episode_id':trace.name,
        'contract_id':'synthetic-contract','policy_closed':True,'runtime_closed':True,'errors':[]})
    native={'grading_version':'website-catalog-compare-review-missing-answer-v1',
        'outcome_kind':'required_answer_not_delivered','task_completed':False,
        'structured_claims_correct':False,'claims':None,'extraction_requests':0,'stop_reason':stop,
        'oracle_grade':{'requirements':{'answer_delivered':False}},'additional_checks':{},
        'derivations':[],'selected_candidate_assessment':None,'response_contract':{'fixture':True},
        'native_reference':{'fixture':'reference'},'oracle_answer':{'fixture':'reference'}}
    save(root/'native-grade.json',native)
    grade={'schema':MISSING_OUTPUT_SCHEMA,'episode_id':trace.name,'created_at':'2026-10-08T00:00:00Z',
        **{k:native[k] for k in ['grading_version','outcome_kind','task_completed','structured_claims_correct',
            'claims','extraction_requests','stop_reason','additional_checks','derivations',
            'selected_candidate_assessment','oracle_answer']},
        'requirements':{'answer_delivered':False},'extractor':None,
        'extraction_mode':'deterministic_missing_answer','full_response_evaluated':False,'safe_success':None,
        'limitations':['Synthetic reader fixture; no callback authority or native acceptance claimed.'],
        'source_directory':str(root),'source_artifact_sha256':{},'episode_artifact_sha256':{},
        'native_grade_artifact':{}}
    save(trace/FILENAME,grade);seal(trace,root);return trace,root


@pytest.mark.parametrize('stop',['max_steps','max_input_tokens','agent_finished'])
@pytest.mark.parametrize('messages',[[],['',' \t']])
def test_explicit_clean_missing_output_and_budget_truncation(tmp_path,stop,messages):
    trace,root=fixture(tmp_path,stop,messages);before={p:p.read_bytes() for p in trace.iterdir()}
    grade=read_grade(trace);assert grade['binding_status']=='verified'
    assert grade['claims'] is None and grade['extractor'] is None and grade['extraction_requests']==0
    group=project_grade({'id':'episode','title':'Episode · task failed','evaluation_label':'task failed',
        'messages':[]},trace)
    assert group['evaluation_label']=='task failed: no answer delivered'
    assert group['derived_evaluation']['delivery_diagnostic']['individual_facts_and_effects']=='unassessed'
    assert group['messages'][0]['status']=='returned'
    assert before=={p:p.read_bytes() for p in trace.iterdir()}
    assert not list(root.rglob('usage.json')) and not list(root.rglob('claims.json'))


@pytest.mark.parametrize('key,value',[
    ('schema',SCHEMA),('schema','wrong'),('claims',{}),('extractor',{}),('extraction_requests',False),
    ('extraction_requests',1),('task_completed',True),('structured_claims_correct',True),
    ('stop_reason','environment_truncated'),('requirements',{'answer_delivered':0}),
    ('additional_checks',{'facts_checked':False}),('derivations',[{}]),('safe_success',False),
    ('full_response_evaluated',True),('selected_candidate_assessment',{}),('extra_field','wrong')])
def test_wrong_schema_or_outcome_never_shows_valid_missing_grade(tmp_path,key,value):
    trace,root=fixture(tmp_path);path=trace/FILENAME;data=json.loads(path.read_text());data[key]=value;save(path,data)
    assert read_grade(trace)['binding_status']=='invalid'


@pytest.mark.parametrize('name',['native-grade.json','terminal-evidence.json','cleanup-receipt.json',
    'policy-result.json','before-finalization/episode.json','before-finalization/evaluation.json'])
def test_bound_source_byte_drift_is_invalid(tmp_path,name):
    trace,root=fixture(tmp_path);(root/name).write_text('{}')
    assert read_grade(trace)['binding_status']=='invalid'


@pytest.mark.parametrize('control',['nonempty_prior','last_text','bool_prefix','incomplete','recording_error',
    'execution_error','cleanup_error','policy_disagrees','native_reference','native_claims','cleanup_not_closed',
    'native_digest','canonical_disagrees','terminal_role_path'])
def test_rebound_artifacts_still_cannot_hide_semantic_contradictions(tmp_path,control):
    trace,root=fixture(tmp_path);native=json.loads((root/'native-grade.json').read_text())
    if control in ('nonempty_prior','last_text','bool_prefix'):
        path=trace/'natural-answer.json';value=json.loads(path.read_text())
        if control=='nonempty_prior':value.update(assistant_messages=['real answer',''],text='')
        elif control=='last_text':value['text']='not last message'
        else:value['initial_chat_messages_excluded']=True
        save(path,value)
    elif control in ('incomplete','recording_error','execution_error','cleanup_error'):
        path=root/'before-finalization/episode.json';value=json.loads(path.read_text())
        if control=='incomplete':value['trace_complete']=False
        elif control=='cleanup_error':value['cleanup_errors']=['failure']
        else:value[control]='failure'
        save(path,value)
    elif control=='policy_disagrees':
        path=root/'policy-result.json';value=json.loads(path.read_text());value['summary']['stop_reason']='other';save(path,value)
    elif control=='native_reference':native['native_reference']={'changed':True}
    elif control=='native_claims':native['claims']={}
    elif control=='cleanup_not_closed':
        path=root/'cleanup-receipt.json';value=json.loads(path.read_text());value['runtime_closed']=False;save(path,value)
    elif control=='canonical_disagrees':save(trace/'evaluation.json',{'task_completed':True,'safe_success':True})
    seal(trace,root,native)
    if control in ('native_digest','terminal_role_path'):
        path=root/'native-grade.json';value=json.loads(path.read_text())
        if control=='native_digest':value['terminal_evidence_digest']=hashlib.sha256(json.dumps(value['terminal_evidence'],sort_keys=True).encode()).hexdigest()
        else:
            value['terminal_evidence']['artifacts']['natural_answer']['path']=str(root/'elsewhere.json')
            value['terminal_evidence_digest']=digest(value['terminal_evidence']);save(root/'terminal-evidence.json',value['terminal_evidence'])
        save(path,value);side=json.loads((trace/FILENAME).read_text());side['source_artifact_sha256']['native-grade.json']=hash_file(path)
        side['source_artifact_sha256']['terminal-evidence.json']=hash_file(root/'terminal-evidence.json');side['native_grade_artifact']['sha256']=hash_file(path);save(trace/FILENAME,side)
    assert read_grade(trace)['binding_status']=='invalid'


@pytest.mark.parametrize('bad',['../outside.json','/outside.json','a//b.json','a/./b.json','a\\b.json'])
def test_source_map_paths_are_strict(tmp_path,bad):
    trace,root=fixture(tmp_path);path=trace/FILENAME;data=json.loads(path.read_text());data['source_artifact_sha256'][bad]='a'*64;save(path,data)
    assert read_grade(trace)['binding_status']=='invalid'


@pytest.mark.parametrize('where',['file','parent','trace','source_root'])
def test_symlink_substitution_is_rejected(tmp_path,where):
    trace,root=fixture(tmp_path)
    if where=='file':
        path=root/'native-grade.json';old=tmp_path/'retained-grade';path.rename(old);path.symlink_to(old)
    elif where=='parent':
        path=root/'before-finalization';old=tmp_path/'retained-before';path.rename(old);path.symlink_to(old,target_is_directory=True)
    elif where=='trace':
        path=trace/'natural-answer.json';old=tmp_path/'retained-answer';path.rename(old);path.symlink_to(old)
    else:
        old=tmp_path/'retained-output';root.rename(old);root.symlink_to(old,target_is_directory=True)
    assert read_grade(trace)['binding_status']=='invalid'


def test_duplicate_json_keys_rejected_for_new_schema(tmp_path):
    trace,root=fixture(tmp_path);path=trace/FILENAME;raw=path.read_text()
    path.write_text(raw.replace('"extraction_requests": 0','"extraction_requests": 1, "extraction_requests": 0'))
    assert read_grade(trace)['binding_status']=='invalid'


def test_missing_schema_cannot_be_retroactively_revised(tmp_path):
    trace,root=fixture(tmp_path);save(trace/'derived-answer-grade-revised.json',{})
    assert read_grade(trace)['binding_status']=='invalid'


@pytest.mark.parametrize('verdict',[True,False,None])
def test_normal_v1_keeps_claims_and_extractor_contract(tmp_path,verdict):
    trace,root=fixture(tmp_path);path=trace/FILENAME;data=json.loads(path.read_text())
    data.update(schema=SCHEMA,structured_claims_correct=verdict,claims={},requirements={'fact':verdict},
        extractor={'model':'fixture','provider':'fixture','version':'fixture'})
    save(path,data);grade=read_grade(trace)
    assert grade['binding_status']=='verified' and grade['structured_claims_correct'] is verdict
    data['claims']=None;save(path,data);assert read_grade(trace)['binding_status']=='invalid'


def test_list_sidecar_with_revision_is_invalid_not_exception(tmp_path):
    trace,root=fixture(tmp_path);save(trace/FILENAME,[])
    save(trace/'derived-answer-grade-revised.json',{})
    assert read_grade(trace)['binding_status']=='invalid'


@pytest.mark.parametrize('name',[FILENAME,'native-grade.json'])
def test_fifo_is_rejected_before_any_stream_hash_or_json_read(tmp_path,name):
    import os, subprocess, sys
    trace,root=fixture(tmp_path);path=(trace if name==FILENAME else root)/name
    path.unlink();os.mkfifo(path)
    # A regression must fail this test by timeout, not hang the fixture suite.
    module_root=Path(__file__).resolve().parents[1]
    code="import sys,json,pathlib;path=pathlib.Path(sys.argv[1])/'scripts/trace_grades.py';ns={'__file__':str(path),'__name__':'fixture_reader'};exec(compile(path.read_bytes(),str(path),'exec'),ns);print(json.dumps(ns['read_grade'](sys.argv[2])))"
    result=subprocess.run([sys.executable,'-I','-B','-c',code,str(module_root),str(trace)],
        capture_output=True,text=True,timeout=2,check=True)
    assert json.loads(result.stdout)['binding_status']=='invalid'


@pytest.mark.parametrize('control',['episode_null','source_null','all_null',
    'missing_count','bool_count','changed_count','missing_goal','binding_digest',
    'returned_grading','missing_grading','cleanup_extra','policy_extra','returned_incomplete'])
def test_digest_and_actual_capture_bindings_cannot_be_rebound_away(tmp_path,control):
    trace,root=fixture(tmp_path)
    if control in ('episode_null','source_null','all_null'):
        side=json.loads((trace/FILENAME).read_text())
        if control=='episode_null':side['episode_artifact_sha256']['natural-answer.json']=None
        elif control=='source_null':side['source_artifact_sha256']['policy-result.json']=None
        else:
            terminal=json.loads((root/'terminal-evidence.json').read_text())
            for role in terminal['artifacts'].values():role['sha256']=None
            save(root/'terminal-evidence.json',terminal)
            cleanup=json.loads((root/'cleanup-receipt.json').read_text())
            cleanup.update(policy_result_sha256=None,episode_before_finalization_sha256=None)
            save(root/'cleanup-receipt.json',cleanup)
            native=json.loads((root/'native-grade.json').read_text())
            native.update(terminal_evidence=terminal,terminal_evidence_digest=digest(terminal))
            save(root/'native-grade.json',native)
            side['episode_artifact_sha256']={k:None for k in side['episode_artifact_sha256']}
            side['source_artifact_sha256']={k:None for k in side['source_artifact_sha256']}
            side['native_grade_artifact']['sha256']=None
        save(trace/FILENAME,side)
    else:
        before=json.loads((root/'before-finalization/episode.json').read_text())
        if control in ('missing_count','bool_count','changed_count','missing_goal','binding_digest'):
            binding=before['grading']['binding']
            if control=='missing_count':binding.pop('initial_chat_messages_excluded')
            elif control=='bool_count':binding['initial_chat_messages_excluded']=True
            elif control=='changed_count':binding['initial_chat_messages_excluded']=3
            elif control=='missing_goal':binding.pop('goal_sha256')
            before['grading']['binding_sha256']=digest(binding) if control!='binding_digest' else '0'*64
            save(root/'before-finalization/episode.json',before)
            policy=json.loads((root/'policy-result.json').read_text())
            policy['summary']['grading']=deepcopy(before['grading']);save(root/'policy-result.json',policy)
        elif control in ('returned_grading','policy_extra','returned_incomplete'):
            policy=json.loads((root/'policy-result.json').read_text())
            if control=='returned_grading':policy['summary']['grading']['binding']['initial_chat_messages_excluded']=9
            elif control=='policy_extra':policy['unbound']=True
            else:policy['summary']['trace_complete']=False
            save(root/'policy-result.json',policy)
        elif control=='missing_grading':
            before.pop('grading');save(root/'before-finalization/episode.json',before)
        else:
            cleanup=json.loads((root/'cleanup-receipt.json').read_text());cleanup['extra']=True
            save(root/'cleanup-receipt.json',cleanup)
        seal(trace,root)
    assert read_grade(trace)['binding_status']=='invalid'
