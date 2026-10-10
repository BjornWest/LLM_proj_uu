"""Prospective, opt-in product disclosure over already manufactured truth.

Policies are read/frozen once. This never samples products, evaluates package
programs or validates manufacturing. The producer supplies authoritative facts;
selection has a separate keyed stream and cannot alter manufacturing RNG state.
"""
from functools import lru_cache
from hashlib import sha256
import json
import math
import re
from pathlib import Path

from .shared_state import freeze, mutable

ROOT = Path(__file__).resolve().parents[2]
CATALOGUE = Path(__file__).parent / 'data/product_feature_policies/catalogue_v1'
VERSION = 'selected-product-content-v1'
DEFAULT_PROBABILITIES = {'highlight': .9, 'detail': .6, 'care': .65}


def _hash(path):
    return sha256(Path(path).read_bytes()).hexdigest()


@lru_cache(maxsize=256)
def load_policy(concept_id, *, verify_sources=False):
    """Load immutable policy once; source regression checks are explicitly opt-in."""
    manifest = _manifest()
    if concept_id not in manifest['concepts']:
        raise ValueError('No accepted publication policy: ' + str(concept_id))
    entry = manifest['concepts'][concept_id]
    path = CATALOGUE / entry['file']
    if _hash(path) != entry['sha256']:
        raise ValueError('Publication policy digest mismatch')
    policy = json.loads(path.read_text())
    if verify_sources:
        for name, expected in policy['source_sha256'].items():
            if _hash(ROOT / name) != expected:
                raise ValueError('Publication source changed: ' + name)
    return freeze(policy)


@lru_cache(maxsize=1)
def _manifest():
    return freeze(json.loads((CATALOGUE / 'manifest.json').read_text()))


def policy_sha256(concept_id):
    """Exact file digest cached in the catalogue manifest, not a new serialization."""
    return _manifest()['concepts'][concept_id]['sha256']


def _probabilities(values):
    result = dict(DEFAULT_PROBABILITIES)
    if values is not None:
        if not isinstance(values, dict) or set(values) - set(result):
            raise ValueError('Unknown disclosure probability control')
        result.update(values)
    if any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in result.values()):
        raise ValueError('Disclosure probabilities must be finite numbers in [0,1]')
    return result


def _draw(seed, retailer_id, product_id, concept_id, group_id):
    payload = json.dumps([VERSION, seed, retailer_id, product_id, concept_id, group_id], ensure_ascii=False, separators=(',', ':'))
    return int.from_bytes(sha256(payload.encode()).digest()[:8], 'big') / 2**64


_MISSING = object()


def _lookup(entities, path):
    value = entities
    for key in path.split('.'):
        if not isinstance(value, dict) or key not in value:
            return _MISSING
        value = value[key]
    return value


def _metadata(value, entities):
    if isinstance(value, dict):
        if set(value) == {'literal'}:
            return mutable(value['literal'])
        if set(value) == {'expr'}:
            expression = value['expr']
            if not isinstance(expression, str) or not re.fullmatch(r'[a-zA-Z_]\w*(?:\.[a-zA-Z_]\w*)+', expression):
                return _MISSING
            return _lookup(entities, expression)
        resolved = {key: _metadata(item, entities) for key, item in value.items()}
        return _MISSING if any(x is _MISSING for x in resolved.values()) else resolved
    if isinstance(value, list):
        resolved = [_metadata(item, entities) for item in value]
        return _MISSING if any(x is _MISSING for x in resolved) else resolved
    return value


