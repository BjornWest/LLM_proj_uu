"""Typed, recipient-scoped shopping defaults; prose follows meaning, not NLP.

Known-recipient tasks only. Ambiguity is surfaced before sampling; it is not a
no-stock answer. No persistent memory writes, temporal precedence or gender inference.
"""
from copy import deepcopy
import json
from math import inf, isfinite, floor, ceil
import re

from experiments.accepted_catalog_commerce import package_export
from .catalog_predicates import PredicateSet, OPERATORS, _same
from .feature_offer_task import _wording
from .adapter import digest

VERSION = 'website-catalog-scoped-memory-v1'
APPAREL = frozenset({'footwear', 'jackets', 'trousers', 'tops', 'knitwear'})


class ClarificationRequired(ValueError):
    def __init__(self, reason, *, fields=()):
        super().__init__(reason)
        self.reason, self.fields = reason, tuple(fields)


def _id(value):
    return type(value) is str and re.fullmatch(r'[a-z][a-z0-9_-]{0,63}', value) is not None


def _scope(value):
    if type(value) is not dict or len(value) != 1:
        raise ValueError('Declare one concept, family or clothing_footwear memory scope')
    key = next(iter(value)); scope = value[key]
    if key == 'domain':
        if scope != 'clothing_footwear':
            raise ValueError('Only the declared clothing/footwear shared default domain is supported')
    elif key in ('concept_ids', 'family_ids'):
        allowed = (set(package_export.SUPPORTED_CONCEPTS) if key == 'concept_ids' else
                   {cid.split('.')[0] for cid in package_export.SUPPORTED_CONCEPTS})
        if (type(scope) is not list or not scope or any(type(s) is not str or s not in allowed for s in scope)
                or len(set(scope)) != len(scope)):
            raise ValueError('Memory scope must name unique adopted concepts/families')
    else:
        raise ValueError('Unknown memory scope')
    return deepcopy(value)


def applies(scope, concept_id):
    if 'concept_ids' in scope:
        return concept_id in scope['concept_ids']
    if 'family_ids' in scope:
        return concept_id.split('.')[0] in scope['family_ids']
    return concept_id.split('.')[0] in APPAREL


def _structural(predicates):
    if type(predicates) is not list or not predicates:
        raise ValueError('A memory must declare a nonempty predicate bundle')
    for p in predicates:
        if (type(p) is not dict or set(p)-{'field', 'operator', 'value', 'unit'} or
                not {'field', 'operator', 'value'} <= set(p) or
                type(p['field']) is not str or not re.fullmatch(r'(?:product\.facts|sku)(?:\.[a-z][a-z0-9_]*)+', p['field']) or
                type(p['operator']) is not str or p['operator'] not in OPERATORS):
            raise ValueError('Malformed typed memory predicate')
        # Native applicable records get full declaration validation below.
        # Inactive record meanings may use another concept's vocabulary.
        values = p['value'] if p['operator'] in ('in', 'not_in') else [p['value']]
        if (type(values) is not list or not values or
                any(type(v) not in (str, bool, int, float) or type(v) is float and not isfinite(v) for v in values) or
                p['operator'] in ('ge', 'le', 'gt', 'lt') and type(p['value']) not in (int, float) or
                'unit' in p and type(p['unit']) is not str):
            raise ValueError('Memory values must use finite scalar predicate operands')
        json.dumps(p, allow_nan=False)  # Not an inactive field/domain type proof.


def conflicts(fields, predicates):
    """Finite local contradictions, not product correlations or a SAT claim."""
    bad = []
    for field in sorted({p['field'] for p in predicates}):
        ps = [p for p in predicates if p['field'] == field]
        def holds(value, p):
            op, target = p['operator'], p['value']
            if op == 'eq': return _same(value, target)
            if op == 'ne': return not _same(value, target)
            if op == 'in': return any(_same(value, x) for x in target)
            if op == 'not_in': return not any(_same(value, x) for x in target)
            if op == 'ge': return value >= target
            if op == 'gt': return value > target
            if op == 'le': return value <= target
            if op == 'lt': return value < target
            return True
        eq = [p['value'] for p in ps if p['operator'] == 'eq']
        sets = [p['value'] for p in ps if p['operator'] == 'in']
        domain = fields[field].get('values', [False, True] if fields[field]['type'] == 'boolean' else None)
        values = eq[:1] or (sets[0] if sets else domain)
        if values is not None and not any(all(holds(v, p) for p in ps) for v in values):
            bad.append(field); continue
        lower = max([(p['value'], p['operator'] == 'gt') for p in ps if p['operator'] in ('ge', 'gt')], default=(-inf, False))
        upper = min([(p['value'], p['operator'] != 'lt') for p in ps if p['operator'] in ('le', 'lt')], default=(inf, True))
        if lower[0] > upper[0] or lower[0] == upper[0] and (lower[1] or not upper[1]):
            bad.append(field); continue
        if isfinite(lower[0]) and isfinite(upper[0]):
            if lower[0] == upper[0] and not all(holds(lower[0], p) for p in ps):
                bad.append(field); continue
            if fields[field]['type'] == 'integer':
                low = floor(lower[0])+1 if lower[1] else ceil(lower[0])
                high = ceil(upper[0])-1 if not upper[1] else floor(upper[0])
                excluded_numbers = {v for p in ps for v in
                    ([p['value']] if p['operator'] == 'ne' else p['value'] if p['operator'] == 'not_in' else [])
                    if type(v) is int and low <= v <= high}
                if low > high or len(excluded_numbers) == high-low+1:
                    bad.append(field); continue
        included = [p['value'] for p in ps if p['operator'] == 'contains']
        excluded = [p['value'] for p in ps if p['operator'] == 'excludes']
        if any(_same(a, b) for a in included for b in excluded):
            bad.append(field)
    return bad


