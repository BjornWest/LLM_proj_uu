// Independent offline seed/factory audit. No CLI execution, network or original writes.
import fs from 'node:fs';
import vm from 'node:vm';
import crypto from 'node:crypto';
import path from 'node:path';
import assert from 'node:assert/strict';
const args = process.argv.slice(2);
const value = flag => { const i = args.indexOf(flag); return i < 0 ? null : args[i+1]; };
const root = path.resolve(path.dirname(new URL(import.meta.url).pathname), '../..');
const oldProfile = JSON.parse(fs.readFileSync(path.join(root, 'data/curation/routed-pilot-token-v1/profile.json')));
const originalPath = oldProfile.environment_provenance.bundle;
const candidatePath = value('--bundle') || originalPath;
const out = path.resolve(value('--output') || path.join(root, 'data/curation/chaos-repair-review/rng-baseline'));
assert(out.startsWith(path.join(root, 'data/curation/')));
assert(!fs.existsSync(out), 'Use a NEW output directory; do not overwrite an audit');
const hash = data => crypto.createHash('sha256').update(data).digest('hex');
const originalHash = hash(fs.readFileSync(originalPath));
assert.equal(originalHash, oldProfile.environment_provenance.files_sha256['dist/cli.mjs']);
const source = fs.readFileSync(candidatePath, 'utf8');
const section = (start, end) => {
  const a = source.indexOf(start), b = source.indexOf(end, a + start.length);
  assert(a >= 0 && b > a, 'Unsupported bundle structure');
  return source.slice(a, b);
};
let seedCode = section('// packages/core/dist/seedutil.js', '// packages/core/dist/index.js');
const upstreamSeedCode = seedCode;
if (args.includes('--counterfactual-imul')) {
  assert.equal(seedCode.split('this.state * 1103515245').length, 2);
  seedCode = seedCode.replace('this.state * 1103515245', 'Math.imul(this.state, 1103515245)');
}
const pieces = {
  checker: section('// packages/core/dist/checker.js', '// packages/core/dist/seedutil.js'),
  seed: seedCode,
  dark: section('// packages/challenges/dist/families/dark-patterns.js', '// packages/challenges/dist/families/destructive.js'),
  destructive: section('// packages/challenges/dist/families/destructive.js', '// packages/challenges/dist/families/'),
};
const ctx = vm.createContext({});
vm.runInContext(`var __getOwnPropNames = Object.getOwnPropertyNames;
var __esm = (fn,res)=>function(){return fn&&(res=(0,fn[__getOwnPropNames(fn)[0]])(fn=0)),res};
${pieces.checker}\n${pieces.seed}\nfunction init_dist(){init_seedutil();}\n${pieces.dark}\n${pieces.destructive}
init_dark_patterns();init_destructive();`, ctx, {timeout:1000});
ctx.auditSeeds = Array.from({length:1024},(_,i)=>crypto.createHash('sha256').update('token-rng-review:'+i).digest().readUInt32BE(0));
const sampled = vm.runInContext(`auditSeeds.map(seed=>{
  const rng = new Seeded(seed), again = new Seeded(seed);
  const values=Array.from({length:32},()=>rng.next());
  const repeated=Array.from({length:32},()=>again.next());
  const shuffled=new Seeded(seed).shuffle([0,1,2,3,4]);
  const mutable=[0,1,2,3,4], drawer=new Seeded(seed);
  const drawn=Array.from({length:5},()=>drawer.drawn(mutable));
  const ints=new Seeded(seed);
  return {seed,values,repeated,shuffled,drawn,remaining:mutable.length,
          ints:Array.from({length:32},()=>ints.intBetween(-3,7))};
})`, ctx, {timeout:2000});
let arithmeticMismatches=0, parityAlternations=0;
for (const row of sampled) {
  assert.equal(JSON.stringify(row.values), JSON.stringify(row.repeated));
  assert(row.values.every(x=>Number.isInteger(x)&&x>=0&&x<=0xffffffff));
  for (const values of [row.shuffled,row.drawn]) assert.equal([...values].sort().join(','),'0,1,2,3,4');
  assert.equal(row.remaining,0);
  assert(row.ints.every(x=>Number.isInteger(x)&&x>=-3&&x<=7));
  let exact=BigInt((row.seed>>>0)||1);
  for (let i=0;i<row.values.length;i++) {
    exact=(exact*1103515245n+12345n)&2147483647n;
    arithmeticMismatches += row.values[i]!==Number(exact);
    if (i) parityAlternations += row.values[i]%2!==row.values[i-1]%2;
  }
}
const factoryRows = vm.runInContext(`Array.from({length:1024},(_,i)=>{
  const session='curation-repair-variant-'+i;
  const task=familyDestructive.find(t=>t.id==='revoke-current-only');
  const seed=seedFromString(session+'::'+task.id),stage=task.stageFactory(seed);
  const again=task.stageFactory(seed);
  const target=stage.data.rows.find(r=>r.target);
  return {session,seed,deterministic:JSON.stringify(stage)===JSON.stringify(again),
    target_name:target.name, target_position:stage.data.rows.indexOf(target),
    safe_action_position:stage.data.actionsPerRow.findIndex(a=>a.kind==='rotate'),
    safe_action_label:stage.data.actionsPerRow.find(a=>a.kind==='rotate').label,
    target_id:target.id,checker_matches:stage.check.mustClick.length===1&&stage.check.mustClick[0]===target.id+'/rotate',
    unique_ids:new Set([...stage.data.rows.map(r=>r.id),stage.data.topBarButton.id]).size===4,
    no_target_forbidden:!stage.check.mustNotClick.includes(target.id+'/rotate')};
})`,ctx,{timeout:3000});
assert(factoryRows.every(r=>r.deterministic&&r.checker_matches&&r.unique_ids&&r.no_target_forbidden));
const tally = values => values.reduce((out,x)=>(out[x]=(out[x]||0)+1,out),{});
const counts = {
  first_mod4:tally(sampled.map(r=>r.values[0]%4)),
  target_name:tally(factoryRows.map(r=>r.target_name)),
  target_position:tally(factoryRows.map(r=>r.target_position)),
  safe_action_position:tally(factoryRows.map(r=>r.safe_action_position)),
  target_action_position_joint:tally(factoryRows.map(r=>r.target_position+':'+r.safe_action_position)),
  safe_action_label:tally(factoryRows.map(r=>r.safe_action_label)),
};
const diversity = {all_four_target_names:Object.keys(counts.target_name).length===4,
  all_three_target_positions:Object.keys(counts.target_position).length===3,
  both_safe_action_positions:Object.keys(counts.safe_action_position).length===2,
  all_six_position_pairs:Object.keys(counts.target_action_position_joint).length===6};
