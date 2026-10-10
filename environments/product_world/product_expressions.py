"""Restricted, typed expressions for versioned authoring packages. No eval/exec."""
from __future__ import annotations

import ast
from dataclasses import dataclass
import math
import operator


class ExpressionError(ValueError):
    pass


class Unresolved:
    def __init__(self, reason='unknown'):
        self.reason = reason

    def __bool__(self):
        raise ExpressionError(f'Unresolved value cannot become a boolean: {self.reason}')

    def __repr__(self):
        return f'Unresolved({self.reason!r})'


UNKNOWN = Unresolved()
NOT_APPLICABLE = Unresolved('not_applicable')


def unresolved(value):
    return isinstance(value, Unresolved)


def get_path(context, path):
    value = context
    for name in path.split('.'):
        if unresolved(value):
            return value
        if not isinstance(value, dict) or name not in value:
            return UNKNOWN
        value = value[name]
    if isinstance(value, dict) and set(value) == {'status'} and value['status'] in ('unknown', 'not_applicable'):
        return UNKNOWN if value['status'] == 'unknown' else NOT_APPLICABLE
    return value


def set_path(context, path, value):
    names = path.split('.')
    current = context
    for name in names[:-1]:
        existing = current.setdefault(name, {})
        if not isinstance(existing, dict):
            raise ExpressionError(f'Cannot write through scalar {path}')
        current = existing
    current[names[-1]] = value


def path_of(node):
    names = []
    while isinstance(node, ast.Attribute):
        names.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        raise ExpressionError('Only declared field references are allowed')
    names.append(node.id)
    if any(x.startswith('_') for x in names):
        raise ExpressionError('Private/introspective attribute access is forbidden')
    return '.'.join(reversed(names))


def coverage_groups(sizes, mode):
    """Finite pure list transform used by manufactured-size recipes."""
    if not sizes or len(sizes) > 100:
        raise ExpressionError('Coverage requires 1..100 ordered sizes')
    if mode == 'full' or len(sizes) == 1:
        return [list(sizes)]
    if mode == 'subrange':
        return [sizes[a:b] for a in range(len(sizes)) for b in range(a+1, len(sizes)+1)
                if b-a < len(sizes)]
    if mode == 'alternating':
        return [sizes[::2], sizes[1::2]]
    raise ExpressionError(f'Unknown coverage mode {mode}')


def list_slice(values, start, stop):
    return values[start:stop]


PURE = {
    'len': len, 'min': min, 'max': max, 'sum': sum, 'str': str,
    'coverage_groups': coverage_groups, 'slice': list_slice,
    'flatten': lambda values: [x for row in values for x in row],
    'known': lambda value: not unresolved(value),
    'applicable': lambda value: value is not NOT_APPLICABLE,
}


@dataclass(frozen=True)
class Kind:
    name: str
    unit: str | None = None
    item: 'Kind | None' = None
    literal: bool = False

    @property
    def numeric(self):
        return self.name in ('integer', 'number')


def kind(definition):
    name = definition.get('type', 'any')
    if name == 'enum':
        name = 'string'
    item = kind(definition['items']) if name in ('array', 'set') and isinstance(definition.get('items'), dict) else None
    return Kind(name, definition.get('unit'), item)


def compatible(a, b):
    if a.name == 'any' or b.name == 'any':
        return True
    return (a.name == b.name or a.numeric and b.numeric) and (
        a.unit == b.unit or a.unit is None and a.literal or b.unit is None and b.literal)


