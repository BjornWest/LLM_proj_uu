"""Typed, three-state requirements over exported catalogue facts and SKU fields.

Declarations come from a source-pinned, inherited package field inventory. This
module neither guesses field meanings nor fills undisclosed facts. Compile once
per task; evaluating an offer reads only the few requested fields.
"""
from copy import deepcopy
from dataclasses import dataclass

from environments.product_world.product_package import validate_value

VERSION = 'website-catalog-predicates-v1'
NUMERIC = {'integer', 'number'}
SCALAR = NUMERIC | {'boolean', 'string', 'enum'}
OPERATORS = {'eq', 'ne', 'ge', 'le', 'gt', 'lt', 'in', 'not_in', 'contains', 'excludes'}
STATUSES = {'known', 'unknown', 'not_applicable'}
MISSING = object()


def _same(left, right):
    # JSON booleans must not compare equal to integers, including enum members.
    if type(left) is bool or type(right) is bool:
        return type(left) is type(right) and left == right
    return left == right


def _lookup(context, path):
    value = context
    for part in path.split('.'):
        if type(value) is not dict or part not in value:
            return MISSING
        value = value[part]
    return value


@dataclass(frozen=True)
class PredicateResult:
    field: str
    status: str
    satisfied: bool | None
    reason: str


class PredicateSet:
    """A conjunction with explicit uncertainty, using existing DSL declarations.

    ``known_paths`` is a narrow explicit adapter capability for legacy pilot
    scalars without status projections. Ordinary declared constants are known
    only when their exact constant is present and no applicability guard exists.
    This is native truth evaluation, not evidence that a shopper saw a fact.
    """
    def __init__(self, fields, predicates, *, known_paths=()):
        if type(fields) is not dict or type(predicates) is not list:
            raise ValueError('Declare fields and a predicate list')
        self.fields = {}
        self.predicates = deepcopy(predicates)
        self.known_paths = frozenset(known_paths)
        if any(type(path) is not str or path not in fields for path in self.known_paths):
            raise ValueError('Known-scalar capability must name declared paths')
        for p in self.predicates:
            if type(p) is not dict or set(p) - {'field', 'operator', 'value', 'unit'} or not {'field', 'operator', 'value'} <= set(p):
                raise ValueError('Use field/operator/value with an optional exact declared unit')
            path, op = p['field'], p['operator']
            if type(path) is not str or not (path.startswith('product.facts.') or path.startswith('sku.')) or path not in fields:
                raise ValueError('Requirement must name a declared product fact or SKU field')
            if type(op) is not str or op not in OPERATORS:
                raise ValueError('Unsupported predicate operator')
            d = deepcopy(fields[path])
            if d['type'] not in SCALAR | {'set', 'array'}:
                raise ValueError('Object requirements need an explicitly declared scalar path')
            if p.get('unit') != d.get('unit'):
                raise ValueError('Predicate unit must equal the declared field unit; no implicit conversion')
            if op in {'ge', 'le', 'gt', 'lt'} and d['type'] not in NUMERIC:
                raise ValueError('Ordered predicates require a numeric field')
            if op in {'contains', 'excludes'}:
                if d['type'] not in {'set', 'array'}:
                    raise ValueError('Membership requires a declared collection, not substring matching')
                values, vd = [p['value']], d['items']
            elif op in {'in', 'not_in'}:
                if d['type'] not in SCALAR or type(p['value']) is not list or not p['value']:
                    raise ValueError('in/not_in requires a nonempty scalar choice list')
                values, vd = p['value'], d
            else:
                if d['type'] not in SCALAR:
                    raise ValueError('Collection equality is outside this first contract')
                values, vd = [p['value']], d
            # Bounds describe sampled values, not the legal threshold domain:
            # a requirement outside that domain is a valid natural no-match.
            operand_d = {k: v for k, v in vd.items() if k not in {'min', 'max'}}
            for value in values:
                validate_value(value, operand_d, path)
                if vd['type'] == 'enum' and not any(_same(value, v) for v in vd['values']):
                    raise ValueError('Enum predicate has the wrong scalar type')
                if any(_same(value, v) for v in [*d.get('unknown_values', []), *d.get('not_applicable_values', [])]):
                    raise ValueError('Unknown/NA sentinels cannot be requested as ordinary values')
            self.fields[path] = d

    def evaluate(self, product, sku, *, catalog_status, sku_status):
        if (type(product.get('product_id')) is not str or not product['product_id'] or
                product['product_id'] != sku.get('product_id')):
            raise ValueError('Supplied SKU belongs to another product')
        context = {'product': product, 'sku': sku}
        results = []
        for p in self.predicates:
            path, op = p['field'], p['operator']
            d, value = self.fields[path], _lookup(context, path)
            statuses = catalog_status if path.startswith('product.') else sku_status
            status = statuses.get(path)
            if status is not None and (type(status) is not str or status not in STATUSES):
                raise ValueError('Unrecognized logical status')
            sentinel = value is not MISSING and any(_same(value, v) for v in d.get('unknown_values', []))
            na_sentinel = value is not MISSING and any(_same(value, v) for v in d.get('not_applicable_values', []))
            if status is None:
                exact_constant = ('constant' in d and value is not MISSING and _same(value, d['constant'])
                                  and 'applicable_when' not in d)
                status = ('not_applicable' if na_sentinel else 'known' if not sentinel and
                          (exact_constant or path in self.known_paths) else 'unknown')
            if status != 'known':
                results.append(PredicateResult(path, status, None, 'Logical status is '+status))
                continue
            if value is MISSING or sentinel or na_sentinel:
                raise ValueError('Known logical status conflicts with missing/sentinel value')
            validate_value(value, d, path)
            if d['type'] == 'enum' and not any(_same(value, member) for member in d['values']):
                raise ValueError('Known enum value has the wrong scalar type')
            target = p['value']
            if op == 'eq': satisfied = _same(value, target)
            elif op == 'ne': satisfied = not _same(value, target)
            elif op == 'in': satisfied = any(_same(value, item) for item in target)
            elif op == 'not_in': satisfied = not any(_same(value, item) for item in target)
            elif op == 'contains': satisfied = any(_same(item, target) for item in value)
            elif op == 'excludes': satisfied = not any(_same(item, target) for item in value)
            elif op == 'ge': satisfied = value >= target
            elif op == 'le': satisfied = value <= target
            elif op == 'gt': satisfied = value > target
            else: satisfied = value < target
            results.append(PredicateResult(path, status, satisfied, 'Typed native comparison'))
        state = ('mismatch' if any(r.satisfied is False for r in results) else
                 'indeterminate' if any(r.satisfied is None for r in results) else 'match')
        return {'state': state, 'predicates': [r.__dict__ for r in results]}
