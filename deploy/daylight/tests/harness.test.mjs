import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {randomUUID,createHash} from 'node:crypto';
import {Harness,TASKS,workerAuthorized} from '../lib/harness.mjs';
import {FileStore} from '../lib/store.mjs';
import {Agent} from '../lib/agent.mjs';

const env={HARNESS_WORKER_TOKEN:'w'.repeat(64),DEMO_DAILY_BUDGET_USD:'1',DEMO_DAILY_CALL_LIMIT:'100'};
test('worker reservation acknowledges exact output ceiling and rejects over-ceiling before charging',async t=>{
  const {h}=await fixture(t),job=await claim(h,'live');
  const request={...job,step:0,input_bytes:1000,request_sha256:'b'.repeat(64)};
  for(const max_tokens of [4097,0,-1,1.5,'4096',null,true])await assert.rejects(h.reserve({...request,max_tokens}),/Output token limit/);
  const receipt=await h.reserve({...request,max_tokens:4096});
  assert.equal(receipt.max_tokens,4096);
  assert.equal(receipt.amount_usd,(1000+2048)*.5/1e6+4096*4/1e6);
  await assert.rejects(h.reserve({...request,max_tokens:4096}),/already attempted/);
  const legacy=await h.reserve({...request,step:1});
  assert.equal(legacy.max_tokens,512);
});
async function fixture(t) {
  const dir=await mkdtemp(path.join(os.tmpdir(),'harness-broker-'));t.after(()=>rm(dir,{recursive:true,force:true}));
  let clock=Date.now();const store=new FileStore(dir),h=new Harness(store,{env,now:()=>clock});
  return {h,store,tick:ms=>clock+=ms};
}
async function claim(h,mode='rehearsal') {
  const worker_id=randomUUID();await h.poll({worker_id,mode,tasks:['rooms','chaos-confirmshaming']});
  const created=await h.start('alice',{task:'rooms',goal:TASKS[0].goal});
  return {...(await h.poll({worker_id,mode,tasks:['rooms','chaos-confirmshaming']})).job,worker_id};
}
test('worker auth requires a dedicated secret and exact bearer token',()=>{
  assert.equal(workerAuthorized('Bearer '+env.HARNESS_WORKER_TOKEN,env),true);
  for(const value of [undefined,'Bearer wrong','w'.repeat(64)])assert.equal(workerAuthorized(value,env),false);
  assert.equal(workerAuthorized('Bearer '+env.HARNESS_WORKER_TOKEN,{}),false);
});
test('owner isolation and fixed/rehearsal task contract enforced by server',async t=>{
  const {h}=await fixture(t),job=await claim(h);
  assert.equal((await h.list('bob')).jobs.length,0);
  await assert.rejects(h.read('bob',job.id),/not found/);
  await assert.rejects(h.start('alice',{task:'rooms',goal:'A custom task'}),/live worker/);
  await assert.rejects(h.start('alice',{task:'chaos-confirmshaming',goal:'Buy things'}),/trusted objective/);
  assert.equal((await h.config()).tasks[0].custom_goal,false);
  assert.equal('lease' in await h.read('alice',job.id),false);
});
test('external task objectives/revisions are fixed and generated goals become immutable',async t=>{
  const {h}=await fixture(t),worker_id=randomUUID(),tasks=TASKS.map(t=>t.id);
  await h.poll({worker_id,mode:'live',tasks,task_revisions:Object.fromEntries(TASKS.map(t=>[t.id,t.revision]))});
  const visible=await h.config();assert.equal(visible.tasks.length,TASKS.length);
  for(const item of visible.tasks)for(const key of ['source_sha256','build','selector','kind'])assert.equal(key in item,false);
  const fixed=TASKS.find(t=>t.id==='tricky-p07-clean');
  await assert.rejects(h.start('alice',{task:fixed.id,goal:'Buy an extra warranty'}),/fixed validated goal/);
  await assert.rejects(h.start('alice',{task:fixed.id,task_revision:'old'}),/revision changed/);
  const created=await h.start('alice',{task:'chaos-revoke-current-only',goal:''});
  assert.equal(created.goal,null);assert.equal(created.goal_resolution,'session_pending');
  const job=(await h.poll({worker_id,mode:'live',tasks,task_revisions:Object.fromEntries(TASKS.map(t=>[t.id,t.revision]))})).job;assert.equal(job.task_revision,created.task_revision);
  await h.update({...job,snapshot:{steps:[],resolved_goal:'Rotate only the token for this generated device.'}});
  const saved=await h.read('alice',job.id);assert.equal(saved.goal,'Rotate only the token for this generated device.');
  assert.equal(saved.goal_resolution,'resolved');
  await assert.rejects(h.update({...job,snapshot:{steps:[],resolved_goal:'Rotate every token'}}),/replace the trusted objective/);
});
test('unavailable tasks reject before enqueuing',async t=>{
  const {h}=await fixture(t);
  await assert.rejects(h.start('alice',{task:'chaos-confirmshaming'}),/not available/);
  assert.equal((await h.list('alice')).jobs.length,0);
});
test('duplicate claim never redelivers an active job; another worker cannot claim it',async t=>{
  const {h}=await fixture(t),job=await claim(h);
  assert.deepEqual(await h.poll({worker_id:job.worker_id,mode:'rehearsal',tasks:['rooms']}),{job:null,active:job.id});
  await assert.rejects(h.poll({worker_id:randomUUID(),mode:'rehearsal',tasks:['rooms']}),/Another worker/);
});
test('expired job is interrupted and never requeued; old lease cannot write',async t=>{
  const {h,tick}=await fixture(t),job=await claim(h);tick(120001);
  assert.equal((await h.read('alice',job.id)).status,'interrupted');
  await assert.rejects(h.checkpoint(job),/lease/);
  const result=await h.poll({worker_id:randomUUID(),mode:'rehearsal',tasks:['rooms']});
  assert.equal(result.job,null);assert.equal((await h.read('alice',job.id)).evaluation,null);
});
test('reservations share existing demo budget and each request is reserved once',async t=>{
  const {h,store}=await fixture(t),job=await claim(h,'live');
  const req={...job,step:0,input_bytes:1000,request_sha256:'a'.repeat(64)};
  const first=await h.reserve(req);
  await assert.rejects(h.reserve(req),/already attempted/);
  const oldDemo=await new Agent(store,{env}).reserve(0.01);
  assert.equal(oldDemo.daily_reserved_usd,first.amount_usd+0.01);
});
test('failed reservation never grants a permit or retries a pending request',async t=>{
  const {h,store}=await fixture(t),job=await claim(h,'live');
  await new Agent(store,{env}).reserve(1);
  const req={...job,step:0,input_bytes:1000,request_sha256:'a'.repeat(64)};
  await assert.rejects(h.reserve(req),/daily allowance/);
  await assert.rejects(h.reserve(req),/already attempted/);
});
test('original artifacts are immutable, hash checked and owner scoped',async t=>{
  const {h}=await fixture(t),job=await claim(h),bytes=Buffer.from('selected AX');
  const value={...job,name:'decision-observation-000.txt',data:bytes.toString('base64'),sha256:createHash('sha256').update(bytes).digest('hex')};
  await h.artifact(value);await h.artifact(value);
  assert.deepEqual(await h.artifactRead('alice',job.id,value.name),bytes);
  await assert.rejects(h.artifactRead('bob',job.id,value.name),/not found/);
  await assert.rejects(h.artifact({...value,name:'../metadata.json'}),/Unsupported/);
  await assert.rejects(h.artifact({...value,data:Buffer.from('changed').toString('base64')}),/hash mismatch/);
});
test('updates require unique ordered immutable steps and issues attach exact artifact',async t=>{
  const {h}=await fixture(t),job=await claim(h);
  const step={step:0,action:"click('1')",error:null,artifact:{}};
  await assert.rejects(h.update({...job,snapshot:{steps:[step,step]}}),/unique and sequential/);
  await h.update({...job,snapshot:{steps:[step],episode:'original-id',runtime:{source:'pinned'}}});
  await assert.rejects(h.update({...job,snapshot:{steps:[{...step,action:"click('2')"}]}}),/rewrite/);
  const issue=await h.issue('alice',job.id,{step:0,comment:'Wrong control'});
  assert.equal(issue.episode,'original-id');assert.deepEqual(issue.runtime,{source:'pinned'});
  await assert.rejects(h.issue('alice',job.id,{step:1,comment:'Missing step'}),/recorded step/);
  await assert.rejects(h.issue('bob',job.id,{step:0,comment:'Wrong owner'}),/not found/);
  const response=await h.read('alice',job.id);assert.equal(response.issues.length,1);assert.equal(response.evaluation,null);
});
test('complete-site tasks require matching worker revision before start and dispatch',async t=>{
 const {h,store}=await fixture(t),worker_id=randomUUID(),task=TASKS.find(t=>t.site_revision);
 await h.poll({worker_id,mode:'live',tasks:[task.id]});
 assert.equal((await h.config()).tasks.find(t=>t.id===task.id).available,false);
 await assert.rejects(h.start('alice',{task:task.id,goal:task.goal}),/not available/);
 const task_revisions={[task.id]:task.revision};await h.poll({worker_id,mode:'live',tasks:[task.id],task_revisions});
 const created=await h.start('alice',{task:task.id,goal:task.goal,task_revision:task.revision});assert.equal(created.site_revision,task.site_revision);
 const before=(await store.read('daylight/harness/control-v1.json')).value.jobs[created.id];
 assert.deepEqual(await h.poll({worker_id,mode:'live',tasks:[task.id],task_revisions:{[task.id]:'old'}}),{job:null});
 assert.deepEqual((await store.read('daylight/harness/control-v1.json')).value.jobs[created.id],before);
 assert.equal((await h.poll({worker_id,mode:'live',tasks:[task.id],task_revisions})).job.id,created.id);
});