def resolve_scalar_records(policy, entities, statuses):
    """Project already authoritative field/status results without graph replay.

    No applicability expression is recomputed. A varying field must have an
    explicit completed-caller status; a declared constant without conditional
    applicability may use its source declaration. Missing subject/qualifier
    inputs and compound-only mappings remain unpublishable.
    """
    records = {}
    for path, field in policy['fields'].items():
        if field['role'] not in {'literal', 'descriptive'} or not field['semantic_id']:
            continue
        value = _lookup(entities, path)
        if value is _MISSING:
            continue
        definition = field['definition']
        status = statuses.get(path)
        if isinstance(status, dict):
            status = 'not_applicable' if status.get('applicable') is False else 'known' if status.get('known') is True else 'unknown'
        if status is None and 'constant' in definition and not definition.get('applicable_when'):
            constant = definition['constant']
            if type(value) is type(constant) and value == constant:
                status = 'known'
        for name, label in [('unknown_values', 'unknown'), ('not_applicable_values', 'not_applicable')]:
            if any(type(value) is type(v) and value == v for v in definition.get(name, [])):
                status = label
        if status != 'known':
            continue
        template = field['subject']
        if not template or not template.get('id_expr'):
            continue
        subject_id = _lookup(entities, template['id_expr'])
        qualifiers = _metadata(field['required_qualifiers'], entities)
        if subject_id is _MISSING or qualifiers is _MISSING:
            continue
        subject = {'kind': template['kind'], 'id': subject_id}
        failed = False
        for key, raw in template.items():
            if key in {'kind','id_expr'}:
                continue
            resolved = _lookup(entities, raw) if key.endswith('_expr') else raw
            if resolved is _MISSING:
                failed = True
                break
            subject[key.removesuffix('_expr')] = mutable(resolved)
        if failed:
            continue
        semantic_status = qualifiers.get('semantic_status')
        if semantic_status is not None and semantic_status != 'known':
            continue
        if definition.get('basis'):
            qualifiers.setdefault('basis', definition['basis'])
        if definition.get('component'):
            subject.setdefault('component', definition['component'])
        records[path] = {'semantic_id': field['semantic_id'], 'field': path,
                         'authority': 'catalog_fact', 'subject': subject,
                         'value': mutable(value), 'status': 'known', 'unit': definition.get('unit'),
                         'qualifiers': mutable(qualifiers)}
    return records


def select_content(policy, facts, *, seed, retailer_id, product_id,
                   probabilities=None, selected_groups=None):
    """Select scoped scalar records; no raw-fact/paragraph fallback is allowed.

    `facts` maps field paths to authoritative resolved records. Compound-only
    assertion mappings require an atomic prose adapter and are not silently
    converted into scalar meanings here. Explicit groups are a fixture/control
    override, not a task-dependent feasibility repair.
    """
    if type(seed) is not int or not all(type(x) is str and x for x in (retailer_id, product_id)):
        raise ValueError('Declare seed and retailer/product identity')
    probabilities = _probabilities(probabilities)
    groups = policy['disclosure_groups']
    requested = None if selected_groups is None else set(selected_groups)
    if requested is not None and requested - set(groups):
        raise ValueError('Unknown disclosure group')
    selected, highlights, withheld = [], [], []
    for key, group in groups.items():
        category = 'care' if group['display_group'] == 'care' else 'highlight' if group['highlight_candidate'] else 'detail'
        choose = key in requested if requested is not None else _draw(seed, retailer_id, product_id, policy['concept_id'], key) < probabilities[category]
        records = []
        if choose:
            for path in group['fields']:
                record, definition = facts.get(path), policy['fields'][path]
                if record is None or record.get('status') != 'known' or record.get('applicable') is False:
                    continue
                semantic_id = definition['semantic_id']
                if not semantic_id:  # preserve compound meanings for their own adapter
                    continue
                if record.get('semantic_id') != semantic_id or record.get('field') != path:
                    raise ValueError('Resolved field identity differs from publication policy')
                records.append(mutable(record))
        if not records:
            withheld.append(key)
            continue
        slot = {'id': group['id'], 'group_key': key, 'display_group': group['display_group'],
                'fields': [r['field'] for r in records], 'assertions': records}
        selected.append(slot)
        if group['highlight_candidate']:
            highlights.append({'slot_id': slot['id'], 'priority': group['highlight_priority']})
    display = []
    for key, definition in policy['display_groups'].items():
        slots = [x for x in selected if x['display_group'] == key]
        if slots:
            display.append({'key': key, 'label': definition['label'],
                            'preferred_representation': definition['preferred_representation'], 'slots': slots})
    return {'schema': VERSION, 'concept_id': policy['concept_id'], 'product_id': product_id,
            'retailer_id': retailer_id, 'display_groups': display,
            'highlight_candidates': highlights, 'withheld_groups': withheld,
            'source_sha256': mutable(policy['source_sha256']),
            'family_rules_sha256': policy['family_rules_sha256'],
            'concept_exceptions_sha256': policy['concept_exceptions_sha256'],
            'probabilities': probabilities,
            'limits': ['Selected content only; buying controls, stock, prices and delivery remain in their native contracts.']}
