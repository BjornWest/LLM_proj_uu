"""Prospective fresh-process construction of four exact native memoizers.

Source preparation only: no integration or effect authority is granted here.
The private issuer retains live construction identities; exported descriptions
and ordinary functools metadata cannot recreate an issuance. Bootstrap must run
before importing native consumers, task/reference code or Runtime.
"""
import ast
import _thread
import builtins
import gc
import importlib
from hashlib import sha256
import json
from pathlib import Path
import sys
from types import CodeType, FunctionType, MappingProxyType, ModuleType

VERSION = 'website-native-cache-construction-v1'
ROLES = (
    ('environments.product_world.geography', 'network', 1),
    ('environments.product_world.geography', 'city_path', 8192),
    ('experiments.footwear_world_pilot.model', '_route', 32768),
    ('experiments.accepted_catalog_commerce.shared_semantics', 'registration', 1),
)


class ConstructionError(ValueError):
    pass


def _hash(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def _code(code):
    """Compare the retained role, including nested executable constants."""
    def constant(value):
        if type(value) is CodeType: return ('code', _code(value))
        if type(value) is tuple: return ('tuple', tuple(constant(v) for v in value))
        if type(value) is frozenset: return ('frozenset', tuple(sorted((constant(v) for v in value), key=repr)))
        return (type(value).__name__, repr(value))
    return tuple(getattr(code, name) for name in (
        'co_filename', 'co_name', 'co_qualname', 'co_flags', 'co_firstlineno',
        'co_argcount', 'co_posonlyargcount', 'co_kwonlyargcount', 'co_nlocals',
        'co_stacksize', 'co_code', 'co_names', 'co_varnames', 'co_freevars',
        'co_cellvars', 'co_linetable', 'co_exceptiontable')) + (
        tuple(constant(value) for value in code.co_consts),)


def _module_function(module, symbol, sources):
    """Require this declared slot, not an interchangeable retained function."""
    path = Path(module.__file__).resolve()
    if str(path) not in sources or _hash(path) != sources[str(path)]:
        raise ConstructionError('Native function source is not retained')
    raw = path.read_bytes()
    tree = ast.parse(raw)
    declarations = [node for node in tree.body
                    if isinstance(node, ast.FunctionDef) and node.name == symbol]
    code = compile(raw, str(path), 'exec', dont_inherit=True)
    candidates = [value for value in code.co_consts if type(value) is CodeType
                  and value.co_qualname == symbol]
    actual = vars(module).get(symbol)
    if len(declarations) != 1 or len(candidates) != 1:
        raise ConstructionError('Declared native role is not unique')
    declaration = declarations[0]
    if declaration.args.kwonlyargs:
        raise ConstructionError('Unsupported keyword-only dependency declaration')
    constants = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            try: value = ast.literal_eval(node.value)
            except (ValueError, TypeError): continue
            for target in node.targets:
                if isinstance(target, ast.Name): constants[target.id] = value
    try:
        expected_defaults = tuple(constants[node.id] if isinstance(node, ast.Name)
                                  else ast.literal_eval(node) for node in declaration.args.defaults) or None
    except (ValueError, TypeError) as error:
        raise ConstructionError('Dynamic dependency default needs separate source admission') from error
    if type(actual) is not FunctionType:
        # CPython's direct function referent is the dispatch target. The
        # writable __wrapped__ attribute alone is explicitly insufficient.
        functions = [value for value in gc.get_referents(actual) if type(value) is FunctionType]
        if len(functions) != 1 or getattr(actual, '__wrapped__', None) is not functions[0]:
            raise ConstructionError('Opaque wrapper has inconsistent actual dispatch')
        actual = functions[0]
    if (actual.__globals__ is not vars(module) or actual.__module__ != module.__name__
            or actual.__qualname__ != symbol or _code(actual.__code__) != _code(candidates[0])
            or _snapshot(actual.__defaults__) != _snapshot(expected_defaults) or actual.__kwdefaults__ is not None
            or actual.__closure__ is not None or actual.__dict__):
        raise ConstructionError('Function does not occupy its exact source/default/namespace role')
    return actual, declaration


def _snapshot(value, seen=None):
    """Retain dependency identity and mutable values without invoking callbacks."""
    seen = set() if seen is None else seen
    if value is None or type(value) in (str, int, bool, float, bytes):
        return (type(value), value)
    if type(value) is Path or isinstance(value, Path):
        return (type(value), str(value))
    if id(value) in seen: return ('cycle', id(value))
    seen.add(id(value))
    try:
        if type(value) in (dict, MappingProxyType):
            return (type(value), tuple(sorted(((_snapshot(k, seen), _snapshot(v, seen))
                       for k, v in value.items()), key=repr)))
        if type(value) in (list, tuple, set, frozenset):
            rows = tuple(_snapshot(v, seen) for v in value)
            return (type(value), tuple(sorted(rows, key=repr)) if type(value) in (set, frozenset) else rows)
        if type(value) is FunctionType:
            return ('function', id(value), _code(value.__code__),
                    _snapshot(value.__defaults__, seen), _snapshot(value.__kwdefaults__, seen),
                    value.__name__, value.__qualname__, value.__module__,
                    _snapshot(value.__annotations__, seen), _snapshot(value.__dict__, seen))
        return ('identity', id(value), type(value))
    finally:
        seen.remove(id(value))


def _role_bindings(module, symbol, function, sources):
    """Explicitly resolve the native dependencies named in the Product contract."""
    if module.__name__ == 'environments.product_world.geography':
        graph = Path(module.__file__).with_name('data')/'europe_locations.json'
        if str(graph.resolve()) not in sources:
            raise ConstructionError('Native geography graph is not retained')
        if symbol == 'network':
            if function.__globals__.get('json') is not json or function.__globals__.get('Path') is not Path:
                raise ConstructionError('Foreign graph loader/JSON binding')
            return (module, json, json.loads, Path, graph)
        cities, _ = _module_function(module, 'cities', sources)
        haversine, _ = _module_function(module, 'haversine', sources)
        network = module.network
        import heapq
        if (function.__globals__.get('cities') is not cities
                or function.__globals__.get('haversine') is not haversine
                or function.__globals__.get('heapq') is not heapq):
            raise ConstructionError('Foreign native shortest-path dependency role')
        return (module, cities, haversine, network, heapq, heapq.heappop, heapq.heappush, graph)
    if (module.__name__, symbol) == ('experiments.footwear_world_pilot.model', '_route'):
        geography = importlib.import_module('environments.product_world.geography')
        route, _ = _module_function(geography, 'route', sources)
        if function.__globals__.get('route') is not route:
            raise ConstructionError('Source-valid route donor is not the declared geography.route')
        if function.__globals__.get('json') is not json:
            raise ConstructionError('Foreign native JSON binding')
        return (geography, route, json, json.loads)
    shared = importlib.import_module('environments.product_world.shared_state')
    freeze, _ = _module_function(shared, 'freeze', sources)
    expected_path = Path(module.__file__).with_name('shared_semantics_v1.json')
    actual_path = function.__globals__.get('REGISTRATION_PATH')
    if actual_path != expected_path or str(expected_path.resolve()) not in sources:
        raise ConstructionError('Registration data/path is not retained')
    if function.__globals__.get('json') is not json:
        raise ConstructionError('Foreign registration JSON binding')
    return (shared, freeze, json, json.loads, actual_path)


def _reject_aliases(previous, role_modules):
    old = {id(value) for value in previous}
    def contains(value, seen=None):
        if id(value) in old: return True
        seen = set() if seen is None else seen
        if id(value) in seen: return False
        seen.add(id(value))
        if type(value) is dict: return any(contains(v, seen) for pair in value.items() for v in pair)
        if type(value) in (list, tuple, set, frozenset): return any(contains(v, seen) for v in value)
        if type(value) is FunctionType:
            cells = tuple(cell.cell_contents for cell in value.__closure__ or ())
            return any(contains(v, seen) for v in (value.__defaults__, value.__kwdefaults__, cells))
        return False
    for name, module in tuple(sys.modules.items()):
        if type(module) is not ModuleType or not name.startswith(('experiments.', 'environments.')):
            continue
        for symbol, value in tuple(vars(module).items()):
            if name in role_modules and (name, symbol) in [row[:2] for row in ROLES]:
                continue
            if contains(value):
                raise ConstructionError('Previous native wrapper has a retained caller alias')
    namespaces = {name: vars(sys.modules[name]) for name in role_modules}
    for wrapper in previous:
        for owner in gc.get_referrers(wrapper):
            if owner is previous: continue
            if any(owner is namespace for namespace in namespaces.values()): continue
            # Do not try to bless arbitrary preconstructed classes, instances,
            # copied namespaces, closure cells or unfamiliar container owners.
            raise ConstructionError('Unknown existing native-cache caller alias')


class _Construction:
    """Opaque identity carrier. It has no public receipt/import constructor."""
    __slots__ = ()


def _cache_info_type(info):
    """Verify the exact four-field tuple constructor used by CPython's cache.

    A replaced named-tuple factory could otherwise make cold-state checks lie.
    This is a narrow generated stdlib constructor check, not class admission.
    """
    import _collections
    fields = ('hits', 'misses', 'maxsize', 'currsize')
    if (type(info) is not type or info.__bases__ != (tuple,) or info.__name__ != 'CacheInfo'
            or info.__module__ != 'functools' or info._fields != fields
            or vars(info).get('__slots__') != () or info.__init__ is not tuple.__init__):
        raise ConstructionError('Foreign cache statistics type')
    new = vars(info).get('__new__')
    if type(new) is staticmethod: new = new.__func__
    code = compile('lambda _cls, hits, misses, maxsize, currsize: '
                   '_tuple_new(_cls, (hits, misses, maxsize, currsize))', '<string>', 'eval')
    expected = next(value for value in code.co_consts if type(value) is CodeType)
    if (type(new) is not FunctionType or _code(new.__code__) != _code(expected)
            or new.__defaults__ is not None or new.__kwdefaults__ is not None
            or new.__closure__ is not None or new.__globals__ != {
                '_tuple_new': tuple.__new__, '__builtins__': {}, '__name__': 'namedtuple_CacheInfo'}):
        raise ConstructionError('Foreign cache statistics constructor/default namespace')
    getter = _collections._tuplegetter
    if type(getter) is not type or not getter.__flags__ & (1 << 8):
        raise ConstructionError('Unknown interpreter tuple field descriptor')
    for index, name in enumerate(fields):
        descriptor = vars(info).get(name)
        if type(descriptor) is not getter or getter.__get__(descriptor, tuple(range(4)), tuple) != index:
            raise ConstructionError('Foreign cache statistics field projection')
    return (id(info), _snapshot(new), tuple((name, id(vars(info)[name])) for name in fields))


def _stdlib_constructor_binding(functools, constructor, info, sources):
    lru, _ = _module_function(functools, 'lru_cache', sources)
    update, _ = _module_function(functools, 'update_wrapper', sources)
    expected = {'_lru_cache_wrapper': constructor, '_CacheInfo': info, 'update_wrapper': update}
    for name in ('isinstance', 'int', 'callable', 'bool', 'TypeError'):
        expected[name] = vars(builtins)[name]
    for name, value in expected.items():
        actual = lru.__globals__.get(name, vars(builtins).get(name))
        if actual is not value: raise ConstructionError('Foreign functools constructor binding: '+name)
    for name in ('getattr', 'setattr', 'AttributeError'):
        if update.__globals__.get(name, vars(builtins).get(name)) is not vars(builtins)[name]:
            raise ConstructionError('Foreign functools metadata constructor binding: '+name)
    return (_snapshot(lru), _snapshot(update), tuple((name, id(value)) for name, value in expected.items()))


def _issuer():
    # This state is deliberately not reconstructed from any serialized receipt.
    # Its exact closure/function/source identity also belongs to later authority.
    issued = None
    attempted = False
    failed = False
    entry = _thread.allocate_lock()
    helper_bindings = None
    def guard():
        if helper_bindings is None: return
        namespace = vars(sys.modules[__name__])
        for name, value, code, defaults, kwdefaults in helper_bindings:
            if namespace.get(name) is not value:
                raise ConstructionError('Construction helper/global identity changed')
            if type(value) is FunctionType and (value.__code__ is not code
                    or value.__defaults__ is not defaults or value.__kwdefaults__ is not kwdefaults):
                raise ConstructionError('Construction helper implementation changed')
    def _bootstrap(*, root, sources, recipe):
        nonlocal issued, attempted, helper_bindings, failed
        if failed:
            raise ConstructionError('Previously invalidated constructor issuer')
        namespace = vars(sys.modules[__name__])
        if any(namespace.get(name) is not function for name, function in (
                ('bootstrap', bootstrap), ('checkpoint', checkpoint), ('admits', admits))):
            raise ConstructionError('Foreign or copied private issuer callbacks')
        if attempted:
            failed = True
            if issued is not None: issued['failed'] = True
            raise ConstructionError('One fresh-process issuance only; previous issuance invalidated')
        attempted = True
        root = Path(root).resolve()
        if Path(__file__).resolve() != root/'environments/website_world/native_cache_construction_v1.py':
            raise ConstructionError('Helper belongs to another execution root')
        if sys.implementation.name != 'cpython' or sys.version_info[:2] != (3, 12):
            raise ConstructionError('Only the reviewed CPython bootstrap is supported')
        allowed = {__name__, 'environments', 'environments.website_world'}
        if any(name.startswith(('environments.', 'experiments.')) and name not in allowed
               for name in sys.modules):
            raise ConstructionError('Native consumers already imported; fresh bootstrap required')
        sources = {str(Path(path).resolve()): value for path, value in sources.items()}
        if str(Path(__file__).resolve()) not in sources:
            raise ConstructionError('Helper source absent from complete retained union')
        for path, expected in sources.items():
            if not Path(path).is_relative_to(root) or _hash(path) != expected:
                raise ConstructionError('Changed or foreign source/data union')
        helper_bindings = tuple((name, value,
            value.__code__ if type(value) is FunctionType else None,
            value.__defaults__ if type(value) is FunctionType else None,
            value.__kwdefaults__ if type(value) is FunctionType else None)
            for name, value in tuple(vars(sys.modules[__name__]).items())
            if not name.startswith('__'))
        recipe_path = Path(recipe['path']).resolve()
        if _hash(recipe_path) != recipe['sha256']:
            raise ConstructionError('Original recipe changed')
        # Source admission of the full stdlib/native dependency graph is an
        # additional authority obligation. Bind the actual constructor here;
        # never accept a caller's "constructor" or "approved" callback.
        import _functools, functools
        constructor = _functools._lru_cache_wrapper
        if (type(constructor) is not type or constructor.__module__ != 'functools'
                or constructor.__name__ != '_lru_cache_wrapper'
                or not constructor.__flags__ & (1 << 8)
                or _functools.__spec__.origin != 'built-in'
                or functools._lru_cache_wrapper is not constructor):
            raise ConstructionError('Unknown interpreter cache constructor')
        info = functools._CacheInfo
        info_binding = _cache_info_type(info)
        cache_info = vars(constructor)['cache_info']
        interpreter = (sys.executable, _hash(sys.executable), sys.implementation.cache_tag,
                       sys.version, id(builtins), id(_functools), id(functools))
        stdlib = {str(Path(functools.__file__).resolve()): _hash(functools.__file__)}
        constructor_binding = _stdlib_constructor_binding(functools, constructor, info, stdlib)
        rows = []
        for module_name, symbol, maxsize in ROLES:
            module = importlib.import_module(module_name)
            old = vars(module).get(symbol)
            if type(old) is not constructor:
                raise ConstructionError('Native declared memoizer was replaced')
            function, declaration = _module_function(module, symbol, sources)
            decorators = declaration.decorator_list
            if (len(decorators) != 1 or ast.unparse(decorators[0]) != f'lru_cache(maxsize={maxsize})'
                    or module.lru_cache is not functools.lru_cache):
                raise ConstructionError('Native decorator differs from exact released role')
            cold = cache_info(old)
            if (type(cold) is not info or cold.hits != 0 or cold.misses != 0
                    or cold.currsize != 0 or cold.maxsize != maxsize):
                raise ConstructionError('Native cache already used or configured differently')
            bindings = _role_bindings(module, symbol, function, sources)
            # Literal parameters are privately recorded from this actual C call.
            wrapper = constructor(function, maxsize, False, info)
            for name in ('__module__', '__name__', '__qualname__', '__doc__', '__annotations__'):
                setattr(wrapper, name, getattr(function, name))
            wrapper.__wrapped__ = function
            def parameters(limit=maxsize): return {'maxsize': limit, 'typed': False}
            wrapper.cache_parameters = parameters
            rows.append({'module': module, 'symbol': symbol, 'maxsize': maxsize,
                         'function': function, 'wrapper': wrapper, 'bindings': bindings,
                         'binding_snapshot': _snapshot(bindings),
                         'metadata': _snapshot(vars(wrapper)),
                         'function_snapshot': _snapshot(function)})
            _reject_aliases([old], {module_name})
            # The released dependency order is network -> city_path -> _route.
            # No consumer use is permitted between these constructions.
            setattr(module, symbol, wrapper)
        token = _Construction()
        issued = {'token': token, 'rows': tuple(rows), 'sources': sources,
                  'recipe': (recipe_path, recipe['sha256']), 'root': root,
                  'constructor': constructor, 'cache_info': cache_info, 'info': info,
                  'info_binding': info_binding,
                  'constructor_binding': constructor_binding,
                  'stdlib': stdlib, 'interpreter': interpreter, 'phase': 'constructed', 'failed': False}
        # No caller can use and clear a cache between construction and this
        # trusted pre-use checkpoint. Return only after the bootstrap completes.
        checkpoint(token, phase='before_native_use')
        return token

    def bootstrap(*, root, sources, recipe):
        nonlocal failed
        if not entry.acquire(False):
            failed = True
            raise ConstructionError('Concurrent or reentrant bootstrap invalidates issuance')
        try:
            return _bootstrap(root=root, sources=sources, recipe=recipe)
        except BaseException:
            failed = True
            if issued is not None: issued['failed'] = True
            raise
        finally:
            entry.release()

    def _checkpoint(token, *, phase):
        guard()
        if issued is None or token is not issued['token'] or type(token) is not _Construction:
            raise ConstructionError('No private construction issuance')
        if failed or issued['failed']:
            raise ConstructionError('Previously invalidated construction issuance')
        if phase not in (None, 'before_native_use', 'before_policy', 'after_policy', 'sealed'):
            raise ConstructionError('Unknown construction checkpoint')
        allowed = {'constructed': 'before_native_use', 'before_native_use': 'before_policy',
                   'before_policy': 'after_policy', 'after_policy': 'sealed'}
        if phase is not None and allowed.get(issued['phase']) != phase:
            raise ConstructionError('Missing, late or reordered construction checkpoint')
        import _functools, functools
        if (_functools._lru_cache_wrapper is not issued['constructor']
                or functools._lru_cache_wrapper is not issued['constructor']
                or functools._CacheInfo is not issued['info']
                or vars(issued['constructor'])['cache_info'] is not issued['cache_info']):
            raise ConstructionError('Constructor/descriptor identity changed')
        if _cache_info_type(issued['info']) != issued['info_binding']:
            raise ConstructionError('Cache statistics construction binding changed')
        if _stdlib_constructor_binding(functools, issued['constructor'], issued['info'],
                                       issued['stdlib']) != issued['constructor_binding']:
            raise ConstructionError('Canonical decorator construction binding changed')
        actual_interpreter = (sys.executable, _hash(sys.executable), sys.implementation.cache_tag,
                              sys.version, id(builtins), id(_functools), id(functools))
        if actual_interpreter != issued['interpreter']:
            raise ConstructionError('Interpreter construction binding changed')
        for path, expected in {**issued['sources'], **issued['stdlib']}.items():
            if _hash(path) != expected: raise ConstructionError('Construction source/data changed')
        if _hash(issued['recipe'][0]) != issued['recipe'][1]:
            raise ConstructionError('Construction recipe changed')
        for row in issued['rows']:
            module, symbol, wrapper = row['module'], row['symbol'], row['wrapper']
            if sys.modules.get(module.__name__) is not module or vars(module).get(symbol) is not wrapper:
                raise ConstructionError('Issued wrapper no longer occupies its native role')
            function, _ = _module_function(module, symbol, issued['sources'])
            if function is not row['function'] or _snapshot(function) != row['function_snapshot']:
                raise ConstructionError('Issued function/default identity changed')
            if _snapshot(vars(wrapper)) != row['metadata']:
                raise ConstructionError('Writable wrapper metadata changed')
            bindings = _role_bindings(module, symbol, function, issued['sources'])
            if _snapshot(bindings) != row['binding_snapshot']:
                raise ConstructionError('Issued native dependency binding changed')
            state = issued['cache_info'](wrapper)
            if state.maxsize != row['maxsize']:
                raise ConstructionError('Actual C cache capacity changed')
            if phase == 'before_native_use' and (state.hits or state.misses or state.currsize):
                raise ConstructionError('Native use preceded trusted bootstrap completion')
        if phase is not None: issued['phase'] = phase
        return {'version': VERSION, 'phase': issued['phase'], 'roles': [
            {'module': row['module'].__name__, 'symbol': row['symbol'],
             'maxsize': row['maxsize'], 'typed': False} for row in issued['rows']]}

    def checkpoint(token, *, phase):
        nonlocal failed
        try:
            if phase is None: raise ConstructionError('Explicit checkpoint phase required')
            return _checkpoint(token, phase=phase)
        except BaseException:
            failed = True
            if issued is not None: issued['failed'] = True
            raise

    def admits(token, value):
        nonlocal failed
        try:
            _checkpoint(token, phase=None)
            return any(value is row['wrapper'] for row in issued['rows'])
        except BaseException:
            failed = True
            if issued is not None: issued['failed'] = True
            raise
    return bootstrap, checkpoint, admits


bootstrap, checkpoint, admits = _issuer()