test('expanded contracts require matching live revision and retain exact public goals',async t=>{
  const {h}=await fixture(t),worker_id=randomUUID(),task=TASKS.find(t=>t.id==='tricky:AU01');
  assert.equal(TASKS.filter(t=>t.expanded).length,203);
  await h.poll({worker_id,mode:'live',tasks:[task.id],task_revisions:{[task.id]:'stale'}});
  assert.equal((await h.config()).tasks.find(t=>t.id===task.id).available,false);
  await assert.rejects(h.start('alice',{task:task.id,task_revision:task.revision}),/not available/);
  await h.poll({worker_id,mode:'rehearsal',tasks:[task.id],task_revisions:{[task.id]:task.revision}});
  assert.equal((await h.config()).tasks.find(t=>t.id===task.id).available,false);
  await h.poll({worker_id,mode:'live',tasks:[task.id],task_revisions:{[task.id]:task.revision}});
  await assert.rejects(h.start('alice',{task:task.id}),/revision changed/);
  await assert.rejects(h.start('alice',{task:task.id,task_revision:task.revision,goal:'Changed objective'}),/fixed validated goal/);
  const job=await h.start('alice',{task:task.id,task_revision:task.revision,interaction_kind:'task'});
  assert.equal(job.goal,task.goal);assert.equal(job.site_id,task.site_id);
  for(const field of ['contract','grader_input','private_contract','policy_input','setup'])assert.equal(field in task,false);
});

