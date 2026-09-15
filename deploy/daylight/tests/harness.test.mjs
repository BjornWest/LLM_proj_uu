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
  await assert.rejects(h.start('alice',{task:'chaos-confirmshaming',goal:'Buy things'}),/fixed validated goal/);
  assert.equal((await h.config()).tasks[0].custom_goal,false);
  assert.equal('lease' in await h.read('alice',job.id),false);
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
