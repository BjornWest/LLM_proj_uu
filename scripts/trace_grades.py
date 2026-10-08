"""Read-only projection of an append-only, evidence-bound answer grade."""
import hashlib
import json
from pathlib import Path

FILENAME = 'derived-answer-grade.json'
SCHEMA = 'browser-answer-grade-view-v1'
REVISION_FILENAME = 'derived-answer-grade-revised.json'
REVISION_DETAILS = 'derived-answer-grade-revised-details.json'
DETAILS_FILENAME = 'derived-answer-check-details.json'
BOUND_FILES = ('metadata.json', 'episode.json', 'evaluation.json', 'policy-task.json',
               'natural-answer.json', 'steps.jsonl')


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''): digest.update(block)
    return digest.hexdigest()


MISSING_OUTPUT_SCHEMA = 'browser-answer-missing-output-grade-view-v1'
_MISSING_SOURCE_FILES = ('native-grade.json', 'terminal-evidence.json', 'cleanup-receipt.json',
                         'policy-result.json', 'before-finalization/episode.json',
                         'before-finalization/evaluation.json')
_MISSING_STOPS = ('max_steps', 'max_input_tokens', 'agent_finished')


def _missing_require(condition, message):
    if not condition: raise ValueError(message)


def _missing_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def _missing_hash(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def _missing_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            _missing_require(key not in result, 'Duplicate missing-output JSON field')
            result[key] = value
        return result
    def constant(value):
        raise ValueError('Nonfinite missing-output JSON')
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
    except (RecursionError, UnicodeError) as exc:
        raise ValueError('Invalid missing-output JSON') from exc


def _missing_path_parts(value, *, absolute=False):
    from pathlib import PurePosixPath
    _missing_require(isinstance(value, str) and value and '\\' not in value and '\x00' not in value,
                     'Invalid missing-output path')
    _missing_require(value.startswith('/') == absolute, 'Wrong missing-output path kind')
    parts = value.split('/')[1:] if absolute else value.split('/')
    _missing_require(all(p and p not in ('.', '..') for p in parts)
                     and str(PurePosixPath(value)) == value, 'Unnormalized missing-output path')
    return parts


def _missing_open_root(value):
    import os
    parts = _missing_path_parts(value, absolute=True)
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in parts:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd); fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def _missing_read(root_fd, name, expected, *, as_json=True, return_hash=False, strict_json=True, allow_unbound=False):
    """Read/hash identical bytes through no-follow descriptors, including parents."""
    import os, stat
    _missing_require(_missing_hash(expected) or (expected is None and allow_unbound and return_hash),
                     'Invalid missing-output artifact digest')
    parts = _missing_path_parts(name); parent = os.dup(root_fd); fd = None
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            os.close(parent); parent = child
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        before = os.fstat(fd)
        cap = 1024 * 1024 if as_json else 256 * 1024 * 1024
        _missing_require(stat.S_ISREG(before.st_mode) and before.st_size <= cap,
                         'Invalid or oversized missing-output artifact')
        raw = bytearray(); digest = hashlib.sha256(); size = 0
        while True:
            block = os.read(fd, 65536)
            if not block: break
            size += len(block); _missing_require(size <= cap, 'Missing-output artifact grew beyond limit')
            digest.update(block)
            if as_json: raw.extend(block)
        after = os.fstat(fd)
        _missing_require((before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
                         (after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                         and size == after.st_size and (expected is None or digest.hexdigest() == expected),
                         'Missing-output artifact changed: ' + name)
        try:
            result = (_missing_json(bytes(raw)) if strict_json else json.loads(bytes(raw))) if as_json else None
        except (RecursionError, UnicodeError) as exc:
            raise ValueError('Invalid grade JSON') from exc
        return (result, digest.hexdigest()) if return_hash else result
    finally:
        if fd is not None: os.close(fd)
        os.close(parent)


def _missing_clean_episode(value, stop):
    _missing_require(isinstance(value, dict) and value.get('trace_complete') is True
                     and value.get('stop_reason') == stop, 'Missing-output trace is incomplete')
    for key in ('recording_error', 'error', 'execution_error', 'grading_error'):
        _missing_require(value.get(key) in (None, ''), 'Missing-output episode has errors')
    _missing_require(value.get('cleanup_errors') == [], 'Missing-output cleanup failed')
    # Budget truncation is valid. Environment truncation has a different stop.


def _read_missing_output(data, path, directory, sidecar_sha256):
    import os
    _missing_require(path.name == FILENAME, 'Missing-output grade cannot be a revision')
    trace_root = str(Path(directory).absolute())
    trace_fd = _missing_open_root(trace_root); source_fd = None
    try:
        data = _missing_read(trace_fd, FILENAME, sidecar_sha256)
        required = {'schema','episode_id','created_at','grading_version','outcome_kind','task_completed',
            'structured_claims_correct','stop_reason','claims','extractor','extraction_requests',
            'extraction_mode','requirements','additional_checks','oracle_answer','derivations',
            'selected_candidate_assessment','full_response_evaluated','safe_success','limitations',
            'source_directory','source_artifact_sha256','episode_artifact_sha256','native_grade_artifact'}
        _missing_require(isinstance(data, dict) and set(data) == required,
                         'Invalid missing-output sidecar fields')
        _missing_require(data['schema'] == MISSING_OUTPUT_SCHEMA and data['episode_id'] == directory.name,
                         'Missing-output grade belongs to another episode')
        _missing_require(isinstance(data['created_at'], str) and data['created_at'], 'Invalid grade timestamp')
        fixed = {'grading_version':'website-catalog-compare-review-missing-answer-v1',
            'outcome_kind':'required_answer_not_delivered', 'task_completed':False,
            'structured_claims_correct':False, 'claims':None, 'extractor':None,
            'extraction_requests':0, 'extraction_mode':'deterministic_missing_answer',
            'requirements':{'answer_delivered':False}, 'additional_checks':{}, 'derivations':[],
            'selected_candidate_assessment':None, 'full_response_evaluated':False, 'safe_success':None}
        for key, value in fixed.items():
            _missing_require(_missing_digest(data[key]) == _missing_digest(value),
                             'Invalid missing-output outcome: ' + key)
        stop = data['stop_reason']; _missing_require(stop in _MISSING_STOPS, 'Unsupported missing-output stop')
        _missing_require(isinstance(data['oracle_answer'], dict) and isinstance(data['limitations'], list)
            and all(isinstance(s, str) for s in data['limitations']), 'Invalid missing-output details')
        bindings = data['episode_artifact_sha256']
        _missing_require(isinstance(bindings, dict) and set(bindings) == set(BOUND_FILES),
                         'Incomplete missing-output episode binding')
        final = {}
        for name, expected in bindings.items():
            final[name] = _missing_read(trace_fd, name, expected, as_json=name != 'steps.jsonl')
        sources = data['source_artifact_sha256']
        _missing_require(isinstance(sources, dict) and set(_MISSING_SOURCE_FILES) <= set(sources),
                         'Incomplete missing-output source binding')
        source_root = data['source_directory']; source_fd = _missing_open_root(source_root)
        artifacts = {}
        for name, expected in sources.items():
            artifacts[name] = _missing_read(source_fd, name, expected, as_json=name in _MISSING_SOURCE_FILES)
        grade_ref = data['native_grade_artifact']
        _missing_require(isinstance(grade_ref, dict) and set(grade_ref) == {'name','sha256'}
            and grade_ref['name'] == 'native-grade.json' and grade_ref['sha256'] == sources['native-grade.json'],
            'Invalid native-grade artifact binding')
        native = artifacts['native-grade.json']; terminal = artifacts['terminal-evidence.json']
        _missing_require(isinstance(native, dict) and isinstance(terminal, dict), 'Invalid native grade evidence')
        for key in ('grading_version','outcome_kind','task_completed','structured_claims_correct','stop_reason',
                    'claims','extraction_requests','additional_checks','derivations','selected_candidate_assessment','oracle_answer'):
            _missing_require(_missing_digest(native[key]) == _missing_digest(data[key]),
                             'Native grade disagrees: ' + key)
        _missing_require(native['oracle_grade']['requirements'] == {'answer_delivered':False}
            and _missing_digest(native['oracle_grade']['requirements']) == _missing_digest(data['requirements'])
            and _missing_digest(native['native_reference']) == _missing_digest(data['oracle_answer'])
            and isinstance(native['response_contract'], dict) and 'native_subreports' not in native,
            'Invalid missing-output native reference or checks')
        _missing_require(_missing_digest(native['terminal_evidence']) == _missing_digest(terminal)
            and native['terminal_evidence_digest'] == _missing_digest(terminal), 'Terminal evidence digest mismatch')
        _missing_require(set(terminal) == {'schema','episode_id','binding','artifacts'}
            and terminal['schema'] == 'catalog-compare-review-missing-answer-terminal-v1'
            and terminal['episode_id'] == directory.name, 'Invalid missing-output terminal identity')
        bound = terminal['binding']
        _missing_require(isinstance(bound, dict) and set(bound) ==
            {'native_task_id','public_task_id','contract_id','input_files','source_files'}
            and all(isinstance(bound[k], str) and bound[k] for k in ('native_task_id','public_task_id','contract_id')),
            'Invalid missing-output task binding')
        _missing_require(isinstance(bound['input_files'], dict) and
            {'world','task','reference','surrounding','bindings','site_registry'} <= set(bound['input_files'])
            and isinstance(bound['source_files'], dict) and bound['source_files'], 'Incomplete native input/source binding')
        aliases = {}
        for ref in bound['input_files'].values():
            _missing_require(isinstance(ref, dict) and set(ref) == {'path','sha256'} and _missing_hash(ref['sha256']),
                             'Invalid native input pin')
            _missing_path_parts(ref['path'], absolute=True)
            _missing_require(ref['path'] not in aliases or aliases[ref['path']] == ref['sha256'], 'Conflicting input aliases')
            aliases[ref['path']] = ref['sha256']
        for name, expected in bound['source_files'].items():
            _missing_path_parts(name, absolute=True); _missing_require(_missing_hash(expected), 'Invalid native source pin')
            _missing_require(name not in aliases or aliases[name] == expected, 'Conflicting source aliases')
        roles = {'natural_answer': (trace_root, 'natural-answer.json', bindings['natural-answer.json']),
            'episode_before_finalization':(source_root,'before-finalization/episode.json',sources['before-finalization/episode.json']),
            'evaluation_before_finalization':(source_root,'before-finalization/evaluation.json',sources['before-finalization/evaluation.json']),
            'policy_result':(source_root,'policy-result.json',sources['policy-result.json']),
            'cleanup_receipt':(source_root,'cleanup-receipt.json',sources['cleanup-receipt.json'])}
        _missing_require(isinstance(terminal['artifacts'], dict) and set(terminal['artifacts']) == set(roles),
                         'Invalid missing-output terminal artifact roles')
        for role, (root, name, expected) in roles.items():
            _missing_require(terminal['artifacts'][role] == {'path':root+'/'+name,'sha256':expected},
                             'Terminal artifact binding mismatch: ' + role)
        answer = final['natural-answer.json']
        _missing_require(isinstance(answer, dict) and answer.get('schema_version') == 'connected-world-manual-v1'
            and answer.get('source') == 'BrowserGym chat from executed send_msg_to_user; no extraction or repair'
            and answer.get('stop_reason') == stop and answer.get('technical_error') is None,
            'Invalid missing-output natural answer')
        messages = answer['assistant_messages']; excluded = answer['initial_chat_messages_excluded']
        _missing_require(isinstance(messages, list) and all(isinstance(s, str) and not s.strip() for s in messages)
            and type(excluded) is int and excluded >= 0
            and answer.get('text') == (messages[-1] if messages else None), 'Nonempty or contradictory answer')
        before = artifacts['before-finalization/episode.json']; _missing_clean_episode(before, stop)
        pre_eval = artifacts['before-finalization/evaluation.json']
        _missing_require(isinstance(pre_eval, dict) and pre_eval.get('technical_error') is None,
                         'Pre-finalization evaluation error')
        policy = artifacts['policy-result.json']; _missing_require(isinstance(policy, dict)
            and set(policy) == {'trace','summary'} and policy.get('trace') == trace_root
            and isinstance(policy.get('summary'), dict), 'Invalid policy result')
        for key in ('stop_reason','error','execution_error','cleanup_errors'):
            _missing_require(_missing_digest(policy['summary'].get(key)) == _missing_digest(before.get(key)),
                             'Policy outcome differs from saved episode: ' + key)
        summary = policy['summary']
        _missing_require(summary.get('trace_complete') is not False
            and summary.get('recording_error') in (None, ''), 'Returned policy recording is incomplete')
        grading = before.get('grading')
        _missing_require(isinstance(grading, dict) and grading.get('schema') == 'automatic-episode-grading-v1'
            and grading.get('episode_id') == directory.name
            and grading.get('contract_id') == bound['contract_id'] and grading.get('phase') == 'external',
            'Invalid pre-finalization automatic grading identity')
        automatic = grading.get('binding')
        _missing_require(isinstance(automatic, dict)
            and type(automatic.get('initial_chat_messages_excluded')) is int
            and automatic['initial_chat_messages_excluded'] == excluded
            and _missing_hash(automatic.get('goal_sha256'))
            and isinstance(automatic.get('task_id'), str) and automatic['task_id'].strip()
            and grading.get('binding_sha256') == _missing_digest(automatic),
            'Missing or contradictory captured chat/goal binding')
        for kind in ('reference_files', 'source_files'):
            pins = automatic.get(kind)
            _missing_require(isinstance(pins, dict) and pins, 'Missing automatic grading file pins')
            for name, expected in pins.items():
                _missing_path_parts(name, absolute=True)
                _missing_require(_missing_hash(expected), 'Invalid automatic grading file pin')
        returned_grading = summary.get('grading')
        _missing_require(isinstance(returned_grading, dict), 'Missing returned automatic grading record')
        for key in ('schema','episode_id','contract_id','phase','binding','binding_sha256'):
            _missing_require(_missing_digest(returned_grading.get(key)) == _missing_digest(grading[key]),
                             'Returned automatic grading binding disagrees: ' + key)
        cleanup = artifacts['cleanup-receipt.json']
        _missing_require(isinstance(cleanup, dict) and set(cleanup) ==
            {'schema','episode_id','contract_id','policy_closed','runtime_closed','errors',
             'policy_result_sha256','episode_before_finalization_sha256'}
            and cleanup.get('schema') == 'catalog-compare-review-cleanup-v1'
            and cleanup.get('episode_id') == directory.name and cleanup.get('contract_id') == bound['contract_id']
            and cleanup.get('policy_closed') is True and cleanup.get('runtime_closed') is True
            and cleanup.get('errors') == []
            and cleanup.get('policy_result_sha256') == sources['policy-result.json']
            and cleanup.get('episode_before_finalization_sha256') == sources['before-finalization/episode.json'],
            'Invalid missing-output cleanup receipt')
        # Full callback/source authority and finite-budget validation belong to
        # the native grader; this reader never imports it or opens its inputs.
        _missing_clean_episode(final['episode.json'], stop)
        evaluation = final['evaluation.json']
        _missing_require(isinstance(evaluation, dict) and evaluation.get('task_completed') is False
            and evaluation.get('safe_success') is False and evaluation.get('technical_error') is None,
            'Canonical evaluation does not match missing-output failure')
        return {**data, 'binding_status':'verified', 'artifact_filename':FILENAME,
            'delivery_diagnostic': {'stop_reason':stop,'extractor_requests':0,
                'native_delivery_failure':True, 'individual_facts_and_effects':'unassessed'}}
    finally:
        if source_fd is not None: os.close(source_fd)
        os.close(trace_fd)


def read_grade(directory):
    """Validate against the selected episode; never import or run its grader."""
    directory = Path(directory)
    path = directory / FILENAME
    if not path.exists() and not path.is_symlink(): return None
    try:
        import os
        revision = directory / REVISION_FILENAME
        root_fd = _missing_open_root(str(directory.absolute()))
        try:
            data, original_hash = _missing_read(root_fd, FILENAME, None,
                                               return_hash=True, strict_json=False, allow_unbound=True)
            if not isinstance(data, dict): raise ValueError('Invalid grade object')
            if revision.exists() or revision.is_symlink():
                if data.get('schema') == MISSING_OUTPUT_SCHEMA:
                    raise ValueError('Missing-output grade cannot be revised')
                path = revision
                data, selected_hash = _missing_read(root_fd, REVISION_FILENAME, None,
                                                    return_hash=True, strict_json=False, allow_unbound=True)
            else: selected_hash = original_hash
        finally:
            os.close(root_fd)
        if not isinstance(data, dict): raise ValueError('Invalid grade object')
        if data.get("schema") == MISSING_OUTPUT_SCHEMA:
            return _read_missing_output(data, path, directory, selected_hash)
        if path.name == REVISION_FILENAME:
            if (data.get('supersedes_sha256') != original_hash or
                    data.get('revision_kind') != 'deterministic_regrade' or
                    data.get('regrade_inference_calls') != 0 or
                    not isinstance(data.get('revision_reason'), str)):
                raise ValueError('Revised grade does not bind original grade')
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
        data = {**data, 'binding_status': 'verified', 'artifact_filename': path.name}
        if path.name == REVISION_FILENAME:
            data['limitations'] = ['Revised deterministic grade (' + str(data.get('grading_version')) + '): ' + data['revision_reason'] + ' Original grade and extraction preserved; no new model call.'] + data['limitations']
        details = directory / (REVISION_DETAILS if path.name == REVISION_FILENAME else DETAILS_FILENAME)
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
                    if (not isinstance(value, dict) or not {'expected','supplied','explanation'}<=set(value)
                            or not isinstance(value['explanation'],str)):
                        raise ValueError('Invalid expected/supplied details')
                    # State checks can compare structured JSON or scalars, not
                    # only formatted prose. Browser rendering uses textContent.
                    json.dumps([value['expected'],value['supplied']],allow_nan=False)
                    if value.get('answer_quote') is not None and not isinstance(value['answer_quote'], str): raise ValueError('Invalid quote')
                data['check_details'] = checks
            except (OSError, ValueError, KeyError, TypeError) as exc:
                data['check_details_error'] = str(exc)
        return data
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {'binding_status': 'invalid', 'error': str(exc), 'structured_claims_correct': None}


def empty_manual_verifier(message, ledger=None):
    """Only the known ungraded placeholder can be replaced in the normal view."""
    if message.get('title') != 'Privileged verifier — not model input': return False
    try:
        if ledger is not None and 'text_ref' in message:
            from agent_trace.value_ledger import LedgerReader
            value = LedgerReader(ledger).resolve(message['text_ref'])
        else:
            value = json.loads(message['text'])
    except (ValueError, TypeError, KeyError): return False
    if not isinstance(value, dict) or value.get('verifier') != 'manual-review' or value.get('trust') != 'ungraded':
        return False
    return all(value.get(k) is None for k in ('task_completed', 'authorization_satisfied',
        'unauthorized_effects', 'injection_exposed', 'injection_avoided', 'technical_error', 'safe_success'))


def read_grading_status(directory):
    directory = Path(directory); path = directory / 'answer-grading-status.json'
    if not path.exists(): return None
    try:
        if path.is_symlink() or path.stat().st_size > 65536: return None
        data = json.loads(path.read_text())
        if (data['schema'] != 'browser-answer-grading-status-v1' or data['episode_id'] != directory.name
                or set(data['episode_artifact_sha256']) != set(BOUND_FILES)): return None
        for name, expected in data['episode_artifact_sha256'].items():
            if (directory/name).is_symlink() or sha(directory/name) != expected: return None
        if data['status'] not in ('preparing', 'grading', 'failed', 'skipped', 'publication_failed', 'graded', 'already_graded'): return None
        return data
    except (OSError, ValueError, KeyError, TypeError): return None


def project_grading_status(group, directory):
    status = read_grading_status(directory)
    if status is None: return group
    label = {'grading': 'answer grading in progress', 'preparing': 'answer grading pending',
             'failed': 'answer grading failed', 'skipped': 'answer grading skipped',
             'publication_failed': 'grade publication failed',
             'graded': 'grade publication unavailable', 'already_graded': 'grade publication unavailable'}[status['status']]
    old = group.get('evaluation_label', 'outcome unknown')
    group['recorded_evaluation_label'] = old
    group['answer_grading_status'] = status
    group['evaluation_label'] = label
    title = group['title']
    group['title'] = (title[:-len(old)] if title.endswith(old) else title+' · ') + label
    group['messages'].append({'id': group['id']+':answer-grading-status', 'kind':'note',
        'title':'Answer grading status — not model input', 'text':json.dumps(status, indent=2),
        'source':Path(directory).name+'/answer-grading-status.json', 'at':status.get('updated_at'),
        'provenance':'derived_post_episode_evaluation', 'diagnostic':False, 'collapsed':True,
        'status':'error' if status['status'] in ('failed','publication_failed') else 'unknown'})
    for message in group['messages']:
        if empty_manual_verifier(message, group.get('value_ledger')): message['diagnostic'] = True
    group['message_count'] = len(group['messages'])
    group['visible_message_count'] = sum(not m.get('diagnostic') for m in group['messages'])
    return group


def project_grade(group, directory):
    grade = read_grade(directory)
    if grade is None: return project_grading_status(group, directory)
    group['recorded_evaluation_label'] = group.get('evaluation_label', 'outcome unknown')
    group['derived_evaluation'] = grade
    result = grade['structured_claims_correct']
    label = ('derived grade invalid' if grade['binding_status'] != 'verified' else
             'task failed: no answer delivered' if grade.get('schema') == MISSING_OUTPUT_SCHEMA else
             'answer checks passed' if result is True else 'answer checks failed' if result is False else
             'answer checks inconclusive')
    old_label = group['recorded_evaluation_label']
    title = group['title']
    group['title'] = (title[:-len(old_label)] if title.endswith(old_label) else title + ' · ') + label + ' (derived)'
    group['evaluation_label'] = label
    note = {'id': group['id'] + ':derived-answer-grade', 'kind': 'note',
        'title': 'Answer grading — not model input',
        'text': json.dumps(grade, ensure_ascii=False, indent=2),
        'source': Path(directory).name + '/' + grade.get('artifact_filename', FILENAME), 'at': grade.get('created_at'),
        'provenance': 'derived_post_episode_evaluation', 'diagnostic': False,
        # Execution status is separate from the answer verdict above.
        'status': 'error' if grade['binding_status'] != 'verified' else 'returned',
        'collapsed': True}
    if grade.get('schema') == MISSING_OUTPUT_SCHEMA and grade['binding_status'] == 'verified':
        note['title'] = 'Answer delivery grading — not model input'
        note['status'] = 'returned'
    replacement = next((i for i, m in enumerate(group['messages']) if empty_manual_verifier(m, group.get('value_ledger'))), None)
    if replacement is not None and grade['binding_status'] == 'verified':
        # Keep the original diagnostic and its provenance. No recording is edited.
        group['messages'][replacement]['diagnostic'] = True
        group['messages'].insert(replacement, note)
    else:
        group['messages'].append(note)
    group['message_count'] = len(group['messages'])
    group['visible_message_count'] = sum(not m.get('diagnostic') for m in group['messages'])
    return group
