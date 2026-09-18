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
