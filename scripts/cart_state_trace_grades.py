"""Append-only views of saved native cart grades; no extraction or regrading.

The compatibility view schema is unchanged. This reader additionally verifies
native state/authority bindings; the companion hub labels the view as state
grading instead of answer grading. It never certifies external effects.
"""
from copy import deepcopy
import datetime as dt
import json
from pathlib import Path

from experiments.accepted_catalog_commerce.execution import _bind
from scripts import trace_grades as legacy

VERSION = 'browser-captured-cart-state-view-v1'
SCOPE = 'captured_cart_state'
NATIVE_FILES = ('cart-grade.private.json', 'cart-capsule.private.json',
                'cart-capture-provenance.private.json')
CHECK_NAMES = ('cart_allocation', 'policy_completion', 'generated_commit_authority')


def descriptor(path):
    path = Path(path).absolute()
    if path.is_symlink() or not path.is_file():
        raise ValueError('Missing or symlinked state evidence: '+str(path))
    return {'path': str(path), 'sha256': legacy.sha(path)}


def checked_json(binding):
    path = Path(binding['path'])
    if descriptor(path) != binding:
        raise ValueError('State evidence changed: '+str(path))
    return json.loads(path.read_text())


def boolean_status(component):
    status = component.get('status', 'inconclusive')
    if status not in ('pass', 'fail', 'inconclusive'):
        raise ValueError('Unsupported native component status')
    return {'pass': True, 'fail': False, 'inconclusive': None}[status]


def _native_projection(directory, bindings):
    """Deterministic presentation of saved output, never calling the grader."""
    directory = Path(directory).resolve()
    if not set(NATIVE_FILES) <= set(bindings):
        raise ValueError('Incomplete native grade bindings')
    grade, capsule, provenance = [checked_json(bindings[n]) for n in NATIVE_FILES]
    for name in NATIVE_FILES:
        if Path(bindings[name]['path']) != directory/name:
            raise ValueError('Native grade belongs to another trace')
    if (grade.get('schema_version') != 'website-catalog-cart-grade-v1'
            or capsule.get('schema_version') != 'website-catalog-cart-capsule-v1'
            or capsule.get('episode_id') != directory.name
            or capsule.get('main_trace_sha256') != legacy.sha(directory/'steps.jsonl')
            or provenance.get('main_trace_sha256') != capsule['main_trace_sha256']):
        raise ValueError('Native episode/trace/schema binding differs')
    policy_task = json.loads((directory/'policy-task.json').read_text())
    if grade.get('task_id') != policy_task['task_id']:
        raise ValueError('Native grade task identity differs')
    required = set(NATIVE_FILES)
    for name, phase in [('before', 'before_policy'), ('after', 'after_policy_before_context_close')]:
        key = 'capture_'+name
        required.add(key)
        if bindings[key] != provenance['captures'][name]:
            raise ValueError('Raw state capture provenance differs')
        if not Path(bindings[key]['path']).resolve().is_relative_to(directory):
            raise ValueError('Raw state capture escaped its actual trace')
        raw = checked_json(bindings[key])
        if raw.get('phase') != phase or raw != capsule[name]:
            raise ValueError('Capsule does not contain the actual raw state')
    authority = None
    authority_pin = provenance.get('effect_authority')
    if authority_pin is not None:
        required.add('authority')
        if {k: authority_pin[k] for k in ('path', 'sha256')} != bindings['authority']:
            raise ValueError('Authority provenance differs')
        if Path(bindings['authority']['path']) != directory/'cart-authority.private.json':
            raise ValueError('Authority belongs to another trace')
        authority = checked_json(bindings['authority'])
        if authority.get('native_effect_envelope') != capsule.get('effect_journal'):
            raise ValueError('Capsule effect envelope differs from saved proof')
        approval_pin = authority.get('independent_acceptance')
        if approval_pin is not None:
            required.add('approval')
            if approval_pin != bindings['approval']:
                raise ValueError('Independent authority approval binding differs')
            approval = checked_json(bindings['approval'])
            if (authority.get('status') != 'accepted_empty_set_proof'
                    or authority.get('episode_id') != directory.name
                    or authority.get('main_trace_sha256') != capsule['main_trace_sha256']
                    or authority.get('captures') != provenance['captures']
                    or authority.get('failures') != []
                    or approval.get('owner') != 'Product' or approval.get('status') != 'accepted'
                    or approval.get('authority_schema') != authority.get('schema')
                    or approval.get('helper_source_sha256') != authority.get('helper_source_sha256')
                    or approval.get('source_sha256') != authority['surface']['source_sha256']
                    or approval.get('stdlib_source_sha256') != authority['surface']['stdlib_source_sha256']):
                raise ValueError('Authority approval does not bind the captured source union')
        elif capsule.get('effect_journal') is not None:
            raise ValueError('Unapproved effect envelope')
    elif capsule.get('effect_journal') is not None:
        raise ValueError('Effect envelope has no captured authority')
    if set(bindings) != required:
        raise ValueError('Unexpected or missing state bindings')
    components = grade['components']
    cart = components.get('cart', components.get('state', components.get('evidence', {})))
    effects = components.get('forbidden_effects', {})
    completion = components.get('policy_completion', {})
    checks = dict(zip(CHECK_NAMES, map(boolean_status, (cart, completion, effects))))
    if checks['generated_commit_authority'] is True and (
            authority is None or authority.get('independent_acceptance') is None):
        raise ValueError('Passing commit check without independently accepted evidence')
    if checks['policy_completion'] is True and provenance.get('policy_completed') is not True:
        raise ValueError('Passing completion check contradicts actual capture')
    if grade.get('verdict') not in ('pass', 'fail', 'inconclusive'):
        raise ValueError('Unsupported native verdict')
    verdict = {'pass': True, 'fail': False, 'inconclusive': None}[grade['verdict']]
    limitations = [*grade['limitations'],
        'Captured-state grade; no answer extraction, model inference or grader replay.',
        'Commit authority is a scoped read-only empty-set proof, not an observed event journal.',
        'Full response quality, external effects and broader safe success remain unknown.']
    return dict(structured_claims_correct=verdict, requirements=checks, additional_checks={},
        safe_success=None, full_response_evaluated=False, grading_scope=SCOPE,
        grading_version=grade['schema_version'], native_verdict=grade['verdict'],
        claims={'task_id': grade['task_id'], 'cart_outcome_correct': grade['cart_outcome_correct'],
                'components': deepcopy(components)}, oracle_answer={},
        source_artifact_sha256={b['path']: b['sha256'] for b in bindings.values()},
        derivations=[{'kind': 'saved_native_state_projection', 'grader_calls': 0,
                      'inference_calls': 0}], limitations=limitations,
        extractor={'kind': 'none', 'model': 'not used', 'provider': 'not used',
                   'version': VERSION, 'inference_calls': 0})


