"""Candidate authority for the actual generated order store and HTTP surface.

Independent Product approval is mandatory for a complete native envelope. This
version never inherits the old read-only admission or its empty-set approval.
External effects and transient client-only history remain outside its scope.
"""
from copy import deepcopy
import ast
import gc
from hashlib import sha256
import json
from pathlib import Path
import sys
from types import (FunctionType, MethodType, ModuleType, BuiltinFunctionType,
                   MethodDescriptorType, WrapperDescriptorType)

from .adapter import ROOT, digest
from .catalog_cart_authority import (
    AuthorityError, ReadOnlyCommitAuthority, binding_hash, closure, code_index,
    code_hash, consumed_globals, file_hash, global_value,
)

VERSION = 'website-generated-order-authority-v1'
NATIVE_AUTHORITY = 'complete_generated_world_order_event_journal'
PHASES = ('before_policy', 'after_policy_before_context_close')


def _record(path, expected):
    path = Path(path).resolve()
    if file_hash(path) != expected:
        raise AuthorityError('Changed retained authority input: ' + str(path))
    return path


def _literal(value, _seen=None):
    """Freeze direct code dependencies; do not mistake mutable caches for code."""
    if isinstance(value, MethodType):
        return ['method', id(value.__self__), id(value.__func__)]
    if isinstance(value, FunctionType):
        return ['function', id(value), code_hash(value.__code__)]
    if isinstance(value, ModuleType):
        return ['module', id(value), {name: [id(member), code_hash(member.__code__) if isinstance(member, FunctionType) else None]
            for name, member in sorted(vars(value).items())
            if isinstance(member, (FunctionType, type)) and not name.startswith('__')}]
    if isinstance(value, type):
        return ['class', id(value), {name: [id(member), code_hash(member.__code__)]
            for name, member in vars(value).items() if isinstance(member, FunctionType)}]
    if value is None or type(value) in (str, bool, int, float, bytes):
        return ['literal', repr(value)]
    if type(value) in (dict, list, tuple, set, frozenset):
        seen = set() if _seen is None else _seen
        if id(value) in seen: return ['container-cycle', id(value)]
        seen.add(id(value))
        try:
            if type(value) is dict:
                return ['dict', sorted([(_literal(k, seen), _literal(v, seen)) for k, v in value.items()], key=repr)]
            rows = [_literal(v, seen) for v in value]
            return [type(value).__name__, sorted(rows, key=repr) if type(value) in (set, frozenset) else rows]
        finally:
            seen.remove(id(value))
    return ['object', id(value), type(value).__module__, type(value).__qualname__]


