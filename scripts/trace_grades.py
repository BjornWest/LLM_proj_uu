"""Read-only projection of an append-only, evidence-bound answer grade."""
import hashlib
import json
from pathlib import Path

FILENAME = 'derived-answer-grade.json'
SCHEMA = 'browser-answer-grade-view-v1'
DETAILS_FILENAME = 'derived-answer-check-details.json'
BOUND_FILES = ('metadata.json', 'episode.json', 'evaluation.json', 'policy-task.json',
               'natural-answer.json', 'steps.jsonl')


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''): digest.update(block)
    return digest.hexdigest()


def read_grade(directory):
    """Validate against the selected episode; never import or run its grader."""
    directory = Path(directory)
    path = directory / FILENAME
    if not path.exists() and not path.is_symlink(): return None
    try:
        if path.is_symlink() or path.stat().st_size > 1024 * 1024:
            raise ValueError('Invalid derived-grade file')
        data = json.loads(path.read_text())
        if not isinstance(data, dict): raise ValueError('Invalid grade object')
        if data.get('schema') != SCHEMA or data.get('episode_id') != directory.name:
            raise ValueError('Grade belongs to another episode or schema')
        bindings = data['episode_artifact_sha256']
        if set(bindings) != set(BOUND_FILES): raise ValueError('Incomplete episode binding')
        for name, expected in bindings.items():
            target = directory / name
            if target.is_symlink() or sha(target) != expected:
                raise ValueError('Episode evidence changed: ' + name)
        verdict = data['structured_claims_correct']
        if verdict is not None and type(verdict) is not bool: raise ValueError('Invalid verdict')
        for field in ('requirements', 'additional_checks'):
            if not isinstance(data[field], dict): raise ValueError('Invalid checks')
            if any(v is not None and type(v) is not bool for v in data[field].values()):
                raise ValueError('Invalid check result')
        if data.get('safe_success') is not None or data.get('full_response_evaluated') is not False:
            raise ValueError('Unsupported broader success claim')
        for key in ('claims', 'oracle_answer', 'source_artifact_sha256'):
            if not isinstance(data.get(key), dict): raise ValueError('Invalid grade details: ' + key)
        if not isinstance(data.get('derivations'), list): raise ValueError('Invalid derivations')
        if not isinstance(data.get('limitations'), list) or any(not isinstance(x, str) for x in data['limitations']):
            raise ValueError('Invalid limitations')
        if not isinstance(data.get('extractor'), dict) or any(not isinstance(data['extractor'].get(k), str)
                for k in ('model', 'provider', 'version')):
            raise ValueError('Missing extractor provenance')
        data = {**data, 'binding_status': 'verified'}
        details = directory / DETAILS_FILENAME
        if details.exists() or details.is_symlink():
            try:
                if details.is_symlink() or details.stat().st_size > 1024 * 1024: raise ValueError('Invalid details file')
                payload = json.loads(details.read_text())
                if (payload['schema'] != 'browser-answer-check-details-v1' or payload['episode_id'] != directory.name
                        or payload['grade_sidecar_sha256'] != sha(path)):
                    raise ValueError('Check details do not match grade')
                checks = payload['checks']
                if not isinstance(checks, dict): raise ValueError('Invalid check details')
                for value in checks.values():
                    if not isinstance(value, dict) or any(not isinstance(value.get(k), str) for k in ('expected','supplied','explanation')):
                        raise ValueError('Invalid expected/supplied details')
                    if value.get('answer_quote') is not None and not isinstance(value['answer_quote'], str): raise ValueError('Invalid quote')
                data['check_details'] = checks
            except (OSError, ValueError, KeyError, TypeError) as exc:
                data['check_details_error'] = str(exc)
        return data
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {'binding_status': 'invalid', 'error': str(exc), 'structured_claims_correct': None}


def empty_manual_verifier(message):
    """Only the known ungraded placeholder can be replaced in the normal view."""
    if message.get('title') != 'Privileged verifier — not model input': return False
    try:
        value = json.loads(message['text'])
    except (ValueError, TypeError, KeyError): return False
    if not isinstance(value, dict) or value.get('verifier') != 'manual-review' or value.get('trust') != 'ungraded':
        return False
    return all(value.get(k) is None for k in ('task_completed', 'authorization_satisfied',
        'unauthorized_effects', 'injection_exposed', 'injection_avoided', 'technical_error', 'safe_success'))


def project_grade(group, directory):
    grade = read_grade(directory)
    if grade is None: return group
    group['recorded_evaluation_label'] = group.get('evaluation_label', 'outcome unknown')
    group['derived_evaluation'] = grade
    result = grade['structured_claims_correct']
    label = ('derived grade invalid' if grade['binding_status'] != 'verified' else
             'answer checks passed' if result is True else 'answer checks failed' if result is False else
             'answer checks inconclusive')
    old_label = group['recorded_evaluation_label']
    title = group['title']
    group['title'] = (title[:-len(old_label)] if title.endswith(old_label) else title + ' · ') + label + ' (derived)'
    group['evaluation_label'] = label
    note = {'id': group['id'] + ':derived-answer-grade', 'kind': 'note',
        'title': 'Answer grading — not model input',
        'text': json.dumps(grade, ensure_ascii=False, indent=2),
        'source': Path(directory).name + '/' + FILENAME, 'at': grade.get('created_at'),
        'provenance': 'derived_post_episode_evaluation', 'diagnostic': False,
        'status': 'error' if result is False or grade['binding_status'] != 'verified' else 'returned' if result is True else 'unknown',
        'collapsed': True}
    replacement = next((i for i, m in enumerate(group['messages']) if empty_manual_verifier(m)), None)
    if replacement is not None and grade['binding_status'] == 'verified':
        # Keep the original diagnostic and its provenance. No recording is edited.
        group['messages'][replacement]['diagnostic'] = True
        group['messages'].insert(replacement, note)
    else:
        group['messages'].append(note)
    group['message_count'] = len(group['messages'])
    group['visible_message_count'] = sum(not m.get('diagnostic') for m in group['messages'])
    return group
