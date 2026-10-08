"""Synthetic saved-output controls, no browser, grader or policy dispatch."""
import copy
import hashlib
import json

import pytest
from scripts import simulated_order_address_trace_grades as view


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False))
    return view.descriptor(path)


def fixture(tmp_path, verdict='pass'):
    root = tmp_path / 'episode-01'
    root.mkdir()
    task = {'task_id': 'task-01', 'delivery_address': {'recipient': 'Example', 'unit': '24'},
            'user_message': 'Please order the item in my cart.', 'memories': ['My address is Example.']}
    task_hash = hashlib.sha256(json.dumps(task, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    task_pin = save(tmp_path / 'simulated-order-task.private.json', task)
    ref = {'task_id': 'task-01', 'task_sha256': task_hash,
           'scoring_scope': view.NATIVE_SCOPE, 'expected_address': task['delivery_address']}
    reference_pin = save(tmp_path / 'order-address-reference.private.json', ref)
    verdict_value = {'pass': True, 'fail': False, 'inconclusive': None}[verdict]
    report = {'task_id': 'task-01', 'schema_version': view.VERSION,
        'scoring_scope': view.NATIVE_SCOPE, 'observation_rule': view.RULE,
        'verdict': verdict, 'address_correct': verdict_value,
        'components': {} if verdict == 'inconclusive' else {'address': {'checks': {'unit': verdict_value}}},
        'full_effects': 'unknown', 'full_order_completion': 'not_assessed',
        'limitations': ['Only address fields are scored.']}
    binding = {'task_id': 'task-01', 'scoring_scope': view.NATIVE_SCOPE,
        'observation_rule': view.RULE, 'reference_files': {
            task_pin['path']: task_pin['sha256'], reference_pin['path']: reference_pin['sha256']}}
    public = {'schema_version': 'connected-world-manual-v1', 'task_id': task['task_id'],
        'user_message': task['user_message'], 'memories': task['memories'],
        'environment_context': {'currency': 'SEK'}, 'start_url': 'https://example.test/#/cart'}
    goal = (public['user_message'] + '\n\nSAVED USER MEMORIES:\n' +
            json.dumps(public['memories'], ensure_ascii=False, sort_keys=True) +
            '\n\nENVIRONMENT CONTEXT:\n' +
            json.dumps(public['environment_context'], ensure_ascii=False, sort_keys=True))
    binding['goal_sha256'] = hashlib.sha256(goal.encode()).hexdigest()
    binding['public_task_sha256'] = hashlib.sha256(json.dumps(public, sort_keys=True,
        ensure_ascii=False, allow_nan=False).encode()).hexdigest()
    binding_hash = hashlib.sha256(json.dumps(binding, sort_keys=True, ensure_ascii=False,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    files = {name: save(root / name, {}) for name in view.legacy.BOUND_FILES}
    canonical = {'verifier': 'simulated-order-address-only', 'verifier_version': view.VERSION,
        'trust': 'native_reference', 'task_completed': verdict_value,
        'technical_error': None, 'authorization_satisfied': None, 'unauthorized_effects': None}
    files['evaluation.json'] = save(root / 'evaluation.json', canonical)
    files['task'], files['reference'] = task_pin, reference_pin
    raw = {'schema': 'automatic-episode-grading-v1', 'episode_id': root.name,
           'contract_id': view.CONTRACT, 'binding_sha256': binding_hash,
           'raw_grade': {'task_id': 'task-01', 'native_grade': report}}
    files['grade'] = save(root / 'automatic-grade.json', raw)
    proof = {'schema': 'automatic-grade-projection-v1', 'episode_id': root.name,
             'verified': True, 'evaluation_sha256': files['evaluation.json']['sha256']}
    files['projection'] = save(root / 'automatic-grade-projection.json', proof)
    manifest = {'schema': raw['schema'], 'status': 'graded', 'infrastructure_complete': True,
        'episode_id': root.name, 'contract_id': view.CONTRACT, 'binding': binding,
        'binding_sha256': binding_hash, 'grade_sha256': files['grade']['sha256'],
        'projection_sha256': files['projection']['sha256']}
    files['manifest'] = save(root / 'automatic-grading.json', manifest)
    files['metadata.json'] = save(root / 'metadata.json', {'episode_id': root.name})
    files['policy-task.json'] = save(root / 'policy-task.json', public)
    files['episode.json'] = save(root / 'episode.json', {'episode_id': root.name,
        'trace_complete': True, 'infrastructure_completed': True, 'grading_error': None,
        'grading': manifest, 'evaluation': canonical, 'error': None,
        'execution_error': None, 'cleanup_errors': []})
    capture = {'task_id': 'task-01', 'task_sha256': task_hash, 'episode_id': root.name,
        'main_trace_sha256': files['steps.jsonl']['sha256'], 'complete_effect_envelope': None,
        'full_effects': 'unknown', 'order_outcome_scored': False,
        'ledger': {}, 'checkout_storage': {}, 'artifacts': {'orders': {}, 'checkout_storage': {}}}
    for category in ('orders', 'checkout_storage'):
        for phase in ('before', 'after'):
            value = {'phase': phase}
            capture['ledger' if category == 'orders' else category][phase] = value
            capture['artifacts'][category][phase] = save(root / (category + '-' + phase + '.json'), value)
    files['capture'] = save(root / 'manual-review-private/order-address-evidence.private.json', capture)
    return root, {'files': files}, report


@pytest.mark.parametrize('verdict', ['pass', 'fail', 'inconclusive'])
def test_scope_and_verdict_are_saved_not_regraded(tmp_path, verdict):
    root, entry, _ = fixture(tmp_path, verdict)
    result = view.read_grade(root, entry)
    assert result['binding_status'] == 'verified'
    assert result['native_verdict'] == verdict
    assert result['full_order_completion'] == 'not_assessed'
    assert result['safe_success'] is None


@pytest.mark.parametrize('name', ['grade', 'manifest', 'projection', 'evaluation.json', 'task', 'capture', 'steps.jsonl'])
def test_late_artifact_drift_is_invalid(tmp_path, name):
    root, entry, _ = fixture(tmp_path)
    path = entry['files'][name]['path']
    with open(path, 'a') as file:
        file.write(' ')
    assert view.read_grade(root, entry)['binding_status'] == 'invalid'


def test_raw_capture_drift_is_invalid(tmp_path):
    root, entry, _ = fixture(tmp_path)
    (root / 'orders-after.json').write_text('{}')
    assert view.read_grade(root, entry)['binding_status'] == 'invalid'


def test_other_trace_cannot_use_saved_grade(tmp_path):
    root, entry, _ = fixture(tmp_path)
    assert view.read_grade(tmp_path / 'other-episode', entry)['binding_status'] == 'invalid'


@pytest.mark.parametrize('name,change', [
    ('metadata.json', {'episode_id': 'foreign'}),
    ('policy-task.json', {'start_url': 'https://foreign.test/'}),
    ('policy-task.json', {'user_message': 'Different request'}),
    ('episode.json', {'infrastructure_completed': False}),
    ('episode.json', {'evaluation': {}})])
def test_repinning_drift_before_publication_cannot_make_a_verified_grade(tmp_path, name, change):
    root, entry, _ = fixture(tmp_path)
    path = root / name
    data = json.loads(path.read_text())
    data.update(change)
    entry['files'][name] = save(path, data)
    assert view.read_grade(root, entry)['binding_status'] == 'invalid'


def test_wrong_http_projection_is_a_system_failure_and_old_registry_is_preserved(tmp_path, monkeypatch):
    root, _, report = fixture(tmp_path)
    registry = tmp_path / 'registry.json'
    original = {'roots': ['old-root'], 'address_grades': {'old-trace': {'unchanged': True}},
                'patterns': ['old-pattern']}
    save(registry, original)
    class Reply:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self): return b'{}'
    monkeypatch.setattr(view, 'urlopen', lambda *args, **kwargs: Reply())
    with pytest.raises(ValueError, match='HTTP viewer'):
        view.publish(trace=root, grade=copy.deepcopy(report), registry=registry,
                     viewer_url='http://localhost:1234', expected_run_root=tmp_path)
    after = json.loads(registry.read_text())
    assert after['address_grades'] == original['address_grades']
    assert after['patterns'] == original['patterns']
    assert after['roots'][0] == 'old-root'
