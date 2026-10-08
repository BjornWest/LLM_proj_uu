"""Publish/display saved address-only grades; never run an episode or grader."""
import fcntl
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen
import uuid

from scripts import trace_grades as legacy

SCOPE = 'captured_address_state'
NATIVE_SCOPE = 'observed_checkout_or_submitted_address_only'
VERSION = 'website-simulated-order-address-grade-v1'
CONTRACT = 'website-simulated-order-address-runner-v1'
RULE = 'last_new_target_retailer_submission_else_terminal_checkout'


def descriptor(path):
    path = Path(path).absolute()
    if path.is_symlink() or not path.is_file():
        raise ValueError('Missing regular saved evidence: ' + str(path))
    return {'path': str(path), 'sha256': legacy.sha(path)}


def checked(pin):
    if descriptor(pin['path']) != pin:
        raise ValueError('Saved address evidence changed: ' + pin['path'])
    path = Path(pin['path'])
    if path.stat().st_size > 32 * 1024 * 1024:
        raise ValueError('Oversized saved evidence')
    return json.loads(path.read_bytes())


def _view(directory, entry):
    directory = Path(directory).resolve()
    files = entry['files']
    required = set(legacy.BOUND_FILES) | {'manifest', 'grade', 'projection', 'task', 'reference', 'capture'}
    if set(files) != required:
        raise ValueError('Incomplete saved address grade binding')
    for name, pin in files.items():
        if descriptor(pin['path']) != pin:
            raise ValueError('Changed saved evidence: ' + name)
    names = {'manifest': 'automatic-grading.json', 'grade': 'automatic-grade.json',
             'projection': 'automatic-grade-projection.json',
             'capture': 'manual-review-private/order-address-evidence.private.json'}
    for name in legacy.BOUND_FILES:
        names[name] = name
    if any(Path(files[key]['path']) != directory / name for key, name in names.items()):
        raise ValueError('Grade artifacts belong to another trace')
    manifest, raw, proof, task, reference, capture, canonical = (
        checked(files[name]) for name in
        ('manifest', 'grade', 'projection', 'task', 'reference', 'capture', 'evaluation.json'))
    binding = manifest['binding']
    metadata, public, episode = (checked(files[name]) for name in
                                ('metadata.json', 'policy-task.json', 'episode.json'))
    public_hash = hashlib.sha256(json.dumps(public, sort_keys=True, ensure_ascii=False,
                                           allow_nan=False).encode()).hexdigest()
    goal = (public['user_message'] + '\n\nSAVED USER MEMORIES:\n' +
            json.dumps(public['memories'], ensure_ascii=False, sort_keys=True) +
            '\n\nENVIRONMENT CONTEXT:\n' +
            json.dumps(public['environment_context'], ensure_ascii=False, sort_keys=True))
    if (metadata['episode_id'] != directory.name or episode['episode_id'] != directory.name
            or public['task_id'] != binding['task_id']
            or public['user_message'] != task['user_message'] or public['memories'] != task['memories']
            or public_hash != binding['public_task_sha256']
            or hashlib.sha256(goal.encode()).hexdigest() != binding['goal_sha256']
            or episode['trace_complete'] is not True
            or episode['infrastructure_completed'] is not True
            or episode['grading_error'] is not None
            or episode['grading'] != manifest or episode['evaluation'] != canonical
            or any(episode.get(key) for key in ('error', 'execution_error', 'cleanup_errors'))):
        raise ValueError('Finalized episode or public request differs from pre-dispatch binding')
    binding_hash = hashlib.sha256(json.dumps(binding, sort_keys=True, ensure_ascii=False,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    if (manifest['schema'] != 'automatic-episode-grading-v1'
            or manifest['status'] != 'graded' or manifest['infrastructure_complete'] is not True
            or manifest['episode_id'] != directory.name or raw['episode_id'] != directory.name
            or raw['schema'] != manifest['schema']
            or manifest['contract_id'] != CONTRACT or raw['contract_id'] != CONTRACT
            or manifest['binding_sha256'] != binding_hash or raw['binding_sha256'] != binding_hash
            or manifest['grade_sha256'] != files['grade']['sha256']
            or manifest['projection_sha256'] != files['projection']['sha256']
            or proof['schema'] != 'automatic-grade-projection-v1'
            or proof['episode_id'] != directory.name or proof['verified'] is not True
            or proof['evaluation_sha256'] != files['evaluation.json']['sha256']):
        raise ValueError('Automatic grade/close/projection binding differs')
    report = raw['raw_grade']['native_grade']
    task_hash = hashlib.sha256(json.dumps(task, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    for name in ('task', 'reference'):
        if binding['reference_files'].get(files[name]['path']) != files[name]['sha256']:
            raise ValueError('Native reference differs from pre-dispatch binding')
    if (raw['raw_grade']['task_id'] != task['task_id'] or binding['task_id'] != task['task_id']
            or report['task_id'] != task['task_id'] or reference['task_id'] != task['task_id']
            or report['schema_version'] != VERSION or report['scoring_scope'] != NATIVE_SCOPE
            or binding['scoring_scope'] != NATIVE_SCOPE or reference['scoring_scope'] != NATIVE_SCOPE
            or report['observation_rule'] != RULE or binding['observation_rule'] != RULE
            or reference['task_sha256'] != task_hash
            or reference['expected_address'] != task['delivery_address']
            or capture['task_sha256'] != task_hash or capture['task_id'] != task['task_id']
            or capture['episode_id'] != directory.name
            or capture['main_trace_sha256'] != files['steps.jsonl']['sha256']
            or capture['complete_effect_envelope'] is not None
            or capture['full_effects'] != 'unknown' or capture['order_outcome_scored'] is not False):
        raise ValueError('Address-only scoring or capture identity differs')
    for category in ('orders', 'checkout_storage'):
        if set(capture['artifacts'][category]) != {'before', 'after'}:
            raise ValueError('Incomplete original capture artifacts')
        for phase, pin in capture['artifacts'][category].items():
            if not Path(pin['path']).is_relative_to(directory) or descriptor(pin['path']) != pin:
                raise ValueError('Original capture artifact changed')
            expected = capture['ledger'][phase] if category == 'orders' else capture['checkout_storage'][phase]
            if checked(pin) != expected:
                raise ValueError('Raw capture and sealed evidence differ')
    verdict = {'pass': True, 'fail': False, 'inconclusive': None}[report['verdict']]
    if (canonical['verifier'] != 'simulated-order-address-only'
            or canonical['verifier_version'] != VERSION or canonical['trust'] != 'native_reference'
            or canonical['task_completed'] is not verdict or report['address_correct'] is not verdict
            or canonical['technical_error'] is not None
            or canonical['authorization_satisfied'] is not None
            or canonical['unauthorized_effects'] is not None
            or report['full_effects'] != 'unknown' or report['full_order_completion'] != 'not_assessed'):
        raise ValueError('Canonical verdict or limited scope differs')
    checks = {'address': verdict}
    fields = report['components'].get('address', {}).get('checks', {})
    if not isinstance(fields, dict) or any(type(v) is not bool for v in fields.values()):
        raise ValueError('Malformed saved field checks')
    if verdict is True and (not fields or not all(fields.values())):
        raise ValueError('Passing address grade contradicts its field checks')
    checks.update({'address_' + key: value for key, value in fields.items()})
    details = {'address': {'expected': reference['expected_address'],
        'supplied': report.get('actual_address'),
        'explanation': 'Saved native address comparison, including apartment/unit. ' +
            'Observation: ' + json.dumps(report.get('selected_evidence'))}}
    return dict(binding_status='verified', structured_claims_correct=verdict,
        grading_scope=SCOPE, scoring_scope=NATIVE_SCOPE, grading_version=VERSION,
        native_verdict=report['verdict'], observation_rule=RULE,
        requirements=checks, additional_checks={}, check_details=details,
        safe_success=None, full_response_evaluated=False,
        full_effects='unknown', full_order_completion='not_assessed',
        claims={'task_id': task['task_id'], 'components': report['components']},
        oracle_answer={'expected_address': reference['expected_address']}, derivations=[],
        source_artifact_sha256={p['path']: p['sha256'] for p in files.values()},
        episode_artifact_sha256={n: files[n]['sha256'] for n in legacy.BOUND_FILES},
        extractor={'model': 'not used', 'provider': 'not used', 'version': VERSION},
        limitations=report['limitations'] + ['Saved automatic output only; display never regrades.'],
        artifact_filename='automatic-grade.json')


def read_grade(directory, entry):
    try:
        return _view(directory, entry)
    except (OSError, ValueError, KeyError, TypeError) as error:
        return dict(binding_status='invalid', error=str(error), grading_scope=SCOPE,
                    structured_claims_correct=None)


def publish(*, trace, grade, registry, viewer_url, expected_run_root):
    """Register exact saved artifacts and require the actual HTTP projection.

    Caller supplies the predeclared run root; existing roots and every previous
    grade mapping are retained. HTTP failure remains a system failure.
    """
    trace = Path(trace).resolve()
    root = Path(expected_run_root).resolve()
    if trace == root or not trace.is_relative_to(root):
        raise ValueError('Returned trace escaped the declared run root')
    manifest = json.loads((trace / 'automatic-grading.json').read_bytes())
    references = manifest['binding']['reference_files']
    def reference(suffix):
        paths = [path for path in references if Path(path).name == suffix]
        if len(paths) != 1:
            raise ValueError('Missing or ambiguous native reference: ' + suffix)
        return paths[0]
    files = {name: descriptor(trace / name) for name in legacy.BOUND_FILES}
    files.update({name: descriptor(path) for name, path in {
        'manifest': trace / 'automatic-grading.json', 'grade': trace / 'automatic-grade.json',
        'projection': trace / 'automatic-grade-projection.json',
        'capture': trace / 'manual-review-private/order-address-evidence.private.json',
        'task': reference('simulated-order-task.private.json'),
        'reference': reference('order-address-reference.private.json')}.items()})
    entry = {'files': files}
    view = read_grade(trace, entry)
    saved = checked(files['grade'])['raw_grade']['native_grade']
    if view['binding_status'] != 'verified' or saved != grade:
        raise ValueError('Saved native grade differs or is invalid: ' + str(view.get('error')))
    registry = Path(registry)
    with registry.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = json.loads(registry.read_bytes())
        entries = data.setdefault('order_address_grades', {})
        key = str(trace)
        if key in entries and entries[key] != entry:
            raise ValueError('Conflicting existing saved grade')
        entries[key] = entry
        if str(trace.parent) not in data['roots']:
            data['roots'].append(str(trace.parent))
        temporary = registry.with_name(registry.name + '.' + uuid.uuid4().hex + '.tmp')
        try:
            with temporary.open('x') as file:
                json.dump(data, file, ensure_ascii=False, indent=2, allow_nan=False)
            temporary.replace(registry)
        finally:
            if temporary.exists():
                temporary.unlink()
    ident = hashlib.sha256(('browsergym:' + trace.name).encode()).hexdigest()[:20]
    api = viewer_url.rstrip('/') + '/api/sessions/' + ident
    with urlopen(api, timeout=30) as response:
        body = response.read()
    public = json.loads(body)
    if (public.get('derived_evaluation') != view
            or public.get('evaluation_label') != 'address checks ' +
                {'pass': 'passed', 'fail': 'failed', 'inconclusive': 'inconclusive'}[grade['verdict']]):
        raise ValueError('Automatic address-only grade missing/different in HTTP viewer')
    return {'status': 'verified', 'viewer_url': viewer_url.rstrip('/') + '/#' + ident,
        'api_url': api, 'response_sha256': hashlib.sha256(body).hexdigest(),
        'native_verdict': grade['verdict'], 'scoring_scope': NATIVE_SCOPE,
        'full_order_completion': 'not_assessed', 'files': files}
