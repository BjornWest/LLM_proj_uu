"""Prepared source-declared copy dispatch/default controls.

Narrow stdlib role validation, not whole-interpreter or effect authority. This
candidate must be independently reviewed before joining order-source admission.
"""
import ast
import builtins
import copy
from hashlib import sha256
from pathlib import Path
import types
import weakref


class RoleError(ValueError):
    pass


def _code(code):
    def value(v):
        if type(v) is types.CodeType: return _code(v)
        if type(v) is tuple: return tuple(value(x) for x in v)
        if type(v) is frozenset: return tuple(sorted((value(x) for x in v), key=repr))
        return (type(v), repr(v))
    return (code.co_filename, code.co_qualname, code.co_firstlineno, code.co_flags,
        code.co_argcount, code.co_posonlyargcount, code.co_kwonlyargcount,
        code.co_code, code.co_linetable, code.co_exceptiontable, code.co_names,
        code.co_varnames, code.co_freevars, code.co_cellvars,
        tuple(value(v) for v in code.co_consts))


def _literal(actual, expected):
    if type(actual) is not type(expected): return False
    if type(expected) is dict:
        return actual.keys() == expected.keys() and all(_literal(actual[k], v) for k, v in expected.items())
    if type(expected) in (list, tuple):
        return len(actual) == len(expected) and all(_literal(a, b) for a, b in zip(actual, expected))
    if expected is None or type(expected) in (str, int, bool, float, bytes): return actual == expected
    raise RoleError('Unsupported source literal type')