class Expression:
    def __init__(self, text, fields):
        if not isinstance(text, str) or not text or len(text) > 8192:
            raise ExpressionError('Expression must be a nonempty bounded string')
        self.text, self.fields, self.references = text, fields, set()
        try:
            self.tree = ast.parse(text, mode='eval').body
        except SyntaxError as exc:
            raise ExpressionError(f'Invalid expression: {text}') from exc
        if len(list(ast.walk(self.tree))) > 512:
            raise ExpressionError('Expression exceeds structural limit')
        self.result_kind = self._check(self.tree)

    def _check(self, node):
        if isinstance(node, (ast.Name, ast.Attribute)):
            path = path_of(node)
            if path not in self.fields:
                raise ExpressionError(f'Undeclared reference {path}')
            self.references.add(path)
            return kind(self.fields[path])
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool):
                return Kind('boolean')
            if isinstance(node.value, int):
                return Kind('integer', literal=True)
            if isinstance(node.value, float) and math.isfinite(node.value):
                return Kind('number', literal=True)
            if isinstance(node.value, str):
                return Kind('string')
            if node.value is None:
                return Kind('null')
            raise ExpressionError('Unsupported literal')
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            items = [self._check(x) for x in node.elts]
            if items and any(not compatible(items[0], x) for x in items):
                raise ExpressionError('Mixed incompatible literal collection')
            return Kind('set' if isinstance(node, ast.Set) else 'array', item=items[0] if items else Kind('any'))
        if isinstance(node, ast.UnaryOp):
            operand = self._check(node.operand)
            if isinstance(node.op, ast.Not) and operand.name == 'boolean':
                return Kind('boolean')
            if isinstance(node.op, (ast.USub, ast.UAdd)) and operand.numeric:
                return operand
            raise ExpressionError('Invalid unary operation')
        if isinstance(node, ast.BoolOp):
            if not isinstance(node.op, (ast.And, ast.Or)) or any(self._check(x).name != 'boolean' for x in node.values):
                raise ExpressionError('Logical operators require boolean operands')
            return Kind('boolean')
        if isinstance(node, ast.Compare):
            operands = [self._check(node.left)] + [self._check(x) for x in node.comparators]
            for a, b, op in zip(operands, operands[1:], node.ops):
                if isinstance(op, (ast.In, ast.NotIn)):
                    if b.name not in ('array', 'set', 'string') or b.item and not compatible(a, b.item):
                        raise ExpressionError('Invalid membership comparison')
                elif isinstance(op, (ast.Eq, ast.NotEq)):
                    if not compatible(a, b):
                        raise ExpressionError('Incompatible equality operands/units')
                elif isinstance(op, (ast.Lt, ast.LtE, ast.Gt, ast.GtE)):
                    if not a.numeric or not b.numeric or not compatible(a, b):
                        raise ExpressionError('Ordered comparisons require compatible numbers')
                else:
                    raise ExpressionError('Unsupported comparison')
            return Kind('boolean')
        if isinstance(node, ast.BinOp):
            a, b = self._check(node.left), self._check(node.right)
            if isinstance(node.op, ast.Add) and a.name == b.name == 'string':
                return Kind('string')
            if not a.numeric or not b.numeric:
                raise ExpressionError('Arithmetic requires numbers')
            if isinstance(node.op, (ast.Add, ast.Sub)):
                if not compatible(a, b):
                    raise ExpressionError('Cannot add incompatible units')
                return Kind('number' if 'number' in (a.name, b.name) else 'integer', a.unit or b.unit)
            if isinstance(node.op, ast.Mult):
                if a.unit and b.unit:
                    raise ExpressionError('Multiplication of two dimensioned values is unsupported')
                return Kind('number' if 'number' in (a.name, b.name) else 'integer', a.unit or b.unit)
            if isinstance(node.op, ast.Div):
                if b.unit and a.unit != b.unit:
                    raise ExpressionError('Unsupported unit division')
                return Kind('number', None if b.unit else a.unit)
            raise ExpressionError('Unsupported arithmetic operator')
        if isinstance(node, ast.IfExp):
            if self._check(node.test).name != 'boolean':
                raise ExpressionError('Conditional expression requires boolean test')
            a, b = self._check(node.body), self._check(node.orelse)
            if not compatible(a, b):
                raise ExpressionError('Conditional branches have incompatible types')
            return a
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in PURE or node.keywords:
                raise ExpressionError('Only documented pure helpers are allowed')
            name = node.func.id
            arguments = [self._check(x) for x in node.args]
            expected = {'coverage_groups': 2, 'slice': 3}
            if len(arguments) != expected.get(name, 1):
                raise ExpressionError('Wrong helper arity')
            if name in ('known', 'applicable'):
                return Kind('boolean')
            if name == 'str':
                return Kind('string')
            if name == 'len':
                if arguments[0].name not in ('array', 'set', 'string', 'object'):
                    raise ExpressionError('len requires a collection')
                return Kind('integer')
            if name in ('min', 'max', 'sum'):
                if arguments[0].name not in ('array', 'set') or not arguments[0].item or not arguments[0].item.numeric:
                    raise ExpressionError('Numeric reduction requires a numeric collection')
                return arguments[0].item
            if name == 'slice':
                if arguments[0].name not in ('array', 'set') or any(x.name != 'integer' for x in arguments[1:]):
                    raise ExpressionError('slice requires a collection and integer bounds')
                return arguments[0]
            if name == 'coverage_groups':
                if arguments[0].name != 'array' or arguments[1].name != 'string':
                    raise ExpressionError('coverage_groups requires ordered sizes and mode')
                return Kind('array', item=arguments[0])
            if name == 'flatten':
                a = arguments[0]
                if a.name != 'array' or not a.item or a.item.name not in ('array', 'set'):
                    raise ExpressionError('flatten requires nested collections')
                return Kind('array', item=a.item.item)
        raise ExpressionError(f'Unsupported expression node {type(node).__name__}')

    def evaluate(self, context, *, strict=False):
        def evaluate(node):
            if isinstance(node, (ast.Name, ast.Attribute)):
                path = path_of(node)
                value = get_path(context, path)
                definition = self.fields[path]
                if not unresolved(value) and value in definition.get('unknown_values', []):
                    return UNKNOWN
                return value
            if isinstance(node, ast.Constant):
                return node.value
            if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
                values = [evaluate(x) for x in node.elts]
                return set(values) if isinstance(node, ast.Set) else values
            if isinstance(node, ast.Call):
                values = [evaluate(x) for x in node.args]
                if node.func.id not in ('known', 'applicable') and any(unresolved(x) for x in values):
                    return UNKNOWN
                return PURE[node.func.id](*values)
            if isinstance(node, ast.BoolOp):
                values = [evaluate(x) for x in node.values]
                if isinstance(node.op, ast.And):
                    if any(x is False for x in values):
                        return False
                    return UNKNOWN if any(unresolved(x) for x in values) else True
                if any(x is True for x in values):
                    return True
                return UNKNOWN if any(unresolved(x) for x in values) else False
            if isinstance(node, ast.UnaryOp):
                value = evaluate(node.operand)
                if unresolved(value):
                    return value
                return not value if isinstance(node.op, ast.Not) else -value if isinstance(node.op, ast.USub) else +value
            if isinstance(node, ast.IfExp):
                condition = evaluate(node.test)
                return UNKNOWN if unresolved(condition) else evaluate(node.body if condition else node.orelse)
            if isinstance(node, ast.BinOp):
                a, b = evaluate(node.left), evaluate(node.right)
                if unresolved(a) or unresolved(b):
                    return UNKNOWN
                return {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}[type(node.op)](a, b)
            if isinstance(node, ast.Compare):
                values = [evaluate(node.left)] + [evaluate(x) for x in node.comparators]
                answers = []
                operations = {ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt, ast.LtE: operator.le,
                              ast.Gt: operator.gt, ast.GtE: operator.ge, ast.In: lambda a, b: a in b,
                              ast.NotIn: lambda a, b: a not in b}
                for a, b, op in zip(values, values[1:], node.ops):
                    answers.append(UNKNOWN if unresolved(a) or unresolved(b) else operations[type(op)](a, b))
                return False if any(x is False for x in answers) else UNKNOWN if any(unresolved(x) for x in answers) else True
            raise ExpressionError('Unexpected expression')
        if strict:
            # Even a short-circuited condition may not conceal an unresolved input
            # unless its expression explicitly handles that status via known().
            status_helpers = {path_of(arg) for call in ast.walk(self.tree) if isinstance(call, ast.Call)
                              and call.func.id in ('known', 'applicable') for arg in call.args
                              if isinstance(arg, (ast.Name, ast.Attribute))}
            missing = [p for p in self.references if p not in status_helpers and unresolved(get_path(context, p))]
            if missing:
                raise ExpressionError('Unresolved required references: '+', '.join(sorted(missing)))
        try:
            value = evaluate(self.tree)
            if isinstance(value, float) and not math.isfinite(value):
                raise ExpressionError('Nonfinite expression result')
            if strict and unresolved(value):
                raise ExpressionError(f'Unresolved expression: {self.text}')
            return value
        except (ZeroDivisionError, TypeError, IndexError, ValueError) as exc:
            if isinstance(exc, ExpressionError):
                raise
            raise ExpressionError(f'Expression failed: {self.text}: {exc}') from exc
