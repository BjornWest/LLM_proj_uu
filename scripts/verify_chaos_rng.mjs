// Offline arithmetic and realized-token-variant comparison. No server/model calls.
import fs from 'node:fs';
import vm from 'node:vm';
import crypto from 'node:crypto';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
const sha=s=>crypto.createHash('sha256').update(s).digest('hex');
const seeds=Array.from({length:1024},(_,i)=>crypto.createHash('sha256').update('token-rng-review:'+i).digest().readUInt32BE(0));
const prefix='var __getOwnPropNames=Object.getOwnPropertyNames;var __esm=(fn,res)=>function(){return fn&&(res=(0,fn[__getOwnPropNames(fn)[0]])(fn=0)),res};';
const exactNext=state=>{let x=BigInt(state);x=(x^(x<<13n))&0xffffffffn;x=x^(x>>17n);x=(x^(x<<5n))&0xffffffffn;return Number(x);};
export function tokenDiversity(variants,requireComplete=false) {
  const count=valueOf=>{
    const values=variants.map(valueOf);
    return Object.fromEntries([...new Set(values)].sort().map(value=>[value,values.filter(v=>v===value).length]));
  };
  const diversity={target_index:count(v=>v.target_index),target_name:count(v=>v.target_name),
    safe_action_index:count(v=>v.safe_action_index),joint_position:count(v=>`${v.target_index}:${v.safe_action_index}`)};
  if(requireComplete) {
    const expected={target_index:['0','1','2'],safe_action_index:['0','1'],
      target_name:['Linux desktop','MacBook Pro','ThinkPad X1','Workstation'],
      joint_position:['0:0','0:1','1:0','1:1','2:0','2:1']};
    for(const [key,values] of Object.entries(expected)) {
      if(JSON.stringify(Object.keys(diversity[key]).sort())!==JSON.stringify(values))
        throw Error(`Token variants lack exact expected coverage: ${key}`);
    }
  }
  return diversity;
}
function summarize(bundle,repaired) {
  const code=fs.readFileSync(bundle,'utf8');
  const section=code.slice(code.indexOf('// packages/core/dist/seedutil.js'),code.indexOf('// packages/core/dist/index.js'));
  const ctx=vm.createContext({seeds});vm.runInContext(prefix+section+';init_seedutil();',ctx,{timeout:1000});
  const rows=vm.runInContext('seeds.map(seed=>{const rng=new Seeded(seed);return {seed,values:Array.from({length:32},()=>rng.next())}})',ctx,{timeout:1000});
  let mismatches=0;const histogram=[0,0,0,0];
  for(const row of rows){let state=row.seed>>>0||1;for(const value of row.values){state=exactNext(state);if(value!==state)mismatches++;}histogram[row.values[0]%4]++;}
  if(repaired&&mismatches)throw Error('Derived stream differs from independent BigInt xorshift32');
  if(repaired&&histogram.some(n=>n<150||n>360))throw Error('Four-way first-choice sample is unexpectedly concentrated');
  const variants=[];
  for(let i=0;i<128;i++) {
    const session='chaos-repair-token-variant:'+i;
    const descriptor=JSON.parse(execFileSync('node',['scripts/inspect_chaos.mjs'],{input:JSON.stringify({bundle:path.resolve(bundle),task:'revoke-current-only',session}),encoding:'utf8'}));
    const stage=descriptor.stage,target=stage.data.rows.findIndex(row=>row.target===true);
    const action=stage.data.actionsPerRow.findIndex(a=>a.kind==='rotate');
    if(target<0||action<0||stage.check.mustClick[0]!==stage.data.rows[target].id+'/rotate')throw Error('Invalid generated contract');
    variants.push({session,seed:descriptor.seed,target_index:target,target_name:stage.data.rows[target].name,
      safe_action_index:action,descriptor_sha256:sha(JSON.stringify(descriptor))});
  }
  const diversity=tokenDiversity(variants,repaired);
  return {bundle:path.resolve(bundle),bundle_sha256:sha(code),seed_section_sha256:sha(section),
    arithmetic_comparison:repaired?'Independent BigInt xorshift32, all 32768 outputs':'Not expected to match xorshift32',
    xorshift_mismatches:mismatches,first_mod4:histogram,diversity,variants};
}
if(path.resolve(process.argv[1]??'')===import.meta.filename) {
const [original,derived,output='.local/preflight/chaos-rng-v2.json']=process.argv.slice(2);
if(!original||!derived)throw Error('Usage: node scripts/verify_chaos_rng.mjs original-cli derived-cli [report]');
const before=summarize(original,false),after=summarize(derived,true);
const report={version:'chaos-xorshift32-v2-validation',scope:'Offline arithmetic and 128 realized token descriptors; not PRNG certification or model evaluation',
  coverage_requirement:'All four pinned token names and all six target-row/safe-action position combinations; full counts retained',
  numeric_seeds:'SHA256(token-rng-review:+i).readUInt32BE(0), i=0..1023',numeric_outputs_per_seed:32,
  source_sha256:sha(fs.readFileSync(import.meta.filename)),inspector_sha256:sha(fs.readFileSync('scripts/inspect_chaos.mjs')),
  algorithm_reference:'https://www.jstatsoft.org/article/view/v008i14',original:before,derived:after,
  limitations:['Xorshift32 is a small deterministic fixture generator, not a cryptographic RNG.','Existing modulo choice/shuffle mapping is retained; no exhaustive distribution claim.','Historical sessions retain original generator semantics.'],passed:true};
fs.mkdirSync(path.dirname(output),{recursive:true});fs.writeFileSync(output,JSON.stringify(report,null,2));
console.log(JSON.stringify({report:output,original:before.diversity,derived:after.diversity,derived_mod4:after.first_mod4,exact_mismatches:after.xorshift_mismatches}));
}