class CopyRoles:
    """Derive exact table/default roles from independently retained copy.py.

    Retaining a donor function's source alone is insufficient: each actual
    table entry must equal the implementation declared for that exact key.
    No dispatcher, function or default is changed or reconstructed here.
    """
    def __init__(self, *, source_sha256):
        self.path = Path(copy.__file__).resolve()
        self.expected_sha256 = source_sha256
        raw = self.path.read_bytes()
        if sha256(raw).hexdigest() != source_sha256:
            raise RoleError('Retained copy source changed')
        self.tree = ast.parse(raw)
        self.declarations = {node.name: node for node in self.tree.body if isinstance(node, ast.FunctionDef)}
        self.codes = {code.co_qualname: code for code in compile(raw, str(self.path), 'exec', dont_inherit=True).co_consts
                      if type(code) is types.CodeType}
        self.bindings = {}
        self.defaults = {}
        self.tables = {}
        self._derive_tables()
        self.check()

    def _function(self, name):
        actual = vars(copy).get(name)
        if (type(actual) is not types.FunctionType or actual.__globals__ is not vars(copy)
                or actual.__module__ != 'copy' or actual.__qualname__ != name
                or name not in self.codes or _code(actual.__code__) != _code(self.codes[name])):
            raise RoleError('Copy callback occupies a foreign source role: '+name)
        return actual

    def _resolve(self, node, local=None):
        local = {} if local is None else local
        if isinstance(node, ast.Name):
            if node.id in local: return local[node.id]
            if node.id in self.declarations: return self._function(node.id)
            if node.id in vars(builtins): return vars(builtins)[node.id]
            raise RoleError('Unsupported copy construction name: '+node.id)
        if isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name) and node.value.id in ('types', 'weakref'):
                module = types if node.value.id == 'types' else weakref
                return vars(module)[node.attr]
            owner = self._resolve(node.value, local)
            # Only source-declared immutable C type descriptors, e.g. list.copy.
            if type(owner) is not type or owner.__module__ != 'builtins':
                raise RoleError('Unsupported copy construction descriptor')
            member = vars(owner).get(node.attr)
            if type(member) is not types.MethodDescriptorType or member.__objclass__ is not owner:
                raise RoleError('Foreign copy method descriptor')
            return member
        if isinstance(node, (ast.Tuple, ast.List)):
            values = [self._resolve(value, local) for value in node.elts]
            return tuple(values) if isinstance(node, ast.Tuple) else values
        try: return ast.literal_eval(node)
        except (ValueError, TypeError) as error: raise RoleError('Unknown copy source expression') from error

    def _derive_tables(self):
        active = None
        for node in self.tree.body:
            if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name)
                    and target.id in ('_copy_dispatch', '_deepcopy_dispatch') for target in node.targets):
                if not isinstance(node.value, ast.Dict) or node.value.keys:
                    raise RoleError('Unknown copy dispatcher construction')
                active = next(target.id for target in node.targets if isinstance(target, ast.Name)
                              and target.id in ('_copy_dispatch', '_deepcopy_dispatch'))
                self.tables[active] = {}
            elif isinstance(node, ast.Delete) and any(isinstance(target, ast.Name) and target.id == 'd'
                                                      for target in node.targets):
                active = None
            elif active is not None and isinstance(node, ast.Assign):
                self._assignment(active, node, {})
            elif active is not None and isinstance(node, ast.For):
                if not isinstance(node.target, ast.Name) or node.orelse:
                    raise RoleError('Unknown copy dispatcher loop')
                for key in self._resolve(node.iter):
                    for assignment in node.body:
                        if not isinstance(assignment, ast.Assign): raise RoleError('Unknown copy dispatcher statement')
                        self._assignment(active, assignment, {node.target.id: key})
            elif active is not None and not isinstance(node, (ast.FunctionDef, ast.Expr)):
                raise RoleError('Unsupported copy dispatcher source shape')

    def _assignment(self, active, node, local):
        if (len(node.targets) != 1 or not isinstance(node.targets[0], ast.Subscript)
                or not isinstance(node.targets[0].value, ast.Name) or node.targets[0].value.id != 'd'):
            raise RoleError('Unknown copy dispatcher assignment')
        target = node.targets[0]
        key, implementation = self._resolve(target.slice, local), self._resolve(node.value, local)
        if key in self.tables[active]: raise RoleError('Repeated source dispatcher key')
        self.tables[active][key] = implementation

    def check(self):
        if sha256(self.path.read_bytes()).hexdigest() != self.expected_sha256:
            raise RoleError('Copy source changed after admission')
        for name, expected in self.tables.items():
            actual = vars(copy).get(name)
            if type(actual) is not dict or actual.keys() != expected.keys():
                raise RoleError('Copy dispatcher key domain changed')
            if name in self.bindings and actual is not self.bindings[name]:
                raise RoleError('Copy dispatcher identity changed')
            self.bindings.setdefault(name, actual)
            for key, implementation in expected.items():
                if actual[key] is not implementation:
                    raise RoleError('Source-valid donor occupies wrong copy dispatcher key')
        for name, declaration in self.declarations.items():
            function = self._function(name)
            if name in self.bindings and self.bindings[name] is not function:
                raise RoleError('Copy function identity changed')
            self.bindings.setdefault(name, function)
            expected = [self._resolve(node) for node in declaration.args.defaults]
            actual = function.__defaults__ or ()
            if len(actual) != len(expected): raise RoleError('Copy positional default domain changed')
            keyword_expected = {arg.arg: self._resolve(node) for arg, node in
                zip(declaration.args.kwonlyargs, declaration.args.kw_defaults) if node is not None}
            keyword_actual = function.__kwdefaults__ or {}
            if keyword_actual.keys() != keyword_expected.keys(): raise RoleError('Copy keyword default domain changed')
            for value, declared in [*zip(actual, expected),
                                    *((keyword_actual[key], value) for key, value in keyword_expected.items())]:
                if callable(declared):
                    if value is not declared: raise RoleError('Source-valid donor replaces declared copy default')
                elif not _literal(value, declared): raise RoleError('Copy literal default differs from source')
            identity = (id(function.__defaults__), id(function.__kwdefaults__), tuple(id(value) for value in actual))
            if name in self.defaults and self.defaults[name] != identity:
                raise RoleError('Copy defaults replaced after admission')
            self.defaults.setdefault(name, identity)
        return {'module': 'copy', 'source_sha256': self.expected_sha256,
                'tables': {name: len(table) for name, table in self.tables.items()}}
