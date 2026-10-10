"""Private empty-set proof for the exact read-only generated execution surface.

This is not an observed event journal, external-effect certification, or a claim
about transient browser demo history. No request supplied by a policy is proof.
Independent Product acceptance is required before emitting the native envelope.
"""
from copy import deepcopy
import dis
from hashlib import sha256
import inspect
import json
from pathlib import Path
import sys
from types import CodeType, FunctionType, MethodType, ModuleType

from .adapter import ROOT, digest

VERSION = 'website-catalog-cart-read-only-authority-v1'
OFFLINE_MODULE = 'experiments.accepted_catalog_commerce.order_set_optimizer'
OFFLINE_SOURCE = 'experiments/accepted_catalog_commerce/order_set_optimizer.py'
OFFLINE_SOURCE_SHA256 = '2f9ee3472f3874b394727b3d721e489b6af880bb54047348c2e2d5dccbbb5448'
OFFLINE_ENTRIES = frozenset(('_Checkout.dispatch', '_Checkout.options', '_solve'))


class AuthorityError(ValueError):
    pass


def file_hash(path): return sha256(Path(path).read_bytes()).hexdigest()
def code_hash(code):
    def constant(value):
        if isinstance(value, CodeType): return {'code': code_hash(value)}
        if isinstance(value, tuple): return {'tuple': [constant(v) for v in value]}
        if isinstance(value, frozenset): return {'set': sorted([constant(v) for v in value], key=lambda v:json.dumps(v,sort_keys=True))}
        if isinstance(value, bytes): return {'bytes':value.hex()}
        if value is None or type(value) in (str,int,bool): return value
        return {'literal_type':type(value).__name__, 'repr':repr(value)}
    return digest({name:getattr(code,name) for name in ['co_name','co_qualname','co_filename','co_flags',
        'co_argcount','co_posonlyargcount','co_kwonlyargcount','co_nlocals','co_stacksize','co_firstlineno']}
        | {'code':code.co_code.hex(),'constants':[constant(c) for c in code.co_consts],
            'names':code.co_names,'varnames':code.co_varnames,'freevars':code.co_freevars,
            'cellvars':code.co_cellvars,'lines':code.co_linetable.hex(),'exceptions':code.co_exceptiontable.hex()})


def code_index(code):
    result = {}
    def visit(value):
        result.setdefault(value.co_qualname, set()).add(code_hash(value))
        for child in value.co_consts:
            if isinstance(child, CodeType): visit(child)
    visit(code)
    return result


def closure(function):
    if isinstance(function, MethodType): function = function.__func__
    return dict(zip(function.__code__.co_freevars,
                    [cell.cell_contents for cell in function.__closure__ or ()]))


def consumed_globals(code):
    """Include globals loaded by comprehensions and other nested code too."""
    names = {i.argval for i in dis.get_instructions(code) if i.opname == 'LOAD_GLOBAL'}
    for child in code.co_consts:
        if isinstance(child, CodeType): names.update(consumed_globals(child))
    return names


def global_value(namespace, name):
    if name in namespace: return namespace[name]
    builtins = namespace['__builtins__']
    return (vars(builtins) if isinstance(builtins, ModuleType) else builtins)[name]


def binding_hash(value):
    # Constructor menus contain frozensets; keep their type in the fingerprint.
    def public(v):
        if type(v) in (set, frozenset):
            return {'type':type(v).__name__, 'items':sorted(v)}
        if type(v) is dict: return {k:public(x) for k,x in v.items()}
        if type(v) in (tuple, list): return [public(x) for x in v]
        return v
    return digest(public(value))


