import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {Agent,completionTokenLimit} from '../lib/agent.mjs';
import {FileStore} from '../lib/store.mjs';

async function fixture(t,settings={},reply={}) {
  const dir=await mkdtemp(tmpdir()+'/reasoning-budget-');t.after(()=>rm(dir,{recursive:true,force:true}));
  const sent=[],store=new FileStore(dir);
  const agent=new Agent(store,{env:{OPENROUTER_API_KEY:'offline-only',...settings},fetcher:async(_,options)=>{
    sent.push(JSON.parse(options.body));return new Response(JSON.stringify({usage:{cost:0},choices:[{
      finish_reason:'stop',message:{reasoning:'Private reasoning retained only as raw evidence',content:JSON.stringify({action:'done',message:'Answer'})}}],...reply}));
  }});
  const {id}=await agent.start('owner',{mode:'assist',goal:'Read page'});
  return {agent,id,sent,body:{id,observation:{text:'Page',controls:[]}}};
}
test('completion ceiling accepts only explicit positive integers',()=>{
  assert.equal(completionTokenLimit(),4096);assert.equal(completionTokenLimit('2048'),2048);
  for(const value of ['',0,-1,1.2,true,'1e3',' 512','4096.0',NaN,Infinity])assert.throws(()=>completionTokenLimit(value));
});
test('reasoning enabled with exact configured ceiling reservation and raw evidence',async t=>{
  for(const limit of [4096,2048]){
    const {agent,id,sent,body}=await fixture(t,limit===4096?{}:{OPENROUTER_MAX_TOKENS:String(limit)});
    const result=await agent.step('owner',body),step=(await agent.read('owner',id)).value.steps[0];
    assert.equal(result.answer,'Answer');assert.equal(result.status,'awaiting_client');
    assert.deepEqual(sent[0].reasoning,{enabled:true});assert.equal(sent[0].max_tokens,limit);
    assert.equal(step.reservation.amount_usd,(Buffer.byteLength(JSON.stringify(sent[0]))+2048)*.5/1e6+limit*4/1e6);
    assert.match(step.response.choices[0].message.reasoning,/Private reasoning/);
    assert.ok(!JSON.stringify(result).includes('Private reasoning'));
  }
});
test('higher output reserve respects unchanged daily cap and sends nothing on rejection',async t=>{
  const {agent,id,sent,body}=await fixture(t,{DEMO_DAILY_BUDGET_USD:'.01'});
  const result=await agent.step('owner',body);
  assert.equal(result.status,'error');assert.match(result.error,/daily allowance/);assert.equal(sent.length,0);
  assert.equal((await agent.read('owner',id)).value.steps[0].response,null);
});
test('reasoning-only length response retains cost/evidence without action or repair',async t=>{
  const {agent,id,sent,body}=await fixture(t,{}, {usage:{cost:.003,completion_tokens:4096,completion_tokens_details:{reasoning_tokens:4096}},choices:[{finish_reason:'length',message:{content:'',reasoning:'Unfinished'}}]});
  const result=await agent.step('owner',body),step=(await agent.read('owner',id)).value.steps[0];
  assert.equal(result.status,'error');assert.equal(result.action,null);assert.equal(sent.length,1);
  assert.match(result.error,/token limit/);assert.equal(step.usage.cost,.003);assert.ok(step.reservation.amount_usd>.003);
  assert.equal(step.response.choices[0].message.reasoning,'Unfinished');
});
