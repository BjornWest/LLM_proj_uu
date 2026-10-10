"""Finite adversarial source/route controls; real-runtime cases require a pin.

Do not count these as executed before the explicit resource release. The runtime
fixture explicitly skips without an opt-in recipe, and never substitutes a reduced host.
Acceptance batches must supply the recipe and require zero skipped cases.
"""
from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
from types import FunctionType, ModuleType, SimpleNamespace
import sys
import httpx
import pytest
from environments.website_world.catalog_cart_authority import (
    AuthorityError, ReadOnlyCommitAuthority, ROOT, closure, code_hash, code_index, consumed_globals)


def test_loaded_code_fingerprint_matches_retained_compilation():
    path=ROOT/'environments/website_world/catalog_cart_authority.py'
    index=code_index(compile(path.read_bytes(),str(path),'exec',dont_inherit=True))
    assert code_hash(ReadOnlyCommitAuthority.checkpoint.__code__) in index[ReadOnlyCommitAuthority.checkpoint.__qualname__]


def test_same_qualname_changed_code_is_not_accepted():
    filename=str(ROOT/'.local/authority-authored.py')
    old=compile('def route():\n return 1\n',filename,'exec');changed=compile('def route():\n return 2\n',filename,'exec')
    namespace={};exec(changed,namespace)
    authority=object.__new__(ReadOnlyCommitAuthority);authority.compiled={filename:code_index(old)}
    with pytest.raises(AuthorityError,match='Loaded code differs'):authority._function(namespace['route'])


def test_unknown_runtime_class_cannot_inherit_authority(tmp_path):
    with pytest.raises(AuthorityError,match='Unrecognized runtime'):
        ReadOnlyCommitAuthority(SimpleNamespace(),tmp_path)


def test_same_code_foreign_function_namespace_is_rejected():
    original=ReadOnlyCommitAuthority.checkpoint
    filename=str(Path(original.__code__.co_filename).resolve())
    authority=object.__new__(ReadOnlyCommitAuthority)
    authority.compiled={filename:code_index(compile(Path(filename).read_bytes(),filename,'exec',dont_inherit=True))}
    foreign=FunctionType(original.__code__,dict(original.__globals__),original.__name__,original.__defaults__,original.__closure__)
    assert authority._function(original)['qualname']==original.__qualname__
    with pytest.raises(AuthorityError,match='Foreign function globals'):authority._function(foreign)


def test_consumed_globals_include_nested_comprehensions_and_exclude_attributes():
    code=compile('def quote():\n return [factory.method(x) for x in values if predicate(x)]\n','authored.py','exec')
    quote=next(c for c in code.co_consts if hasattr(c,'co_qualname'))
    assert consumed_globals(quote)=={'factory','values','predicate'}


def test_wraps_metadata_does_not_change_the_actual_namespace_owner():
    from intent_browser import debug_timings
    wrapper=debug_timings.timed('authored-test')(ReadOnlyCommitAuthority.checkpoint)
    assert wrapper.__module__==ReadOnlyCommitAuthority.__module__
    assert wrapper.__globals__ is vars(debug_timings)
    path=Path(debug_timings.__file__).resolve()
    authority=object.__new__(ReadOnlyCommitAuthority)
    authority.compiled={str(path):code_index(compile(path.read_bytes(),str(path),'exec',dont_inherit=True))}
    assert authority._function(wrapper)['source']=='intent_browser/debug_timings.py'
    foreign=FunctionType(wrapper.__code__,dict(wrapper.__globals__),wrapper.__name__,wrapper.__defaults__,wrapper.__closure__)
    with pytest.raises(AuthorityError,match='Foreign function globals'):authority._function(foreign)


def offline_inventory_authority():
    from experiments.accepted_catalog_commerce import order_set_optimizer as offline
    from experiments.footwear_world_pilot import order_set_optimizer as historical
    authority=object.__new__(ReadOnlyCommitAuthority)
    authority.compiled={};authority.module_names=None;authority.module_bindings={};authority.late_module_bindings={}
    for module in [offline,historical]:
        path=Path(module.__file__).resolve()
        authority.compiled[str(path)]=code_index(compile(path.read_bytes(),str(path),'exec',dont_inherit=True))
    return authority,offline


def test_exact_three_offline_bindings_are_inventory_only():
    authority,offline=offline_inventory_authority()
    rows=authority._loaded_modules()[offline.__name__]
    exceptions={name for name,row in rows.items() if 'inventory_scope' in row}
    assert exceptions=={'_Checkout.dispatch','_Checkout.options','_solve'}
    assert all('namespace not certified' in rows[name]['inventory_scope'] for name in exceptions)
    assert authority._loaded_modules()[offline.__name__]==rows


