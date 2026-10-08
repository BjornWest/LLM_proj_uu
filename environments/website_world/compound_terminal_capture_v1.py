"""Prepared missing-answer terminal capture for the accepted live callback.

Caller must actually close policy and Runtime and check the pinned native/public
inputs and callback sources. This helper stores observations, never issues
cleanup authority from caller flags and never reconstructs a historical run.
No execution consumer installs this draft yet.
"""
from hashlib import sha256
import json
from pathlib import Path

from .compound_answer_delivery_v1 import select_answer_path
from .compound_missing_output_v1 import terminal_digest


def _file(path):
    path = Path(path)
    if not path.is_absolute() or any(parent.is_symlink() for parent in (path, *path.parents)) or not path.is_file():
        raise ValueError('Require real absolute file without symlink substitution')
    return path


def _pin(path):
    path = _file(path)
    return {'path':str(path), 'sha256':sha256(path.read_bytes()).hexdigest()}


def _parse(payload):
    def constant(value): raise ValueError('Nonfinite terminal value '+value)
    def pairs(items):
        value={}
        for key,item in items:
            if key in value: raise ValueError('Duplicate terminal JSON field')
            value[key]=item
        return value
    return json.loads(payload, object_pairs_hook=pairs, parse_constant=constant)


def _load(path):
    return _parse(_file(path).read_bytes())


def bind_capture_artifacts(*, source_files, execution_plan_pin, policy_task_path, expected_public):
    """Bind creation-pinned budget and actual prepared public task before dispatch.

    execution_plan_pin must be retained when the caller writes its real plan.
    This function must not obtain a fresh budget baseline from current metadata.
    It adds neither inference nor an independent authority mechanism.
    """
    if (type(source_files) is not dict or type(execution_plan_pin) is not dict
            or set(execution_plan_pin) != {'path', 'sha256'}
            or type(execution_plan_pin['sha256']) is not str
            or len(execution_plan_pin['sha256']) != 64
            or any(c not in '0123456789abcdef' for c in execution_plan_pin['sha256'])
            or type(expected_public) is not dict):
        raise ValueError('Require actual source union, retained creation pin and expected public task')
    plan = _pin(execution_plan_pin['path'])
    if plan != execution_plan_pin:
        raise ValueError('Finite execution plan changed after creation')
    public_path = _file(policy_task_path)
    if public_path == Path(plan['path']):
        raise ValueError('Execution budget and public task alias one file')
    payload = public_path.read_bytes()
    if terminal_digest(_parse(payload)) != terminal_digest(expected_public):
        raise ValueError('Prepared actual public task differs from bound task')
    public = {'path':str(public_path),'sha256':sha256(payload).hexdigest()}
    additions = {plan['path']:plan['sha256'],public['path']:public['sha256']}
    for path, expected in additions.items():
        if path in source_files and source_files[path] != expected:
            raise ValueError('Capture pin conflicts with retained source union')
        if _pin(path)['sha256'] != expected:
            raise ValueError('Capture file changed before prospective bind')
    source_files.update(additions)
    return additions


def _write(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)


