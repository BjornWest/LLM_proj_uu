"""Copied-source and synthetic observer controls; no browser/model evidence."""
from copy import deepcopy
from hashlib import sha256
import base64
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from . import selector_action_capture as capture
from . import partial_url_navigation

ROOT = Path(__file__).resolve().parents[2]
SETTINGS = {'shop': {'page_id': 'page', 'control_token': '1'*32}}


class SelectorCaptureTests(unittest.TestCase):
    def test_full_source_inverse_and_other_assets_survive_composition(self):
        source = (ROOT/'environments/website_drafts/shop.js').read_bytes()
        assets = {'shop.js': source, 'other.js': b'unchanged'}
        assets, _ = partial_url_navigation.project_assets(assets, expected_source_sha256=sha256(source).hexdigest())
        before = deepcopy(assets)
        changed, evidence = capture.project_assets(assets, expected_source_sha256=sha256(assets['shop.js']).hexdigest(), settings=SETTINGS)
        self.assertEqual(capture.restore_source(changed['shop.js'], evidence), before['shop.js'])
        self.assertEqual(changed['other.js'], b'unchanged')
        self.assertEqual(changed['resolve-navigation.js'], before['resolve-navigation.js'])
        self.assertEqual(assets, before)

    def test_initialization_before_change_during_top_level_refresh(self):
        source = "const site='shop', window=globalThis, document={addEventListener(){}};\nconst state={selection:{page:{size_eu:'40',colour:'brown'}}}, products=[{id:'page'}];\nconst route=()=>({id:'page'}), sentinel={};let calls=0;\nconst resolveProduct=(id,selection)=>({variant:{selection}});\nfunction changeSelection(key,value) {\n const p=products[0];state.selection[p.id]={...state.selection[p.id],[key]:value};\n const {variant}=resolveProduct(p.id,state.selection[p.id]);state.selection[p.id]={...variant.selection};\n calls++;return sentinel;\n}\ndocument.addEventListener('change',event=>{});\nawait Promise.resolve().then(()=>{assert.equal(changeSelection('size_eu','38'),sentinel);});\nassert.equal(calls,1);assert.equal(state.selection.page.size_eu,'38');\n".encode()
        assets, evidence = capture.project_assets({'shop.js':source},expected_source_sha256=sha256(source).hexdigest(),settings=SETTINGS)
        self.assertEqual(capture.restore_source(assets['shop.js'],evidence),source)
        uri = 'data:text/javascript;base64,'+base64.b64encode(assets['selector-action-capture.js']).decode()
        code = 'import assert from "node:assert/strict";\n'+assets['shop.js'].decode().replace('"./selector-action-capture.js"',json.dumps(uri))
        result=subprocess.run(['node','--input-type=module','-e',code],capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_malformed_settings_changed_source_and_duplicate_observer_reject(self):
        for value in (False, {}, {'shop': {'page_id': 'page', 'control_token': 'bad'}}):
            with self.assertRaises(ValueError): capture.options(value)
        source = (ROOT/'environments/website_drafts/shop.js').read_bytes()
        with self.assertRaises(ValueError): capture.project_assets({'shop.js':source}, expected_source_sha256='bad', settings=SETTINGS)
        changed, _ = capture.project_assets({'shop.js':source}, expected_source_sha256=sha256(source).hexdigest(), settings=SETTINGS)
        with self.assertRaises(ValueError): capture.project_assets(changed, expected_source_sha256=sha256(changed['shop.js']).hexdigest(), settings=SETTINGS)

    def test_absent_or_ambiguous_target_is_rejected(self):
        for pages in ([], [{'id': 'other'}], [{'id': 'page'}, {'id': 'page'}]):
            with self.assertRaises(ValueError): capture.validate_catalog({'siteId': 'shop', 'products': pages}, retailer_id='shop', settings=SETTINGS)

    def test_native_projection_never_repairs_missing_event_chain(self):
        initial, final = {'size_eu': '40', 'colour': 'brown'}, {'size_eu': '39', 'colour': 'black'}
        middle = {'size_eu': '38', 'colour': 'brown'}
        task = {'page_id':'page'}
        raw = {'documentToken':'actual-document','pageId':'page','initialSelection':initial,'finalSelection':final,
               'complete':True,'faults':[], 'events':[
                   {'page_id':'page','axis':'size_eu','requested_value':'38','before':initial,'after':middle,'sequence':0,'started_at':1,'finished_at':2},
                   {'page_id':'page','axis':'colour','requested_value':'black','before':middle,'after':final,'sequence':1,'started_at':3,'finished_at':4}]}
        args = {'task':task,'main_trace_sha256':'a'*64,'document_token':'actual-document','page_retained':True,
                'initial_selection':initial,'final_selection':final}
        self.assertEqual(len(capture.native_projection(raw, **args)['events']),2)
        projected = capture.native_projection(raw, **args)
        projected['events'][0]['after']['size_eu'] = 'mutated-copy'
        self.assertEqual(raw['events'][0]['after']['size_eu'], '38')
        for kind in ('incomplete','document','sequence','before','timestamp','overflow'):
            changed = deepcopy(raw)
            if kind=='incomplete': changed['complete']=False
            elif kind=='document': changed['documentToken']='new-document'
            elif kind=='sequence': changed['events'][1]['sequence']=0
            elif kind=='before': changed['events'][1]['before']=initial
            elif kind=='timestamp': changed['events'][1]['finished_at']=float('nan')
            else: changed['faults']=['overflow']
            self.assertIsNone(capture.native_projection(changed, **args))
        self.assertIsNone(capture.native_projection(raw, **{**args,'page_retained':False}))

    def test_actual_js_recorder_state_machine_without_browser(self):
        helper = Path(capture.__file__).with_suffix('.js').read_bytes()
        uri = 'data:text/javascript;base64,' + base64.b64encode(helper).decode()
        code = '''import assert from 'node:assert/strict';
const {selectorJournal}=await import(URI);
const initial={size_eu:'40',colour:'brown'}, middle={size_eu:'38',colour:'brown'}, final={size_eu:'39',colour:'black'};
const journal=selectorJournal('secret');
assert.equal(journal.before('page','colour','brown',initial),null);
const baseline=journal.begin('secret','page',initial);
journal.after(journal.before('page','size_eu','38',initial),middle,false);
journal.after(journal.before('page','colour','black',middle),final,false);
const raw=journal.seal('secret',final);
assert.equal(raw.complete,true);assert.equal(raw.events.length,2);assert.equal(raw.documentToken,baseline.documentToken);
assert.ok(Object.isFrozen(raw.events[0].after));assert.throws(()=>journal.seal('secret',final));
const reset=selectorJournal('secret');assert.notEqual(reset.begin('secret','page',initial).documentToken,baseline.documentToken);
assert.throws(()=>selectorJournal('secret').seal('secret',initial));
for(const mode of ['no-change','exception','reentrant','overflow','unobserved']){
 const j=selectorJournal('secret',mode==='overflow'?1:256);j.begin('secret','page',initial);
 const first=j.before('page','size_eu','40',initial);
 if(mode==='reentrant')j.before('page','colour','black',initial);
 j.after(first,initial,mode==='exception');
 if(mode==='overflow')j.after(j.before('page','size_eu','40',initial),initial,false);
 const sealed=j.seal('secret',mode==='unobserved'?final:initial);
 assert.equal(sealed.complete,mode==='no-change',mode);
 assert.equal(sealed.events[0].requested_value,'40');
}
console.log('actual helper controls pass; synthetic state, no browser');'''.replace('URI',json.dumps(uri))
        result=subprocess.run(['node','--input-type=module','-e',code],capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_runtime_bad_option_rejects_before_loading_pin(self):
        from .runtime import Runtime
        with self.assertRaisesRegex(ValueError, 'recorder'):
            Runtime('/nonexistent-source', selector_capture=False)

    def test_wrapped_original_handler_runs_once_and_preserves_return_and_throw(self):
        source = '''const site='shop', window=globalThis, document={addEventListener(){}};
const state={selection:{page:{size_eu:'40',colour:'brown'}}}, products=[{id:'page'}];
const route=()=>({id:'page'}), sentinel={}, marker={message:'original error'};let calls=0;
const resolveProduct=(id,selection)=>({variant:{selection}});
function changeSelection(key,value) {
 const r=route(),p=products.find(p=>p.id===r.id);state.selection[p.id]={...state.selection[p.id],[key]:value};
 const {variant}=resolveProduct(p.id,state.selection[p.id]);state.selection[p.id]={...variant.selection};
 calls++;if(value==='throw')throw marker;return sentinel;
}
document.addEventListener('change',event=>{});
'''.encode()
        assets, _ = capture.project_assets({'shop.js':source},expected_source_sha256=sha256(source).hexdigest(),settings=SETTINGS)
        uri = 'data:text/javascript;base64,'+base64.b64encode(assets['selector-action-capture.js']).decode()
        code = 'import assert from "node:assert/strict";\n'+assets['shop.js'].decode().replace('"./selector-action-capture.js"',json.dumps(uri))
        code += '''
window.__websiteSelectorActionsV1.begin('11111111111111111111111111111111','page',state.selection.page);
assert.equal(changeSelection('size_eu','38'),sentinel);assert.equal(calls,1);
let caught;try{changeSelection('size_eu','throw');}catch(error){caught=error;}
assert.equal(caught,marker);assert.equal(calls,2);
const raw=window.__websiteSelectorActionsV1.seal('11111111111111111111111111111111',state.selection.page);
assert.equal(raw.events.length,2);assert.equal(raw.complete,false);
assert.ok(raw.faults.includes('Original selector handler threw'));
'''
        result=subprocess.run(['node','--input-type=module','-e',code],capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stderr)


class SelectorLifecycleTests(unittest.TestCase):
    """Synthetic callback lifecycle; these are not accepted browser evidence."""
    def fixture(self, directory):
        initial = {'size_eu': '40', 'colour': 'brown'}
        middle = {'size_eu': '38', 'colour': 'brown'}
        final = {'size_eu': '39', 'colour': 'black'}
        raw = {'documentToken': 'document', 'pageId': 'page', 'initialSelection': initial,
            'finalSelection': final, 'complete': True, 'faults': [], 'events': [
                {'page_id': 'page', 'axis': 'size_eu', 'requested_value': '38', 'before': initial,
                 'after': middle, 'sequence': 0, 'started_at': 1, 'finished_at': 2},
                {'page_id': 'page', 'axis': 'colour', 'requested_value': 'black', 'before': middle,
                 'after': final, 'sequence': 1, 'started_at': 3, 'finished_at': 4}]}
        events = []
        class Context:
            def __init__(self): self.handlers = {}
            def on(self, name, fn): self.handlers[name] = fn
        class Page:
            def __init__(self):
                self.url = 'https://shop.test/#/product/page'
                self.context = Context(); self.handlers = {}
                self.main_frame = SimpleNamespace(url=self.url)
                self.selection = deepcopy(initial); self.raw = deepcopy(raw)
            def on(self, name, fn): self.handlers[name] = fn
            def evaluate(self, code, arg):
                if 'localStorage.getItem' in code: return deepcopy(self.selection)
                if '.begin(' in code:
                    events.append('begin')
                    return {'documentToken': 'document', 'phase': 'policy', 'pageId': 'page',
                            'initialSelection': deepcopy(self.selection)}
                if '.seal(' in code:
                    events.append('seal')
                    if isinstance(self.raw, Exception): raise self.raw
                    return deepcopy(self.raw)
                raise AssertionError('Unexpected page operation')
        page = Page();env = SimpleNamespace(unwrapped=SimpleNamespace(page=page))
        task = {'page_id': 'page', 'retailer_id': 'shop'}
        runtime = SimpleNamespace(origins={'shop': 'https://shop.test'},
            asset_hashes={'shop.js': 'b'*64, 'selector-action-capture.js': 'c'*64},
            selector_capture_evidence={'schema': capture.VERSION, 'after_sha256': 'b'*64,
                'helper_sha256': 'c'*64, 'settings': SETTINGS})
        def init(obj, runtime, task, **kw):
            obj.runtime, obj.task = runtime, deepcopy(task)
            obj.binding = {'retailers': {'shop': {'storage_key': 'state.shop'}}}
        with patch.object(capture.AddressCapture, '__init__', init):
            observer = capture.SelectorCapture(runtime, task)
        trace = SimpleNamespace(directory=Path(directory), episode_id='synthetic')
        (trace.directory/'manual-review-private').mkdir()
        def before(*args): events.append('baseline');return {'synthetic': True}
        def after(*args): events.append('terminal');return {'synthetic': True}
        return observer, env, trace, page, final, events, before, after

    def finish(self, observer, trace):
        capsule = {'main_trace_sha256': 'a'*64}
        with patch.object(capture.AddressCapture, 'seal', return_value=(capsule, True)):
            self.assertEqual(observer.seal(trace.directory, {}), (capsule, True))
        return json.loads((trace.directory/'selector-interaction.private.json').read_bytes())

    def test_begin_before_baseline_seal_before_terminal_and_detached_projection(self):
        with tempfile.TemporaryDirectory() as directory:
            observer, env, trace, page, final, events, before, after = self.fixture(directory)
            with patch.object(capture.AddressCapture, 'before', side_effect=before), patch.object(capture.AddressCapture, 'after', side_effect=after):
                observer.before(env, trace);page.selection = final
                observer.after(env, trace, {})
            self.assertEqual(events, ['begin', 'baseline', 'seal', 'terminal'])
            record = self.finish(observer, trace)
            self.assertEqual(len(record['interaction']['events']), 2)
            page.raw['events'].clear()
            self.assertEqual(len(record['interaction']['events']), 2)

    def test_same_product_query_updates_survive_but_leave_and_return_loses_evidence(self):
        for leaves in (False, True):
            with self.subTest(leaves=leaves), tempfile.TemporaryDirectory() as directory:
                observer, env, trace, page, final, _, before, after = self.fixture(directory)
                with patch.object(capture.AddressCapture, 'before', side_effect=before), patch.object(capture.AddressCapture, 'after', side_effect=after):
                    observer.before(env, trace)
                    page.main_frame.url = 'https://shop.test/#/cart' if leaves else page.url + '?size_eu=38'
                    page.handlers['framenavigated'](page.main_frame)
                    page.main_frame.url = page.url
                    page.handlers['framenavigated'](page.main_frame)
                    page.selection = final;observer.after(env, trace, {})
                self.assertEqual(self.finish(observer, trace)['interaction'] is None, leaves)

    def test_document_replacement_seal_failure_and_new_page_are_incomplete(self):
        for mode in ('replacement', 'seal_error', 'new_page', 'active_page'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                observer, env, trace, page, final, _, before, after = self.fixture(directory)
                with patch.object(capture.AddressCapture, 'before', side_effect=before), patch.object(capture.AddressCapture, 'after', side_effect=after):
                    observer.before(env, trace);page.selection = final
                    if mode == 'replacement': page.raw['documentToken'] = 'replacement'
                    elif mode == 'seal_error': page.raw = RuntimeError('Document recorder lost')
                    elif mode == 'new_page': page.context.handlers['page'](object())
                    else: env.unwrapped.page = SimpleNamespace(url=page.url, context=page.context)
                    observer.after(env, trace, {})
                self.assertIsNone(self.finish(observer, trace)['interaction'])

    def test_tampered_actual_capture_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            observer, env, trace, page, final, _, before, after = self.fixture(directory)
            with patch.object(capture.AddressCapture, 'before', side_effect=before), patch.object(capture.AddressCapture, 'after', side_effect=after):
                observer.before(env, trace);page.selection = final;observer.after(env, trace, {})
            Path(observer.selector_artifacts['after']['path']).write_text('{}')
            with self.assertRaisesRegex(ValueError, 'artifact changed'): self.finish(observer, trace)


if __name__ == '__main__': unittest.main()

class ScopedTaskActionTests(unittest.TestCase):
    """Real copied helper exercised in Node; synthetic state, no browser evidence."""
    def test_composed_order_and_basket_renderer_has_exact_action_inverse(self):
        from .basket import basket_shop_source
        from .simulated_order_presentation import project_assets as orders
        source = (ROOT/'environments/website_drafts/shop.js').read_bytes()
        basket = basket_shop_source(source.decode(), canonical_domain=True).encode()
        quote = b'export const worldBinding={...itemBinding,basket:true,inquiryKey,\nconst key=inquiryKey(draft);\nrequests.set(key,{value});\nreturn key===inquiryKey(draft);'
        assets, _ = orders({'shop.js':basket,'quote.js':quote}, expected_source_sha256=sha256(basket).hexdigest())
        before = deepcopy(assets)
        changed, evidence = capture.project_assets(assets,expected_source_sha256=sha256(assets['shop.js']).hexdigest(),
            settings={'shop':{**SETTINGS['shop'],'task_actions':True}})
        self.assertEqual(len(evidence['action_hooks']),3)
        self.assertEqual(capture.restore_source(changed['shop.js'],evidence),before['shop.js'])
        for name in before:
            if name!='shop.js':self.assertEqual(changed[name],before[name])
        for hook in evidence['action_hooks']:
            self.assertEqual(changed['shop.js'].decode().count(hook['replacement']),1)
        # An unsupported/changed actual remove-handler seam must fail closed.
        with self.assertRaisesRegex(ValueError,'seam absent'):
            bad=before['shop.js'].replace(b'if(target.dataset.remove){',b'if(target.dataset.deleted){')
            capture.project_assets({**before,'shop.js':bad},expected_source_sha256=sha256(bad).hexdigest(),
                settings={'shop':{**SETTINGS['shop'],'task_actions':True}})

    def test_add_remove_submit_and_setup_exclusion_retained_in_actual_helper(self):
        helper=Path(capture.__file__).with_suffix('.js').read_bytes()
        uri='data:text/javascript;base64,'+base64.b64encode(helper).decode()
        code='''import assert from 'node:assert/strict';
const {selectorJournal}=await import(URI);
const selection={colour:'brown',size_eu:'40'}, j=selectorJournal('secret',256,true);
j.taskAction({kind:'cart_add',offer_id:'setup/offer',quantity:1});
j.begin('secret','page',selection);
j.taskAction({kind:'cart_add',offer_id:'shop/black39',quantity:1});
j.taskAction({kind:'cart_remove',offer_id:'shop/black39',quantity:1});
j.taskAction({kind:'order_submit'});
const raw=j.seal('secret',selection);
assert.equal(raw.complete,true);assert.equal(raw.taskEvents.length,3);
assert.deepEqual(raw.taskEvents.map(x=>x.kind),['cart_add','cart_remove','order_submit']);
assert.ok(Object.isFrozen(raw.taskEvents[0]));
const legacy=selectorJournal('secret');legacy.begin('secret','page',selection);
legacy.taskAction({kind:'cart_add',offer_id:'shop/item',quantity:1});
assert.equal('taskEvents' in legacy.seal('secret',selection),false);
for(const invalid of [{kind:'cart_add',offer_id:'shop/item',quantity:0},{kind:'cart_add',quantity:1},{kind:'unknown'}]){
 const bad=selectorJournal('secret',256,true);bad.begin('secret','page',selection);bad.taskAction(invalid);
 assert.equal(bad.seal('secret',selection).complete,false);
}
const overflow=selectorJournal('secret',1,true);overflow.begin('secret','page',selection);
overflow.taskAction({kind:'cart_add',offer_id:'shop/item',quantity:1});overflow.taskAction({kind:'order_submit'});
assert.equal(overflow.seal('secret',selection).complete,false);
'''.replace('URI',json.dumps(uri))
        result=subprocess.run(['node','--input-type=module','-e',code],capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_same_document_cart_navigation_preserves_actual_selector_and_action_rows(self):
        fixture=SelectorLifecycleTests()
        with tempfile.TemporaryDirectory() as directory:
            observer, env, trace, page, final, events, before, after=fixture.fixture(directory)
            observer.target['task_actions']=True
            page.raw['taskEvents']=[{'kind':'cart_add','offer_id':'shop/black39','quantity':1},
                                    {'kind':'cart_remove','offer_id':'shop/black39','quantity':1}]
            with patch.object(capture.AddressCapture,'before',side_effect=before), patch.object(capture.AddressCapture,'after',side_effect=after):
                observer.before(env,trace);page.selection=final
                page.url='https://shop.test/#/cart';page.main_frame.url=page.url
                page.handlers['framenavigated'](page.main_frame)
                observer.after(env,trace,{})
            record=fixture.finish(observer,trace)
            self.assertEqual(len(record['interaction']['events']),2)
            self.assertTrue(record['task_actions']['complete'])
            self.assertEqual(len(record['task_actions']['events']),2)
            self.assertEqual(record['task_actions']['main_trace_sha256'],'a'*64)
            self.assertEqual(record['task_actions']['retailer_id'],'shop')

    def test_lost_document_does_not_invent_empty_task_events(self):
        fixture=SelectorLifecycleTests()
        with tempfile.TemporaryDirectory() as directory:
            observer, env, trace, page, final, events, before, after=fixture.fixture(directory)
            observer.target['task_actions']=True;page.raw['taskEvents']=[]
            with patch.object(capture.AddressCapture,'before',side_effect=before), patch.object(capture.AddressCapture,'after',side_effect=after):
                observer.before(env,trace);page.selection=final;page.raw['documentToken']='reloaded'
                observer.after(env,trace,{})
            record=fixture.finish(observer,trace)
            self.assertIsNone(record['interaction']);self.assertIsNone(record['task_actions'])

class ScopedCaptureCorrectionTests(unittest.TestCase):
    """Failure paths exercise copied JS and synthetic callbacks, not browser acceptance."""
    def test_pagehide_fault_survives_restoration_but_setup_is_excluded(self):
        helper=Path(capture.__file__).with_suffix('.js').read_bytes()
        uri='data:text/javascript;base64,'+base64.b64encode(helper).decode()
        code='''import assert from 'node:assert/strict';
const listeners=[];globalThis.addEventListener=(name,fn)=>{assert.equal(name,'pagehide');listeners.push(fn);};
const {selectorJournal}=await import(URI);
const selection={size_eu:'40'},j=selectorJournal('secret',256,true);
listeners[0]();j.begin('secret','page',selection);
j.taskAction({kind:'cart_add',offer_id:'shop/item',quantity:1});
listeners[0](); // Full document departure, then original document restored.
const raw=j.seal('secret',selection);
assert.equal(raw.complete,false);assert.equal(raw.taskEvents.length,1);
assert.ok(raw.faults.includes('Document departed during policy'));
const setup=selectorJournal('secret',256,true);listeners[1]();setup.begin('secret','page',selection);
assert.equal(setup.seal('secret',selection).complete,true);
'''.replace('URI',json.dumps(uri))
        result=subprocess.run(['node','--input-type=module','-e',code],capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_unresolved_remove_cannot_block_native_handler_or_observe_setup(self):
        from .basket import basket_shop_source
        from .simulated_order_presentation import project_assets as orders
        source=(ROOT/'environments/website_drafts/shop.js').read_bytes()
        basket=basket_shop_source(source.decode(),canonical_domain=True).encode()
        quote=b'export const worldBinding={...itemBinding,basket:true,inquiryKey,\nconst key=inquiryKey(draft);\nrequests.set(key,{value});\nreturn key===inquiryKey(draft);'
        assets,_=orders({'shop.js':basket,'quote.js':quote},expected_source_sha256=sha256(basket).hexdigest())
        changed,evidence=capture.project_assets(assets,expected_source_sha256=sha256(assets['shop.js']).hexdigest(),
            settings={'shop':{**SETTINGS['shop'],'task_actions':True}})
        original=assets['shop.js'].decode().split("  if(target.dataset.remove){",1)[1].split('\n',1)[0]
        hooked=next(x['replacement'] for x in evidence['action_hooks'] if 'target.dataset.remove' in x['original'])
        uri='data:text/javascript;base64,'+base64.b64encode(changed['selector-action-capture.js']).decode()
        code='''import assert from 'node:assert/strict';
const {selectorJournal}=await import(URI);
const selection={size_eu:'40'},__selectorJournal=selectorJournal('secret',256,true),__selectorSettings={task_actions:true};
const state={cart:[],editing:null},target={dataset:{remove:'1'}};
let lookups=0;const byVariant=()=>{lookups++;return null;};const revise=()=>{};
function remove(){HOOK ORIGINAL}
state.cart=[{id:'1',key:'stale-key',quantity:1}];remove();
assert.equal(state.cart.length,0);assert.equal(lookups,0); // setup exclusion
__selectorJournal.begin('secret','page',selection);
__selectorJournal.taskAction({kind:'cart_add',offer_id:'shop/known',quantity:1});
state.cart=[{id:'1',key:'stale-key',quantity:1}];remove();
assert.equal(state.cart.length,0);assert.equal(lookups,1);
const raw=__selectorJournal.seal('secret',selection);
assert.equal(raw.complete,false);assert.equal(raw.taskEvents.length,1);
assert.ok(raw.faults.includes('Unable to observe actual task action'));
'''.replace('URI',json.dumps(uri)).replace('HOOK',hooked).replace('ORIGINAL',original)
        result=subprocess.run(['node','--input-type=module','-e',code],capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_same_origin_document_departure_restoration_preserves_known_rows_incomplete(self):
        fixture=SelectorLifecycleTests()
        with tempfile.TemporaryDirectory() as directory:
            observer,env,trace,page,final,_,before,after=fixture.fixture(directory)
            observer.target['task_actions']=True
            page.raw['taskEvents']=[{'kind':'cart_remove','offer_id':'shop/known','quantity':1}]
            with patch.object(capture.AddressCapture,'before',side_effect=before),patch.object(capture.AddressCapture,'after',side_effect=after):
                observer.before(env,trace)
                for url in ('https://shop.test/other-document','https://shop.test/#/product/page'):
                    page.main_frame.url=url;page.handlers['framenavigated'](page.main_frame)
                page.selection=final;observer.after(env,trace,{})
            record=fixture.finish(observer,trace)
            self.assertIsNone(record['interaction'])
            self.assertFalse(record['task_actions']['complete'])
            self.assertEqual(record['task_actions']['events'],page.raw['taskEvents'])

    def test_atomic_native_schema_is_explicit_and_bound(self):
        fixture=SelectorLifecycleTests()
        with tempfile.TemporaryDirectory() as directory:
            observer,env,trace,page,final,_,before,after=fixture.fixture(directory)
            runtime,task=observer.runtime,observer.task
            runtime.selector_capture_evidence['settings']={'shop':{**SETTINGS['shop'],'task_actions':True}}
            def init(obj,runtime,task,**kw):
                obj.runtime,obj.task=runtime,deepcopy(task);obj.binding={'retailers':{'shop':{'storage_key':'state.shop'}}}
            with patch.object(capture.AddressCapture,'__init__',init):
                observer=capture.SelectorCapture(runtime,task,task_action_schema='website-atomic-task-action-journal-v1')
                with self.assertRaisesRegex(ValueError,'schema'):
                    capture.SelectorCapture(runtime,task,task_action_schema='unrecognized')
            page.raw['taskEvents']=[{'kind':'cart_remove','offer_id':'shop/known','quantity':1}]
            with patch.object(capture.AddressCapture,'before',side_effect=before),patch.object(capture.AddressCapture,'after',side_effect=after):
                observer.before(env,trace);page.selection=final;observer.after(env,trace,{})
            journal=fixture.finish(observer,trace)['task_actions']
            self.assertEqual(journal['schema_version'],'website-atomic-task-action-journal-v1')
            self.assertEqual(journal['task_sha256'],capture.digest(task))
            self.assertEqual(journal['main_trace_sha256'],'a'*64)
            self.assertTrue(journal['complete'])
