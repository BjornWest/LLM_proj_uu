import test from 'node:test';
import assert from 'node:assert/strict';
import {traceToolEvidence} from '../client/tool-activity.js';
const request=names=>({response_format:{json_schema:{schema:{properties:{action:{enum:names}}}}}});
test('available action inventory uses each recorded request, not observed actions or current runtime',()=>{
  const evidence=traceToolEvidence([{id:'one',steps:[
    {request:request(['click','fill','done']),action:{action:'click',id:'126'},observation:{controls:[{id:'126',label:'October appointment'}]},client_result:{description:'Clicked'}},
    {request:request(['click','done']),action:{action:'click',id:'126'},observation:{controls:[{id:'126',label:'November appointment'}]}},
  ]}]);
  assert.deepEqual(evidence.map(step=>step.available.map(tool=>tool.name)),[['click','fill','done'],['click','done']]);
  assert.deepEqual(evidence.map(step=>step.calls[0].title),['click · October appointment','click · November appointment']);
  assert.deepEqual(evidence.map(step=>step.calls[0].status),['recorded','unconfirmed']);
  assert.equal(evidence[0].available[1].name,'fill');assert.equal(evidence[0].selected,'click');
});
test('unknown inventory differs from explicit empty tools; done answers are not browser tool calls',()=>{
  const evidence=traceToolEvidence([{id:'one',steps:[
    {action:{action:'click',id:'a'},client_result:{error:'Navigation failed'}},
    {request:{tools:[]},action:{action:'done',message:'Answer'}},
  ]}]);
  assert.equal(evidence[0].available,null);assert.equal(evidence[0].calls[0].status,'failed');
  assert.deepEqual(evidence[1].available,[]);assert.deepEqual(evidence[1].calls,[]);
});
test('native function definitions and calls preserve names and raw parameters without assuming execution',()=>{
  const tool={type:'function',function:{name:'read_page',description:'Read current page',parameters:{type:'object'}}};
  const call={id:'call-a',type:'function',function:{name:'read_page',arguments:'{}'}};
  const evidence=traceToolEvidence([{id:'one',steps:[{request:{tools:[tool]},response:{choices:[{message:{tool_calls:[call]}}]}}]}]);
  assert.equal(evidence[0].available[0].definition,tool);assert.equal(evidence[0].calls[0].action,call);assert.equal(evidence[0].calls[0].status,'unconfirmed');
});

test('live worker batches retain each call and distinguish AX, skipped and failed actions',async()=>{
 const {jobToolEvidence}=await import('../client/tool-activity.js');
 const decisions=jobToolEvidence({id:'job',steps:[{step:0,action:null,calls:[
  {action:"fill(bid='13', value='Aurora')",status:'recorded',browser_stepped:true},
  {action:"ax_search(query='Blue')",status:'recorded',browser_stepped:false},
  {action:"click(bid='14')",status:'skipped',browser_stepped:false,stop_reason:'document_or_navigation_changed'},
  {action:"click(bid='99')",status:'failed',error:'Not found'}]}]});
 assert.equal(decisions[0].label,'Model turn 1');assert.equal(decisions[0].calls.length,4);
 assert.deepEqual(decisions[0].calls.map(c=>c.status),['recorded','recorded','skipped','failed']);
 assert.equal(decisions[0].calls[1].name,'ax_search');assert.equal(decisions[0].calls[2].resultSummary,'document_or_navigation_changed');
 const old=jobToolEvidence({id:'old',steps:[{step:0,action:null,browser_stepped:true}]});assert.deepEqual(old[0].calls,[]);
});
