// BigInt reference for the candidate's declared xorshift32(13,17,5) algorithm.
import fs from 'node:fs';
import vm from 'node:vm';
import crypto from 'node:crypto';
import assert from 'node:assert/strict';
const candidate=process.argv[2]||'.local/chaos-fifo-xor32-v1/dist/cli.mjs';
const output=process.argv[3]||'data/curation/chaos-repair-review/xorshift32-reference.json';
assert(!fs.existsSync(output),'Use a fresh report path');
const oldProfile=JSON.parse(fs.readFileSync('data/curation/routed-pilot-token-v1/profile.json'));
const originalPath=oldProfile.environment_provenance.bundle;
const hash=x=>crypto.createHash('sha256').update(x).digest('hex');
const original=fs.readFileSync(originalPath,'utf8'),source=fs.readFileSync(candidate,'utf8');
assert.equal(hash(original),oldProfile.environment_provenance.files_sha256['dist/cli.mjs']);
const old='this.state = this.state * 1103515245 + 12345 & 2147483647;';
const replacement='let x = this.state; x ^= x << 13; x ^= x >>> 17; x ^= x << 5; this.state = x >>> 0;';
assert.equal(original.split(old).length,2);
assert.equal(source,original.replace(old,replacement),'Candidate changes more than the declared RNG body');
const section=source.slice(source.indexOf('// packages/core/dist/seedutil.js'),source.indexOf('// packages/core/dist/index.js'));
const ctx=vm.createContext({});
vm.runInContext('var __getOwnPropNames=Object.getOwnPropertyNames;var __esm=(fn,res)=>function(){return fn&&(res=(0,fn[__getOwnPropNames(fn)[0]])(fn=0)),res};'+section+';init_seedutil();',ctx,{timeout:1000});
const seeds=[0,1,2,0x7fffffff,0x80000000,0xffffffff,...Array.from({length:1024},(_,i)=>crypto.createHash('sha256').update('independent-xorshift:'+i).digest().readUInt32BE(0))];
ctx.seeds=seeds;
const rows=vm.runInContext('seeds.map(seed=>{const r=new Seeded(seed);return {seed,values:Array.from({length:64},()=>r.next())};})',ctx,{timeout:1000});
const mask=0xffffffffn;
function next(x){x=(x^(x<<13n))&mask;x=(x^(x>>17n))&mask;x=(x^(x<<5n))&mask;return x;}
let checked=0;
for(const row of rows){let state=BigInt((row.seed>>>0)||1);for(const value of row.values){state=next(state);assert.equal(value,Number(state));assert(value>0&&value<=0xffffffff);checked++;}}
assert.equal(hash(fs.readFileSync(originalPath)),hash(original));
const report={algorithm:'xorshift32-v1 (13,17,5)',candidate,candidate_sha256:hash(source),original_sha256:hash(original),
 script_sha256:hash(fs.readFileSync(new URL(import.meta.url))),seed_count:seeds.length,values_per_seed:64,
 exact_bigint_checks:checked,mismatches:0,seed_zero_policy:'constructor maps uint32 zero to one; original behavior retained',
 only_declared_rng_body_changed:true,examples:rows.slice(0,6).map(r=>({seed:r.seed,first_eight:r.values.slice(0,8)})),
 passed:true,limits:'Arithmetic/reference equivalence, not cryptographic/security or statistical quality certification.',model_calls:0,browser_calls:0};
fs.writeFileSync(output,JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify(report,null,2));
