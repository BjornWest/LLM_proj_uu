"""Prepared prospective missing-output publication; no extraction or grading.

The accepted live callback and native validator must already have run. These
artifact joins verify their recorded finalization; self-consistent JSON does not
issue callback, lifecycle or native authority. Not installed in execution yet.
"""
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile

from .compound_answer_delivery_v1 import select_answer_path

SCHEMA = 'browser-answer-missing-output-grade-view-v1'
VERSION = 'website-catalog-compare-review-missing-answer-v1'
BOUND_FILES = ('metadata.json', 'episode.json', 'evaluation.json', 'policy-task.json',
               'natural-answer.json', 'steps.jsonl')
SOURCE_NAMES = ('native-grade.json', 'terminal-evidence.json', 'cleanup-receipt.json',
                'policy-result.json', 'before-finalization/episode.json',
                'before-finalization/evaluation.json')
ROLE_NAMES = {'episode_before_finalization': 'before-finalization/episode.json',
              'evaluation_before_finalization': 'before-finalization/evaluation.json',
              'policy_result': 'policy-result.json', 'cleanup_receipt': 'cleanup-receipt.json'}


def _safe_file(path):
    path = Path(path)
    if not path.is_absolute() or any(part in ('.', '..') for part in path.parts):
        raise ValueError('Require absolute normalized artifact path')
    if any(parent.is_symlink() for parent in (path, *path.parents)) or not path.is_file():
        raise ValueError('Artifact or parent is a symlink or not a regular file')
    return path


def _sha(path):
    return sha256(_safe_file(path).read_bytes()).hexdigest()


def _pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value: raise ValueError('Duplicate JSON field')
        value[key] = item
    return value


def _load(path):
    def reject(value): raise ValueError('Nonfinite JSON value: '+value)
    return json.loads(_safe_file(path).read_bytes(), object_pairs_hook=_pairs, parse_constant=reject)


def terminal_digest(value):
    """Product's compact sorted UTF8 convention, distinct from file hashes."""
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                            separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def _pin(record, path):
    if (type(record) is not dict or set(record) != {'path', 'sha256'}
            or record['path'] != str(path) or record['sha256'] != _sha(path)):
        raise ValueError('Terminal artifact path/hash differs from actual retained file')


