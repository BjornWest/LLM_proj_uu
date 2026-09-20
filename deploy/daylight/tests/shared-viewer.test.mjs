import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,readFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {prepareViewer} from '../prepare-viewer.mjs';
import {browserProjection,allowedViewerAsset} from '../client/trace-browser.js';

test('project extension keeps selected and transition observations separate and uses retained tool definitions',()=>{
  const request={tools:[{type:'function',function:{name:'click'}},{type:'function',function:{name:'fill'}}]};
  const session={id:'example',messages:[
    {id:'a',turn:1,kind:'note',observation_role:'transition',text:'Old toast'},
    {id:'b',turn:1,kind:'note',observation_role:'selected',text:'Fresh policy observation'},
    {id:'c',turn:1,kind:'prompt',provenance:'retained_request_input',text:JSON.stringify(request)},
    {id:'d',turn:1,kind:'tool',text:'click(126)',status:'returned'},
    {id:'e',turn:1,kind:'result',title:'Raw model response',text:'{"error":"not a browser result"}',status:'error'},
    {id:'f',turn:2,kind:'note',observation_role:'selected',text:'Different appointment'},
    {id:'g',turn:2,kind:'prompt',provenance:'selected_context',text:JSON.stringify(request)},
    {id:'h',turn:2,kind:'tool',text:'click(126)',status:'unknown'}
  ]};
  const before=JSON.stringify(session),steps=browserProjection(session);
  assert.deepEqual(steps[0].available.map(tool=>tool.name),['click','fill']);assert.equal(steps[1].available,null);
  assert.equal(steps[0].calls[0].observation.text,'Fresh policy observation');assert.equal(steps[1].calls[0].observation.text,'Different appointment');
  assert.equal(steps[0].calls[0].status,'recorded');assert.equal(steps[1].calls[0].status,'unconfirmed');
  assert.equal(steps[0].calls[0].receipt,null);assert.equal(JSON.stringify(session),before);
});
test('viewer accepts only same-origin authorized attachment paths',()=>{
  const previous=globalThis.location;globalThis.location={origin:'https://viewer.example'};
  try{
    assert.ok(allowedViewerAsset('/api/library/sessions/opaque/assets/opaque'));
    for(const value of ['https://foreign.example/api/library/sessions/a/assets/b','/artifacts/private.png','javascript:alert(1)','/api/library/sessions/a/assets/b?redirect=1','/api/library/sessions/a/assets/../secret'])assert.equal(allowedViewerAsset(value),false);
  }finally{globalThis.location=previous;}
});
test('packaging preserves shared readable renderer while extracting inline code for protected CSP',async()=>{
  const directory=await mkdtemp(tmpdir()+'/shared-viewer-assets-'),files=await prepareViewer(directory);
  const html=await readFile(directory+'/trace-viewer.html','utf8'),js=await readFile(directory+'/trace-viewer.js','utf8');
  assert.ok(files.includes('trace-viewer-source.json'));assert.doesNotMatch(html,/<script>/);assert.doesNotMatch(html,/<style>/);
  assert.match(html,/type="module" src="\/assets\/trace-viewer.js"/);assert.match(js,/function contentView/);assert.match(js,/function captureTracePosition/);
  assert.match(js,/projectExtension.update\(current\)/);assert.doesNotMatch(js,/setInterval\(async/);assert.match(js,/loadViewerIndex/);
});
test('batch projection pairs each result by ID and keeps recorded target labels current',()=>{
  const messages=[];
  function turn(n,items,tools,results,document='d1'){
    if(items)messages.push({turn:n,kind:'note',observation_role:'selected',text:JSON.stringify({document,items})});
    messages.push({turn:n,kind:'result',title:'Raw model response',text:JSON.stringify({choices:[{message:{reasoning_details:[{type:'encrypted'}],reasoning:'Recorded plan',tool_calls:tools.map(([id,name,args])=>({id,function:{name,arguments:JSON.stringify(args)}}))}}]})});
    for(const [id,name,args]of tools)messages.push({turn:n,kind:'tool',tool_call_id:id,text:name+'(...)',status:results[id]?.skipped?'unknown':'completed',execution_status:results[id]?.skipped?'skipped':'completed'});
    // Results deliberately reversed to ensure pairing never depends on position.
    for(const [id,result]of Object.entries(results).reverse())messages.push({turn:n,kind:'result',tool_call_id:id,text:JSON.stringify({result})});
  }
  turn(0,[{ref:'d1n1',bid:'36',name:'Submit booking request'}],[['a','click',{bid:'36'}],['b','fill',{bid:'99',value:'Example'}]],{a:{execution:'call_completed'},b:{error:'Missing control'}});
  turn(1,[{ref:'d1n1',name:'Cancel request'}],[['c','click',{bid:'36'}]],{c:{skipped:true,reason:'document_changed'}});
  turn(2,[],[['d','click',{bid:'36'}]],{d:{execution:'call_completed'}},'d2');
  const rows=browserProjection({id:'batch',messages});
  assert.equal(rows[0].calls[0].title,'Click “Submit booking request”');
  assert.equal(rows[0].calls[1].result.error,'Missing control');
  assert.equal(rows[0].reasoning,'Recorded plan');
  assert.equal(rows[1].calls[0].title,'Click “Cancel request”');
  assert.equal(rows[1].calls[0].status,'skipped');
  assert.match(rows[1].calls[0].resultSummary,/Not executed/);
  assert.equal(rows[2].calls[0].title,'Click “control 36”');
});
test('legacy flat snapshots and removed AX nodes cannot reuse stale labels',()=>{
  const call=(turn)=>[{turn,kind:'result',title:'Raw model response',text:JSON.stringify({choices:[{message:{tool_calls:[{id:'a',function:{name:'click',arguments:'{"bid":"36"}'}}]}}]})},{turn,kind:'tool',text:"click('36')",status:'returned'}];
  const rows=browserProjection({id:'legacy',messages:[
    {turn:0,kind:'note',observation_role:'selected',text:"[36] button 'Save'"},...call(0),
    {turn:1,kind:'note',observation_role:'selected',text:"[37] button 'Cancel'"},...call(1),
    {turn:2,kind:'note',observation_role:'selected',text:'{"document":"d1","items":[{"ref":"d1n1","bid":"36","name":"Buy"}]}'},...call(2),
    {turn:3,kind:'note',observation_role:'selected',text:'{"document":"d1","items":[{"ref":"d1n1","removed":true}]}'},...call(3)]});
  assert.deepEqual(rows.map(r=>r.calls[0].title),['Click “Save”','Click “control 36”','Click “Buy”','Click “control 36”']);
});