@pytest.mark.parametrize('entry',['_Checkout.dispatch','_Checkout.options','_solve'])
def test_offline_inventory_exception_never_accepts_a_direct_callable(entry):
    authority,offline=offline_inventory_authority()
    value=offline._solve if entry=='_solve' else getattr(offline._Checkout,entry.split('.')[1])
    assert 'inventory_scope' in authority._inventory_function(offline,entry,value)
    with pytest.raises(AuthorityError,match='Foreign function globals'):authority._function(value)


def test_offline_clone_as_actual_commerce_callback_is_rejected(actual_runtime,monkeypatch):
    from experiments.accepted_catalog_commerce import order_set_optimizer as offline
    runtime,recipe=actual_runtime;authority=ReadOnlyCommitAuthority(runtime,recipe)
    host=runtime.sites[next(iter(runtime.origins))]
    monkeypatch.setattr(host.server.RequestHandlerClass,'do_POST',offline._solve)
    with pytest.raises(AuthorityError):authority._surface()


def test_offline_inventory_has_no_whole_module_exception(monkeypatch):
    authority,offline=offline_inventory_authority()
    monkeypatch.setattr(offline,'foreign_entry',offline._solve,raising=False)
    with pytest.raises(AuthorityError,match='Foreign function globals'):authority._loaded_modules()


def test_offline_inventory_preserves_method_identity(monkeypatch):
    authority,offline=offline_inventory_authority();authority._loaded_modules()
    fn=offline._Checkout.dispatch
    replacement=FunctionType(fn.__code__,fn.__globals__,fn.__name__,fn.__defaults__,fn.__closure__)
    monkeypatch.setattr(offline._Checkout,'dispatch',replacement)
    with pytest.raises(AuthorityError,match='Loaded callable/import bindings changed'):authority._loaded_modules()


def late_import_inventory(tmp_path,monkeypatch):
    parent=ModuleType('cart_authority_inventory_parent');child=ModuleType('cart_authority_inventory_child')
    parent_file=tmp_path/'parent.py';child_file=tmp_path/'child.py'
    parent_file.write_text('def guard():\n return None\n');child_file.write_text('# retained lazy module\n')
    parent.__file__=str(parent_file);child.__file__=str(child_file)
    exec(compile(parent_file.read_bytes(),str(parent_file),'exec'),vars(parent))
    monkeypatch.setitem(sys.modules,parent.__name__,parent)
    monkeypatch.setitem(sys.modules,child.__name__,child)
    authority=object.__new__(ReadOnlyCommitAuthority)
    authority.compiled={str(p):code_index(compile(p.read_bytes(),str(p),'exec',dont_inherit=True)) for p in [parent_file,child_file]}
    authority.module_names=None;authority.module_bindings={};authority.late_module_bindings={}
    initial=authority._loaded_modules()
    return authority,parent,child,initial


def test_late_registered_retained_module_preserves_inventory(tmp_path,monkeypatch):
    authority,parent,child,initial=late_import_inventory(tmp_path,monkeypatch)
    parent.child=child
    assert authority._loaded_modules()==initial
    assert authority.late_module_bindings[parent.__name__]=={'child':id(child)}
    assert authority._loaded_modules()==initial


@pytest.mark.parametrize('fault',['foreign_module','new_callable','replace_original','replace_late','remove_late','unregistered_retained_module'])
def test_late_imports_do_not_weaken_original_or_added_bindings(tmp_path,monkeypatch,fault):
    authority,parent,child,_=late_import_inventory(tmp_path,monkeypatch)
    parent.child=child;authority._loaded_modules()
    if fault=='foreign_module':parent.foreign=ModuleType('foreign')
    elif fault=='new_callable':parent.added=parent.guard
    elif fault=='replace_original':parent.guard=lambda:None
    elif fault=='replace_late':parent.child=ModuleType(child.__name__);parent.child.__file__=child.__file__
    elif fault=='remove_late':del parent.child
    else:
        added=ModuleType('unregistered');added.__file__=child.__file__;parent.added=added
    with pytest.raises(AuthorityError):authority._loaded_modules()


