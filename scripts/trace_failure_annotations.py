"""Read-only evidence-bound notes, separate from recorded episode grades."""
import hashlib
import json
import math
from pathlib import Path
import re

SCHEMA = 'evaluation-derived-failure-stages-v1'
STAGES = {
    'automatic_answer_grading': 'Automatic answer grading failed',
    'policy_interrupted_by_sibling_infrastructure_abort': 'Cancelled after a sibling infrastructure failure',
}
MAX_MANIFEST_BYTES = 256 * 1024
MAX_EVIDENCE_BYTES = 1024 * 1024
MAX_ENTRY_BYTES = 2 * MAX_EVIDENCE_BYTES


def bounded_bytes(path, limit):
    with path.open('rb') as stream:
        value = stream.read(limit + 1)
    if len(value) > limit:
        raise ValueError('Annotation evidence exceeds the size limit')
    return value


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate annotation key')
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError('Non-finite annotation number: ' + value)


def parse_json(raw):
    def finite_float(value):
        number = float(value)
        if not math.isfinite(number):
            reject_constant(value)
        return number
    return json.loads(raw, object_pairs_hook=unique_object, parse_constant=reject_constant, parse_float=finite_float)


def project_annotation(entry):
    try:
        if not isinstance(entry, dict):
            raise ValueError('Invalid annotation entry')
        ident, episode_id = entry['session_id'], entry['episode_id']
        if (not isinstance(episode_id, str) or '/' in episode_id or '\\' in episode_id
                or hashlib.sha256(('browsergym:' + episode_id).encode()).hexdigest()[:20] != ident):
            raise ValueError('Annotation trace identity differs')
        stage = entry['failure_stage']
        if stage not in STAGES or entry['task_verdict'] is not None:
            raise ValueError('Failure annotation must retain an unknown task verdict')
        for field in ('case', 'policy_stop_reason', 'grading_error', 'causal_scope'):
            if not isinstance(entry.get(field), str) or not 1 <= len(entry[field]) <= 4096:
                raise ValueError('Invalid annotation field: ' + field)
        if (type(entry.get('answer_delivered')) is not bool
                or entry.get('policy_execution_error') is not None and not isinstance(entry['policy_execution_error'], str)):
            raise ValueError('Invalid policy status')
        evidence = entry['evidence']
        if not isinstance(evidence, list) or not 5 <= len(evidence) <= 8:
            raise ValueError('Use between five and eight evidence files')
        paths, projected, documents, total, directories = set(), [], {}, 0, set()
        for pin in evidence:
            if not isinstance(pin, dict) or not isinstance(pin.get('path'), str):
                raise ValueError('Invalid annotation evidence')
            path = Path(pin['path'])
            if not path.is_absolute() or not re.fullmatch('[a-f0-9]{64}', pin.get('sha256', '')):
                raise ValueError('Invalid evidence path or digest')
            path = path.resolve()
            if path in paths or not path.is_file():
                raise ValueError('Duplicate or non-file annotation evidence')
            raw = bounded_bytes(path, MAX_EVIDENCE_BYTES)
            total += len(raw)
            if total > MAX_ENTRY_BYTES:
                raise ValueError('Annotation evidence exceeds the entry size limit')
            if hashlib.sha256(raw).hexdigest() != pin['sha256']:
                raise ValueError('Annotation evidence changed: ' + path.name)
            paths.add(path)
            projected.append({'path': str(path), 'sha256': pin['sha256']})
            if path.parent.name == episode_id:
                directories.add(path.parent)
                if path.name in documents:
                    raise ValueError('Duplicate evidence document: ' + path.name)
                documents[path.name] = parse_json(raw)
            elif path.name == 'capacity-terminal.json':
                if path.name in documents:
                    raise ValueError('Duplicate capacity evidence')
                documents[path.name] = parse_json(raw)
        if len(directories) != 1:
            raise ValueError('Annotation mixes recording directories')
        episode, evaluation, answer, grading, capacity = (documents[name] for name in
            ('episode.json', 'evaluation.json', 'natural-answer.json', 'automatic-grading.json', 'capacity-terminal.json'))
        if (episode.get('case') != entry['case'] or episode.get('episode_id') != episode_id
                or grading.get('episode_id') != episode_id
                or episode.get('stop_reason') != entry['policy_stop_reason']
                or episode.get('execution_error') != entry['policy_execution_error']
                or episode.get('grading_error') != entry['grading_error']
                or grading.get('error') != entry['grading_error']
                or grading.get('status') != 'failed' or grading.get('infrastructure_complete') is not False
                or grading['grade_artifact'] is not None or grading['projection_artifact'] is not None
                or bool(answer.get('text')) != entry['answer_delivered']
                or evaluation['task_completed'] is not None or evaluation['safe_success'] is not None
                or capacity.get('stop_cause') != entry['suite_root_cause']
                or entry['suite_root_cause'].get('infrastructure') is not True):
            raise ValueError('Annotation contradicts recorded failure evidence')
        if stage == 'automatic_answer_grading':
            if (entry['policy_stop_reason'] != 'agent_finished' or entry['policy_execution_error'] is not None
                    or not entry['answer_delivered'] or entry['suite_root_cause'].get('case') != entry['case']):
                raise ValueError('Grading-stage annotation contradicts policy completion')
        elif (entry['answer_delivered'] or entry['policy_stop_reason'] != 'error'
                or entry['suite_root_cause'].get('case') == entry['case']
                or capacity['status']['episodes'][entry['case']].get('cancelled') is not True
                or capacity['status']['episodes'][entry['case']].get('done') is not False):
            raise ValueError('Sibling-abort annotation lacks recorded cancellation')
        fields = ('case', 'failure_stage', 'policy_stop_reason', 'policy_execution_error',
                  'grading_error', 'answer_delivered', 'task_verdict', 'suite_root_cause', 'causal_scope')
        return dict(binding_status='verified', label=STAGES[stage], evidence=projected,
                    trace_directory=str(next(iter(directories))), derived=True, **{field: entry[field] for field in fields})
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, AttributeError) as error:
        return dict(binding_status='invalid', derived=True, error=str(error))


def read_failure_annotations(path):
    """Absence leaves metadata unchanged; bad notes cannot break folder APIs."""
    path = Path(path)
    try:
        raw = bounded_bytes(path, MAX_MANIFEST_BYTES)
    except FileNotFoundError:
        return None
    except (OSError, ValueError, RuntimeError) as error:
        return dict(entries={}, error=str(error))
    try:
        value = parse_json(raw)
        if (not isinstance(value, dict) or value.get('schema') != SCHEMA
                or not isinstance(value.get('cases'), list)):
            raise ValueError('Invalid failure annotation manifest')
        entries, warnings = {}, []
        for entry in value['cases'][:16]:
            ident = entry.get('session_id') if isinstance(entry, dict) else None
            if not isinstance(ident, str) or not re.fullmatch('[a-f0-9]{20}', ident):
                warnings.append('Ignored annotation with invalid session ID');continue
            if ident in entries:
                entries[ident] = dict(binding_status='invalid', derived=True, error='Duplicate annotation session ID');continue
            entries[ident] = project_annotation(entry)
        if len(value['cases']) > 16:
            warnings.append('Only the first sixteen annotations are supported')
        return dict(entries=entries, **({'warnings': warnings} if warnings else {}))
    except (ValueError, TypeError, RuntimeError) as error:
        return dict(entries={}, error=str(error))