def publish(directory):
    """Create exactly one additive compatibility view; original outputs unchanged."""
    directory = Path(directory).resolve()
    bindings = {n: descriptor(directory/n) for n in NATIVE_FILES}
    provenance = checked_json(bindings[NATIVE_FILES[2]])
    for name in ('before', 'after'):
        bindings['capture_'+name] = deepcopy(provenance['captures'][name])
    if provenance.get('effect_authority') is not None:
        bindings['authority'] = {k: provenance['effect_authority'][k] for k in ('path', 'sha256')}
        authority = checked_json(bindings['authority'])
        if authority.get('independent_acceptance') is not None:
            bindings['approval'] = deepcopy(authority['independent_acceptance'])
    view = {**_native_projection(directory, bindings), 'schema': legacy.SCHEMA,
        'episode_id': directory.name, 'created_at': dt.datetime.now(dt.timezone.utc).isoformat(),
        'episode_artifact_sha256': {n: descriptor(directory/n)['sha256'] for n in legacy.BOUND_FILES},
        'native_state_bindings': bindings}
    with (directory/legacy.FILENAME).open('x', encoding='utf-8') as stream:
        json.dump(view, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    return view


def read_grade(directory):
    grade = legacy.read_grade(directory)
    if grade is None or grade.get('binding_status') != 'verified' or grade.get('grading_scope') != SCOPE:
        return grade
    try:
        projected = _native_projection(directory, grade['native_state_bindings'])
        if any(grade.get(k) != v for k, v in projected.items()):
            raise ValueError('State view differs from the bound native output')
        return grade
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {'binding_status': 'invalid', 'error': str(exc),
                'grading_scope': SCOPE, 'structured_claims_correct': None}


def project_grade(group, directory):
    grade = read_grade(directory)
    result = _bind(legacy.project_grade, read_grade=lambda _: grade)(group, directory)
    if grade is not None and grade.get('grading_scope') == SCOPE:
        label = ('captured-state grade invalid' if grade['binding_status'] != 'verified' else
                 'captured-state checks passed' if grade['structured_claims_correct'] is True else
                 'captured-state checks failed' if grade['structured_claims_correct'] is False else
                 'captured-state checks inconclusive')
        result['title'] = result['title'].replace(result['evaluation_label'], label)
        result['evaluation_label'] = label
        for note in result['messages']:
            if note.get('id') == result['id']+':derived-answer-grade':
                note['title'] = 'Captured-state grading — not model input'
                note['provenance'] = 'derived_post_episode_captured_state_evaluation'
    return result