def capture_terminal(*, trace, run_root, native_task_id, public_task_id, contract_id,
                     input_files, source_files, actual_goal_sha256, actual_initial_count):
    """Capture once from the actual callback after its successful context exits.

    The goal/count arguments come from the accepted task's retained live bind
    closure, not configuration constants or caller-prepared metadata. Native
    grading subsequently validates the terminal and full source-bound lifecycle.
    """
    trace, root = Path(trace).absolute(), Path(run_root).absolute()
    if (any(type(value) is not str or not value for value in (native_task_id,public_task_id,contract_id))
            or type(actual_initial_count) is not int or actual_initial_count < 0
            or type(actual_goal_sha256) is not str or len(actual_goal_sha256)!=64
            or any(c not in '0123456789abcdef' for c in actual_goal_sha256)):
        raise ValueError('Require actual nonempty task/contract and capture identities')
    required={'world','task','reference','surrounding','bindings','site_registry'}
    if type(input_files) is not dict or not required <= set(input_files) or type(source_files) is not dict or not source_files:
        raise ValueError('Require complete checked native input and callback source union')
    inputs={role:_pin(path) for role,path in input_files.items()}
    for path,expected in source_files.items():
        if _pin(path)['sha256']!=expected:raise ValueError('Callback source changed before capture')
    references={record['path']:record['sha256'] for record in inputs.values()}
    before=_load(trace/'episode.json');natural=_load(trace/'natural-answer.json')
    if select_answer_path(natural,before)!='missing_answer':
        raise ValueError('Capture is only for actually absent delivered answers')
    record=before.get('grading')
    if (type(record) is not dict or record.get('schema')!='automatic-episode-grading-v1'
            or record.get('episode_id')!=trace.name or record.get('contract_id')!=contract_id
            or record.get('phase')!='external' or record.get('status')!='pending_external'
            or type(record.get('binding')) is not dict):
        raise ValueError('Require the attached prospective pending external grader')
    binding=record['binding']
    if (record.get('binding_sha256')!=terminal_digest(binding)
            or binding.get('task_id')!=public_task_id or binding.get('goal_sha256')!=actual_goal_sha256
            or type(binding.get('initial_chat_messages_excluded')) is not int
            or binding['initial_chat_messages_excluded']!=actual_initial_count
            or natural['initial_chat_messages_excluded']!=actual_initial_count
            or binding.get('reference_files')!=references or binding.get('source_files')!=source_files):
        raise ValueError('Captured goal/count or native input/source union differs from actual bind')
    policy=_load(root/'policy-result.json')
    if type(policy) is not dict or set(policy)!= {'trace','summary'} or policy['trace']!=str(trace) or type(policy['summary']) is not dict:
        raise ValueError('Require the original returned trace/summary wrapper')
    returned=policy['summary']
    if (('trace_complete' in returned and returned['trace_complete'] is not True)
            or any(returned.get(key)!=before.get(key) for key in ('stop_reason','error','execution_error','cleanup_errors'))
            or type(returned.get('grading')) is not dict):
        raise ValueError('Actual returned policy summary disagrees with saved terminal')
    for key in ('schema','episode_id','contract_id','phase','binding','binding_sha256'):
        if terminal_digest(returned['grading'].get(key))!=terminal_digest(record.get(key)):
            raise ValueError('Returned policy grading identity/binding differs from captured terminal')
    evaluation_path=trace/'evaluation.json'
    if _load(evaluation_path).get('technical_error') is not None:
        raise ValueError('Pre-finalization canonical evaluation has a technical failure')
    # Exclusively retain original bytes before canonical external finalization.
    snapshots=root/'before-finalization';snapshots.mkdir(exist_ok=False)
    for name in ('episode.json','evaluation.json'):
        with (snapshots/name).open('xb') as stream:stream.write(_file(trace/name).read_bytes())
    cleanup={'schema':'catalog-compare-review-cleanup-v1','episode_id':trace.name,'contract_id':contract_id,
             'policy_closed':True,'runtime_closed':True,'errors':[],
             'policy_result_sha256':_pin(root/'policy-result.json')['sha256'],
             'episode_before_finalization_sha256':_pin(snapshots/'episode.json')['sha256']}
    _write(root/'cleanup-receipt.json',cleanup)
    evidence={'schema':'catalog-compare-review-missing-answer-terminal-v1','episode_id':trace.name,
              'binding':{'native_task_id':native_task_id,'public_task_id':public_task_id,'contract_id':contract_id,
                         'input_files':inputs,'source_files':dict(source_files)},
              'artifacts':{'natural_answer':_pin(trace/'natural-answer.json'),
                           'episode_before_finalization':_pin(snapshots/'episode.json'),
                           'evaluation_before_finalization':_pin(snapshots/'evaluation.json'),
                           'policy_result':_pin(root/'policy-result.json'),
                           'cleanup_receipt':_pin(root/'cleanup-receipt.json')}}
    _write(root/'terminal-evidence.json',evidence)
    return evidence
