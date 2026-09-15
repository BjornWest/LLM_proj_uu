// Independent acceptance of a specified copied queue module; no browser/network.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {pathToFileURL} from 'node:url';
import assert from 'node:assert/strict';
const modulePath=path.resolve(process.argv[2]||'.local/chaos-fifo-v1/dist/web/assets/intent-stage-queue.mjs');
const output=path.resolve(process.argv[3]||'data/curation/chaos-repair-review/queue-v1-unit.json');
assert(!fs.existsSync(output),'Do not overwrite an independent review');
const digest=p=>crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
const initial=digest(modulePath);
const {createStageQueue}=await import(pathToFileURL(modulePath));
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return {promise,resolve,reject};};
const tick=async()=>{await Promise.resolve();await Promise.resolve();};
const results=[];
async function check(name,fn){try{const detail=await fn();results.push({name,passed:true,...detail});}catch(e){results.push({name,passed:false,error:String(e)});}}
await check('input-before-save-under-delayed-response-and-immutable-payload',async()=>{
 const gate=deferred(),sent=[],outcomes=[];
 const q=createStageQueue({send:async e=>{sent.push(e);return sent.length===1?gate.promise:{outcome:'success'};},onOutcome:r=>outcomes.push(r)});
 const input={kind:'input',target:'name',value:'requested',meta:{initial:true}};
 const a=q.emit(input);input.value='mutated';input.meta.initial=false;
 const b=q.emit({kind:'click',target:'save'});await tick();
 assert.equal(sent.length,1);assert.equal(sent[0].value,'requested');assert.equal(sent[0].meta.initial,true);
 gate.resolve({outcome:'incomplete'});await Promise.all([a,b]);await q.drain();
 assert.deepEqual(sent.map(e=>e.kind),['input','click']);assert.equal(sent[1].target,'save');
 assert.deepEqual(outcomes.map(r=>r.outcome),['incomplete','success']);
 return {dispatches:sent.length,order:sent.map(e=>e.kind)};
});
await check('two-field-blurs-and-commit-preserve-event-order',async()=>{
 const sent=[];const q=createStageQueue({send:async e=>{sent.push(e);return {outcome:e.kind==='click'?'success':'incomplete'};}});
 const values=[{kind:'input',target:'name',value:'requested'},{kind:'input',target:'owner',value:'unchanged'},{kind:'click',target:'save'}];
 await Promise.all(values.map(e=>q.emit(e)));assert.deepEqual(sent,values);
 return {dispatches:sent.length};
});
await check('success-discards-already-queued-and-later-clicks-without-hidden-retry',async()=>{
 const sent=[];const q=createStageQueue({send:async e=>{sent.push(e);return {outcome:'success'};}});
 const a=q.emit({kind:'click',target:'first'}),b=q.emit({kind:'click',target:'duplicate'});
 await Promise.all([a,b]);const later=await q.emit({kind:'click',target:'later'});
 assert.equal(sent.length,1);assert.equal(later.dispatched,false);
 assert.equal(q.snapshot().events.filter(e=>e.phase==='discarded').length,2);
 return {dispatches:sent.length,discarded:2};
});
await check('every-terminal-outcome-stops-pending-work',async()=>{
 for(const terminal of ['success','failure','rejected','skipped']){
  let sent=0;const q=createStageQueue({send:async()=>{sent++;return {outcome:terminal};}});
  await Promise.all([q.emit({kind:'click',target:'commit'}),q.emit({kind:'click',target:'extra'})]);
  assert.equal(sent,1);assert.equal(q.snapshot().reason,'terminal:'+terminal);
 }
 return {terminal_outcomes:4};
});
await check('input-transport-failure-discards-commit-without-retry',async()=>{
 let sends=0,errors=0,outcomes=0;
 const q=createStageQueue({send:async()=>{sends++;throw Error('synthetic transport failure');},onError:()=>errors++,onOutcome:()=>outcomes++});
 const result=await Promise.all([q.emit({kind:'input',target:'name'}),q.emit({kind:'click',target:'save'})]);
 assert.equal(sends,1);assert.equal(errors,1);assert.equal(outcomes,0);
 assert.equal(result[1].dispatched,false);assert.equal(q.snapshot().reason,'request_failed');
 return {dispatches:sends,error_callbacks:errors};
});
await check('unmount-before-dispatch-cancels-work',async()=>{
 let sends=0;const q=createStageQueue({send:async()=>{sends++;return {outcome:'incomplete'};}});
 const work=q.emit({kind:'click',target:'save'});q.close('unmounted');await work;assert.equal(sends,0);
 return {dispatches:sends};
});
await check('unmount-with-request-in-flight-ignores-old-result-and-discards-pending',async()=>{
 const gate=deferred();let sends=0,outcomes=0,errors=0;
 const q=createStageQueue({send:async()=>{sends++;return gate.promise;},onOutcome:()=>outcomes++,onError:()=>errors++});
 const first=q.emit({kind:'input',target:'name'}),pending=q.emit({kind:'click',target:'save'});
 await tick();assert.equal(sends,1);q.close('unmounted');gate.resolve({outcome:'success'});
 const result=await Promise.all([first,pending]);assert.equal(result[0].ignored_after_close,true);
 assert.equal(sends,1);assert.equal(outcomes,0);assert.equal(errors,0);
 return {dispatches:sends,stale_callbacks:outcomes+errors};
});
await check('new-mount-queue-is-independent-of-old-request',async()=>{
 const gate=deferred(),log=[];
 const old=createStageQueue({send:async()=>gate.promise,onOutcome:()=>log.push('old')});
 const oldRequest=old.emit({kind:'click',target:'old'});await tick();old.close('unmounted');
 const fresh=createStageQueue({send:async()=>({outcome:'success'}),onOutcome:()=>log.push('fresh')});
 await fresh.emit({kind:'click',target:'new'});gate.resolve({outcome:'success'});await oldRequest;
 assert.deepEqual(log,['fresh']);return {stale_callbacks:0};
});
await check('multiple-edits-not-coalesced-or-reordered-before-save',async()=>{
 const sent=[];const q=createStageQueue({send:async e=>{sent.push(e);return {outcome:'incomplete'};}});
 const events=[{kind:'input',target:'name',value:'A'},{kind:'input',target:'name',value:'B'},{kind:'click',target:'save'}];
 await Promise.all(events.map(e=>q.emit(e)));assert.deepEqual(sent,events);
 assert.equal(q.snapshot().events.filter(e=>e.phase==='dispatched').length,3);
 return {dispatches:3};
});
assert.equal(digest(modulePath),initial,'Candidate module changed while testing');
const report={scope:'Independent deterministic unit acceptance of copied module only; not React/browser integration or a grader certificate.',
 candidate:modulePath,candidate_sha256:initial,audit_script_sha256:digest(new URL(import.meta.url)),
 cases:results,passed:results.every(r=>r.passed),model_calls:0,browser_calls:0};
fs.mkdirSync(path.dirname(output),{recursive:true});fs.writeFileSync(output,JSON.stringify(report,null,2)+'\n');
console.log(JSON.stringify(report,null,2));if(!report.passed)process.exitCode=1;
