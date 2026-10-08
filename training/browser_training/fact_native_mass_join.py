"""Exact approved two-row mass/basis conjunction; no Website modification.

The caller pins the Product decision and task. Availability may use private
actual captures; delivery uses only confirmed scoped transport records. These
paths share a join but never share evidence or an answer-key-derived value.
"""
from collections import Counter, defaultdict
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from .fact_compare_review_features import project as base_project
from .fact_exposure import object_digest, require
from .fact_public_readiness import _parts, audit_captures as base_audit

MASS = 'product.facts.reference_mass_g'
BASIS = 'product.facts.mass_basis'
LITERAL = 'one item, EU 40 reference configuration'
TASK_ID = 'catalog-compare-review-6765f187a46d71e19529eb94'
ROLES = [f'model_{i}.fact.{MASS}' for i in (1, 2)]
DECLARATIONS = {
    'environments/product_world/data/product_packages/footwear.walking_shoes.json':
        'c72d08c0965876cc383ea245b8fc74646dbe32275d6dd035309b7271f57d082f',
    'environments/product_world/data/product_feature_policies/catalogue_v2/footwear.walking_shoes.json':
        'f1b3122b825e58ca5ec8a4e63ad51091938ed7907cd36196f9598ccdaa593d11'}


def load_contract(task_path, decision_path, source_root):
    """Check the exact approved task/declarations before interpreting these rows."""
    task_bytes = Path(task_path).read_bytes()
    decision_bytes = Path(decision_path).read_bytes()
    task, decision = json.loads(task_bytes), json.loads(decision_bytes)
    scope = decision['scope']
    require(decision['status'] == 'accepted_exact_scoped_consumer_semantic_join'
            and decision['task']['sha256'] == sha256(task_bytes).hexdigest()
            and task['task_id'] == scope['task_id'] == TASK_ID
            and scope['concept_id'] == 'footwear.walking_shoes'
            and scope['roles'] == ROLES and scope['mass_field'] == MASS
            and scope['basis_field'] == BASIS and scope['unit'] == 'g'
            and scope['basis'] == LITERAL and scope['grain'] == 'manufactured_product_model'
            and decision['source_declarations'] == DECLARATIONS,
            'Foreign or unsupported mass contract')
    for relative, expected in DECLARATIONS.items():
        require(sha256((Path(source_root) / relative).read_bytes()).hexdigest() == expected,
                'Mass declaration changed')
    return {'task_sha256': object_digest(task), 'decision_sha256': sha256(decision_bytes).hexdigest(),
            'declarations': deepcopy(DECLARATIONS), 'roles': ROLES.copy()}


def _identity(record, role):
    b, state = record['binding'], record['effective_state']
    pid = role['product_id']
    if (b.get('source_family') != 'retailer' or b.get('authority') != 'native_public_field'
            or b.get('subject_type') != 'product' or b.get('subject_id') != pid
            or b.get('product_id') != pid or state.get('product_id') != pid
            or b.get('field') not in (MASS, BASIS)):
        return None
    scope = record.get('render_scope', {})
    require(all(isinstance(b.get(k), str) and b[k] for k in ('site_id', 'page_id')),
            'Missing site/page identity')
    require(state.get('site') == b['site_id'] and state.get('page_id') == b['page_id'],
            'Conflicting occurrence/state authority')
    require(all(isinstance(scope.get(k), str) and scope[k] for k in ('document_id', 'frame_id'))
            and type(scope.get('render_revision')) is int and scope['render_revision'] >= 0,
            'Missing qualified render scope')
    return object_digest({'source_family': b['source_family'], 'site_id': b['site_id'],
        'page_id': b['page_id'], 'subject_id': pid, 'state': state, 'render_scope': scope})


def _value(record):
    """None means incomplete evidence; invalid complete evidence raises."""
    parts = record.get('parts', {})
    if not all(parts.get(k, {}).get('status') == 'complete' for k in ('label', 'value')):
        return None
    require(all(parts[k].get('source_mapping_complete') is True for k in ('label', 'value')),
            'Unmapped complete part')
    require(record.get('source_spans'), 'Missing exact source spans')
    b = record['binding']
    require(b.get('status') in (None, 'known'), 'Unknown/NA public scalar')
    value = b.get('displayed_value')
    label, text = parts['label'].get('observed_text'), parts['value'].get('observed_text')
    if b['field'] == MASS:
        require(type(value) is int and 0 <= value <= 2**53 - 1
                and label == 'Reference mass g' and text == str(value)
                and b.get('unit') in (None, 'g'), 'Invalid observed mass/unit')
    else:
        require(type(value) is str and value == text == LITERAL and label == 'Mass basis'
                and b.get('unit') is None, 'Invalid observed measurement basis')
    return value


