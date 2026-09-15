// Offline inspection only. Never starts or modifies the installed Chaos CLI.
import fs from 'node:fs';
import vm from 'node:vm';
import crypto from 'node:crypto';

const state = new URL('./routed-pilot-token-v1/', import.meta.url);
const profile = JSON.parse(fs.readFileSync(new URL('profile.json', state), 'utf8'));
const bundle = profile.environment_provenance.bundle;
const source = fs.readFileSync(bundle, 'utf8');
const hash = text => crypto.createHash('sha256').update(text).digest('hex');
if (hash(source) !== profile.environment_provenance.files_sha256['dist/cli.mjs']) {
  throw new Error('Pinned bundle changed');
}
const section = source.slice(source.indexOf('// packages/core/dist/seedutil.js'),
  source.indexOf('// packages/core/dist/index.js'));
const prefix = 'var __getOwnPropNames=Object.getOwnPropertyNames;var __esm=(fn,res)=>function(){return fn&&(res=(0,fn[__getOwnPropNames(fn)[0]])(fn=0)),res};';
function context(code) {
  const ctx = vm.createContext({});
  vm.runInContext(prefix + code + ';init_seedutil();', ctx, {timeout:1000});
  return ctx;
}
const seeds = Array.from({length:1024}, (_,i) =>
  crypto.createHash('sha256').update('token-rng-review:'+i).digest().readUInt32BE(0));
function sample(ctx) {
  ctx.reviewSeeds = seeds;
  return vm.runInContext(`reviewSeeds.map(seed=>{
    const rng=new Seeded(seed);
    const values=Array.from({length:32},()=>rng.next());
    return {seed,first:values[0],firstMod4:values[0]%4,
      evenAfterFirst:values.slice(1).filter(x=>x%2===0).length,samples:31};
  })`, ctx, {timeout:1000});
}
const actual = sample(context(section));
const replacement = 'Math.imul(this.state, 1103515245)';
if (section.split('this.state * 1103515245').length !== 2) throw new Error('Unexpected source');
const altered = sample(context(section.replace('this.state * 1103515245', replacement)));
const tally = values => Object.fromEntries([...new Set(values)].sort().map(v=>
  [v,values.filter(x=>x===v).length]));
const exactFirst = seed => Number((BigInt(seed)*1103515245n+12345n)&2147483647n);
const summarize = rows => ({
  first_pick_four_way_index_counts:tally(rows.map(r=>r.firstMod4)),
  even_later_values:rows.reduce((sum,r)=>sum+r.evenAfterFirst,0),
  later_values_total:rows.reduce((sum,r)=>sum+r.samples,0),
  first_update_differs_from_exact_integer:rows.filter(r=>r.first!==exactFirst(r.seed)).length,
});
const report = {
  scope:'Pinned installed seed utility in isolated JS context; 1024 SHA256-spread seeds,32 outputs each. No browser/model calls or environment changes.',
  source_bundle:bundle,source_bundle_sha256:hash(source),seedutil_sha256:hash(section),
  review_script_sha256:hash(fs.readFileSync(new URL(import.meta.url))),
  seed_derivation:'SHA256("token-rng-review:"+i).readUInt32BE(0), i=0..1023',
  sample_count:1024,original:summarize(actual),counterfactual_imul:summarize(altered),
  counterfactual_note:'In-memory diagnostic only. First updates checked against exact BigInt arithmetic. Not a deployed repair or general PRNG/distribution certification.',
  source_excerpt:section,examples:actual.slice(0,8).map(r=>({...r,exact_first:exactFirst(r.seed)})),
};
fs.writeFileSync(new URL('rng-review.json',state),JSON.stringify(report,null,2)+'\n');
console.log(JSON.stringify({original:report.original,counterfactual:report.counterfactual_imul},null,2));
