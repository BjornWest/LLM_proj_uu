"""Synthetic native terminal controls; fixtures never issue live authority."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import pytest

from . import compound_missing_answer_native_v1 as native


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False))


def pin(path):
    return {'path': str(path), 'sha256': sha256(path.read_bytes()).hexdigest()}


@pytest.fixture
def case(tmp_path):
    root = tmp_path / 'run'; trace = root / 'runs' / 'episode'
    task = {'task_id': 'native', 'user_message': 'Compare these models.', 'memories': []}
    reference = {'task_id': 'native', 'truth': 3}
    inputs = {'world': {'id': 'world'}, 'task': task, 'reference': reference,
              'surrounding': {}, 'bindings': {}, 'site_registry': {}}
    files = {}
    for name, value in inputs.items():
        p = root / 'inputs' / (name + '.json'); write(p, value); files[name] = pin(p)
    public = {**task, 'environment_context': {'scenario_date': '2026-09-30'}}
    write(trace / 'policy-task.json', public)
    plan = {'schema': 'website-catalog-compare-review-execution-v1',
            'runner_options': {'max_steps': 2, 'max_input_tokens': 500}}
    write(root / 'execution-plan.private.json', plan)
    paths = [Path(native.__file__).absolute(), trace / 'policy-task.json', root / 'execution-plan.private.json']
    sources = {str(p): pin(p)['sha256'] for p in paths}
    goal = (public['user_message'] + '\n\nSAVED USER MEMORIES:\n' + json.dumps(public['memories'], ensure_ascii=False, sort_keys=True)
            + '\n\nENVIRONMENT CONTEXT:\n' + json.dumps(public['environment_context'], ensure_ascii=False, sort_keys=True))
    actual = {'task_id': 'native', 'goal_sha256': sha256(goal.encode()).hexdigest(),
              'initial_chat_messages_excluded': 2, 'source_files': sources,
              'reference_files': {v['path']: v['sha256'] for v in files.values()}}
    grading = {'schema': 'automatic-episode-grading-v1', 'episode_id': 'episode',
               'contract_id': 'contract', 'phase': 'external', 'status': 'pending_external',
               'binding': actual, 'binding_sha256': native.digest(actual), 'infrastructure_complete': False}
    before = {'stop_reason': 'max_steps', 'trace_complete': True, 'recording_error': None,
              'error': None, 'execution_error': None, 'grading_error': None, 'cleanup_errors': [],
              'terminated': False, 'truncated': True, 'step_count': 2, 'max_input_tokens': 500, 'grading': grading}
    evaluation = {'schema_version': 1, 'verifier': 'automatic-grading-pending', 'verifier_version': '1',
                  'trust': 'pending_external', 'task_completed': None, 'authorization_satisfied': None,
                  'unauthorized_effects': None, 'injection_exposed': None, 'injection_avoided': None,
                  'technical_error': None, 'evidence': [],
                  'limitations': ['Native automatic grading is pending external finalization.'], 'safe_success': None}
    before.update(evaluation=evaluation, evaluation_file='evaluation.json')
    natural = {'schema_version': 'connected-world-manual-v1',
               'source': 'BrowserGym chat from executed send_msg_to_user; no extraction or repair',
               'text': None, 'assistant_messages': [], 'stop_reason': 'max_steps',
               'initial_chat_messages_excluded': 2, 'technical_error': None, 'correctness': None}
    write(trace / 'natural-answer.json', natural)
    write(root / 'before-finalization/episode.json', before)
    write(root / 'before-finalization/evaluation.json', evaluation)
    write(root / 'policy-result.json', {'trace': str(trace), 'summary': deepcopy(before)})
    cleanup = {'schema': 'catalog-compare-review-cleanup-v1', 'episode_id': 'episode',
               'contract_id': 'contract', 'policy_closed': True, 'runtime_closed': True, 'errors': [],
               'policy_result_sha256': pin(root / 'policy-result.json')['sha256'],
               'episode_before_finalization_sha256': pin(root / 'before-finalization/episode.json')['sha256']}
    write(root / 'cleanup-receipt.json', cleanup)
    evidence = {'schema': native.WIRE, 'episode_id': 'episode',
                'binding': {'native_task_id': 'native', 'public_task_id': 'native', 'contract_id': 'contract',
                            'input_files': files, 'source_files': sources},
                'artifacts': {'natural_answer': pin(trace / 'natural-answer.json'),
                             **{role: pin(root / name) for role, name in native.ROLES.items()}}}
    return {'root': root, 'trace': trace, 'task': task, 'reference': reference, 'inputs': inputs,
            'evidence': evidence, 'before': before, 'natural': natural, 'cleanup': cleanup}


def invoke(c, **kwargs):
    return native.grade_missing_answer(c['evidence'], task=c['task'], reference=c['reference'],
        response_contract={'required_obligations': ['fact', 'review']},
        expected_input_digests={k: native.input_digest(v) for k, v in c['inputs'].items()}, **kwargs)


def refresh(c):
    root = c['root']
    write(c['trace'] / 'natural-answer.json', c['natural'])
    write(root / 'before-finalization/episode.json', c['before'])
    write(root / 'policy-result.json', {'trace': str(c['trace']), 'summary': deepcopy(c['before'])})
    c['cleanup']['policy_result_sha256'] = pin(root / 'policy-result.json')['sha256']
    c['cleanup']['episode_before_finalization_sha256'] = pin(root / 'before-finalization/episode.json')['sha256']
    write(root / 'cleanup-receipt.json', c['cleanup'])
    for role, old in c['evidence']['artifacts'].items():
        c['evidence']['artifacts'][role] = pin(Path(old['path']))


@pytest.mark.parametrize('stop', ['max_steps', 'max_input_tokens', 'agent_finished'])
def test_clean_missing_output(case, stop):
    case['before']['stop_reason'] = case['natural']['stop_reason'] = stop
    case['before']['truncated'] = stop != 'agent_finished'
    refresh(case)
    result = invoke(case)
    assert result['task_completed'] is False and result['claims'] is None
    assert result['extraction_requests'] == 0 and result['stop_reason'] == stop
    assert result['oracle_grade']['requirements'] == {'answer_delivered': False}
    assert result['native_reference'] == result['oracle_answer'] == case['reference']
    assert result['terminal_evidence_digest'] == native.digest(case['evidence'])
    assert 'native_subreports' not in result


@pytest.mark.parametrize('key,value', [('trace_complete', False), ('recording_error', 'lost'),
    ('error', 'provider'), ('execution_error', 'error'), ('grading_error', 'failure'),
    ('cleanup_errors', [{'phase': 'runtime', 'error': 'failed'}]), ('terminated', True),
    ('truncated', False), ('step_count', True), ('step_count', 1),
    ('max_input_tokens', True), ('stop_reason', 'environment_truncated'), ('stop_reason', 'interrupted')])
def test_terminal_corruptions(case, key, value):
    case['before'][key] = value
    if key == 'stop_reason': case['natural'][key] = value
    refresh(case)
    with pytest.raises(ValueError): invoke(case)


@pytest.mark.parametrize('key,value', [('technical_error', 'failure'), ('initial_chat_messages_excluded', True),
    ('initial_chat_messages_excluded', 3), ('schema_version', 'foreign'), ('source', 'reasoning'),
    ('correctness', True), ('text', ''), ('assistant_messages', ['earlier answer'])])
def test_answer_corruptions(case, key, value):
    case['natural'][key] = value; refresh(case)
    with pytest.raises(ValueError): invoke(case)


def test_prior_nonempty_reply_is_not_absence(case):
    case['natural'].update(assistant_messages=['earlier answer', ''], text='')
    refresh(case)
    with pytest.raises(ValueError): invoke(case)


def test_whitespace_messages_are_absence(case):
    case['natural'].update(assistant_messages=[' ', '\n'], text='\n'); refresh(case)
    assert invoke(case)['claims'] is None


@pytest.mark.parametrize('key,value', [('goal_sha256', '0' * 64), ('initial_chat_messages_excluded', True),
    ('initial_chat_messages_excluded', 3), ('task_id', 'other'), ('source_files', {}), ('reference_files', {})])
def test_actual_binding_corruptions(case, key, value):
    record = case['before']['grading'];record['binding'][key] = value
    record['binding_sha256'] = native.digest(record['binding']);refresh(case)
    with pytest.raises(ValueError): invoke(case)


@pytest.mark.parametrize('role', sorted(native.INPUTS))
def test_rehashed_foreign_input_not_bound_to_constructor(case, role):
    old = case['evidence']['binding']['input_files'][role]; p = Path(old['path'])
    write(p, {'foreign': role});case['evidence']['binding']['input_files'][role] = pin(p)
    case['before']['grading']['binding']['reference_files'][str(p)] = pin(p)['sha256']
    case['before']['grading']['binding_sha256'] = native.digest(case['before']['grading']['binding']);refresh(case)
    with pytest.raises(ValueError): invoke(case)


@pytest.mark.parametrize('key,value', [('policy_closed', False), ('runtime_closed', False),
    ('policy_closed', 1), ('errors', ['late']), ('contract_id', 'other'), ('schema', 'other')])
def test_cleanup_corruptions(case, key, value):
    case['cleanup'][key] = value;refresh(case)
    with pytest.raises(ValueError): invoke(case)


def test_digest_conventions_distinct():
    value = {'label': 'é', 'nested': [None, False]}
    assert native.digest(value) != native.input_digest(value)


def test_stale_pin_and_symlink_reject(case):
    path = Path(case['evidence']['artifacts']['cleanup_receipt']['path'])
    path.write_text('{}')
    with pytest.raises(ValueError): invoke(case)
    original = path.with_name('preserved.json');path.rename(original);path.symlink_to(original)
    case['evidence']['artifacts']['cleanup_receipt']['sha256'] = pin(original)['sha256']
    with pytest.raises(ValueError): invoke(case)


def repin_role(case, role):
    old = case['evidence']['artifacts'][role]
    case['evidence']['artifacts'][role] = pin(Path(old['path']))


@pytest.mark.parametrize('key,value', [('schema_version', True), ('verifier', 'other'),
    ('verifier_version', '2'), ('trust', 'native_reference'), ('task_completed', True),
    ('task_completed', False), ('authorization_satisfied', True), ('technical_error', 'failure'),
    ('safe_success', False), ('limitations', 'not a list')])
def test_canonical_pending_evaluation_corruptions(case, key, value):
    value_record = deepcopy(case['before']['evaluation']);value_record[key] = value
    case['before']['evaluation'] = value_record;refresh(case)
    write(case['root'] / 'before-finalization/evaluation.json', value_record)
    repin_role(case, 'evaluation_before_finalization')
    with pytest.raises(ValueError): invoke(case)


@pytest.mark.parametrize('record', [{}, {'technical_error': None}])
def test_missing_canonical_shape(case, record):
    write(case['root'] / 'before-finalization/evaluation.json', record)
    repin_role(case, 'evaluation_before_finalization')
    with pytest.raises(ValueError): invoke(case)


def test_episode_canonical_evaluation_disagreement(case):
    case['before']['evaluation']['limitations'] = ['changed'];refresh(case)
    with pytest.raises(ValueError): invoke(case)


@pytest.mark.parametrize('where,key,value', [('grading', 'status', 'failed'), ('grading', 'error', 'failure'),
    ('grading', 'error', ''), ('grading', 'infrastructure_complete', True),
    ('summary', 'grading_error', 'failure'), ('summary', 'evaluation_file', 'foreign.json')])
def test_independent_returned_summary_corruptions(case, where, key, value):
    p = case['root'] / 'policy-result.json';data = json.loads(p.read_bytes())
    (data['summary']['grading'] if where == 'grading' else data['summary'])[key] = value
    write(p, data);case['cleanup']['policy_result_sha256'] = pin(p)['sha256']
    write(case['root'] / 'cleanup-receipt.json', case['cleanup'])
    repin_role(case, 'policy_result');repin_role(case, 'cleanup_receipt')
    with pytest.raises(ValueError): invoke(case)


@pytest.mark.parametrize('name', ['execution-plan.private.json', 'policy-task.json'])
def test_bound_budget_and_public_capture_required(case, name):
    path = case['root'] / name if name == 'execution-plan.private.json' else case['trace'] / name
    case['evidence']['binding']['source_files'].pop(str(path))
    case['before']['grading']['binding_sha256'] = native.digest(case['before']['grading']['binding']);refresh(case)
    with pytest.raises(ValueError): invoke(case)


def test_overflowing_recorded_number_rejects(case):
    p = case['root'] / 'before-finalization/evaluation.json'
    p.write_text('{"technical_error":null,"unused":1e400}')
    repin_role(case, 'evaluation_before_finalization')
    with pytest.raises(ValueError, match='Nonfinite'): invoke(case)


def test_parent_symlink_rejects(case):
    directory = case['root'] / 'before-finalization';saved = case['root'] / 'preserved'
    directory.rename(saved);directory.symlink_to(saved, target_is_directory=True)
    with pytest.raises(ValueError): invoke(case)


def test_normalized_path_required(case):
    record = case['evidence']['artifacts']['natural_answer']
    record['path'] = str(case['trace']) + '/../episode/natural-answer.json'
    with pytest.raises(ValueError): invoke(case)


def test_accepted_public_adaptation_joins_all_four_inputs(case):
    public = {**case['task'], 'task_id': 'accepted-public', 'user_message': 'What do reviews and retailers say?',
              'environment_context': {'scenario_date': '2026-09-30'}}
    values = {role: {'role': role, 'accepted': True} for role in native.ADAPTED}
    for role, value in values.items():
        p = case['root'] / 'inputs' / (role + '.json');write(p, value)
        case['evidence']['binding']['input_files'][role] = pin(p)
        case['before']['grading']['binding']['reference_files'][str(p)] = pin(p)['sha256']
    p = case['trace'] / 'policy-task.json';write(p, public)
    case['evidence']['binding']['source_files'][str(p)] = pin(p)['sha256']
    case['evidence']['binding']['public_task_id'] = public['task_id']
    actual = case['before']['grading']['binding'];actual['task_id'] = public['task_id']
    goal = public['user_message'] + '\n\nSAVED USER MEMORIES:\n[]\n\nENVIRONMENT CONTEXT:\n' + json.dumps(public['environment_context'], sort_keys=True)
    actual['goal_sha256'] = sha256(goal.encode()).hexdigest()
    case['before']['grading']['binding_sha256'] = native.digest(actual);refresh(case)
    signatures = {k: native.input_digest(v) for k, v in values.items()}
    assert invoke(case, expected_public=public, adapted_input_digests=signatures)['claims'] is None
    for role in native.ADAPTED:
        wrong = {**signatures, role: '0' * 64}
        with pytest.raises(ValueError): invoke(case, expected_public=public, adapted_input_digests=wrong)


@pytest.mark.parametrize('where', ['before', 'returned'])
@pytest.mark.parametrize('version', [True, 1.0])
def test_embedded_canonical_schema_type_must_match(case, where, version):
    if where == 'before':
        case['before']['evaluation']['schema_version'] = version;refresh(case)
    else:
        p = case['root'] / 'policy-result.json';record = json.loads(p.read_bytes())
        record['summary']['evaluation']['schema_version'] = version;write(p, record)
        case['cleanup']['policy_result_sha256'] = pin(p)['sha256']
        write(case['root'] / 'cleanup-receipt.json', case['cleanup'])
        repin_role(case, 'policy_result');repin_role(case, 'cleanup_receipt')
    with pytest.raises(ValueError): invoke(case)


def test_same_named_trace_outside_run_root_rejects(case):
    old = case['trace'];foreign = case['root'] / 'foreign' / old.name
    foreign.parent.mkdir();old.rename(foreign);case['trace'] = foreign
    sources = case['evidence']['binding']['source_files'];sources.pop(str(old / 'policy-task.json'))
    sources[str(foreign / 'policy-task.json')] = pin(foreign / 'policy-task.json')['sha256']
    case['before']['grading']['binding_sha256'] = native.digest(case['before']['grading']['binding'])
    case['evidence']['artifacts']['natural_answer'] = pin(foreign / 'natural-answer.json');refresh(case)
    with pytest.raises(ValueError, match='confined'): invoke(case)
