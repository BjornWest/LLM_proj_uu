"""Unrun synthetic publisher controls; these fixtures grant no live authority."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import pytest

from environments.website_world.compound_answer_delivery_v1 import SCHEMA as ANSWER_SCHEMA, SOURCE
from environments.website_world.compound_missing_output_v1 import (
    BOUND_FILES, SCHEMA, VERSION, build_sidecar, publish, terminal_digest,
)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')


def digest(path): return sha256(path.read_bytes()).hexdigest()
def pin(path): return {'path':str(path), 'sha256':digest(path)}


@pytest.fixture
def records(tmp_path):
    trace, root = tmp_path/'synthetic-episode', tmp_path/'synthetic-run'
    trace.mkdir(); root.mkdir()
    stop = 'max_steps'
    natural = {'schema_version':ANSWER_SCHEMA, 'source':SOURCE, 'text':None,
               'assistant_messages':[], 'stop_reason':stop, 'initial_chat_messages_excluded':2,
               'technical_error':None, 'correctness':None}
    before = {'trace_complete':True, 'error':None, 'execution_error':None, 'cleanup_errors':[],
              'stop_reason':stop, 'terminated':False, 'truncated':True}
    for name in BOUND_FILES: write(trace/name, {})
    write(trace/'natural-answer.json', natural)
    write(trace/'episode.json', {**before, 'infrastructure_completed':True, 'grading_error':None})
    write(trace/'evaluation.json', {'task_completed':False, 'safe_success':False})
    write(root/'before-finalization/episode.json', before)
    write(root/'before-finalization/evaluation.json', {'task_completed':None, 'safe_success':None})
    policy = {key:value for key,value in before.items() if key!='trace_complete'}
    write(root/'policy-result.json', {'trace':str(trace), 'summary':policy})
    contract = 'synthetic-missing-output-contract'
    cleanup = {'schema':'catalog-compare-review-cleanup-v1', 'episode_id':trace.name,
               'contract_id':contract, 'policy_closed':True, 'runtime_closed':True, 'errors':[],
               'policy_result_sha256':digest(root/'policy-result.json'),
               'episode_before_finalization_sha256':digest(root/'before-finalization/episode.json')}
    write(root/'cleanup-receipt.json', cleanup)
    inputs = {}
    for role in ('world','task','reference','surrounding','bindings','site_registry'):
        path=root/'synthetic-inputs'/f'{role}.json';write(path, {'synthetic_only':role});inputs[role]=pin(path)
    source_file=root/'synthetic-callback-source.py';source_file.write_text('# synthetic fixture, no authority\n')
    source_files={str(source_file):digest(source_file)}
    binding={'native_task_id':'synthetic-native', 'public_task_id':'synthetic-public',
             'contract_id':contract, 'input_files':inputs, 'source_files':source_files}
    artifacts = {'natural_answer':pin(trace/'natural-answer.json'),
                 'episode_before_finalization':pin(root/'before-finalization/episode.json'),
                 'evaluation_before_finalization':pin(root/'before-finalization/evaluation.json'),
                 'policy_result':pin(root/'policy-result.json'), 'cleanup_receipt':pin(root/'cleanup-receipt.json')}
    evidence={'schema':'catalog-compare-review-missing-answer-terminal-v1',
              'episode_id':trace.name, 'binding':binding, 'artifacts':artifacts}
    write(root/'terminal-evidence.json', evidence)
    reference={'synthetic_only':'é'}
    grade={'grading_version':VERSION,'outcome_kind':'required_answer_not_delivered',
           'task_completed':False,'structured_claims_correct':False,'claims':None,'extraction_requests':0,
           'additional_checks':{},'derivations':[],'selected_candidate_assessment':None,
           'oracle_grade':{'requirements':{'answer_delivered':False}},'stop_reason':stop,
           'terminal_evidence':evidence,'terminal_evidence_digest':terminal_digest(evidence),
           'native_reference':reference,'oracle_answer':reference,'limitations':['Synthetic test only.']}
    def seal(value=grade):
        write(root/'native-grade.json', value)
        automatic_binding={'task_id':'synthetic-public', 'initial_chat_messages_excluded':2,
                           'reference_files':{p['path']:p['sha256'] for p in inputs.values()},
                           'source_files':source_files}
        write(trace/'automatic-grade.json', {'schema':'automatic-episode-grading-v1', 'episode_id':trace.name,
              'contract_id':contract,
              'binding_sha256':terminal_digest(automatic_binding), 'raw_grade':{'native_grade':value}})
        proof={'schema':'automatic-grade-projection-v1','episode_id':trace.name, 'verified':True,
               'evaluation_sha256':digest(trace/'evaluation.json')}
        write(trace/'automatic-grade-projection.json',proof)
        declaration={'schema':'automatic-episode-grading-v1','episode_id':trace.name,
              'contract_id':contract,'status':'graded','phase':'external','infrastructure_complete':True,
              'grade_artifact':'automatic-grade.json','projection_artifact':'automatic-grade-projection.json',
              'projection_sha256':digest(trace/'automatic-grade-projection.json'),
              'grade_sha256':digest(trace/'automatic-grade.json'), 'binding':automatic_binding,
              'binding_sha256':terminal_digest(automatic_binding)}
        write(trace/'automatic-grading.json', declaration)
        write(trace/'episode.json', {**before,'infrastructure_completed':True,'grading_error':None,
                                    'success':False,'grading':declaration,
                                    'evaluation':json.loads((trace/'evaluation.json').read_bytes())})
    seal()
    return {'trace':trace, 'root':root, 'contract':contract, 'grade':grade, 'seal':seal}


def build(record):
    return build_sidecar(trace=record['trace'], source_directory=record['root'], contract_id=record['contract'])


def test_missing_output_has_no_formatter_claims_or_usage(records):
    value=build(records)
    assert value['schema']==SCHEMA and value['task_completed'] is False
    assert value['claims'] is None and value['extractor'] is None
    assert value['extraction_requests']==0 and value['safe_success'] is None
    assert value['requirements']=={'answer_delivered':False}
    assert 'terminal_evidence' not in value and 'native_reference' not in value
    assert not list(records['root'].rglob('*usage*'))


@pytest.mark.parametrize('field,value', [('task_completed',True),('structured_claims_correct',True),
    ('claims',{}),('extraction_requests',True),('extraction_requests',1),('derivations',[{}]),
    ('additional_checks',{'price':False}),('selected_candidate_assessment',{}),
    ('outcome_kind','ordinary_failed_answer')])
def test_outcome_contradictions_are_rejected(records,field,value):
    grade=deepcopy(records['grade']);grade[field]=value;records['seal'](grade)
    with pytest.raises(ValueError):build(records)


def test_compact_semantic_digest_is_distinct_from_pretty_file_hash(records):
    grade=deepcopy(records['grade'])
    assert grade['terminal_evidence_digest']!=digest(records['root']/'terminal-evidence.json')
    grade['terminal_evidence_digest']=sha256(json.dumps(grade['terminal_evidence'],sort_keys=True).encode()).hexdigest()
    records['seal'](grade)
    with pytest.raises(ValueError):build(records)


@pytest.mark.parametrize('name', ['policy-result.json','cleanup-receipt.json',
                                'before-finalization/episode.json','before-finalization/evaluation.json'])
def test_actual_terminal_byte_drift_is_rejected(records,name):
    path=records['root']/name;path.write_text(path.read_text()+' ')
    with pytest.raises(ValueError):build(records)


def test_automatic_capture_prefix_drift_is_rejected(records):
    path=records['trace']/'automatic-grading.json';value=json.loads(path.read_bytes())
    value['binding']['initial_chat_messages_excluded']=3
    value['binding_sha256']=terminal_digest(value['binding']);write(path,value)
    with pytest.raises(ValueError):build(records)


def test_native_oracle_is_never_treated_as_agent_claim(records):
    grade=deepcopy(records['grade']);grade['oracle_answer']={'synthetic_only':'different'}
    records['seal'](grade)
    with pytest.raises(ValueError):build(records)


@pytest.mark.parametrize('field,value', [('task_completed',True),('safe_success',True),
                                       ('technical_error','projection failed')])
def test_canonical_failure_must_agree_with_native_delivery_outcome(records,field,value):
    path=records['trace']/'evaluation.json';evaluation=json.loads(path.read_bytes())
    evaluation[field]=value;write(path,evaluation)
    with pytest.raises(ValueError):build(records)


def test_exclusive_publication_preserves_first_sidecar(records):
    path=publish(trace=records['trace'],source_directory=records['root'],contract_id=records['contract'])
    original=path.read_bytes()
    with pytest.raises(FileExistsError):
        publish(trace=records['trace'],source_directory=records['root'],contract_id=records['contract'])
    assert path.read_bytes()==original


def test_symlink_parent_is_rejected(records,tmp_path):
    alias=tmp_path/'alias';alias.symlink_to(records['root'],target_is_directory=True)
    with pytest.raises(ValueError):
        build_sidecar(trace=records['trace'],source_directory=alias,contract_id=records['contract'])


def test_existing_revision_is_never_rebound(records):
    write(records['trace']/'derived-answer-grade-revised.json', {'preserved':True})
    with pytest.raises(ValueError):
        publish(trace=records['trace'],source_directory=records['root'],contract_id=records['contract'])


@pytest.mark.parametrize('name,field,value', [
    ('automatic-grading.json','episode_id','foreign'),
    ('automatic-grade.json','schema','unknown'),
    ('automatic-grade-projection.json','evaluation_sha256','0'*64),
    ('episode.json','grading',{}),('episode.json','evaluation',{}),
    ('automatic-grade-projection.json','verified',False)])
def test_automatic_finalization_and_projection_are_bound(records,name,field,value):
    path=records['trace']/name;record=json.loads(path.read_bytes());record[field]=value;write(path,record)
    with pytest.raises(ValueError):build(records)


@pytest.mark.parametrize('name', ['synthetic-inputs/world.json','synthetic-callback-source.py',
                                'automatic-grading.json','automatic-grade.json','automatic-grade-projection.json'])
def test_nested_dependencies_are_rechecked_before_link(records,monkeypatch,name):
    from environments.website_world import compound_missing_output_v1 as publisher
    original=publisher.json.dump
    target=(records['trace'] if name.startswith('automatic-') else records['root'])/name
    def mutate_after_serialization(*args,**kwargs):
        result=original(*args,**kwargs);target.write_text(target.read_text()+' ');return result
    monkeypatch.setattr(publisher.json,'dump',mutate_after_serialization)
    with pytest.raises(ValueError):
        publish(trace=records['trace'],source_directory=records['root'],contract_id=records['contract'])
    assert not (records['trace']/'derived-answer-grade.json').exists()
