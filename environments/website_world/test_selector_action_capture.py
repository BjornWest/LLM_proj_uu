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