def _build_sidecar(*, trace, source_directory, contract_id):
    """Join the new native outcome to final automatic grading and real artifacts.

    Caller owns accepted source/input checks and native terminal validation.
    The native outcome is read from its retained file, never fabricated here.
    """
    trace, root = Path(trace).absolute(), Path(source_directory).absolute()
    sources = {name: _sha(root/name) for name in SOURCE_NAMES}
    artifacts = {name: _sha(trace/name) for name in BOUND_FILES}
    native = _load(root/'native-grade.json')
    evidence = _load(root/'terminal-evidence.json')
    fixed = {'grading_version': VERSION, 'outcome_kind': 'required_answer_not_delivered',
             'task_completed': False, 'structured_claims_correct': False, 'claims': None,
             'extraction_requests': 0, 'additional_checks': {}, 'derivations': [],
             'selected_candidate_assessment': None}
    if (type(native) is not dict or any(type(native.get(k)) is not type(v)
            or native[k] != v for k, v in fixed.items())
            or type(native.get('oracle_grade')) is not dict
            or native['oracle_grade'].get('requirements') != {'answer_delivered': False}
            or native['oracle_grade']['requirements'].get('answer_delivered') is not False
            or native.get('terminal_evidence') != evidence
            or native.get('terminal_evidence_digest') != terminal_digest(evidence)
            or 'native_reference' not in native or native.get('oracle_answer') != native['native_reference']):
        raise ValueError('Not the exact native missing-answer outcome')
    if (type(evidence) is not dict or set(evidence) != {'schema', 'episode_id', 'binding', 'artifacts'}
            or evidence['schema'] != 'catalog-compare-review-missing-answer-terminal-v1'
            or evidence['episode_id'] != trace.name
            or type(evidence['binding']) is not dict
            or set(evidence['binding']) != {'native_task_id', 'public_task_id', 'contract_id',
                                           'input_files', 'source_files'}
            or evidence['binding']['contract_id'] != contract_id
            or type(evidence['artifacts']) is not dict
            or set(evidence['artifacts']) != set(ROLE_NAMES) | {'natural_answer'}):
        raise ValueError('Terminal evidence shape/episode/contract mismatch')
    for role, name in ROLE_NAMES.items(): _pin(evidence['artifacts'][role], root/name)
    _pin(evidence['artifacts']['natural_answer'], trace/'natural-answer.json')
    if (type(evidence['binding']['input_files']) is not dict
            or type(evidence['binding']['source_files']) is not dict
            or not evidence['binding']['input_files'] or not evidence['binding']['source_files']):
        raise ValueError('Missing actual native inputs or callback source binding')
    for record in evidence['binding']['input_files'].values():
        _pin(record, Path(record['path']))
    for path, expected in evidence['binding']['source_files'].items():
        if _sha(path) != expected: raise ValueError('Bound callback/input source changed')
    before = _load(root/'before-finalization/episode.json')
    natural = _load(trace/'natural-answer.json')
    if select_answer_path(natural, before) != 'missing_answer' or native.get('stop_reason') != before['stop_reason']:
        raise ValueError('Actual executed messages do not qualify as missing output')
    policy = _load(root/'policy-result.json')
    if (type(policy) is not dict or policy.get('trace') != str(trace)
            or type(policy.get('summary')) is not dict):
        raise ValueError('Policy result does not retain the actual trace and returned summary')
    returned = policy['summary']
    if (('trace_complete' in returned and returned['trace_complete'] is not True)
            or any(returned.get(key) != before.get(key) for key in
                   ('stop_reason', 'error', 'execution_error', 'cleanup_errors'))):
        raise ValueError('Returned and persisted policy outcomes differ')
    cleanup = _load(root/'cleanup-receipt.json')
    if (type(cleanup) is not dict or cleanup.get('schema') != 'catalog-compare-review-cleanup-v1'
            or cleanup.get('episode_id') != trace.name or cleanup.get('contract_id') != contract_id
            or cleanup.get('policy_closed') is not True or cleanup.get('runtime_closed') is not True
            or cleanup.get('errors') != []
            or cleanup.get('policy_result_sha256') != sources['policy-result.json']
            or cleanup.get('episode_before_finalization_sha256') != sources['before-finalization/episode.json']):
        raise ValueError('Cleanup receipt does not bind the actual retained terminal files')
    declaration = _load(trace/'automatic-grading.json')
    raw = _load(trace/'automatic-grade.json')
    final = _load(trace/'episode.json')
    evaluation = _load(trace/'evaluation.json')
    proof = _load(trace/'automatic-grade-projection.json')
    for envelope in (declaration, raw):
        if (type(envelope) is not dict or envelope.get('schema') != 'automatic-episode-grading-v1'
                or envelope.get('episode_id') != trace.name):
            raise ValueError('Automatic grade envelope belongs to a foreign schema or episode')
    if (declaration.get('contract_id') != contract_id or declaration.get('status') != 'graded'
            or declaration.get('phase') != 'external'
            or declaration.get('infrastructure_complete') is not True
            or declaration.get('grade_artifact') != 'automatic-grade.json'
            or declaration.get('projection_artifact') != 'automatic-grade-projection.json'
            or declaration.get('grade_sha256') != _sha(trace/'automatic-grade.json')
            or declaration.get('projection_sha256') != _sha(trace/'automatic-grade-projection.json')
            or raw.get('contract_id') != contract_id or raw.get('raw_grade', {}).get('native_grade') != native
            or final.get('infrastructure_completed') is not True or final.get('grading_error')
            or final.get('trace_complete') is not True
            or final.get('grading') != declaration or final.get('evaluation') != evaluation
            or final.get('success') is not False
            or any(final.get(key) != before.get(key) for key in
                   ('stop_reason', 'error', 'execution_error', 'cleanup_errors', 'terminated', 'truncated'))
            or evaluation.get('task_completed') is not False
            or evaluation.get('safe_success') is not False or evaluation.get('technical_error')):
        raise ValueError('Missing-output grade is outside its finalized automatic contract')
    if (type(proof) is not dict or proof.get('schema') != 'automatic-grade-projection-v1'
            or proof.get('episode_id') != trace.name or proof.get('verified') is not True
            or proof.get('evaluation_sha256') != artifacts['evaluation.json']):
        raise ValueError('Canonical projection does not bind the final evaluation')
    binding = declaration.get('binding')
    references = {record['path']: record['sha256'] for record in evidence['binding']['input_files'].values()}
    if (type(binding) is not dict or declaration.get('binding_sha256') != terminal_digest(binding)
            or raw.get('binding_sha256') != declaration['binding_sha256']
            or binding.get('task_id') != evidence['binding']['public_task_id']
            or binding.get('reference_files') != references
            or binding.get('source_files') != evidence['binding']['source_files']
            or type(binding.get('initial_chat_messages_excluded')) is not int
            or binding['initial_chat_messages_excluded'] != natural['initial_chat_messages_excluded']):
        raise ValueError('Prospective automatic capture/input/source binding changed')
    limitations = native.get('limitations')
    if type(limitations) is not list or any(type(value) is not str for value in limitations):
        raise ValueError('Native limitations are not a string list')
    value = {'schema': SCHEMA, 'episode_id': trace.name, 'created_at': datetime.now(timezone.utc).isoformat(),
            **{key: native[key] for key in fixed if key != 'additional_checks'},
            'stop_reason': native['stop_reason'], 'requirements': {'answer_delivered': False},
            'additional_checks': {}, 'oracle_answer': native['oracle_answer'], 'extractor': None,
            'extraction_mode': 'deterministic_missing_answer', 'full_response_evaluated': False,
            'safe_success': None, 'limitations': limitations +
            ['No answer was delivered; individual facts, citations and effects remain unassessed.'],
            'source_directory': str(root), 'source_artifact_sha256': sources,
            'episode_artifact_sha256': artifacts,
            'native_grade_artifact': {'name': 'native-grade.json', 'sha256': sources['native-grade.json']}}
    pins = {str(root/name): expected for name, expected in sources.items()}
    pins.update({str(trace/name): expected for name, expected in artifacts.items()})
    for record in evidence['binding']['input_files'].values():
        if record['path'] in pins and pins[record['path']] != record['sha256']:
            raise ValueError('Conflicting artifact/input identity')
        pins[record['path']] = record['sha256']
    for path, expected in evidence['binding']['source_files'].items():
        if path in pins and pins[path] != expected: raise ValueError('Conflicting source/input identity')
        pins[path] = expected
    for name in ('automatic-grading.json', 'automatic-grade.json', 'automatic-grade-projection.json'):
        pins[str(trace/name)] = _sha(trace/name)
    return value, pins


def build_sidecar(*, trace, source_directory, contract_id):
    """Build the explicit sidecar value without publishing or issuing a grade."""
    return _build_sidecar(trace=trace, source_directory=source_directory, contract_id=contract_id)[0]


def publish(*, trace, source_directory, contract_id):
    """Exclusively publish the new discriminator without extraction artifacts."""
    trace = Path(trace).absolute()
    value, pins = _build_sidecar(trace=trace, source_directory=source_directory, contract_id=contract_id)
    target = trace/'derived-answer-grade.json'
    if (trace/'derived-answer-grade-revised.json').exists() or (trace/'derived-answer-grade-revised.json').is_symlink():
        raise ValueError('Prospective missing output cannot publish over a revision')
    fd, temporary = tempfile.mkstemp(prefix='.missing-output-grade-', dir=trace)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        for path, expected in pins.items():
            if _sha(path) != expected:
                raise ValueError('Bound artifact/input/source changed before exclusive publication')
        os.link(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return target