@pytest.fixture(scope='module')
def actual_runtime():
    configured=os.environ.get('WEBSITE_CART_AUTHORITY_RECIPE')
    if not configured:pytest.skip('Explicit frozen cart authority recipe required; acceptance must run with zero skips')
    recipe=Path(configured).resolve()
    from environments.website_world.runtime import Runtime
    read=lambda name:json.loads((recipe/name).read_text())
    with Runtime(recipe/'pin',presentation=read('presentation.json'),surrounding=read('surrounding.private.json'),
            basket_plan=read('basket-plan.private.json'),checkout_domain=read('checkout-domain.private.json'),
            delivery_plan=read('delivery-plan.private.json') if (recipe/'delivery-plan.private.json').exists() else None,
            readable_origins=True,discovery_mode='tool',lazy_publication=True) as runtime:
        yield runtime,recipe


def test_actual_host_dispatch_denies_commit_routes_and_methods(actual_runtime):
    runtime,recipe=actual_runtime;authority=ReadOnlyCommitAuthority(runtime,recipe);before=deepcopy(runtime.world)
    hosts=[*runtime.sites.values(),runtime.index,runtime.research]
    for host in hosts:
        for method,path in [('POST','/api/orders'),('POST','/api/account'),('POST','/api/subscription'),
                            ('POST','/api/basket-quote?purchase=1'),('PUT','/api/orders'),('DELETE','/api/orders'),('PATCH','/api/account')]:
            response=httpx.request(method,host.origin+path,json={},timeout=10)
            assert response.status_code==(405 if method=='POST' else 501)
        assert httpx.get(host.origin+'/api/orders',timeout=10).status_code==404
    assert runtime.world==before and authority._surface()==authority.initial


def test_actual_native_prepared_quotes_do_not_mutate_world_or_policy(actual_runtime):
    runtime,recipe=actual_runtime;authority=ReadOnlyCommitAuthority(runtime,recipe)
    world,plan,domain=deepcopy(runtime.world),deepcopy(runtime.baskets.plan),deepcopy(runtime.baskets.domain)
    joined=[]
    for r in runtime.world['retailers']:
        rid=r['retailer_id'];offer=r['offers'][0]
        context=runtime.world['address_context']['addresses'][0]['address']
        address={'name':context['recipient'],'street':(context['street']+' '+context['house_number']).strip(),
            'unit':context['unit'],'postcode':context['postcode'],'city':context['city']}
        body={'revision':0,'world_id':world['world_id'],'plan_id':runtime.baskets.plan_id,
            'domain_id':runtime.baskets.domain_id,'lines':[{'line_id':offer['offer_id'],'offer_id':offer['offer_id'],'quantity':1}],
            'address':address,'selections':None,'split':False,'coupon_code':None}
        native=runtime.baskets.quote(rid,body)
        response=httpx.post(runtime.sites[rid].origin+'/api/basket-quote',json=body,timeout=15)
        assert response.status_code==200 and response.json()==native;joined.append(rid)
    assert joined and runtime.world==world and runtime.baskets.plan==plan and runtime.baskets.domain==domain
    assert authority._surface()==authority.initial


@pytest.mark.parametrize('when',['before_authority','after_initial','between_checkpoints'])
def test_prepared_non_override_global_replacement_is_rejected(actual_runtime,monkeypatch,tmp_path,when):
    runtime,recipe=actual_runtime
    assert runtime.prepared is not None
    namespace=getattr(runtime.prepared,'_PreparedQuote__call').__globals__
    if when=='before_authority':
        monkeypatch.setitem(namespace,'_build_option',lambda *a,**kw: {})
        with pytest.raises(AuthorityError,match='Foreign prepared global: _build_option'):
            ReadOnlyCommitAuthority(runtime,recipe)
    else:
        authority=ReadOnlyCommitAuthority(runtime,recipe)
        trace=SimpleNamespace(directory=tmp_path,episode_id='global-replacement')
        if when=='between_checkpoints':authority.checkpoint('before_policy',trace)
        monkeypatch.setitem(namespace,'_build_option',lambda *a,**kw: {})
        with pytest.raises(AuthorityError,match='Foreign prepared global: _build_option'):
            if when=='between_checkpoints':authority.checkpoint('after_policy_before_context_close',trace)
            else:authority._surface()
        if when=='between_checkpoints':assert authority.failures