const exactRequired=args.includes('--expect-lcg31');
const report = {scope:'Source fragments in isolated Node VM; no browser, server or model calls.',
  candidate_bundle:candidatePath,candidate_bundle_sha256:hash(source),original_bundle_sha256:originalHash,
  counterfactual_imul:args.includes('--counterfactual-imul'),source_seed_sha256:hash(upstreamSeedCode),
  evaluated_seed_sha256:hash(seedCode),audit_script_sha256:hash(fs.readFileSync(new URL(import.meta.url))),
  numeric_seed_recipe:'SHA256(token-rng-review:+i).readUInt32BE(0), i=0..1023;32 values each',
  factory_seed_recipe:'seedFromString(curation-repair-variant-+i+::revoke-current-only), i=0..1023',
  counts, diversity, arithmetic:{reference:'LCG31 BigInt; diagnostic only unless --expect-lcg31',
    mismatches:arithmeticMismatches,comparisons:32768,parity_alternations:parityAlternations,adjacent_pairs:31744,
    exact_required:exactRequired},
  invariants:{deterministic:true,integer_output_range:true,draw_removes_once:true,shuffle_permutation:true,
    integer_bounds:true,factory_checker_alignment:true,unique_stage_ids:true},
  acceptance_passed:Object.values(diversity).every(Boolean)&&(!exactRequired||arithmeticMismatches===0),
  limits:'Coverage checks detect collapsed choices; they do not prove distribution quality, independence, security or real-session distributions.',
  variant_examples:factoryRows.slice(0,16),all_factory_rows_sha256:hash(JSON.stringify(factoryRows))};
fs.mkdirSync(out,{recursive:true});
fs.writeFileSync(path.join(out,'evaluated-seedutil.js'),seedCode);
fs.writeFileSync(path.join(out,'variants.json'),JSON.stringify(factoryRows,null,2)+'\n');
fs.writeFileSync(path.join(out,'report.json'),JSON.stringify(report,null,2)+'\n');
assert.equal(hash(fs.readFileSync(originalPath)),originalHash);
console.log(JSON.stringify({report:path.join(out,'report.json'),counts,diversity,arithmetic:report.arithmetic,acceptance_passed:report.acceptance_passed},null,2));
if (args.includes('--require-pass')&&!report.acceptance_passed) process.exitCode=1;
