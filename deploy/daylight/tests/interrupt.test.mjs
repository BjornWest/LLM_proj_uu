import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {Agent} from '../lib/agent.mjs';
import {FileStore} from '../lib/store.mjs';
const env={OPENROUTER_API_KEY:'offline-only'};
const obs={text:'Page',controls:[{id:'buy',tag:'button',label:'Buy'}]};
const deferred=()=>{let resolve;const promise=new Promise(r=>{resolve=r;});return {promise,resolve};};
const response=()=>new Response(JSON.stringify({choices:[{message:{content:'{"action":"click","id":"buy"}'}}],usage:{cost:0.0001}}));
const setup=async(fetcher)=>new Agent(new FileStore(await mkdtemp(tmpdir()+'/daylight-interrupt-')),{env,fetcher});

test('interrupt pending inference, retain late response and cost, never deliver its action or resurrect trace',async()=>{
  const entered=deferred(),release=deferred();let calls=0;
  const agent=await setup(async()=>{calls++;entered.resolve();await release.promise;return response();});
  const {id}=await agent.start('one',{mode:'assist',goal:'Buy one'});
  const pending=agent.step('one',{id,observation:obs});await entered.promise;
  await assert.rejects(agent.interrupt('two',{id}),{status:404});
  assert.equal((await agent.interrupt('one',{id})).status,'interrupted');
  const cancelled=(await agent.read('one',id)).value;
  assert.equal(cancelled.steps[0].response,null);assert.equal(cancelled.goal,'Buy one');
  const next=await agent.start('one',{mode:'assist',goal:'Do not buy',continuation_of:id});
  assert.equal((await agent.read('one',next.id)).value.continuation_of,id);
  await assert.rejects(agent.start('two',{mode:'assist',goal:'Spoof',continuation_of:id}),{status:404});
  release.resolve();const result=await pending;
  assert.equal(result.status,'interrupted');assert.equal(result.action,null);assert.equal(result.answer,null);assert.equal(result.cost,0.0001);
  const saved=(await agent.read('one',id)).value;
  assert.equal(saved.status,'interrupted');assert.deepEqual(saved.interruption,cancelled.interruption);assert.equal(saved.finished_at,cancelled.finished_at);
  assert.equal(saved.steps[0].action.id,'buy');assert.ok(saved.steps[0].response_text);assert.equal(saved.steps[0].client_result,null);
  assert.equal(saved.steps[0].usage.cost,0.0001);assert.equal(saved.evaluation,null);
  await assert.rejects(agent.step('one',{id,observation:obs}),{status:409});
  assert.equal((await agent.interrupt('one',{id})).status,'interrupted');assert.equal(calls,1);
});

test('interrupt before dispatch prevents model call even across conditional-write race',async()=>{
  for(const boundary of ['request','dispatch']) {
    let calls=0,blocked=false;const agent=await setup(async()=>{calls++;return response();});
    const {id}=await agent.start('one',{mode:'assist',goal:'Buy one'});
    const original=agent.store.write.bind(agent.store);
    agent.store.write=async(key,value,etag)=>{
      if(!blocked&&value.id===id&&value.status==='pending'&&(boundary==='request'||value.steps[0].dispatch_at)) {
        blocked=true;await agent.interrupt('one',{id});
      }
      return original(key,value,etag);
    };
    const result=await agent.step('one',{id,observation:obs});
    assert.equal(result.status,'interrupted');assert.equal(calls,0);
    const trace=(await agent.read('one',id)).value;
    assert.equal(trace.status,'interrupted');assert.ok(!trace.steps[0]?.dispatch_at);
  }
});

test('already executing action may save its exact receipt after interruption without resuming',async()=>{
  for(const race of [false,true]) {
    const agent=await setup(async()=>response());
    const {id}=await agent.start('one',{mode:'assist',goal:'Buy one'});
    await agent.step('one',{id,observation:obs});
    if(!race)await agent.interrupt('one',{id});
    else {
      const original=agent.store.write.bind(agent.store);let blocked=false;
      agent.store.write=async(key,value,etag)=>{
        if(!blocked&&value.id===id&&value.steps[0]?.client_result){blocked=true;await agent.interrupt('one',{id});}
        return original(key,value,etag);
      };
    }
    const receipt={description:'Already applied',page_after:obs,state_after:{orders:[1]}};
    assert.equal((await agent.event('one',{id,result:receipt})).status,'interrupted');
    const trace=(await agent.read('one',id)).value;
    assert.equal(trace.status,'interrupted');assert.equal(trace.steps[0].client_result.description,receipt.description);
    assert.deepEqual(trace.steps[0].client_result.state_after,receipt.state_after);
    await assert.rejects(agent.event('one',{id,result:receipt}),{status:409});
  }
});

test('interruption retries only conditional conflicts and never overwrites terminal completed evidence',async()=>{
  const agent=await setup(async()=>response());
  const {id}=await agent.start('one',{mode:'assist',goal:'Buy one'});
  await agent.step('one',{id,observation:obs});
  const original=agent.store.write.bind(agent.store);let blocked=false;
  agent.store.write=async(key,value,etag)=>{
    if(!blocked&&value.id===id&&value.interruption){blocked=true;await agent.event('one',{id,result:{stop:true,description:'Finished'}});}
    return original(key,value,etag);
  };
  assert.equal((await agent.interrupt('one',{id})).status,'complete');
  assert.equal((await agent.read('one',id)).value.interruption,undefined);
  const next=await agent.start('one',{mode:'assist',goal:'Next'});
  agent.store.write=async()=>{throw Error('Storage unavailable');};
  await assert.rejects(agent.interrupt('one',next),/Storage unavailable/);
  assert.equal((await agent.read('one',next.id)).value.status,'ready');
});

test('a competing step claim cannot overwrite dispatched intent after an interruption',async()=>{
  const entered=deferred(),release=deferred();const agent=await setup(async()=>{entered.resolve();await release.promise;return response();});
  const {id}=await agent.start('one',{mode:'assist',goal:'Buy one'});
  const original=agent.store.write.bind(agent.store);const held=deferred(),resume=deferred();let blocked=false;
  agent.store.write=async(key,value,etag)=>{
    if(!blocked&&value.id===id&&value.status==='pending'&&value.steps[0].observation.text==='Competing page') {
      blocked=true;held.resolve();await resume.promise;
    }
    return original(key,value,etag);
  };
  const competing=agent.step('one',{id,observation:{...obs,text:'Competing page'}});await held.promise;
  const accepted=agent.step('one',{id,observation:obs});await entered.promise;
  const originalStep=(await agent.read('one',id)).value.steps[0];
  await agent.interrupt('one',{id});resume.resolve();assert.equal((await competing).status,'interrupted');
  release.resolve();assert.equal((await accepted).status,'interrupted');
  const saved=(await agent.read('one',id)).value.steps[0];
  assert.equal(saved.attempt_id,originalStep.attempt_id);assert.deepEqual(saved.request,originalStep.request);assert.equal(saved.observation.text,'Page');assert.ok(saved.response_text);
});
