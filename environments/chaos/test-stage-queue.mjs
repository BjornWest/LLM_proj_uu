import test from 'node:test';
import assert from 'node:assert/strict';
import {createStageQueue} from './stage-queue.mjs';
const event=(kind,target,value)=>({kind,target,value,clientTs:123,isTrusted:true});
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};};
test('blur input and one click dispatch once each in FIFO order',async()=>{
  const gate=deferred(),sent=[];
  const q=createStageQueue({send:async e=>{sent.push(e);if(e.kind==='input')await gate.promise;return {outcome:e.kind==='click'?'success':'pending'};}});
  const input=q.emit(event('input','name','new-name')),click=q.emit(event('click','save'));
  await Promise.resolve();assert.deepEqual(sent.map(e=>e.kind),['input']);
  gate.resolve();await Promise.all([input,click]);
  assert.deepEqual(sent.map(e=>e.kind),['input','click']);assert.equal(q.snapshot().closed,true);
});
test('terminal response prevents a queued duplicate click from dispatching',async()=>{
  let calls=0;const q=createStageQueue({send:async()=>{calls++;return {outcome:'success'};}});
  await Promise.all([q.emit(event('click','save')),q.emit(event('click','save'))]);
  assert.equal(calls,1);assert.equal(q.snapshot().events.filter(e=>e.phase==='discarded').length,1);
});
test('unmount cancels queued work and ignores an in-flight response',async()=>{
  const gate=deferred();let calls=0,outcomes=0;
  const q=createStageQueue({send:async()=>{calls++;await gate.promise;return {outcome:'pending'};},onOutcome:()=>outcomes++});
  const a=q.emit(event('input','name','value')),b=q.emit(event('click','save'));
  await Promise.resolve();q.close();gate.resolve();await Promise.all([a,b]);
  assert.equal(calls,1);assert.equal(outcomes,0);
});
test('transport failure closes queue without retry or replay',async()=>{
  let calls=0,errors=0;const q=createStageQueue({send:async()=>{calls++;throw Error('offline');},onError:()=>errors++});
  await Promise.all([q.emit(event('input','name')),q.emit(event('click','save'))]);
  assert.equal(calls,1);assert.equal(errors,1);assert.equal(q.snapshot().reason,'request_failed');
});
test('event values are captured at emission, not after waiting',async()=>{
  const sent=[],q=createStageQueue({send:async e=>{sent.push(e);return {outcome:'pending'};}});
  const source=event('input','name','first'),p=q.emit(source);source.value='later';await p;
  assert.equal(sent[0].value,'first');assert.equal(sent[0].clientTs,123);assert.equal(sent[0].isTrusted,true);
});
test('throwing error callback settles pending events with discard records',async()=>{
  const q=createStageQueue({send:async()=>{throw Error('transport');},onError:()=>{throw Error('callback');}});
  await Promise.all([q.emit(event('input','name')),q.emit(event('click','save'))]);
  assert.equal(q.snapshot().reason,'request_failed');
  assert.deepEqual(q.snapshot().events.map(e=>e.phase),['queued','queued','dispatched','failed','callback_failed','discarded']);
});
test('rejected async outcome callback does not mislabel completed transport',async()=>{
  let calls=0;const q=createStageQueue({send:async()=>{calls++;return {outcome:'pending'};},onOutcome:async()=>{throw Error('callback');}});
  await Promise.all([q.emit(event('input','name')),q.emit(event('click','save'))]);
  assert.equal(calls,1);assert.equal(q.snapshot().reason,'callback_failed:onOutcome');
  assert.equal(q.snapshot().events.some(e=>e.phase==='failed'),false);
  assert.equal(q.snapshot().events.filter(e=>e.phase==='callback_failed').length,1);
});
test('terminal reason survives a later callback failure and unmount',async()=>{
  const q=createStageQueue({send:async()=>({outcome:'success'}),onOutcome:()=>{throw Error('callback');}});
  await q.emit(event('click','save'));q.close('unmounted');
  assert.equal(q.snapshot().reason,'terminal:success');
  assert.equal(q.snapshot().events.filter(e=>e.phase==='completed').length,1);
  assert.equal(q.snapshot().events.some(e=>e.phase==='failed'),false);
});
