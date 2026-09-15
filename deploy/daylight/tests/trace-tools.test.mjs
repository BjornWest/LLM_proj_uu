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
