"""Prepared synthetic capture controls; no native/callback authority is issued."""
from copy import deepcopy
import json

import pytest

from environments.website_world.compound_missing_output_v1 import terminal_digest
from environments.website_world.compound_terminal_capture_v1 import capture_terminal, bind_capture_artifacts
from environments.website_world.test_compound_missing_output_v1 import records, write


@pytest.fixture
def pending(records):
    trace,root=records['trace'],records['root']
    evidence=json.loads((root/'terminal-evidence.json').read_bytes())
    declaration=json.loads((trace/'automatic-grading.json').read_bytes())
    binding=declaration['binding'];binding['goal_sha256']='a'*64
    declaration.update(status='pending_external',infrastructure_complete=False,
                       binding_sha256=terminal_digest(binding))
    before=json.loads((root/'before-finalization/episode.json').read_bytes())
    before['grading']=declaration;write(trace/'episode.json',before)
    returned={key:value for key,value in before.items() if key!='trace_complete'}
    write(root/'policy-result.json',{'trace':str(trace),'summary':returned})
    write(trace/'evaluation.json',{'task_completed':None,'safe_success':None,'technical_error':None})
    # Only this fresh synthetic preparation is removed. No historical evidence.
    for path in (root/'before-finalization').iterdir():path.unlink()
    (root/'before-finalization').rmdir()
    (root/'terminal-evidence.json').unlink();(root/'cleanup-receipt.json').unlink()
    kwargs={'trace':trace,'run_root':root,'native_task_id':'synthetic-native',
            'public_task_id':'synthetic-public','contract_id':records['contract'],
            'input_files':{role:pin['path'] for role,pin in evidence['binding']['input_files'].items()},
            'source_files':evidence['binding']['source_files'],
            'actual_goal_sha256':'a'*64,'actual_initial_count':2}
    return kwargs


def test_capture_preserves_original_snapshot_bytes_and_exact_wire(pending):
    trace=pending['trace'];original=(trace/'episode.json').read_bytes()
    evidence=capture_terminal(**pending)
    assert (pending['run_root']/'before-finalization/episode.json').read_bytes()==original
    assert set(evidence)=={'schema','episode_id','binding','artifacts'}
    cleanup=json.loads((pending['run_root']/'cleanup-receipt.json').read_bytes())
    assert set(cleanup)=={'schema','episode_id','contract_id','policy_closed','runtime_closed','errors',
                         'policy_result_sha256','episode_before_finalization_sha256'}
    assert evidence==json.loads((pending['run_root']/'terminal-evidence.json').read_bytes())


@pytest.mark.parametrize('key,value',[('actual_initial_count',True),('actual_initial_count',3),
                                     ('actual_goal_sha256','b'*64),('public_task_id','foreign'),
                                     ('contract_id','foreign')])
def test_capture_requires_actual_task_bind_identity(pending,key,value):
    kwargs=dict(pending);kwargs[key]=value
    with pytest.raises(ValueError):capture_terminal(**kwargs)


def test_actual_returned_binding_drift_is_rejected(pending):
    path=pending['run_root']/'policy-result.json';policy=json.loads(path.read_bytes())
    policy['summary']['grading']['binding']['initial_chat_messages_excluded']=3
    policy['summary']['grading']['binding_sha256']=terminal_digest(policy['summary']['grading']['binding'])
    write(path,policy)
    with pytest.raises(ValueError):capture_terminal(**pending)


def test_source_drift_is_rejected_before_snapshot_creation(pending):
    path=next(iter(pending['source_files']));from pathlib import Path
    Path(path).write_text('# changed synthetic source\n')
    with pytest.raises(ValueError):capture_terminal(**pending)
    assert not (pending['run_root']/'before-finalization').exists()


def test_capture_is_exclusive_without_historical_reconstruction(pending):
    capture_terminal(**pending)
    with pytest.raises(FileExistsError):capture_terminal(**pending)


@pytest.fixture
def binding_files(tmp_path):
    from hashlib import sha256
    plan=tmp_path/'execution-plan.private.json'
    public=tmp_path/'policy-task.json'
    write(plan, {'runner_options':{'max_steps':40,'max_input_tokens':100000}})
    value={'task_id':'synthetic-public','user_message':'Synthetic test only','memories':{'flag':False}}
    write(public,value)
    return {'source_files':{},'execution_plan_pin':{'path':str(plan),'sha256':sha256(plan.read_bytes()).hexdigest()},
            'policy_task_path':public,'expected_public':value}


def test_bind_adds_actual_plan_and_prepared_public_byte_pins(binding_files):
    from hashlib import sha256
    result=bind_capture_artifacts(**binding_files)
    assert result==binding_files['source_files']
    for path,expected in result.items():
        from pathlib import Path
        assert sha256(Path(path).read_bytes()).hexdigest()==expected


def test_changed_budget_is_never_adopted_as_new_baseline(binding_files):
    from pathlib import Path
    path=Path(binding_files['execution_plan_pin']['path'])
    write(path, {'runner_options':{'max_steps':400,'max_input_tokens':100000}})
    with pytest.raises(ValueError,match='changed after creation'):bind_capture_artifacts(**binding_files)
    assert binding_files['source_files']=={}


def test_prepared_public_task_requires_exact_json_types(binding_files):
    altered=deepcopy(binding_files['expected_public']);altered['memories']['flag']=0
    write(binding_files['policy_task_path'],altered)
    with pytest.raises(ValueError):bind_capture_artifacts(**binding_files)
    assert binding_files['source_files']=={}


def test_budget_and_public_task_cannot_alias(binding_files):
    binding_files['policy_task_path']=binding_files['execution_plan_pin']['path']
    with pytest.raises(ValueError,match='alias'):bind_capture_artifacts(**binding_files)


@pytest.mark.parametrize('role',['execution_plan_pin','policy_task_path'])
def test_new_capture_binding_cannot_replace_existing_pin(binding_files,role):
    path=(binding_files[role]['path'] if role=='execution_plan_pin' else str(binding_files[role]))
    binding_files['source_files'][path]='0'*64
    original=dict(binding_files['source_files'])
    with pytest.raises(ValueError,match='conflicts'):bind_capture_artifacts(**binding_files)
    assert binding_files['source_files']==original


@pytest.mark.parametrize('role',['execution_plan_pin','policy_task_path'])
def test_bind_rejects_symlink_capture_files(binding_files,role,tmp_path):
    from pathlib import Path
    path=Path(binding_files[role]['path'] if role=='execution_plan_pin' else binding_files[role])
    alias=tmp_path/'alias';alias.symlink_to(path)
    if role=='execution_plan_pin':binding_files[role]['path']=str(alias)
    else:binding_files[role]=alias
    with pytest.raises(ValueError):bind_capture_artifacts(**binding_files)


@pytest.mark.parametrize('value',[True,'z'*64])
def test_creation_pin_digest_must_be_an_actual_sha256(binding_files,value):
    binding_files['execution_plan_pin']['sha256']=value
    with pytest.raises(ValueError):bind_capture_artifacts(**binding_files)