@pytest.mark.parametrize('fault',['foreign_namespace','wrong_constructor_lambda','changed_validation','foreign_choices'])
def test_prepared_constructor_provenance_and_bindings_are_checked(actual_runtime,monkeypatch,fault):
    runtime,recipe=actual_runtime;authority=ReadOnlyCommitAuthority(runtime,recipe)
    call=getattr(runtime.prepared,'_PreparedQuote__call');namespace=call.__globals__
    if fault=='foreign_namespace':
        fn=namespace['_choices']
        monkeypatch.setitem(namespace,'_choices',FunctionType(fn.__code__,dict(fn.__globals__),fn.__name__,fn.__defaults__,fn.__closure__))
    elif fault=='wrong_constructor_lambda':monkeypatch.setitem(namespace,'_world',namespace['validate_plan'])
    elif fault=='changed_validation':monkeypatch.setitem(closure(namespace['validate_plan'])['validation'],'valid',False)
    else:
        fn=namespace['_choices'];cell=fn.__closure__[fn.__code__.co_freevars.index('original_choices')]
        monkeypatch.setattr(cell,'cell_contents',lambda *a: [])
    with pytest.raises(AuthorityError):authority._surface()


@pytest.mark.parametrize('admitted',[False,True])
def test_prepared_constructor_control_allows_admission_and_cache_warming(actual_runtime,admitted):
    from experiments.accepted_catalog_commerce import basket_quote,prepared_quote,delivery_admission
    runtime,_=actual_runtime;world=runtime.world;plan=runtime.baskets.plan
    admission=delivery_admission.make_plan(world,plan,seed=86) if admitted else None
    prepared=prepared_quote.prepare(world,plan=plan,admission_plan=admission)
    authority=object.__new__(ReadOnlyCommitAuthority)
    authority.compiled={}
    for module in [basket_quote,prepared_quote]:
        path=Path(module.__file__).resolve()
        authority.compiled[str(path)]=code_index(compile(path.read_bytes(),str(path),'exec',dont_inherit=True))
    authority.runtime=SimpleNamespace(world=world,baskets=SimpleNamespace(plan=plan),delivery_plan=admission)
    before=authority._prepared(prepared)
    call=getattr(prepared,'_PreparedQuote__call')
    # Exercise the actual permitted cache, not an authored cache payload.
    rid=world['retailers'][0]['retailer_id']
    retailers=closure(call.__globals__['_world'])['retailers']
    policy=next(p for p in plan['retailer_policies'] if p['retailer_id']==rid)
    rows=call.__globals__['_choices'](getattr(prepared,'_PreparedQuote__world'),retailers[rid],policy,world['user_location'])
    cache=closure(call.__globals__['_choices'])['choices_cache']
    assert cache
    expected=basket_quote._choices(world,retailers[rid],policy,world['user_location'])
    if admitted:
        menu=next(r['admitted_route_keys'] for r in admission['retailers'] if r['retailer_id']==rid)
        expected=[c for c in expected if delivery_admission.route_key(c) in menu]
    assert rows==expected and authority._prepared(prepared)==before


def test_prepared_builtin_shadowing_is_rejected(actual_runtime,monkeypatch):
    runtime,recipe=actual_runtime;authority=ReadOnlyCommitAuthority(runtime,recipe)
    namespace=getattr(runtime.prepared,'_PreparedQuote__call').__globals__
    monkeypatch.setitem(namespace,'len',lambda unused: 0)
    with pytest.raises(AuthorityError,match='Foreign prepared global: len'):authority._surface()


@pytest.mark.parametrize('fault',['coupons','foreign_host','foreign_post','changed_assets','changed_loaded_quote'])
def test_bound_runtime_rejects_foreign_execution_surface(actual_runtime,monkeypatch,fault):
    runtime,recipe=actual_runtime;authority=ReadOnlyCommitAuthority(runtime,recipe)
    rid=next(iter(runtime.origins));host=runtime.sites[rid];handler=host.server.RequestHandlerClass
    if fault=='coupons':monkeypatch.setattr(runtime,'coupons',object())
    elif fault=='foreign_host':monkeypatch.setitem(runtime.sites,'foreign',host)
    elif fault=='foreign_post':monkeypatch.setattr(handler,'do_POST',lambda self:None)
    elif fault=='changed_assets':monkeypatch.setitem(runtime.asset_hashes,'shop.js','0'*64)
    else:monkeypatch.setattr(runtime.baskets,'quote',lambda *a,**kw:{})
    with pytest.raises(AuthorityError):authority._surface()


