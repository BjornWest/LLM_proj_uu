// Independent gate review using saved descriptors only; no new generator/browser runs.
import fs from 'node:fs';
import crypto from 'node:crypto';
import assert from 'node:assert/strict';
import {tokenDiversity} from '../../scripts/verify_chaos_rng.mjs';

const output=process.argv[2];
assert(output&&!fs.existsSync(output),'Supply a fresh output path');
const read=p=>JSON.parse(fs.readFileSync(p));
const sha=p=>crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
const freshPath='.local/preflight/chaos-rng-joint-gate-v2.json';
const oldPath='.local/preflight/chaos-rng-v2.json';
const fresh=read(freshPath),old=read(oldPath);
assert.equal(fresh.source_sha256,sha('scripts/verify_chaos_rng.mjs'));
assert.equal(fresh.inspector_sha256,sha('scripts/inspect_chaos.mjs'));
assert.equal(fresh.derived.xorshift_mismatches,0);
for(const kind of ['original','derived']) {
  assert.deepEqual(fresh[kind].variants,old[kind].variants);
  assert.equal(fresh[kind].bundle_sha256,sha(fresh[kind].bundle));
  assert.deepEqual(tokenDiversity(fresh[kind].variants,kind==='derived'),fresh[kind].diversity);
  assert.deepEqual(fresh[kind].first_mod4,old[kind].first_mod4);
}
const cases=[];
for(const name of ['rng-imul','rng-xorshift32-v1']) {
  const file=`data/curation/chaos-repair-review/${name}/variants.json`;
  const variants=read(file).map(v=>({target_name:v.target_name,target_index:v.target_position,safe_action_index:v.safe_action_position}));
  const counts=tokenDiversity(variants);
  let rejected=false,error=null;
  try {tokenDiversity(variants,true);} catch(e) {rejected=true;error=String(e);}
  assert.equal(rejected,name==='rng-imul');
  if(rejected)assert.match(error,/joint_position/);
  cases.push({source:file,source_sha256:sha(file),variants:variants.length,rejected,error,counts});
}
const result={scope:'Independent validator review on saved real factory descriptors, not new arithmetic/browser execution.',passed:true,
  audit_script_sha256:sha(import.meta.filename),validator_sha256:sha('scripts/verify_chaos_rng.mjs'),
  author_tests_sha256:sha('scripts/test_chaos_rng_coverage.mjs'),fresh_report_sha256:sha(freshPath),
  historical_report_sha256:sha(oldPath),unchanged_report_descriptors:256,
  fresh_derived_joint_counts:fresh.derived.diversity.joint_position,saved_sample_checks:cases,
  model_calls:0,browser_calls:0,
  finding:'Gate is correct. At this reviewed source version the default output still names existing historical chaos-rng-v2.json and writeFileSync overwrites it; recommend a fresh default plus reject-existing output guard. No file was overwritten by this review.'};
fs.writeFileSync(output,JSON.stringify(result,null,2)+'\n');
console.log(JSON.stringify({passed:true,unchanged_descriptors:256,saved_sample_checks:cases.map(c=>({source:c.source,rejected:c.rejected})),output}));