def resolve(*, recipient, concept_id, explicit, records, inventory):
    if recipient is None or recipient == 'unspecified':
        raise ClarificationRequired('Establish the intended recipient before applying personal defaults')
    if not _id(recipient):
        raise ValueError('Declare a stable known recipient ID, including self for the shopper')
    if concept_id != inventory.concept_id or type(records) is not list:
        raise ValueError('Declare records for the target field inventory')
    current = PredicateSet(inventory.fields, explicit, known_paths=inventory.known_paths).predicates
    override_fields = {p['field'] for p in current}
    canonical, active, provenance, ids = [], [], [], set()
    for record in records:
        if (type(record) is not dict or set(record) != {'id', 'subject', 'scope', 'channel', 'predicates'} or
                not _id(record['id']) or not _id(record['subject']) or record['id'] in ids or
                record['channel'] not in ('profile', 'episodic')):
            raise ValueError('Declare unique memory IDs, subject, scope, channel and predicates')
        ids.add(record['id']); scope = _scope(record['scope']); _structural(record['predicates'])
        if 'domain' in scope and any(p['field'] != 'product.facts.market_range' for p in record['predicates']):
            raise ValueError('The shared clothing/footwear domain declares market-range defaults only')
        in_scope = applies(scope, concept_id)
        relevant = record['subject'] == recipient and in_scope
        predicates = (PredicateSet(inventory.fields, record['predicates'], known_paths=inventory.known_paths).predicates
                      if in_scope else deepcopy(record['predicates']))
        canonical.append({**deepcopy(record), 'scope': scope, 'predicates': predicates})
        for p in predicates:
            state = ('irrelevant_recipient' if record['subject'] != recipient else
                     'irrelevant_scope' if not relevant else 'overridden_by_request'
                     if p['field'] in override_fields else 'active')
            provenance.append({'memory_id': record['id'], 'subject': record['subject'],
                'channel': record['channel'], 'predicate': deepcopy(p), 'status': state})
            if state == 'active': active.append(p)
    combined, seen = [], set()
    for p in [*active, *current]:
        key = digest(p)
        if key not in seen: combined.append(deepcopy(p)); seen.add(key)
    conflict = conflicts(inventory.fields, combined)
    if conflict:
        raise ClarificationRequired('Conflicting active shopping defaults/current requirements', fields=conflict)
    if not combined:
        raise ValueError('This feature-memory task needs an explicit or applicable remembered requirement')
    return {'schema_version': VERSION, 'recipient': recipient, 'concept_id': concept_id,
        'explicit_predicates': deepcopy(current), 'records': canonical,
        'resolved_predicates': combined, 'provenance': provenance,
        'override_policy': 'explicit_current_field_replaces_remembered_defaults_for_that_field'}


def prose(record, inventory):
    scope = record['scope']
    label = ('my clothing and footwear' if scope.get('domain') == 'clothing_footwear' and record['subject'] == 'self'
             else 'clothing and footwear' if 'domain' in scope else
             ', '.join(scope.get('concept_ids', scope.get('family_ids', []))).replace('.', ' ').replace('_', ' '))
    person = 'my own purchases' if record['subject'] == 'self' else 'purchases for '+record['subject']
    definitions = inventory.fields if applies(scope, inventory.concept_id) else {}
    words = '; '.join(_wording(p, definitions.get(p['field'], {'unit': p['unit']} if 'unit' in p else {}))
                     for p in record['predicates'])
    return f'For {person} in {label}, my remembered shopping defaults are: {words}.'
