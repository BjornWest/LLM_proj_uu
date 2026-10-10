// Synthetic presentation control. No generated native fixture or browser run.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {productionResolver} from './variant_transition_probe.mjs';

const inputs = process.argv.slice(2);
if (inputs.length !== 2) throw new Error('Pass original and projected synthetic catalogs');
const modules = await Promise.all(inputs.map(async path=>productionResolver(JSON.parse(await readFile(path,'utf8')))));
const selection = {colour:'black',size_eu:'42',width:'standard'};
const baseline = modules[0].module.resolveProduct('page', selection).variant;
const varied = modules[1].module.resolveProduct('page', selection).variant;
assert.equal(baseline.key, 'navy42'); // Size-first retains its available tuple.
assert.equal(varied.key, 'black41'); // Colour-first honors black and resets size.
assert.equal(varied.selection.colour, 'black');
assert.equal(varied.selection.size_eu, '41');
assert.equal(modules[0].module.byVariant('navy42').variant.state, 'unavailable');
assert.equal(modules[1].module.byVariant('navy42').variant.state, 'unavailable');
assert.deepEqual(modules[1].module.byVariant('black41').variant, modules[0].module.byVariant('black41').variant);
assert.deepEqual(modules[1].sources, modules[0].sources);
console.log(JSON.stringify({passed:true, baseline_key:baseline.key, varied_key:varied.key,
  production_sources:modules[0].sources, scope:'Synthetic controls, not native menu or browser evidence'}));