def join_role(role, records):
    """Resolve conjunction before any reference comparison; conflicts stay unknown."""
    groups = defaultdict(lambda: {MASS: [], BASIS: []})
    used, errors, observed_values = [], [], set()
    partial = False
    for record in records:
        try:
            key = _identity(record, role)
            if key is None:
                continue
            value = _value(record)
            partial |= any(p.get('observed_utf16', 0) > 0 for p in record.get('parts', {}).values())
            if value is None:
                continue
            groups[key][record['binding']['field']].append(record)
            if record['binding']['field'] == MASS:
                observed_values.add(value)
        except (KeyError, TypeError, ValueError) as exc:
            errors.append({'record': record.get('id'), 'reason': str(exc)})
    if errors or len(observed_values) > 1:
        return {'observation_status': 'unknown', 'reason': 'conflicting_or_invalid_scoped_evidence',
                'evidence': [], 'diagnostics': errors}
    evidence = []
    for key, rows in sorted(groups.items()):
        if rows[MASS] and rows[BASIS]:
            hits = rows[MASS] + rows[BASIS]
            used.extend(r['id'] for r in hits)
            evidence.append({'join_scope_sha256': key,
                'render_scope': hits[0]['render_scope'], 'effective_state': hits[0]['effective_state'],
                'observed_value': rows[MASS][0]['binding']['displayed_value'], 'unit': 'g', 'basis': LITERAL,
                'records': [{'id': r['id'], 'occurrence_ids': r['occurrence_ids'],
                    'binding': r['binding'], 'source_spans': r['source_spans'],
                    'content_ids': r.get('content_ids', [])} for r in hits]})
    return {'observation_status': 'complete' if evidence else 'partial' if partial else 'unknown',
            'reason': None if evidence else 'both_complete_labeled_rows_in_same_render_required',
            'native_record_ids': sorted(set(used)), 'evidence': evidence, 'diagnostics': errors}


def project(task, native, contract):
    require(object_digest(task) == contract['task_sha256'], 'Unapproved task projection')
    result = base_project(task, native)
    for row in result['roles']:
        if row['role_id'] in contract['roles']:
            require(row['field'] == MASS and row.get('unit') == 'g' and row.get('basis') == LITERAL,
                    'Unapproved mass role')
            row.update(join_role(row, native['records']))
            row['semantic_contract'] = deepcopy(contract)
    counts = Counter(r['observation_status'] for r in result['roles'])
    result['features'].update({f'{s}_role_count': counts[s] for s in ('complete', 'partial', 'unknown')})
    return result


def audit_captures(task, reference, paths, *, runtime_binding_sha256, contract):
    """Add only scoped mass evidence to the existing actual-source audit."""
    require(object_digest(task) == contract['task_sha256'], 'Unapproved task audit')
    result = base_audit(task, reference, paths, runtime_binding_sha256=runtime_binding_sha256)
    records = []
    for filename in paths:
        path = Path(filename).resolve()
        raw = path.read_bytes()
        require(sha256(raw).hexdigest() == result['files'][str(path)],
                'Capture changed between public-audit passes')
        saved = json.loads(raw)
        normalized = saved.get('normalized', saved)
        for occurrence in normalized['occurrences']:
            if occurrence['binding'].get('field') not in (MASS, BASIS):
                continue
            try:
                texts = _parts(normalized, occurrence)
                scope = {k: normalized[k] for k in ('document_id', 'frame_id', 'render_revision')}
                spans = [{**span, 'part': part['part'], 'document': str(path),
                          'document_sha256': result['files'][str(path)]}
                         for part in occurrence['parts'] for span in part['spans']]
                records.append({'id': object_digest({'document': str(path), 'occurrence': occurrence['id']}),
                    'binding': deepcopy(occurrence['binding']), 'effective_state': occurrence['effective_state'],
                    'render_scope': scope, 'occurrence_ids': [occurrence['id']], 'source_spans': spans,
                    'parts': {name: {'status': 'complete', 'source_mapping_complete': True,
                                      'observed_text': text} for name, text in texts.items()}})
            except (KeyError, TypeError, ValueError) as exc:
                result['diagnostics'].append({'document': str(path), 'occurrence': occurrence['id'],
                                              'reason': str(exc)})
    roles = {r['role_id']: r for r in task['required_obligations']}
    expected = {m['product_id']: m['facts'][MASS] for m in reference['comparison']['models']}
    for row in result['roles']:
        if row['role_id'] not in contract['roles']:
            continue
        joined = join_role(roles[row['role_id']], records)
        value = expected[row['product_id']]
        verified = (joined['observation_status'] == 'complete' and value['status'] == 'known'
                    and type(value['value']) is int and value.get('unit') == 'g'
                    and value.get('basis') == LITERAL
                    and all(e['observed_value'] == value['value'] for e in joined['evidence']))
        row.update(status='known' if verified else 'unresolved', evidence=joined['evidence'],
                   reason=None if verified else joined['reason'] or 'reference_disagrees_with_observed_join',
                   semantic_contract=deepcopy(contract))
        row['document'] = joined['evidence'][0]['records'][0]['source_spans'][0]['document'] if verified else None
        row['locator'] = 'conjunctive_native_mass_and_basis_rows' if verified else None
    result['status'] = 'sufficient' if all(r['status'] == 'known' for r in result['roles']) else 'unresolved'
    result['semantic_contract'] = deepcopy(contract)
    return result