def fake_sealing_authority(tmp_path):
    trace=tmp_path/'trace';trace.mkdir();(trace/'steps.jsonl').write_text('{}\n')
    authority=object.__new__(ReadOnlyCommitAuthority)
    authority.phases={p:{'episode_id':'actual','trace_directory':str(trace.resolve())} for p in ['before_policy','after_policy_before_context_close']}
    authority.failures=[];authority.initial={'scope':'authored-seal-control'};authority._surface=lambda:deepcopy(authority.initial)
    authority.source_hashes={};authority.stdlib_sources={}
    captures={}
    for phase in ['before','after']:
        path=trace/(phase+'.json');path.write_text('{}')
        captures[phase]={'path':str(path),'sha256':sha256(path.read_bytes()).hexdigest()}
    return authority,trace,captures


def test_unbound_helper_cannot_emit_an_authority_receipt(tmp_path):
    authority,trace,captures=fake_sealing_authority(tmp_path)
    with pytest.raises(AuthorityError,match='Unbound authority'):
        authority.seal(trace,episode_id='actual',main_trace_sha256=sha256((trace/'steps.jsonl').read_bytes()).hexdigest(),captures=captures)


def actual_sealing_authority(actual_runtime,tmp_path):
    runtime,recipe=actual_runtime;authority=ReadOnlyCommitAuthority(runtime,recipe)
    trace=tmp_path/'actual-source-proof';trace.mkdir();(trace/'steps.jsonl').write_text('{}\n')
    t=SimpleNamespace(directory=trace,episode_id='source-proof-control')
    for phase in ['before_policy','after_policy_before_context_close']:authority.checkpoint(phase,t)
    captures={}
    for label in ['before','after']:
        p=trace/(label+'.json');p.write_text('{}')
        captures[label]={'path':str(p),'sha256':sha256(p.read_bytes()).hexdigest()}
    return authority,trace,t.episode_id,captures


def test_actual_candidate_proof_requires_independent_acceptance(actual_runtime,tmp_path):
    authority,trace,eid,captures=actual_sealing_authority(actual_runtime,tmp_path)
    proof=authority.seal(trace,episode_id=eid,main_trace_sha256=sha256((trace/'steps.jsonl').read_bytes()).hexdigest(),captures=captures)
    assert proof['native_effect_envelope'] is None
    assert proof['status']=='candidate_empty_set_proof_independent_acceptance_required'
    assert proof['proof_kind'].startswith('Empty-set proof')
    # Raw bytes here are authored seal fixtures, not browser capture proof.


@pytest.mark.parametrize('fault',['unaccepted','wrong_helper_hash','wrong_source_hash','wrong_stdlib_hash','wrong_receipt_hash'])
def test_actual_valid_seal_reaches_approval_rejection(actual_runtime,tmp_path,fault):
    authority,trace,eid,captures=actual_sealing_authority(actual_runtime,tmp_path)
    path=tmp_path/'approval.json'
    data={'owner':'Product','status':'accepted','authority_schema':'website-catalog-cart-read-only-authority-v1',
        'helper_source_sha256':sha256((ROOT/'environments/website_world/catalog_cart_authority.py').read_bytes()).hexdigest(),
        'source_sha256':authority.source_hashes,'stdlib_source_sha256':authority.stdlib_sources}
    if fault=='unaccepted':data['status']='candidate'
    elif fault=='wrong_helper_hash':data['helper_source_sha256']='0'*64
    elif fault=='wrong_source_hash':data['source_sha256']={}
    elif fault=='wrong_stdlib_hash':data['stdlib_source_sha256']={}
    path.write_text(json.dumps(data))
    approval={'path':str(path),'sha256':'0'*64 if fault=='wrong_receipt_hash' else sha256(path.read_bytes()).hexdigest()}
    with pytest.raises(AuthorityError,match='Missing exact independent authority acceptance'):
        authority.seal(trace,episode_id=eid,main_trace_sha256=sha256((trace/'steps.jsonl').read_bytes()).hexdigest(),captures=captures,approval=approval)


@pytest.mark.parametrize('fault',['missing_phase','different_episode','different_trace_hash','tampered_capture','failed_checkpoint'])
def test_sealing_requires_actual_phases_and_exact_independent_approval(tmp_path,fault):
    authority,trace,captures=fake_sealing_authority(tmp_path);eid='actual';h=sha256((trace/'steps.jsonl').read_bytes()).hexdigest();approval=None
    if fault=='missing_phase':authority.phases.pop('before_policy')
    elif fault=='different_episode':eid='foreign'
    elif fault=='different_trace_hash':h='0'*64
    elif fault=='tampered_capture':Path(captures['before']['path']).write_text('changed')
    elif fault=='failed_checkpoint':authority.failures.append({'error':'unbound'})
    with pytest.raises(AuthorityError):authority.seal(trace,episode_id=eid,main_trace_sha256=h,captures=captures,approval=approval)
