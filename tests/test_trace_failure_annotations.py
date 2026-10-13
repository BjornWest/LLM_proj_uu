import copy
import hashlib
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT.parent / 'common_agent_util')]
from scripts.trace_failure_annotations import SCHEMA, read_failure_annotations
from scripts.trace_hub import Hub


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def fixture(root):
    cases = []
    capacity = root / 'capacity-terminal.json'
    cause = dict(case='H03', type='RuntimeError', message='Child lifecycle exited 1', infrastructure=True)
    write(capacity, {'stop_cause': cause, 'status': {'episodes': {'B14': {'cancelled': True, 'done': False}}}})
    for name, stage, stop, execution, text in [
        ('H03', 'automatic_answer_grading', 'agent_finished', None, 'Saved answer'),
        ('B14', 'policy_interrupted_by_sibling_infrastructure_abort', 'error', 'BrokenPipeError', None),
    ]:
        trace = root / 'runs' / name
        error = 'Unsupported quote' if name == 'H03' else 'Saved-answer grade unavailable'
        write(trace / 'metadata.json', {'browsergym_version': 'fixture', 'trace_title': name, 'driver': 'scripted', 'tags': ['scripted']})
        write(trace / 'steps.jsonl', {'step': 0, 'model_response': {'choices': [{'message': {'content': 'Fixture'}}]}})
        write(trace / 'episode.json', {'case': name, 'episode_id': name, 'stop_reason': stop, 'execution_error': execution, 'grading_error': error, 'error': error})
        write(trace / 'evaluation.json', {'task_completed': None, 'safe_success': None, 'technical_error': error})
        write(trace / 'natural-answer.json', {'text': text})
        write(trace / 'automatic-grading.json', {'episode_id': name, 'error': error, 'grade_artifact': None, 'projection_artifact': None, 'status': 'failed', 'infrastructure_complete': False})
        pins = [{'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()} for path in [
            trace / 'episode.json', trace / 'evaluation.json', trace / 'natural-answer.json', trace / 'automatic-grading.json', capacity,
        ]]
        cases.append(dict(case=name, session_id=hashlib.sha256(('browsergym:' + name).encode()).hexdigest()[:20],
                          episode_id=name, failure_stage=stage, policy_stop_reason=stop, policy_execution_error=execution,
                          grading_error=error, answer_delivered=text is not None, task_verdict=None,
                          suite_root_cause=cause, causal_scope='H03 failed during grading; B14 was cancelled by the cohort.', evidence=pins))
    manifest = root / 'failure-annotations.json'
    write(manifest, {'schema': SCHEMA, 'cases': cases})
    return manifest, cases


def test_distinct_stages_and_original_body_grade_preserved(tmp_path):
    manifest, cases = fixture(tmp_path)
    projected = read_failure_annotations(manifest)['entries']
    assert [projected[c['session_id']]['binding_status'] for c in cases] == ['verified', 'verified']
    assert projected[cases[0]['session_id']]['label'] != projected[cases[1]['session_id']]['label']
    assert all(projected[c['session_id']]['task_verdict'] is None for c in cases)
    registry = tmp_path / 'sources.json'
    write(registry, {'project_root': str(tmp_path), 'roots': [str(tmp_path / 'runs')]})
    hub = Hub(registry)
    _, entries = hub.snapshot()
    before = hub.load(entries.entries[cases[0]['session_id']])
    original = {pin['path']: Path(pin['path']).read_bytes() for case in cases for pin in case['evidence']}
    metadata = hub.collection_metadata()
    assert metadata['failure_annotations']['entries'] == projected
    assert hub.load(entries.entries[cases[0]['session_id']]) == before
    assert 'failure_annotations' not in json.loads(before[0])
    assert original == {path: Path(path).read_bytes() for path in original}