class OrderCommitAuthority(ReadOnlyCommitAuthority):
    """Reuse source-code validators, with a separate order-capable admission.

    ``retained_sources`` is the complete source union's absolute path -> archived
    file descriptor map. ``inputs`` pins the task, reference, episode, setup,
    recipe, world, basket/domain and delivery files. All are trusted runner data.
    No constructor here starts a server, samples a world or edits a capture.
    """
    def __init__(self, runtime, capture, *, retained_sources, inputs, cleanup_state):
        from .runtime import Runtime
        from .simulated_order_capture import OrderCapture
        if type(runtime) is not Runtime or not isinstance(capture, OrderCapture):
            raise AuthorityError('Require actual generated Runtime/order capture')
        if capture.runtime is not runtime or capture.store is not runtime.orders:
            raise AuthorityError('Capture is bound to another private store')
        if not inputs or set(retained_sources) != set(capture.source_files):
            raise AuthorityError('Retain the complete capture/source union and recipe inputs')
        if type(cleanup_state) is not dict or set(cleanup_state) != {'policy_closed', 'runtime_closed', 'grade'} or cleanup_state != {'policy_closed': False, 'runtime_closed': False, 'grade': None}:
            raise AuthorityError('Bind the actual prospective runner cleanup state before dispatch')
        self.cleanup_state = cleanup_state
        self.receipt = None
        self.receipt_sha256 = None
        self.runtime, self.capture = runtime, capture
        self.runtime_identity = id(runtime)
        self.store = runtime.orders
        self.source_files = deepcopy(capture.source_files)
        self.retained_sources = deepcopy(retained_sources)
        self.inputs = deepcopy(inputs)
        self.source_hashes = {}
        self.compiled, self.archives = {}, {}
        self.module_bindings, self.late_module_bindings = {}, {}
        self.module_names = None
        self.direct_bindings, self.class_bindings = {}, {}
        self.host_ids = {}
        self.phases, self.failures = {}, []
        self.sealed = False
        for path, expected in self.source_files.items():
            source = _record(path, expected)
            if not source.is_relative_to(ROOT):
                raise AuthorityError('Source union must belong to the detached execution root')
            archived = self.retained_sources[path]
            if archived['sha256'] != expected:
                raise AuthorityError('Archive and source union disagree')
            raw = _record(archived['path'], expected).read_bytes()
            name = str(source.relative_to(ROOT))
            self.source_hashes[name] = expected
            self.archives[name] = raw
            if source.suffix == '.py':
                self.compiled[str(source)] = code_index(compile(raw, str(source), 'exec', dont_inherit=True))
        if str(Path(__file__).resolve()) not in self.source_files:
            raise AuthorityError('Authority implementation is absent from source union')
        required = {'task', 'reference', 'episode', 'setup', 'recipe', 'world', 'basket_plan', 'checkout_domain'}
        if not required <= set(inputs):
            raise AuthorityError('Missing native/public instance or recipe input')
        # Compile transport/lifecycle sources before any consumed native call.
        import http.server, socketserver, threading, contextlib
        self.stdlib_sources = {}
        for module in (http.server, socketserver, threading, contextlib):
            path = Path(module.__file__).resolve();raw = path.read_bytes()
            self.stdlib_sources[str(path)] = sha256(raw).hexdigest()
            self.compiled[str(path)] = code_index(compile(raw, str(path), 'exec', dont_inherit=True))
        self._check_files()
        documents = {key: json.loads(Path(inputs[key]['path']).read_bytes()) for key in required}
        if documents['task'] != capture.task or documents['world'] != runtime.world:
            raise AuthorityError('Actual task/world differs from retained instance')
        if documents['basket_plan'] != runtime.baskets.plan or documents['checkout_domain'] != runtime.baskets.domain:
            raise AuthorityError('Actual native quote plan/domain differs from retained instance')
        if runtime.delivery_plan is not None:
            if 'delivery_plan' not in inputs or json.loads(Path(inputs['delivery_plan']['path']).read_bytes()) != runtime.delivery_plan:
                raise AuthorityError('Actual admitted delivery menu is not retained')
        public = documents['episode'].get('manual_task')
        if public != {'user_message': capture.task['user_message'], 'memories': capture.task['memories']}:
            raise AuthorityError('Original public request/memories are not the native task')
        from . import simulated_order_task as native
        self._function(native.make);self._function(native.reference)
        if capture.task != native.make(runtime.baskets, capture.task['spec']) or documents['reference'] != native.reference(runtime.baskets, capture.task):
            raise AuthorityError('Actual native task/reference differs from retained instance')
        recipe = documents['recipe']
        if recipe.get('simulated_order_recipe') != 'website-simulated-order-publication-v1':
            raise AuthorityError('Not an exact native ordering recipe')
        recipe_root = Path(inputs['recipe']['path']).resolve().parent
        self.recipe_files = {}
        for name, expected in recipe['files'].items():
            path = (recipe_root/name).resolve()
            if not path.is_relative_to(recipe_root):
                raise AuthorityError('Recipe file escaped retained container')
            _record(path, expected);self.recipe_files[str(path)] = expected
        for name, expected in recipe['source_sha256'].items():
            if self.source_files.get(str((ROOT/name).resolve())) != expected:
                raise AuthorityError('Recipe source does not match complete capture union')
        for key in required - {'recipe'}:
            if self.recipe_files.get(str(Path(inputs[key]['path']).resolve())) != inputs[key]['sha256']:
                raise AuthorityError('Instance input is outside actual retained recipe: '+key)
        if documents['setup'] != {'start': {'kind': 'cart'}, 'prepared_cart': [{
                'offer_id': capture.task['spec']['offer_id'], 'quantity': capture.task['spec']['quantity']}]}:
            raise AuthorityError('Ordering setup declaration differs from native item/start')
        from .short_task_setup import make_plan
        self._function(make_plan)
        self.setup_plan = make_plan(runtime, retailer_id=capture.task['retailer_id'], **documents['setup'])
        self.setup_receipt = None
        self.input_documents = documents
        self.world_hash = digest(runtime.world)
        self.helper_method_ids = {owner.__module__+'.'+owner.__qualname__+'.'+name: id(fn)
            for owner in type(self).__mro__ if owner is not object for name, fn in vars(owner).items()
            if isinstance(fn, FunctionType)}
        self.initial = self._surface()
        # Repeat after completing the finite implementation inventory so the
        # initial surface includes every discovered stdlib source pin.
        self.initial = self._surface()

    def _assert_helper(self):
        if type(self) is not OrderCommitAuthority:
            raise AuthorityError('Foreign order authority implementation')
        for owner in type(self).__mro__:
            if owner is object: continue
            for name, fn in vars(owner).items():
                if not isinstance(fn, FunctionType): continue
                key = owner.__module__+'.'+owner.__qualname__+'.'+name
                if self.helper_method_ids.get(key) != id(fn):
                    raise AuthorityError('Authority class method changed')
                # Use the inherited validator directly, rather than trusting an
                # instance-provided replacement of the validation callback.
                ReadOnlyCommitAuthority._code_function(self, fn)
                if name in vars(self):
                    raise AuthorityError('Authority instance method override: '+name)

    def _check_files(self):
        for path, expected in self.source_files.items():
            _record(path, expected)
            descriptor = self.retained_sources[path]
            _record(descriptor['path'], expected)
        for path, expected in getattr(self, 'recipe_files', {}).items():
            _record(path, expected)
        for descriptor in self.inputs.values():
            _record(descriptor['path'], descriptor['sha256'])
        for path, expected in getattr(self, 'stdlib_sources', {}).items():
            _record(path, expected)

    def _global_binding(self, fn, name, value):
        # HTTP worker startup/shutdown legitimately changes these registries.
        # Their actual objects and type remain bound; replacements still reject.
        if fn.__globals__.get('__name__') == 'threading' and name in ('_active', '_limbo', '_shutdown_locks'):
            if type(value) is not (set if name == '_shutdown_locks' else dict):
                raise AuthorityError('Foreign threading lifecycle registry')
            return ['threading-lifecycle-registry', id(value), type(value).__name__]
        return _literal(value)

    def _admit_dependency(self, value):
        if not hasattr(self, '_dependency_stack'): self._dependency_stack = set()
        if id(value) in self._dependency_stack: return
        self._dependency_stack.add(id(value))
        try:
            self._dependency(value)
        finally:
            self._dependency_stack.remove(id(value))

    def _dependency(self, value):
        if isinstance(value, MethodType): value = value.__func__
        if isinstance(value, FunctionType):
            filename = str(Path(value.__code__.co_filename).resolve())
            owner = sys.modules.get(value.__globals__.get('__name__'))
            frozen = value.__code__.co_filename.startswith('<frozen ')
            if frozen:
                if (owner is None or value.__globals__ is not vars(owner) or
                        value.__code__.co_filename != '<frozen '+owner.__name__+'>' or
                        getattr(getattr(owner, '__spec__', None), 'origin', None) != 'frozen'):
                    raise AuthorityError('Foreign frozen stdlib callable')
                source = Path(owner.__file__).resolve()
                import sysconfig
                if not source.is_relative_to(Path(sysconfig.get_path('stdlib')).resolve()):
                    raise AuthorityError('Frozen callable is outside interpreter stdlib')
                raw = source.read_bytes()
                expected = self.stdlib_sources.get(str(source))
                if expected is not None and expected != sha256(raw).hexdigest():
                    raise AuthorityError('Frozen stdlib source changed')
                self.stdlib_sources[str(source)] = sha256(raw).hexdigest()
                self.compiled.setdefault(filename, code_index(compile(raw, value.__code__.co_filename, 'exec', dont_inherit=True)))
            if filename not in self.compiled:
                # Only the interpreter's own stdlib may extend the implementation
                # inventory. Project and third-party dependencies must be pinned
                # explicitly in the source union, never admitted from live bytes.
                import sysconfig
                standard = Path(sysconfig.get_path('stdlib')).resolve()
                source = Path(filename)
                if (not source.is_relative_to(standard) or 'site-packages' in source.parts
                        or 'dist-packages' in source.parts or not source.is_file()):
                    raise AuthorityError('Consumed callable source is outside retained union: '+filename)
                raw = source.read_bytes()
                self.stdlib_sources[filename] = sha256(raw).hexdigest()
                self.compiled[filename] = code_index(compile(raw, filename, 'exec', dont_inherit=True))
            self._function(value)
        elif type(value) in (dict, list, tuple, set, frozenset):
            members = [member for row in value.items() for member in row] if type(value) is dict else value
            for member in members: self._admit_dependency(member)
        elif isinstance(value, type):
            if value.__module__ in ('builtins', '_thread'):
                owner = sys.modules.get(value.__module__)
                exported = owner is not None and any(member is value for member in vars(owner).values())
                # Several immutable C types are exported by types rather than
                # builtins: NoneType, CodeType, FunctionType, MethodType, etc.
                types_module = sys.modules.get('types')
                intrinsic = (value.__module__ == 'builtins' and value.__flags__ & (1 << 8)
                    and types_module is not None and any(member is value for member in vars(types_module).values()))
                if not exported and not intrinsic:
                    raise AuthorityError('Foreign interpreter class')
                return
            for member in vars(value).values():
                if isinstance(member, (classmethod, staticmethod)): member = member.__func__
                if isinstance(member, property):
                    for accessor in (member.fget, member.fset, member.fdel):
                        if accessor is not None: self._admit_dependency(accessor)
                elif isinstance(member, FunctionType): self._admit_dependency(member)
        elif isinstance(value, ModuleType):
            # Close before-construction replacements hidden behind module.attr.
            # Admitting its ordinary Python functions also verifies their source,
            # namespaces, defaults and transitive consumed dependencies.
            if value.__name__ in ('sys', 'builtins'): return
            for name, member in tuple(vars(value).items()):
                if isinstance(member, FunctionType):
                    self._admit_dependency(member)
                    self._assert_declared_symbol(vars(value), name, member)
                elif callable(member) and not isinstance(member, type):
                    self._admit_dependency(member)
        elif isinstance(value, (MethodDescriptorType, WrapperDescriptorType)):
            owner = value.__objclass__
            if owner.__module__ != 'builtins' or vars(owner).get(value.__name__) is not value:
                raise AuthorityError('Foreign interpreter method descriptor')
        elif isinstance(value, BuiltinFunctionType):
            owner = sys.modules.get(value.__module__)
            if owner is None or vars(owner).get(value.__name__) is not value:
                # json.decoder defaults bind the immutable compiled whitespace
                # pattern's C match method. Authenticate its exact receiver and
                # dispatch descriptor; arbitrary receiver-bound C calls reject.
                import re
                receiver = getattr(value, '__self__', None)
                descriptor = vars(re.Pattern).get(value.__name__)
                if (type(receiver) is re.Pattern and value.__name__ == 'match'
                        and isinstance(descriptor, MethodDescriptorType)
                        and descriptor.__objclass__ is re.Pattern
                        and value.__qualname__ == 'Pattern.match'):
                    return
                raise AuthorityError('Unadmitted interpreter callable')
        elif callable(value):
            self._cache_dependency(value)

    def _cache_dependency(self, value):
        """Only a source-declared CPython lru_cache wrapper is admitted.

        Inspect the actual C wrapper's direct function referent; __wrapped__
        metadata alone is writable and cannot establish its dispatch target.
        Other callable objects require their own explicit reviewed boundary.
        """
        from functools import _lru_cache_wrapper
        if sys.implementation.name != 'cpython' or type(value) is not _lru_cache_wrapper:
            raise AuthorityError('Unknown executable dependency object')
        functions = [fn for fn in gc.get_referents(value) if isinstance(fn, FunctionType)]
        if len(functions) != 1 or getattr(value, '__wrapped__', None) is not functions[0]:
            raise AuthorityError('Cache metadata differs from actual function dispatch')
        fn = functions[0]
        self._admit_dependency(fn)
        parameters = value.cache_parameters
        self._admit_dependency(parameters)
        if parameters() != self._cache_spec(fn):
            raise AuthorityError('Cache parameters differ from source declaration')

    def _cache_spec(self, fn):
        owner = sys.modules.get(fn.__globals__.get('__name__'))
        source = Path(owner.__file__).resolve()
        raw = self.archives.get(str(source.relative_to(ROOT))) if source.is_relative_to(ROOT) else source.read_bytes()
        if raw is None: raise AuthorityError('Cache declaration lacks retained source')
        tree = ast.parse(raw)
        candidates = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and n.name == fn.__name__ and fn.__code__.co_firstlineno in
            [n.lineno, *[d.lineno for d in n.decorator_list]]]
        if len(candidates) != 1 or len(candidates[0].decorator_list) != 1:
            raise AuthorityError('Cache decorator declaration is not unique')
        declaration = candidates[0].decorator_list[0]
        constants = {}
        for node in tree.body:
            if isinstance(node, ast.Assign):
                try: literal = ast.literal_eval(node.value)
                except (ValueError, TypeError): continue
                for target in node.targets:
                    if isinstance(target, ast.Name): constants[target.id] = literal
        def literal(node):
            if isinstance(node, ast.Name) and node.id in constants: return constants[node.id]
            try: return ast.literal_eval(node)
            except (ValueError, TypeError) as error: raise AuthorityError('Dynamic cache parameters require separate admission') from error
        if ast.unparse(declaration) in ('cache', 'functools.cache'):
            return {'maxsize': None, 'typed': False}
        if not isinstance(declaration, ast.Call) or ast.unparse(declaration.func) not in ('lru_cache', 'functools.lru_cache'):
            raise AuthorityError('Unknown cache decorator')
        if len(declaration.args) > 1 or any(k.arg not in ('maxsize', 'typed') for k in declaration.keywords):
            raise AuthorityError('Unknown cache parameter shape')
        result = {'maxsize': literal(declaration.args[0]) if declaration.args else 128, 'typed': False}
        result.update({k.arg: literal(k.value) for k in declaration.keywords})
        if type(result['typed']) is not bool or (result['maxsize'] is not None and type(result['maxsize']) is not int):
            raise AuthorityError('Foreign cache parameter type')
        return result

    def _assert_declared_symbol(self, namespace, name, value):
        owner = sys.modules.get(namespace.get('__name__'))
        if owner is None: raise AuthorityError('Dependency namespace owner is absent')
        source = getattr(owner, '__file__', None)
        if source is None: return
        filename = str(Path(source).resolve())
        if getattr(getattr(owner, '__spec__', None), 'origin', None) == 'frozen':
            filename = str(Path('<frozen '+owner.__name__+'>').resolve())
        expected = self.compiled.get(filename, {}).get(name)
        if expected is not None:
            if isinstance(value, type):
                if value.__module__ == owner.__name__ and value.__qualname__ == name:
                    self._admit_dependency(value)
                    return
            elif isinstance(value, FunctionType) and code_hash(value.__code__) in expected:
                return
            elif callable(value):
                self._cache_dependency(value)
                wrapped = value.__wrapped__
                if wrapped.__globals__ is namespace and code_hash(wrapped.__code__) in expected:
                    return
            raise AuthorityError('Declared dependency implementation was replaced: '+owner.__name__+'.'+name)

    def _function(self, value):
        fn = value.__func__ if isinstance(value, MethodType) else value
        if isinstance(fn, FunctionType) and fn.__code__.co_filename.startswith('<frozen '):
            owner = sys.modules.get(fn.__globals__.get('__name__'))
            if owner is None or fn.__globals__ is not vars(owner) or fn.__code__.co_filename != '<frozen '+owner.__name__+'>':
                raise AuthorityError('Foreign frozen function namespace')
            binding = ReadOnlyCommitAuthority._code_function(self, fn)
        else:
            binding = ReadOnlyCommitAuthority._function(self, value)
        # In-place mutation of a function's code/defaults/globals is not hidden
        # by retaining the same function object or source file on disk.
        key = id(fn)
        if key in getattr(self, '_admitting', set()): return binding
        if not hasattr(self, '_admitting'): self._admitting = set()
        self._admitting.add(key)
        try:
            self._admit_dependency(fn.__defaults__)
            self._admit_dependency(fn.__kwdefaults__)
            for name in sorted(consumed_globals(fn.__code__)):
                actual = global_value(fn.__globals__, name)
                lifecycle_registry = (fn.__globals__.get('__name__') == 'threading'
                    and name in ('_active', '_limbo', '_shutdown_locks'))
                if not lifecycle_registry: self._admit_dependency(actual)
                self._assert_declared_symbol(fn.__globals__, name, actual)
        finally:
            self._admitting.remove(key)
        current = {'code': code_hash(fn.__code__),
            'defaults': _literal(fn.__defaults__), 'kwdefaults': _literal(fn.__kwdefaults__),
            'globals': {name: self._global_binding(fn, name, global_value(fn.__globals__, name))
                        for name in sorted(consumed_globals(fn.__code__))}}
        if key in self.direct_bindings and self.direct_bindings[key] != current:
            raise AuthorityError('Loaded function/default/global binding changed: ' + fn.__qualname__)
        self.direct_bindings.setdefault(key, current)
        return binding

    def _class(self, value):
        """Reject additions/replacements, including same-code method clones."""
        rows = {}
        for owner in value.__mro__:
            if owner is object:
                continue
            module = sys.modules.get(owner.__module__)
            filename = getattr(module, '__file__', None)
            if filename is None or str(Path(filename).resolve()) not in self.compiled:
                raise AuthorityError('Unretained implementation class: ' + owner.__qualname__)
            methods = {}
            for name, member in vars(owner).items():
                raw = member.__func__ if isinstance(member, (staticmethod, classmethod)) else member
                if isinstance(raw, property):
                    for suffix, fn in (('get', raw.fget), ('set', raw.fset), ('del', raw.fdel)):
                        if fn is not None:
                            self._function(fn); methods[name+'.'+suffix] = id(fn)
                elif isinstance(raw, FunctionType):
                    self._function(raw); methods[name] = id(raw)
            key = owner.__module__ + '.' + owner.__qualname__
            current = {'members': sorted(vars(owner)), 'methods': methods}
            if key in self.class_bindings and self.class_bindings[key] != current:
                raise AuthorityError('Loaded class dispatch changed: ' + key)
            self.class_bindings.setdefault(key, current)
            rows[key] = current
        return rows

    def _instance(self, instance):
        rows = self._class(type(instance))
        for name in vars(instance):
            if callable(getattr(instance, name)) and any(name in vars(c) for c in type(instance).__mro__):
                raise AuthorityError('Instance method override: ' + name)
        return rows

    def _host(self, key, host, *, renderer=None, retailer=False):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from .runtime import Host
        from .simulated_order_runtime import submit
        if type(host) is not Host or type(host.server) is not ThreadingHTTPServer:
            raise AuthorityError('Foreign generated host/server')
        self._instance(host); self._instance(host.server)
        handler = host.server.RequestHandlerClass
        if handler.__bases__ != (BaseHTTPRequestHandler,) or set(vars(handler)) - {
                '__module__', '__dict__', '__weakref__', '__doc__',
                'log_message', 'respond', 'do_GET', 'do_POST'}:
            raise AuthorityError('Unknown HTTP method/handler surface')
        self._class(handler)
        get, post = closure(handler.do_GET), closure(handler.do_POST)
        if set(get) != {'max_query_fields', 'render'} or set(post) != {'post_handlers'} or closure(handler.respond) != {'outer': host}:
            raise AuthorityError('Unknown HTTP router closure')
        render, routes = get['render'], post['post_handlers']
        self._function(render)
        if type(routes) is not dict or set(routes) != ({'/api/basket-quote', '/api/order'} if retailer else set()):
            raise AuthorityError('Unknown or missing generated POST route')
        if renderer is not None and render != renderer:
            raise AuthorityError('Surrounding/index renderer replacement')
        if retailer:
            cells = closure(render)
            if render.__qualname__ != 'Runtime.__init__.<locals>.render' or set(cells) != {'assets', 'self'} or cells['self'] is not self.runtime:
                raise AuthorityError('Retailer GET router belongs to another Runtime')
            if render.__kwdefaults__['sid'] != key:
                raise AuthorityError('Retailer GET subject changed')
            if {n: sha256(v).hexdigest() for n, v in cells['assets'].items()} != self.runtime.asset_hashes:
                raise AuthorityError('Served assets changed')
            if sha256(render.__kwdefaults__['body'].encode()).hexdigest() != self.runtime.html_hashes[key]:
                raise AuthorityError('Served retailer document changed')
            for route, callback in routes.items():
                self._function(callback)
                if callback.__qualname__ != 'Runtime.__init__.<locals>.<lambda>' or callback.__defaults__ != (key,):
                    raise AuthorityError('Unrecognized retailer mutation callback')
                wanted = {'self': self.runtime} if route == '/api/basket-quote' else {'self': self.runtime, 'submit_order': submit}
                if closure(callback) != wanted:
                    raise AuthorityError('Foreign quote/order callback binding')
        elif key == '@start' and render.__qualname__ != 'Runtime.__init__.<locals>.research_page':
            raise AuthorityError('Unknown discovery-start router')
        identities = [id(host), id(host.server), id(handler), id(host.thread), id(host.lock), id(render),
                      id(routes), *[id(v) for _, v in sorted(routes.items())]]
        if key in self.host_ids and self.host_ids[key] != identities:
            raise AuthorityError('HTTP host/router identity changed')
        self.host_ids.setdefault(key, identities)
        return {'origin': host.origin, 'get': self._function(render),
                'post': {name: self._function(fn) for name, fn in sorted(routes.items())},
                'identities': identities, 'query_field_limit': get['max_query_fields']}

    def _surface(self):
        from . import adapter, catalog_adapter, checkout_domain, catalog_checkout_domain
        from .basket import Baskets
        from .simulated_order_store import OrderStore
        from . import simulated_order_record as record_api
        from . import simulated_order_runtime as order_api
        from .native_review_pages import NativeReviewPage
        from .surrounding_pages import ReviewPage, ComparisonPage as LegacyComparisonPage
        from .comparison_pages import ComparisonPage
        from experiments.accepted_catalog_commerce import basket_quote as catalog_quote, delivery_admission, prepared_quote
        from experiments.footwear_world_pilot import basket_quote as footwear_quote
        r, store = self.runtime, self.store
        if id(r) != self.runtime_identity or type(r.orders) is not OrderStore or r.orders is not store:
            raise AuthorityError('Actual Runtime/store was replaced')
        if type(r.baskets) is not Baskets or store._baskets is not r.baskets or r.baskets.adapter is not r.adapter:
            raise AuthorityError('Order maker is not bound to the actual quote transport')
        catalog = r.world['schema_version'] == 'accepted-catalog-commerce-world-v1'
        if r.world['schema_version'] not in ('accepted-catalog-commerce-world-v1', 'footwear-world-pilot-v1'):
            raise AuthorityError('Unrecognized generated commerce schema')
        backend = catalog_quote if catalog else footwear_quote
        domain = catalog_checkout_domain if catalog else checkout_domain
        expected_adapter = catalog_adapter.PublicAdapter if catalog else adapter.PublicAdapter
        if type(r.adapter) is not expected_adapter or r.baskets.domain_provider is not domain or r.domain_provider is not domain:
            raise AuthorityError('Unknown commerce adapter/domain')
        if r.catalog_backend is not (catalog_adapter if catalog else None):
            raise AuthorityError('Unknown catalog backend')
        if r.coupons is not None or r.baskets.coupons is not None or any('account' in p for p in r.public_catalogs.values()):
            raise AuthorityError('Account/subscription/coupon-enabled surface requires separate admission')
        if r.baskets.prepared is not r.prepared or (r.baskets.oracle is not (getattr(r, 'delivery_oracle', None) or footwear_quote)):
            raise AuthorityError('Native/prepared quote object changed')
        delivery_oracle = getattr(r, 'delivery_oracle', None)
        if type(delivery_oracle) is delivery_admission.Oracle:
            oracle = delivery_oracle
            self._instance(oracle)
            if oracle._backend is not backend or oracle._admission != r.delivery_plan:
                raise AuthorityError('Delivery Oracle backend/menu changed')
            oracle_state = {'admission': deepcopy(oracle._admission), 'menus': binding_hash(oracle._menus),
                            'digest': oracle._digest, 'identity': id(oracle)}
        elif delivery_oracle in (backend, None) and (delivery_oracle is not None or not catalog):
            oracle_state = {'backend': backend.__name__}
        else:
            raise AuthorityError('Foreign native delivery Oracle')
        from threading import RLock
        if type(store._lock) is not type(RLock()) or type(store._records) is not list or type(store._events) is not list or type(store._receipts) is not dict:
            raise AuthorityError('Store lock or append-only containers were replaced')
        if store._maker is not record_api.make:
            raise AuthorityError('Foreign native order record maker')
        precommit = store._precommit
        self._function(precommit)
        if precommit.__qualname__ != 'initialize.<locals>.<lambda>' or closure(precommit) != {'runtime': r}:
            raise AuthorityError('Foreign public precommit projection')
        for fn in (record_api.make, record_api.validate, order_api.public_confirmation, order_api.submit):
            self._function(fn)
        classes = {type(o).__qualname__: self._instance(o) for o in (r, r.baskets, r.adapter, store, self.capture)}
        if digest(r.world) != self.world_hash or r.adapter.world is not r.world:
            raise AuthorityError('Native world changed')
        if any(self.source_files.get(str((ROOT/name).resolve())) != expected for name, expected in r.sources.items()):
            raise AuthorityError('Actual Runtime publication source is outside the retained union')
        if set(r.public_catalogs) != set(r.origins) or set(r.origins) != set(r.adapter.retailers):
            raise AuthorityError('Retailer/available-catalog coverage changed')
        views = getattr(r, 'surrounding_views', {})
        if set(r.sites) != set(r.origins) | set(views):
            raise AuthorityError('Uncovered generated host')
        hosts = {}
        for key, host in r.sites.items():
            if key in r.origins:
                hosts[key] = self._host(key, host, retailer=True)
            else:
                view = views[key]
                if type(view) not in (NativeReviewPage, ComparisonPage, ReviewPage, LegacyComparisonPage):
                    raise AuthorityError('Unknown surrounding renderer')
                self._instance(view)
                hosts[key] = self._host(key, host, renderer=view.page)
        hosts['@index'] = self._host('@index', r.index, renderer=r.index_page)
        if r.discovery_mode == 'tool':
            hosts['@start'] = self._host('@start', r.research)
        prepared = None
        if r.prepared is not None:
            if not catalog or type(r.prepared) is not prepared_quote.PreparedQuote:
                raise AuthorityError('Foreign prepared quote implementation')
            prepared = self._prepared(r.prepared)
        bound_domain = r.baskets._bound_domain
        if bound_domain is not None:
            if type(bound_domain) is not catalog_checkout_domain._BoundDomain:
                raise AuthorityError('Unknown private checkout-domain snapshot')
            self._instance(bound_domain)
        return {'schema': r.world['schema_version'], 'world_sha256': self.world_hash,
            'hosts': hosts, 'classes': classes, 'loaded_modules': self._loaded_modules(),
            'assets': deepcopy(r.asset_hashes), 'html': deepcopy(r.html_hashes),
            'retailers': digest(r.adapter.retailers), 'products': digest(r.adapter.products),
            'adapter_plan': digest(getattr(r.adapter, 'plan', None)),
            'adapter_oracle': id(getattr(r.adapter, 'oracle', None)),
            'adapter_prepared': id(getattr(r.adapter, 'prepared', None)),
            'delivery_orders': digest(r.adapter.delivery_orders),
            'catalogs': digest(r.public_catalogs), 'plan': digest(r.baskets.plan),
            'domain': digest(r.baskets.domain), 'plan_id': r.baskets.plan_id, 'domain_id': r.baskets.domain_id,
            'bound_domain': binding_hash(vars(bound_domain)) if bound_domain is not None else None,
            'oracle': oracle_state, 'prepared': prepared, 'store_identity': id(store),
            'store_containers': [id(store._records), id(store._events), id(store._receipts)],
            'store_lock': id(store._lock), 'cleanup_state_identity': id(self.cleanup_state), 'store_maker': id(store._maker), 'store_precommit': id(precommit),
            'store_runtime_id': store._runtime_id, 'adapter_identity': id(r.adapter), 'baskets_identity': id(r.baskets),
            'origin_map': r.origin_map.descriptor if r.origin_map is not None else None,
            'source_union_sha256': digest(self.source_files), 'inputs': deepcopy(self.inputs),
            'stdlib_source_sha256': deepcopy(self.stdlib_sources)}

    def checkpoint(self, phase, trace):
        try:
            OrderCommitAuthority._assert_helper(self)
            if phase not in PHASES or phase in self.phases or (phase == PHASES[1] and PHASES[0] not in self.phases):
                raise AuthorityError('Missing/duplicate/out-of-order actual authority phase')
            self._check_files()
            if self._surface() != self.initial:
                raise AuthorityError('Actual order-capable surface changed')
            if self.capture.trace is not trace or self.capture.binding is None:
                raise AuthorityError('Authority checkpoint is not an actual order capture')
            self._function(self.checkpoint); self._function(self.seal)
            snapshot = self.store.snapshot()
            expected = {'episode_id': trace.episode_id, 'task_sha256': digest(self.capture.task),
                'source_union_sha256': digest(self.source_files), 'capture_implementation_sha256': self.capture.capture_sha256}
            if snapshot['episode_binding'] != expected or self.capture.binding != {'runtime_id': snapshot['runtime_id'], 'episode_binding': expected}:
                raise AuthorityError('Episode/task/source/capture binding differs')
            setup_path = trace.directory/'manual-review-private/order-prepared-setup.private.json'
            actual_setup = json.loads(setup_path.read_bytes())
            if actual_setup != self.capture.prepared_setup or actual_setup.get('plan') != self.setup_plan:
                raise AuthorityError('Actual ordinary setup receipt/plan differs from retained declaration')
            receipt = {'path': str(setup_path.resolve()), 'sha256': file_hash(setup_path)}
            if self.setup_receipt is not None and self.setup_receipt != receipt:
                raise AuthorityError('Original actual setup receipt changed during policy')
            self.setup_receipt = receipt
            artifact = self.capture.artifacts['before' if phase == PHASES[0] else 'after']
            document = _record(artifact['path'], artifact['sha256'])
            if not document.is_relative_to(trace.directory.resolve()) or json.loads(document.read_bytes()) != {'phase': phase, 'order_snapshot': snapshot}:
                raise AuthorityError('Checkpoint does not match actual retained full ledger')
            identity = {'episode_id': trace.episode_id, 'trace': str(trace.directory.resolve()),
                        'binding': deepcopy(self.capture.binding)}
            if self.phases and any(v['identity'] != identity for v in self.phases.values()):
                raise AuthorityError('Actual authority phases belong to different episodes')
            self.phases[phase] = {'identity': identity, 'capture': deepcopy(artifact), 'snapshot': snapshot}
        except Exception as error:
            self.failures.append({'phase': phase, 'error': str(error)}); raise

    def seal(self, trace, summary, capsule, *, approval=None):
        """After both cleanups and raw capture sealing; never edits the original."""
        OrderCommitAuthority._assert_helper(self)
        if self.sealed:
            raise AuthorityError('Authority can be sealed only once')
        self.sealed = True
        self._check_files()
        if set(self.phases) != set(PHASES) or self.failures or not self.capture.sealed or self.store._sealed is not True:
            raise AuthorityError('Incomplete/failed actual phase or store sealing')
        if self._surface() != self.initial:
            raise AuthorityError('Source/router/store state changed before authority sealing')
        hosts = [*self.runtime.sites.values(), self.runtime.index]
        if self.runtime.discovery_mode == 'tool': hosts.append(self.runtime.research)
        if (self.runtime._stack._exit_callbacks or any(h.thread.is_alive() or h.server.socket.fileno() != -1 or
                not h.server._BaseServer__is_shut_down.is_set() for h in hosts)
                or any(not bridge.closed for _, bridge in self.runtime._browser_bridges)):
            raise AuthorityError('Actual Runtime transport cleanup is incomplete')
        if self.cleanup_state['policy_closed'] is not True or self.cleanup_state['runtime_closed'] is not True:
            raise AuthorityError('Actual prospective runner has not completed both cleanups')
        if any(summary.get(k) for k in ('error', 'execution_error', 'cleanup_errors')):
            raise AuthorityError('Policy/Runtime cleanup error cannot establish complete effects')
        path = Path(trace).resolve()
        raw_path = path/'order-capsule.private.json'
        if capsule != json.loads(raw_path.read_bytes()) or capsule['effect_journal'] is not None:
            raise AuthorityError('Require the original null-authority capsule')
        if capsule['episode_id'] != self.capture.trace.episode_id or path != self.capture.trace.directory.resolve() or capsule['main_trace_sha256'] != file_hash(path/'steps.jsonl'):
            raise AuthorityError('Terminal main trace/episode differs from actual capture')
        if self.setup_receipt is None:
            raise AuthorityError('Actual ordinary setup evidence is missing')
        _record(self.setup_receipt['path'], self.setup_receipt['sha256'])
        before, after = (self.phases[p]['snapshot'] for p in PHASES)
        for phase, field in zip(PHASES, ('before', 'after')):
            entry = self.phases[phase]
            _record(entry['capture']['path'], entry['capture']['sha256'])
            if capsule[field] != {'phase': phase, 'order_snapshot': entry['snapshot']}:
                raise AuthorityError('Raw capsule differs from actual authority phase')
        if self.store.snapshot() != after or after['orders'][:len(before['orders'])] != before['orders'] or after['events'][:len(before['events'])] != before['events']:
            raise AuthorityError('Order ledger is not complete sealed append-only history')
        from .simulated_order_record import validate
        for record in after['orders']:
            validate(self.runtime.baskets, record['retailer_id'], record)
        if len(after['events']) != len(after['orders']):
            raise AuthorityError('Order/event ledger lengths differ')
        for number, (record, event) in enumerate(zip(after['orders'], after['events']), 1):
            if event != {'sequence': number, 'order_id': record['order_id'], 'retailer_id': record['retailer_id'],
                         'submission_sha256': record['submission_sha256'], 'record_sha256': digest(record)}:
                raise AuthorityError('Private event does not identify its native committed record')
        expected_receipts = {(record['retailer_id'], record['submission']['idempotency_key']):
            {'submission_sha256': record['submission_sha256'], 'record': record} for record in after['orders']}
        if len(expected_receipts) != len(after['orders']) or self.store._receipts != expected_receipts:
            raise AuthorityError('Idempotency map differs from complete private committed ledger')
        evidence = {'schema': VERSION, 'status': 'candidate_independent_acceptance_required',
            'helper_source_sha256': file_hash(__file__), 'source_files': deepcopy(self.source_files),
            'stdlib_source_sha256': deepcopy(self.stdlib_sources), 'inputs': deepcopy(self.inputs),
            'surface': deepcopy(self.initial), 'phases': deepcopy(self.phases),
            'actual_setup_receipt': deepcopy(self.setup_receipt),
            'served_asset_sha256': deepcopy(self.initial['assets']), 'served_html_sha256': deepcopy(self.initial['html']),
            'native_context': {k: self.initial[k] for k in ('schema', 'world_sha256', 'plan', 'domain', 'plan_id', 'domain_id')},
            'raw_capsule': {'path': str(raw_path), 'sha256': file_hash(raw_path)},
            'episode_id': capsule['episode_id'], 'main_trace_sha256': capsule['main_trace_sha256'],
            'events': [{'kind': 'order_committed', **deepcopy(event)} for event in after['events'][len(before['events']):]],
            'scope': 'Authoritative generated order commits; payment/subscription/account paths excluded by admitted implementation',
            'excluded': ['External effects', 'Transient browser-only history'], 'native_effect_envelope': None}
        if approval is not None:
            approved = json.loads(_record(approval['path'], approval['sha256']).read_bytes())
            exact = {k: evidence[k] for k in ('helper_source_sha256', 'source_files', 'stdlib_source_sha256', 'inputs', 'served_asset_sha256', 'served_html_sha256', 'native_context')}
            if (approved.get('owner') != 'Product' or approved.get('status') != 'accepted'
                    or approved.get('authority_schema') != VERSION or approved.get('bindings') != exact
                    or not approved.get('evidence_manifest')):
                raise AuthorityError('Missing exact independent order authority approval')
            _record(approved['evidence_manifest']['path'], approved['evidence_manifest']['sha256'])
            evidence.update(status='accepted_generated_order_journal', independent_acceptance=deepcopy(approval),
                native_effect_envelope={'authority': NATIVE_AUTHORITY, 'complete': True, 'events': deepcopy(evidence['events'])})
        self.receipt = deepcopy(evidence)
        self.receipt_sha256 = digest(self.receipt)
        return deepcopy(evidence)