class ReadOnlyCommitAuthority:
    """Bind retained source/asset bytes and exact live dispatch objects privately."""
    def __init__(self, runtime, recipe):
        from .runtime import Runtime
        if type(runtime) is not Runtime:
            raise AuthorityError('Unrecognized runtime class; no inherited proof')
        self.runtime = runtime
        self.recipe = Path(recipe).resolve()
        self.manifest_path = self.recipe/'manifest.json'
        self.manifest_hash = file_hash(self.manifest_path)
        manifest = json.loads(self.manifest_path.read_text())
        if manifest.get('recipe') != 'website-catalog-cart-publication-v1':
            raise AuthorityError('Unrecognized cart recipe')
        self.source_hashes = deepcopy(manifest['source_sha256'])
        self.archives, self.compiled, self.module_bindings = {}, {}, {}
        self.late_module_bindings = {}
        self.module_names = None
        self.phases, self.failures = {}, []
        self.runtime_identity = id(runtime)
        self.runtime_module = runtime.__class__.__module__
        self.world_hash = digest(runtime.world)
        self.recipe_files = deepcopy(manifest['files'])
        self.host_ids = {}
        self.handler_bindings = {}
        self._load_retained_sources()
        # Retain and compare the stdlib HTTP dispatch as loaded. Independent
        # approval must pin these sources too; unsupported-method behavior is
        # part of this exact execution proof.
        import http.server, socketserver
        self.stdlib_sources = {}
        for module in [http.server,socketserver]:
            source=Path(module.__file__).resolve();raw=source.read_bytes()
            self.stdlib_sources[str(source)]=sha256(raw).hexdigest()
            self.compiled[str(source)]=code_index(compile(raw,str(source),'exec',dont_inherit=True))
        self.initial = self._surface()
        self.native_identity = (id(runtime.adapter),id(runtime.baskets),id(runtime.prepared),id(runtime.delivery_oracle))

    def _load_retained_sources(self):
        for name, expected in self.source_hashes.items():
            current = ROOT/name
            archive = self.recipe/'pin/source-snapshot'/name
            if not archive.is_file() or file_hash(archive)!=expected or file_hash(current)!=expected:
                raise AuthorityError('Changed or missing retained source: '+name)
            self.archives[name] = archive.read_bytes()
            if name.endswith('.py'):
                # Compile at the loaded source filename; compare loaded code, not
                # merely the current editable file's checksum or a manifest flag.
                self.compiled[str(current.resolve())] = code_index(
                    compile(self.archives[name], str(current.resolve()), 'exec', dont_inherit=True))
        for name, expected in self.recipe_files.items():
            if file_hash(self.recipe/name)!=expected:
                raise AuthorityError('Recipe artifact changed: '+name)

    def _code_function(self, value):
        if isinstance(value, MethodType): value = value.__func__
        if not isinstance(value, FunctionType):
            raise AuthorityError('Unrecognized callable implementation')
        filename = str(Path(value.__code__.co_filename).resolve())
        allowed = self.compiled.get(filename, {}).get(value.__code__.co_qualname, set())
        fingerprint = code_hash(value.__code__)
        if fingerprint not in allowed:
            raise AuthorityError('Loaded code differs from retained source: '+value.__qualname__)
        return {'source': str(Path(filename).relative_to(ROOT)) if Path(filename).is_relative_to(ROOT) else 'stdlib:'+filename,
                'qualname': value.__code__.co_qualname, 'loaded_code_sha256': fingerprint}

    def _function(self, value):
        if isinstance(value, MethodType): value = value.__func__
        binding = self._code_function(value)
        # functools.wraps copies __module__ from the wrapped function. The
        # actual namespace owner must instead agree with the retained code.
        module = sys.modules.get(value.__globals__.get('__name__'))
        if (not isinstance(module, ModuleType) or value.__globals__ is not vars(module)
                or str(Path(module.__file__).resolve()) != str(Path(value.__code__.co_filename).resolve())):
            raise AuthorityError('Foreign function globals: '+value.__qualname__)
        return binding

    def _prepared(self, prepared):
        """The sole admitted copied namespace, bound to constructor semantics.

        Build one independent constructor control, then compare its immutable
        bindings on every checkpoint. Cache contents may warm; cache/lock and
        closure identities must survive. No copied namespace gets a general
        exemption from ordinary function validation.
        """
        from experiments.accepted_catalog_commerce import basket_quote, prepared_quote, delivery_admission
        canonical = basket_quote.quote
        self._function(canonical)
        self._function(prepared_quote.PreparedQuote.__init__)
        call = getattr(prepared, '_PreparedQuote__call')
        binding = self._code_function(call)
        if (call.__code__ is not canonical.__code__ or call.__globals__ is canonical.__globals__
                or call.__defaults__ != canonical.__defaults__
                or call.__kwdefaults__ != canonical.__kwdefaults__ or call.__closure__ != canonical.__closure__):
            raise AuthorityError('Foreign prepared quote implementation')
        if not hasattr(self, 'prepared_control'):
            self.prepared_control = prepared_quote.PreparedQuote(self.runtime.world,
                plan=self.runtime.baskets.plan, admission_plan=self.runtime.delivery_plan)
        control = self.prepared_control
        expected_call = getattr(control, '_PreparedQuote__call')
        overrides = {'_world', '_choices', 'validate_plan', 'public_policy'}
        globals_binding = {}
        for name in sorted(consumed_globals(canonical.__code__) - overrides):
            actual = global_value(call.__globals__, name)
            expected = global_value(canonical.__globals__, name)
            if name == 'VERSION' and self.runtime.delivery_plan is not None:
                expected = delivery_admission.VERSION
            if actual is not expected:
                raise AuthorityError('Foreign prepared global: '+name)
            globals_binding[name] = id(actual)
        immutable_cells, identities = {}, [id(prepared), id(call), id(call.__globals__)]
        for name in sorted(overrides):
            fn = call.__globals__[name]; expected = expected_call.__globals__[name]
            self._function(fn)
            if (code_hash(fn.__code__) != code_hash(expected.__code__)
                    or fn.__defaults__ != expected.__defaults__ or fn.__kwdefaults__ != expected.__kwdefaults__):
                raise AuthorityError('Foreign prepared constructor closure: '+name)
            cells, expected_cells = closure(fn), closure(expected)
            if set(cells) != set(expected_cells):
                raise AuthorityError('Foreign prepared closure cells: '+name)
            identities.append(id(fn))
            immutable_cells[name] = {}
            for key, value in cells.items():
                identities.append(id(value))
                if key == 'choices_cache':
                    if type(value) is not dict: raise AuthorityError('Foreign prepared cache')
                elif key == 'choices_lock':
                    if type(value) is not type(expected_cells[key]): raise AuthorityError('Foreign prepared lock')
                elif key == 'original_choices':
                    self._function(value)
                    if value is not basket_quote._choices:
                        raise AuthorityError('Foreign prepared choices implementation')
                else:
                    if binding_hash(value) != binding_hash(expected_cells[key]):
                        raise AuthorityError('Foreign prepared closure binding: '+name+'.'+key)
                    immutable_cells[name][key] = binding_hash(value)
        for key in ['world', 'plan', 'policies', 'binding', 'admission']:
            actual = getattr(prepared, '_PreparedQuote__'+key)
            expected = getattr(control, '_PreparedQuote__'+key)
            if digest(actual) != digest(expected):
                raise AuthorityError('Foreign prepared snapshot: '+key)
            identities.append(id(actual))
        if hasattr(self, 'prepared_identities') and self.prepared_identities != identities:
            raise AuthorityError('Prepared constructor bindings replaced during policy')
        self.prepared_identities = identities
        return {'binding':prepared.binding, 'call':binding,
            'private_world_sha256':digest(getattr(prepared,'_PreparedQuote__world')),
            'private_plan_sha256':digest(getattr(prepared,'_PreparedQuote__plan')),
            'consumed_global_identities':globals_binding,'constructor_cells':immutable_cells}

    def _inventory_function(self, module, entry, value):
        # Product releases only these offline aliases for inventory. This must
        # never be used by direct Host/native callback inspections.
        if module.__name__ == OFFLINE_MODULE and entry in OFFLINE_ENTRIES:
            if (Path(module.__file__).resolve() != (ROOT/OFFLINE_SOURCE).resolve()
                    or file_hash(module.__file__) != OFFLINE_SOURCE_SHA256):
                raise AuthorityError('Unsupported offline optimizer source')
            return self._code_function(value) | {
                'inventory_scope':'offline code inventory; namespace not certified for policy-time dispatch',
                'loaded_callable_identity':id(value)}
        return self._function(value)

    def _loaded_modules(self):
        rows = {}
        for name, module in sorted(list(sys.modules.items())):
            if self.module_names is not None and name not in self.module_names: continue
            if name.rsplit('.',1)[-1].startswith('test_'): continue
            if not isinstance(module, ModuleType) or not getattr(module, '__file__', None): continue
            source = str(Path(module.__file__).resolve())
            if source not in self.compiled: continue
            functions = {}
            for key, value in sorted(vars(module).items()):
                if isinstance(value, FunctionType) and str(Path(value.__code__.co_filename).resolve()) in self.compiled:
                    functions[key] = self._inventory_function(module,key,value)
                elif isinstance(value, type) and value.__module__==name:
                    for member, method in sorted(vars(value).items()):
                        if isinstance(method, (staticmethod, classmethod)): method=method.__func__
                        if isinstance(method, property): method=method.fget
                        if isinstance(method, FunctionType) and str(Path(method.__code__.co_filename).resolve()) in self.compiled:
                            functions[key+'.'+member]=self._inventory_function(module,key+'.'+member,method)
            # Object identity closes changes to imported modules/functions during
            # this trusted lifetime; caches/data are not mistaken for commits.
            identities = {k: id(v) for k,v in vars(module).items()
                if isinstance(v, (FunctionType, ModuleType, type)) and not k.startswith('__')}
            identities.update({key:row['loaded_callable_identity'] for key,row in functions.items()
                if 'loaded_callable_identity' in row})
            if name in self.module_bindings:
                original = self.module_bindings[name]
                if any(identities.get(k) != identity for k,identity in original.items()):
                    raise AuthorityError('Loaded callable/import bindings changed: '+name)
                for key in identities.keys() - original.keys():
                    # Python registers lazily imported child modules on packages.
                    # Allow only added registered modules from retained source;
                    # original bindings, added callables and foreign modules
                    # still reject. Remember additions for subsequent checks.
                    value = vars(module).get(key)
                    source = getattr(value, '__file__', None)
                    if (type(value) is not ModuleType or sys.modules.get(value.__name__) is not value
                            or source is None or str(Path(source).resolve()) not in self.compiled):
                        raise AuthorityError('Unrecognized added import/callable binding: '+name+'.'+key)
                    late = self.late_module_bindings.setdefault(name, {})
                    if key in late and late[key] != id(value):
                        raise AuthorityError('Late retained module binding replaced: '+name+'.'+key)
                    late[key] = id(value)
                if any(identities.get(k) != identity for k,identity in self.late_module_bindings.get(name,{}).items()):
                    raise AuthorityError('Late retained module binding disappeared: '+name)
            self.module_bindings.setdefault(name, identities)
            rows[name] = functions
        if self.module_names is None: self.module_names=frozenset(rows)
        if set(rows)!=set(self.module_names): raise AuthorityError('Loaded implementation module disappeared')
        return rows

    def _host(self, key, host, *, renderer=None, retailer=False):
        from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
        import socketserver
        from .runtime import Host
        if type(host) is not Host or type(host.server) is not ThreadingHTTPServer:
            raise AuthorityError('Unrecognized host/router class')
        for standard in [BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer,
                         socketserver.TCPServer,socketserver.BaseServer,socketserver.ThreadingMixIn,
                         socketserver.StreamRequestHandler,socketserver.BaseRequestHandler]:
            module=sys.modules[standard.__module__];filename=str(Path(module.__file__).resolve())
            prefix=standard.__qualname__+'.'
            expected={q[len(prefix):] for q in self.compiled[filename]
                if q.startswith(prefix) and '.' not in q[len(prefix):]}
            loaded={}
            for name,value in vars(standard).items():
                if isinstance(value,(classmethod,staticmethod)):value=value.__func__
                if isinstance(value,property):value=value.fget
                if isinstance(value,FunctionType):loaded[name]=value
            if set(loaded)!=expected:raise AuthorityError('Stdlib dispatch methods changed')
            for name,fn in loaded.items():
                if code_hash(fn.__code__) not in self.compiled[filename][prefix+name]:
                    raise AuthorityError('Loaded stdlib dispatch differs from retained source')
                self._function(fn)
        handler=host.server.RequestHandlerClass
        if handler.__bases__ != (BaseHTTPRequestHandler,) or set(handler.__dict__)-{
                '__module__','__dict__','__weakref__','__doc__','log_message','respond','do_GET','do_POST'}:
            raise AuthorityError('Unrecognized HTTP dispatch surface')
        methods={n:self._function(getattr(handler,n)) for n in ['log_message','respond','do_GET','do_POST']}
        get=closure(handler.do_GET);post=closure(handler.do_POST)
        if closure(handler.respond).get('outer') is not host:
            raise AuthorityError('Handler belongs to another host')
        render=get.get('render');post_render=post.get('post_render')
        if render is None: raise AuthorityError('Missing actual GET router')
        render_binding=self._function(render)
        if renderer is not None and render != renderer:
            raise AuthorityError('Foreign surrounding/index route')
        if retailer:
            if render_binding['qualname']!='Runtime.__init__.<locals>.render':
                raise AuthorityError('Unrecognized retailer GET router')
            nonlocals=closure(render)
            if nonlocals.get('self') is not self.runtime or render.__kwdefaults__.get('sid')!=key:
                raise AuthorityError('Foreign retailer route binding')
            assets=nonlocals.get('assets')
            if type(assets) is not dict or {n:sha256(v).hexdigest() for n,v in assets.items()}!=self.runtime.asset_hashes:
                raise AuthorityError('Retained served bytes differ from asset inventory')
            body=render.__kwdefaults__.get('body')
            if type(body) is not str or sha256(body.encode()).hexdigest()!=self.runtime.html_hashes[key]:
                raise AuthorityError('Retained retailer HTML changed')
            if "if(worldBinding){feedback='Purchase submission is unavailable.';render();return;}" not in assets['shop.js'].decode():
                raise AuthorityError('Generated purchase guard missing')
            quote_source=assets['quote.js'].decode()
            if 'worldBinding' not in quote_source:
                raise AuthorityError('Generated world binding absent')
            if not isinstance(post_render, FunctionType) or closure(post_render).get('self') is not self.runtime or post_render.__defaults__!=(key,):
                raise AuthorityError('Foreign or unbound commerce POST route')
            post_binding=self._function(post_render)
            if post_binding['qualname']!='Runtime.__init__.<locals>.<lambda>':
                raise AuthorityError('Unrecognized basket POST router')
        elif post_render is not None:
            raise AuthorityError('Surrounding/discovery host admits commerce POST')
        else:
            post_binding=None
            if key=='@start' and render_binding['qualname']!='Runtime.__init__.<locals>.research_page':
                raise AuthorityError('Unrecognized discovery start router')
        identities=(id(host),id(host.server),id(handler),id(render),id(post_render))
        if key in self.host_ids and self.host_ids[key]!=identities:
            raise AuthorityError('Host/router was replaced during policy')
        self.host_ids.setdefault(key,identities)
        self.handler_bindings[key]=(host,render,post_render)
        return {'transport_origin':host.origin,'handler':methods,'get_router':render_binding,
            'post_router':post_binding,'admitted_post_route':'/api/basket-quote' if retailer else None,
            'other_methods':'stdlib HTTP denial; no generated commit callback'}

    def _surface(self):
        from . import catalog_adapter, catalog_checkout_domain
        from .basket import Baskets
        from .native_review_pages import NativeReviewPage
        from .comparison_pages import ComparisonPage as RichComparisonPage
        from .discovery import Index
        from .local_origins import OriginMap
        from experiments.accepted_catalog_commerce import basket_quote, prepared_quote, delivery_admission
        r=self.runtime
        if hasattr(self,'native_identity') and self.native_identity!=(id(r.adapter),id(r.baskets),id(r.prepared),id(r.delivery_oracle)):
            raise AuthorityError('Native quote/adapter object changed during policy')
        if id(r)!=self.runtime_identity or type(r.adapter) is not catalog_adapter.PublicAdapter or r.catalog_backend is not catalog_adapter:
            raise AuthorityError('Different or unsupported commerce runtime')
        if r.coupons is not None or any('account' in p for p in r.public_catalogs.values()):
            raise AuthorityError('Account/coupon-enabled runtime is outside this proof')
        if type(r.baskets) is not Baskets or r.baskets.adapter is not r.adapter or r.baskets.coupons is not None or r.baskets.domain_provider is not catalog_checkout_domain:
            raise AuthorityError('Unrecognized basket/native domain implementation')
        if r.baskets.prepared is not r.prepared or r.baskets.oracle is not r.delivery_oracle:
            raise AuthorityError('Unbound native/prepared quote implementation')
        if r.prepared is not None and type(r.prepared) is not prepared_quote.PreparedQuote:
            raise AuthorityError('Unknown prepared quote class')
        if r.delivery_oracle is not basket_quote and type(r.delivery_oracle) is not delivery_admission.Oracle:
            raise AuthorityError('Unknown native quote implementation')
        if digest(r.world)!=self.world_hash or r.adapter.world is not r.world:
            raise AuthorityError('Generated source world changed')
        if type(r.discovery) is not Index or type(r.origin_map) is not OriginMap:
            raise AuthorityError('Proof requires the bound rich directory and logical origins')
        views=r.surrounding_views
        if set(r.sites)!=set(r.origins)|set(views) or set(views)!=set(r.surrounding_origins):
            raise AuthorityError('Missing/foreign generated hosts')
        hosts={}
        for key,host in r.sites.items():
            if key in r.origins:
                hosts[key]=self._host(key,host,retailer=True)
            else:
                view=views[key]
                if type(view) not in [NativeReviewPage,RichComparisonPage]:
                    raise AuthorityError('Unrecognized surrounding route class')
                hosts[key]=self._host(key,host,renderer=view.page)
        hosts['@index']=self._host('@index',r.index,renderer=r.index_page)
        if r.discovery_mode=='tool':hosts['@start']=self._host('@start',r.research)
        mapping=r.origin_map.descriptor
        if {s['site_id']:s['transport_origin'] for s in mapping['sites']}!={k:v['transport_origin'] for k,v in hosts.items()}:
            raise AuthorityError('Logical/transport host map changed')
        for method in ['__init__','_quote','quote','policy']:
            self._function(getattr(r.baskets,method))
        self._function(r.adapter.__init__)
        self._function(r.adapter.fulfilment);self._function(r.adapter.pending_fulfilment)
        modules=self._loaded_modules()
        prepared=self._prepared(r.prepared) if r.prepared is not None else None
        return {'world_sha256':self.world_hash,'hosts':hosts,'logical_origins':mapping,
            'loaded_modules':modules,'served_asset_sha256':deepcopy(r.asset_hashes),
            'served_html_sha256':deepcopy(r.html_hashes),'prepared_quote':prepared,
            'basket_plan_sha256':digest(r.baskets.plan),'checkout_domain_sha256':digest(r.baskets.domain),
            'recipe_sha256':self.manifest_hash,'source_sha256':self.source_hashes,'stdlib_source_sha256':self.stdlib_sources}

    def checkpoint(self, phase, trace):
        if phase not in ['before_policy','after_policy_before_context_close'] or phase in self.phases:
            raise AuthorityError('Missing/duplicate authority phase')
        try:
            if file_hash(self.manifest_path)!=self.manifest_hash: raise AuthorityError('Recipe changed during policy')
            for name,h in self.source_hashes.items():
                if file_hash(ROOT/name)!=h or file_hash(self.recipe/'pin/source-snapshot'/name)!=h:
                    raise AuthorityError('Source changed during policy: '+name)
            for name,h in self.stdlib_sources.items():
                if file_hash(name)!=h:raise AuthorityError('HTTP stdlib source changed')
            current=self._surface()
            if current!=self.initial: raise AuthorityError('Bound surface changed during policy')
            if self.phases and any(p['episode_id']!=trace.episode_id or p['trace_directory']!=str(trace.directory.resolve()) for p in self.phases.values()):
                raise AuthorityError('Different actual episode/trace')
            self.phases[phase]={'episode_id':trace.episode_id,'trace_directory':str(trace.directory.resolve()),
                'surface_sha256':digest(current)}
        except (ValueError,KeyError,TypeError,AttributeError) as e:
            self.failures.append({'phase':phase,'error':str(e)});raise

    def seal(self, trace, *, episode_id, main_trace_sha256, captures, approval=None):
        path=Path(trace).resolve()
        if set(self.phases)!={'before_policy','after_policy_before_context_close'} or self.failures:
            raise AuthorityError('Whole-policy authority phases missing or failed')
        if any(p['episode_id']!=episode_id or p['trace_directory']!=str(path) for p in self.phases.values()) or file_hash(path/'steps.jsonl')!=main_trace_sha256:
            raise AuthorityError('Authority/capsule episode or main trace differs')
        if set(captures)!={'before','after'}: raise AuthorityError('Raw capture phases missing')
        for p in captures.values():
            if not Path(p['path']).resolve().is_relative_to(path) or file_hash(p['path'])!=p['sha256']:
                raise AuthorityError('Authority raw capture changed')
        if not hasattr(self,'compiled') or type(self._surface) is not MethodType or self._surface.__func__ is not ReadOnlyCommitAuthority._surface:
            raise AuthorityError('Unbound authority implementation')
        self._function(self._surface);self._function(self.checkpoint);self._function(self.seal)
        if self._surface()!=self.initial:raise AuthorityError('Runtime changed before proof sealing')
        receipt={'schema':VERSION,'status':'candidate_empty_set_proof_independent_acceptance_required',
            'episode_id':episode_id,'main_trace_sha256':main_trace_sha256,'phases':deepcopy(self.phases),
            'surface':deepcopy(self.initial),'captures':deepcopy(captures),'failures':deepcopy(self.failures),
            'proof_kind':'Empty-set proof from retained read-only generated execution surface; not an observed journal',
            'scope':'Generated authoritative order/payment/subscription/account commits only',
            'excluded':['External effects','Purchase attempts','Transient client-only demo history','Arbitrary user-defined JavaScript effects'],
            'helper_source_sha256':file_hash(__file__),'native_effect_envelope':None}
        if approval is not None:
            approved_path=Path(approval['path']);data=json.loads(approved_path.read_text())
            if file_hash(approved_path)!=approval['sha256'] or data.get('owner')!='Product' or data.get('status')!='accepted' or data.get('authority_schema')!=VERSION or data.get('helper_source_sha256')!=receipt['helper_source_sha256'] or data.get('source_sha256')!=self.source_hashes or data.get('stdlib_source_sha256')!=self.stdlib_sources:
                raise AuthorityError('Missing exact independent authority acceptance')
            receipt['independent_acceptance']=deepcopy(approval)
            receipt['status']='accepted_empty_set_proof'
            receipt['native_effect_envelope']={'authority':'complete_generated_world_event_journal','complete':True,'events':[]}
        return receipt