@pytest.mark.parametrize('defect', ['hash', 'answer', 'stop', 'grading', 'root', 'verdict', 'identity', 'missing', 'cancel', 'mix'])
def test_stale_or_contradictory_annotation_cannot_display_claim(tmp_path, defect):
    manifest, cases = fixture(tmp_path)
    case = cases[1]
    if defect == 'hash':
        path = Path(case['evidence'][0]['path']); path.write_text(path.read_text() + ' ')
    elif defect == 'answer': case['answer_delivered'] = True
    elif defect == 'stop': case['policy_stop_reason'] = 'agent_finished'
    elif defect == 'grading': case['grading_error'] = 'Different error'
    elif defect == 'root': case['suite_root_cause'] = {'case': 'Other'}
    elif defect == 'verdict': case['task_verdict'] = True
    elif defect == 'identity': case['episode_id'] = 'Other'
    elif defect == 'missing': case['evidence'] = case['evidence'][1:]
    elif defect == 'cancel':
        path = Path(case['evidence'][-1]['path']); value = json.loads(path.read_text()); value['status']['episodes']['B14']['cancelled'] = False
        write(path, value); case['evidence'][-1]['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    elif defect == 'mix':
        path = tmp_path / 'different' / 'B14' / 'evaluation.json'; path.parent.mkdir(parents=True); path.write_bytes(Path(case['evidence'][1]['path']).read_bytes()); case['evidence'][1]['path'] = str(path)
    write(manifest, {'schema': SCHEMA, 'cases': cases})
    value = read_failure_annotations(manifest)['entries'][case['session_id']]
    assert value['binding_status'] == 'invalid'
    assert 'failure_stage' not in value and 'grading_error' not in value


@pytest.mark.parametrize('value', [None, [], {}])
def test_invalid_manifest_is_separate_from_folder_metadata(tmp_path, value):
    write(tmp_path / 'failure-annotations.json', value)
    write(tmp_path / 'sources.json', {'project_root': str(tmp_path), 'roots': []})
    hub = Hub(tmp_path / 'sources.json')
    assert hub.collection_metadata()['writable'] is True
    assert hub.collection_metadata()['failure_annotations']['error']


def test_optional_missing_duplicate_and_oversized_manifests(tmp_path):
    path = tmp_path / 'failure-annotations.json'
    assert read_failure_annotations(path) is None
    path.write_text('{"schema":"x","schema":"y"}')
    assert read_failure_annotations(path)['error']
    path.write_bytes(b'x' * (256 * 1024 + 1))
    assert read_failure_annotations(path)['error']
    manifest, cases = fixture(tmp_path)
    write(manifest, {'schema': SCHEMA, 'cases': [cases[0], copy.deepcopy(cases[0])]})
    assert read_failure_annotations(manifest)['entries'][cases[0]['session_id']]['binding_status'] == 'invalid'


@pytest.mark.parametrize('defect', ['case', 'episode_id', 'grading_id', 'verdict_keys', 'grade_artifact', 'projection_artifact', 'infrastructure', 'second_capacity', 'nonfinite'])
def test_review_identity_and_native_grade_guards(tmp_path, defect):
    manifest, cases = fixture(tmp_path)
    case = cases[1]
    if defect in ('case', 'episode_id', 'verdict_keys'):
        pin = case['evidence'][0 if defect != 'verdict_keys' else 1]
        path = Path(pin['path']); value = json.loads(path.read_text())
        if defect == 'case': value['case'] = 'C07'
        elif defect == 'episode_id': value['episode_id'] = 'C07'
        else: value = {'verdict': 'pass', 'success': True}
        write(path, value); pin['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    elif defect in ('grading_id', 'grade_artifact', 'projection_artifact'):
        pin = case['evidence'][3]; path = Path(pin['path']); value = json.loads(path.read_text())
        value['episode_id' if defect == 'grading_id' else defect] = 'Other'
        write(path, value); pin['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    elif defect in ('infrastructure', 'nonfinite'):
        pin = case['evidence'][-1]; path = Path(pin['path']); value = json.loads(path.read_text())
        value['stop_cause']['infrastructure' if defect == 'infrastructure' else 'invalid_number'] = False if defect == 'infrastructure' else float('inf')
        case['suite_root_cause'] = value['stop_cause']
        write(path, value); pin['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    else:
        path = tmp_path / 'other' / 'capacity-terminal.json'; path.parent.mkdir(); path.write_bytes(Path(case['evidence'][-1]['path']).read_bytes())
        case['evidence'].append({'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    write(manifest, {'schema': SCHEMA, 'cases': cases})
    result = read_failure_annotations(manifest)
    assert result.get('error') or result['entries'][case['session_id']]['binding_status'] == 'invalid'
    json.dumps(result, allow_nan=False)


def test_invalid_and_over_limit_cases_do_not_erase_valid_notes(tmp_path):
    manifest, cases = fixture(tmp_path)
    write(manifest, {'schema': SCHEMA, 'cases': [None, cases[0], {}, cases[1]]})
    result = read_failure_annotations(manifest)
    assert all(result['entries'][c['session_id']]['binding_status'] == 'verified' for c in cases)
    write(manifest, {'schema': SCHEMA, 'cases': cases + [{}] * 15})
    result = read_failure_annotations(manifest)
    assert all(result['entries'][c['session_id']]['binding_status'] == 'verified' for c in cases)
    assert result['warnings']


def test_overflow_number_is_rejected_without_nonfinite_api_output(tmp_path):
    path = tmp_path / 'failure-annotations.json'
    path.write_text('{"schema":"'+SCHEMA+'","cases":[],"extra":1e999}')
    result = read_failure_annotations(path)
    assert result['error']
    json.dumps(result, allow_nan=False)
