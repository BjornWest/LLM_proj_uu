// Offline multi-family comparison of original, imul diagnostic, and copied xorshift.
import fs from 'node:fs';
import vm from 'node:vm';
import crypto from 'node:crypto';
import assert from 'node:assert/strict';
import path from 'node:path';
const candidatePath=process.argv[2]||'.local/chaos-fifo-xor32-v1/dist/cli.mjs';
const out=process.argv[3]||'data/curation/chaos-repair-review/family-diversity-v1.json';
assert(!fs.existsSync(out),'Use a fresh output path');
const hash=data=>crypto.createHash('sha256').update(data).digest('hex');
const originalProfile=JSON.parse(fs.readFileSync('data/curation/routed-pilot-token-v1/profile.json'));
const originalPath=originalProfile.environment_provenance.bundle;
const original=fs.readFileSync(originalPath,'utf8'),candidate=fs.readFileSync(candidatePath,'utf8');
assert.equal(hash(original),originalProfile.environment_provenance.files_sha256['dist/cli.mjs']);
const tasks=['confirmshaming','drip-pricing','archive-vs-delete','revoke-current-only','drop-database','transfer-by-not-clicking-save','force-push'];
function create(source,imul=false){
 const cut=(a,b)=>{const i=source.indexOf(a),j=source.indexOf(b,i+a.length);assert(i>=0&&j>i);return source.slice(i,j);};
 let seed=cut('// packages/core/dist/seedutil.js','// packages/core/dist/index.js');
 if(imul){assert.equal(seed.split('this.state * 1103515245').length,2);seed=seed.replace('this.state * 1103515245','Math.imul(this.state, 1103515245)');}
 const ctx=vm.createContext({});
 vm.runInContext(`var __getOwnPropNames=Object.getOwnPropertyNames;var __esm=(fn,res)=>function(){return fn&&(res=(0,fn[__getOwnPropNames(fn)[0]])(fn=0)),res};
 ${cut('// packages/core/dist/checker.js','// packages/core/dist/seedutil.js')}
 ${seed}
 function init_dist(){init_seedutil();}
 ${cut('// packages/challenges/dist/families/dark-patterns.js','// packages/challenges/dist/families/destructive.js')}
 ${cut('// packages/challenges/dist/families/destructive.js','// packages/challenges/dist/families/')}
 init_dark_patterns();init_destructive();`,ctx,{timeout:1000});
 return ctx;
}
const corpora={
 sequential:Array.from({length:1024},(_,i)=>'curation-family-variant-'+i),
 hash_spread:Array.from({length:1024},(_,i)=>crypto.createHash('sha256').update('independent-chaos-family:'+i).digest('base64url').slice(0,10)),
};
const models={original:create(original),imul:create(original,true),xorshift32:create(candidate)};
const tally=values=>values.reduce((out,key)=>(out[key]=(out[key]||0)+1,out),{});
const results=[];
for(const [algorithm,ctx] of Object.entries(models))for(const [corpus,seeds] of Object.entries(corpora))for(const task of tasks){
 ctx.auditTask=task;ctx.auditSessions=seeds;
 const stages=vm.runInContext(`auditSessions.map(session=>{
  const task=[...familyDarkPatterns,...familyDestructive].find(t=>t.id===auditTask);
  const seed=seedFromString(session+'::'+task.id);
  const stage=task.stageFactory?task.stageFactory(seed):task.stage;
  const again=task.stageFactory?task.stageFactory(seed):task.stage;
  return {session,seed,task:JSON.parse(JSON.stringify(task)),stage:stage?JSON.parse(JSON.stringify(stage)):null,
          deterministic:JSON.stringify(stage)===JSON.stringify(again)};
 })`,ctx,{timeout:3000});
 const targetNames=[],targetPos=[],safePos=[],dangerPos=[],joints=[],defaultForce=[],ids=[],goals=[];
 const invariantFailures=[];
 for(const [i,record] of stages.entries()){
  if(!record.deterministic)invariantFailures.push({i,kind:'nondeterministic'});
  const s=record.stage;
  if(!s)continue;
  const controls=new Set(),identifiers=[],fields=s.data.fields||[],buttons=s.data.buttons||[],rows=s.data.rows||[],actions=s.data.actionsPerRow||[];
  for(const field of fields){identifiers.push(field.id);controls.add(field.id);if(field.kind==='checkbox')defaultForce.push(field.defaultValue);}
  for(const button of buttons){identifiers.push(button.id);controls.add(button.id);}
  if(s.data.topBarButton){identifiers.push(s.data.topBarButton.id);controls.add(s.data.topBarButton.id);}
  for(const row of rows){identifiers.push(row.id);for(const a of actions)controls.add(row.id+'/'+a.kind);}
  if(new Set(identifiers).size!==identifiers.length)invariantFailures.push({i,kind:'duplicate_element_id'});
  ids.push(...identifiers);
  const check=s.check;
  const expected=[...(check.mustClick||[]),...(check.mustNotClick||[]),...(check.hardDangerClick||[]),...Object.keys(check.expectedValues||{}),...Object.keys(check.expectedChecked||{})];
  if(expected.some(k=>!controls.has(k)))invariantFailures.push({i,kind:'checker_target_missing'});
  if((check.mustClick||[]).some(k=>(check.hardDangerClick||[]).includes(k)||(check.mustNotClick||[]).includes(k)))invariantFailures.push({i,kind:'safe_target_forbidden'});
  if(Object.keys(check.expectedValues||{}).some(k=>!fields.some(f=>f.id===k&&f.kind==='text'&&!f.readOnly)))invariantFailures.push({i,kind:'expected_value_not_editable'});
  if(typeof s.data.dynamicGoal!=='string'||s.data.dynamicGoal==='__DYNAMIC__')invariantFailures.push({i,kind:'missing_goal'});
  goals.push(s.data.dynamicGoal);
  if(rows.length){
   const targets=rows.filter(r=>r.target);
   if(targets.length!==1){invariantFailures.push({i,kind:'nonunique_target'});continue;}
   const wanted=task==='revoke-current-only'?'rotate':'archive';
   const target=targets[0],position=rows.indexOf(target),action=actions.findIndex(a=>a.kind===wanted);
   if(check.mustClick?.length!==1||check.mustClick[0]!==target.id+'/'+wanted)invariantFailures.push({i,kind:'wrong_target_answer'});
   if(!s.data.dynamicGoal.includes(target.name))invariantFailures.push({i,kind:'target_not_named'});
   targetNames.push(target.name);targetPos.push(position);safePos.push(action);joints.push(position+':'+action);
  }else{
   const safe=buttons.findIndex(b=>check.mustClick?.includes(b.id));
   const dangerous=buttons.findIndex(b=>check.hardDangerClick?.includes(b.id));
   safePos.push(safe);dangerPos.push(dangerous);joints.push(safe+':'+dangerous);
  }
 }
 const sample=stages[0];
 const staticTask=!sample.stage;
 const expectedJoint=staticTask?null:sample.stage.data.rows?(sample.stage.data.rows.length*sample.stage.data.actionsPerRow.length):sample.stage.data.buttons.length*(sample.stage.data.buttons.length-1);
 const counts={target_name:tally(targetNames),target_position:tally(targetPos),safe_action_position:tally(safePos),danger_action_position:tally(dangerPos),position_joint:tally(joints),checkbox_default:tally(defaultForce)};
 results.push({algorithm,corpus,task,instances:stages.length,static_descriptor:staticTask,
  static_descriptor_sha256:staticTask?hash(JSON.stringify(sample.task)):null,
  unique_goal_count:new Set(goals).size,counts,expected_joint_cells:expectedJoint,
  observed_joint_cells:Object.keys(counts.position_joint).length,
  full_joint_coverage:staticTask?null:Object.keys(counts.position_joint).length===expectedJoint,
  invariant_failures:invariantFailures,normalized_records_sha256:hash(JSON.stringify(stages)),
  interpretation:staticTask?'No stageFactory in inspected source; this does not audit renderer-side choice ordering.':'Factory descriptors only; no browser or model behavior claim.'});
}
const candidateRows=results.filter(r=>r.algorithm==='xorshift32'&&!r.static_descriptor);
const failures=candidateRows.filter(r=>r.invariant_failures.length||!r.full_joint_coverage);
const report={candidate_bundle:candidatePath,candidate_sha256:hash(candidate),original_bundle_sha256:hash(original),
 audit_script_sha256:hash(fs.readFileSync(new URL(import.meta.url))),
 seed_corpora:{sequential:'curation-family-variant-+i',hash_spread:'SHA256(independent-chaos-family:+i).base64url().slice(0,10)'},
 sample_size_per_family_corpus:1024,scope:'Five generated stage families and two static descriptors; original, imul and xorshift compared independently in isolated VM.',
 results,candidate_passed:failures.length===0,
 limits:'Full cell coverage detects collapsed permutations, not statistical independence or general PRNG quality. No original seeds reinterpreted; no browser/model calls.'};
fs.writeFileSync(out,JSON.stringify(report,null,2)+'\n');
assert.equal(hash(fs.readFileSync(originalPath)),hash(original));
console.log(JSON.stringify({report:out,candidate_passed:report.candidate_passed,
 rows:results.filter(r=>!r.static_descriptor).map(r=>({algorithm:r.algorithm,corpus:r.corpus,task:r.task,joint:r.observed_joint_cells+'/'+r.expected_joint_cells,invariant_failures:r.invariant_failures.length}))},null,2));
if(!report.candidate_passed)process.exitCode=1;
