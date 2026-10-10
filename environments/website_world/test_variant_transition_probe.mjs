import test from 'node:test';
import assert from 'node:assert/strict';
import {probe} from './variant_transition_probe.mjs';

// Synthetic resolver controls only; not repaired native worlds or published SKUs.
const row = (colour, size, state='in_stock') => ({key:`${colour}-${size}`,
  skuId:`sku-${colour}-${size}`, offerId:`offer-${colour}-${size}`,
  selection:{colour, size_eu:String(size)}, state});
const data = (variants, axes=['colour','size_eu']) => ({products:[{
  id:'page', canonicalProductId:'model', options:axes.map(key=>({key})), variants}]});

test('honoured colour change resets size only to an existing tuple', async()=>{
  const result=await probe(data([row('navy',42),row('black',41)]));
  assert.equal(result.transitions.length,1);
  assert.equal(result.transitions[0].after.sku_id,'sku-black-41');
  assert.equal(result.transitions[0].before.selection.size_eu,'42');
});
test('later colour axis rejected by current resolver is not a reset', async()=>{
  const result=await probe(data([row('navy',42),row('black',41)],['size_eu','colour']));
  assert.equal(result.transitions.length,0);
  assert.equal(result.rejected_colour_requests.length,1);
});
test('zero-stock listed black size is not absent', async()=>{
  const result=await probe(data([row('navy',42),row('black',42,'unavailable'),row('black',41)]));
  assert.equal(result.transitions.length,0);
  assert.equal(result.stock_only_cases.length,1);
});
test('colour partition without colour selector cannot realize transition', async()=>{
  assert.equal((await probe(data([row('navy',42)],['size_eu']))).inspected,0);
});
test('duplicate reachable selection is rejected', async()=>{
  const input=data([row('navy',42),{...row('navy',42),key:'alias'},row('black',41)]);
  await assert.rejects(probe(input),/Ambiguous or unreachable/);
});
