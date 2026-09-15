import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {randomUUID} from 'node:crypto';
import {Agent} from '../lib/agent.mjs';
import {FileStore} from '../lib/store.mjs';
import {groupTraceSessions} from '../client/tool-activity.js';
const setup=async()=>new Agent(new FileStore(await mkdtemp(tmpdir()+'/daylight-conversations-')));

test('conversation identity groups turns without replacing per-turn IDs or owner scope',async()=>{
  const agent=await setup(),first=await agent.start('one',{mode:'assist',goal:'Find rooms',interaction_kind:'ask'});
  const second=await agent.start('one',{mode:'assist',goal:'For four please',interaction_kind:'ask',conversation_id:first.conversation_id});
  assert.notEqual(first.id,second.id);assert.equal(first.conversation_id,second.conversation_id);
  await agent.start('two',{mode:'assist',goal:'Other owner',conversation_id:first.conversation_id});
  const rows=(await agent.list('one')).traces;assert.equal(rows.length,2);assert.equal(groupTraceSessions(rows).length,1);
  assert.ok(rows.every(row=>row.conversation_id===first.conversation_id));
  assert.equal(rows.find(row=>row.id===first.id).conversation_source,'server_generated');
  assert.equal(rows.find(row=>row.id===second.id).conversation_source,'client_declaration');
  await assert.rejects(agent.read('two',first.id),{status:404});
  await assert.rejects(agent.start('one',{mode:'assist',goal:'Invalid',conversation_id:'bad'}),{status:400});
});

test('interrupted continuation inherits conversation identity and rejects conflicting identity',async()=>{
  const agent=await setup(),first=await agent.start('one',{mode:'assist',goal:'Old'});await agent.interrupt('one',first);
  const second=await agent.start('one',{mode:'assist',goal:'New',continuation_of:first.id});
  assert.equal(second.conversation_id,first.conversation_id);
  const rows=(await agent.list('one')).traces,row=rows.find(row=>row.id===second.id);
  assert.equal(row.previous_trace_id,first.id);assert.equal(row.previous_trace_source,'continuation_of');
  await assert.rejects(agent.start('one',{mode:'assist',goal:'Mismatch',continuation_of:first.id,conversation_id:randomUUID()}),{status:400});
  await assert.rejects(agent.start('two',{mode:'assist',goal:'Foreign',continuation_of:first.id}),{status:404});
});

test('historical explicit activity links are read without rewriting traces or guessing from text',async()=>{
  const agent=await setup(),first=await agent.start('one',{mode:'assist',goal:'Same goal'}),second=await agent.start('one',{mode:'assist',goal:'Same goal'}),unrelated=await agent.start('one',{mode:'assist',goal:'Same goal'}),foreign=await agent.start('two',{mode:'assist',goal:'Private'});
  for(const [id,previous] of [[first.id,null],[second.id,first.id],[unrelated.id,foreign.id]]){
    const row=await agent.read('one',id);delete row.value.conversation_id;delete row.value.conversation_source;
    row.value.steps=[{request:{messages:[{role:'user',content:JSON.stringify({prior_activity:JSON.stringify({last_trace:previous})})}]}}];
    await agent.store.write('daylight/traces/one/'+id+'.json',row.value,row.etag);
  }
  const before=await Promise.all([first,second,unrelated].map(row=>agent.read('one',row.id)));
  const rows=(await agent.list('one')).traces;
  assert.equal(rows.find(row=>row.id===second.id).previous_trace_id,first.id);
  assert.equal(rows.find(row=>row.id===second.id).previous_trace_source,'recorded_prior_activity.last_trace');
  assert.equal(rows.find(row=>row.id===unrelated.id).previous_trace_id,null);
  assert.ok(rows.every(row=>row.conversation_id===null));assert.equal(groupTraceSessions(rows).length,2);
  assert.deepEqual(await Promise.all([first,second,unrelated].map(row=>agent.read('one',row.id))),before);
});

test('grouping follows explicit metadata, keeps unknown turns separate and handles cyclic links',()=>{
  const at='2026-09-15T12:00:00Z';
  assert.equal(groupTraceSessions([{id:'a',goal:'Same',created_at:at},{id:'b',goal:'Same',created_at:at}]).length,2);
  const groups=groupTraceSessions([{id:'a',previous_trace_id:'b',created_at:at},{id:'b',previous_trace_id:'a',created_at:at},{id:'c',previous_trace_id:'missing',created_at:at}]);
  assert.equal(groups.length,2);assert.equal(groups[0].length,2);
});
