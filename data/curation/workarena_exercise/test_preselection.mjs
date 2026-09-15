// Offline behavior checks for the proposed script, not proof of ServiceNow compatibility.
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import test from 'node:test';
const script = fs.readFileSync(new URL('../../../environments/workarena_exercise/preselect_acrobat.js', import.meta.url), 'utf8');
function fixture({title='Standard Laptop', label='Adobe Acrobat', initial='false', top=false, ready=true, path='/com.glideapp.servicecatalog_cat_item_view.do'}={}) {
  let value=initial, changes=0, interval, now=1000; const listeners={};
  const location={pathname:path};
  const win={top:{}, frameElement:{id:'gsft_main'}, WORKARENA_LOAD_COMPLETE:ready, addEventListener(name,fn){listeners[name]=fn;}, g_form:{
    getEditableFields:()=>['field'],getControl:()=>({type:'hidden',innerText:'',parentElement:{innerText:label}}),
    getValue:()=>value,setValue:(field,next)=>{changes++;value=next;}
  }};
  if(top)win.top=win;
  vm.runInNewContext(script,{window:win,location,
    document:{querySelectorAll:()=>[{textContent:title}]},Date:{now:()=>now},
    setInterval:fn=>{interval=fn;return 1;},clearInterval(){}});
  return {win,location,pagehide(){listeners.pagehide?.();},get value(){return value;},get changes(){return changes;},tick(){interval?.();},
    remove(){value='false';},expire(){now+=31000;interval?.();}};
}
test('once-only preselection; user removal stays removed',()=>{
  const x=fixture();assert.equal(x.value,'true');assert.equal(x.changes,1);
  x.remove();x.tick();assert.equal(x.value,'false');assert.equal(x.changes,1);
});
test('wrong product or label never changed',()=>{
  for(const config of [{title:'Other Laptop'},{label:'Adobe Photoshop'}]){
    const x=fixture(config);x.expire();assert.equal(x.changes,0);assert.equal(x.win.__workarenaAcrobatPreselection.reason,'form-not-confirmed');
  }
});
test('unexpected initial state is not silently relabeled as insertion',()=>{
  const x=fixture({initial:'true'});assert.equal(x.changes,0);assert.equal(x.win.__workarenaAcrobatPreselection.inserted,false);
});
test('top-level page untouched',()=>{const x=fixture({top:true});assert.equal(x.changes,0);assert.equal(x.win.__workarenaAcrobatPreselection,undefined);});

test('about:blank initialization can become the native product route',()=>{
  const x=fixture({path:'blank',ready:false});assert.equal(x.changes,0);
  x.location.pathname='/com.glideapp.servicecatalog_cat_item_view.do';x.win.WORKARENA_LOAD_COMPLETE=true;
  x.tick();assert.equal(x.changes,1);assert.equal(x.value,'true');
});
test('native readiness is required before changing a field',()=>{
  const x=fixture({ready:false});x.tick();assert.equal(x.changes,0);
  x.win.WORKARENA_LOAD_COMPLETE=true;x.tick();assert.equal(x.changes,1);
});

test('native bootstrap pagehide does not cancel pending product initialization',()=>{
  const x=fixture({path:'blank',ready:false});x.pagehide();
  x.location.pathname='/com.glideapp.servicecatalog_cat_item_view.do';x.win.WORKARENA_LOAD_COMPLETE=true;
  x.tick();assert.equal(x.value,'true');assert.equal(x.changes,1);
});