test('expanded limits follow pinned task and authoritative publication follows grading phase',async t=>{
  const {h}=await fixture(t),worker_id=randomUUID(),task=TASKS.find(t=>t.id==='webarena:117');
  const capability={worker_id,mode:'live',tasks:[task.id],task_revisions:{[task.id]:task.revision}};
  await h.poll(capability);await h.start('alice',{task:task.id,task_revision:task.revision});
  const job=(await h.poll(capability)).job;
  await assert.rejects(h.reserve({...job,step:task.execution_limits.max_steps,input_bytes:1,request_sha256:'a'.repeat(64)}),/request index/);
  const receipt=await h.reserve({...job,step:0,input_bytes:300000,request_sha256:'a'.repeat(64)});
  assert.equal(receipt.amount_usd,(300000+2048)*.5/1e6+512*4/1e6);
  await assert.rejects(h.update({...job,snapshot:{steps:[],evaluation:{task_completed:true}}}),/terminal-only/);
  await assert.rejects(h.update({...job,snapshot:{steps:[],status:'finished',evaluation:{task_completed:true}}}),/authoritative final/);
  const evaluation={task_completed:true,authorization_satisfied:null,safe_success:null};
  await h.update({...job,snapshot:{steps:[],status:'finished',evaluation,grading_phase:'after_browser_close',evaluation_source:'authoritative-evaluation.json'}});
  const saved=await h.read('alice',job.id);assert.deepEqual(saved.evaluation,evaluation);
  assert.equal(saved.grading_phase,'after_browser_close');assert.equal(saved.evaluation_source,'authoritative-evaluation.json');
});

test('legacy task bounds stay at twelve decisions and 250k request bytes',async t=>{
  const {h}=await fixture(t),job=await claim(h,'live');
  await assert.rejects(h.reserve({...job,step:12,input_bytes:1,request_sha256:'a'.repeat(64)}),/request index for task/);
  await assert.rejects(h.reserve({...job,step:0,input_bytes:250001,request_sha256:'a'.repeat(64)}),/task bound/);
});

test('worker cost settlement binds lease/request, frees unused budget, and accepts late response after termination',async t=>{
 const {h,store}=await fixture(t),job=await claim(h,'live');
 const req={...job,step:0,input_bytes:1000,request_sha256:'a'.repeat(64),max_tokens:4096};
 const receipt=await h.reserve(req);
 const response_text=JSON.stringify({id:'generation1',usage:{cost:.001},choices:[]});
 await assert.rejects(h.settle({...req,request_sha256:'b'.repeat(64),response_text}),/does not match/);
 await assert.rejects(h.settle({...req,lease:randomUUID(),response_text}),/does not match/);
 await h.update({...job,snapshot:{steps:[],status:'error',error:'Parser failure'}});
 const settled=await h.settle({...req,response_text});assert.equal(settled.actual_spent_usd,.001);assert.equal(settled.outstanding_usd,0);
 assert.deepEqual(await h.settle({...req,response_text}),settled);
 const row=(await store.read(`daylight/budgets/${receipt.date}.json`)).value;assert.equal(row.calls,1);
 assert.equal((await h.read('alice',job.id)).status,'error');
});
