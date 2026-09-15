import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {createServer} from 'node:http';
import {once} from 'node:events';
import {Agent} from '../lib/agent.mjs';
import {BlobStore,FileStore} from '../lib/store.mjs';
import {createHandler} from '../api/index.mjs';
import {digest} from '../lib/auth.mjs';

const env={OPENROUTER_API_KEY:'offline-test-only',DEMO_SESSION_SECRET:'s'.repeat(64),
  DEMO_INVITES_JSON:JSON.stringify({one:digest('a'.repeat(43)),two:digest('b'.repeat(43))})};
const store=async()=>new FileStore(await mkdtemp(tmpdir()+'/daylight-interactive-'));
const response=action=>new Response(JSON.stringify({provider:'Offline',choices:[{message:{content:JSON.stringify(action)}}],usage:{cost:0}}));
const shop={text:'Campus Supply',controls:[{id:'nav',tag:'a',label:'Study rooms'}]};
const rooms={text:'Study room availability',controls:[{id:'people',tag:'select',label:'People',options:[{value:'1'},{value:'3'}]}]};

test('assist navigates, filters and answers with every request/receipt retained',async()=>{
  const calls=[],actions=[{action:'click',id:'nav'},{action:'select',id:'people',value:'3'},
    {action:'done',message:'The displayed room is available for three people.'}];
  const agent=new Agent(await store(),{env,fetcher:async(_,options)=>{
    calls.push(JSON.parse(options.body));return response(actions[calls.length-1]);
  }});
  const {id}=await agent.start('one',{mode:'assist',goal:'When are study rooms available for three people?'});
  for(let index=0;index<3;index++) {
    const result=await agent.step('one',{id,observation:index?rooms:shop,
      conversation:[{role:'user',content:'Earlier unrelated request'}],activity:'Earlier steps'});
    assert.equal(result.status,'awaiting_client');assert.deepEqual(result.action,{...actions[index],message:actions[index].message||''});
    if(index===2)assert.equal(result.answer,actions[2].message);
    const receipt=await agent.event('one',{id,result:{description:'Browser applied step '+index}});
    assert.equal(receipt.status,index===2?'complete':'ready');
  }
  assert.equal(calls.length,3);
  for(const call of calls) {
    assert.equal(call.session_id,id);assert.match(call.messages[0].content,/CAN follow/);
    assert.equal(call.stream,false);assert.equal(call.response_format.type,'json_schema');
    assert.equal(call.response_format.json_schema.strict,true);assert.equal(call.provider.require_parameters,true);
    assert.deepEqual(call.response_format.json_schema.schema.required,['action','id','value','message']);
    assert.match(call.messages[0].content,/NOT a reservation/);
    assert.ok(!call.messages[0].content.includes('You cannot click'));
  }
  const trace=(await agent.read('one',id)).value;
  assert.equal(trace.protocol,'interactive-actions-v1');assert.equal(trace.evaluation,null);
  assert.equal(trace.steps.length,3);assert.ok(trace.steps.every(s=>s.request&&s.response_text&&s.client_result));
});

test('plain-text final answer preserves earlier receipts and raw error without replay or invented completion',async()=>{
  const text='I have all the information needed to answer the question about room availability.';
  const raw=JSON.stringify({provider:'Offline',choices:[{finish_reason:'stop',message:{content:text}}],usage:{cost:0}});
  let calls=0;
  const agent=new Agent(await store(),{env,fetcher:async()=>++calls===1?response({action:'select',id:'people',value:'3'}):new Response(raw)});
  const {id}=await agent.start('one',{mode:'assist',goal:'When are rooms available for three people?'});
  await agent.step('one',{id,observation:rooms});
  await agent.event('one',{id,result:{description:'People filter set to 3'}});
  const before=(await agent.read('one',id)).value.steps[0];
  const result=await agent.step('one',{id,observation:rooms});
  assert.equal(result.status,'error');assert.equal(result.action,null);assert.equal(result.answer,null);
  assert.match(result.error,/invalid action format/);assert.ok(!result.error.includes("Unexpected token"));
  const trace=(await agent.read('one',id)).value;
  assert.deepEqual(trace.steps[0],before);assert.equal(trace.evaluation,null);
  assert.equal(trace.steps[1].output,text);assert.equal(trace.steps[1].response_text,raw);
  assert.equal(trace.steps[1].error_code,'MODEL_ACTION_INVALID_JSON');assert.ok(trace.steps[1].error_detail);
  assert.ok(trace.steps[1].reservation);assert.equal(trace.steps[1].client_result,null);
  await assert.rejects(agent.step('one',{id,observation:rooms}));assert.equal(calls,2);
});

test('structured done returns the answer and requires a saved receipt; length cutoff never executes an action',async()=>{
  for(const finish of ['stop','length']) {
    let request;
    const action={action:'done',id:null,value:null,message:'A room for three is available at 10:00.'};
    const agent=new Agent(await store(),{env,fetcher:async(_,options)=>{
      request=JSON.parse(options.body);
      return new Response(JSON.stringify({choices:[{finish_reason:finish,message:{content:JSON.stringify(action)}}],usage:{cost:0}}));
    }});
    const {id}=await agent.start('one',{mode:'assist',goal:'Find availability'});
    const result=await agent.step('one',{id,observation:rooms});
    assert.equal(request.response_format.json_schema.name,'daylight_action');
    if(finish==='stop') {
      assert.equal(result.answer,action.message);assert.equal(result.status,'awaiting_client');
      assert.deepEqual(result.action,{action:'done',message:action.message});
      assert.equal((await agent.event('one',{id,result:{description:'Answer shown'}})).status,'complete');
    } else {
      assert.equal(result.status,'error');assert.equal(result.action,null);assert.match(result.error,/token limit/);
      assert.equal((await agent.read('one',id)).value.steps[0].output,JSON.stringify(action));
    }
  }
});

test('assist bad action stops without a client action or an implicit retry',async()=>{
  let calls=0;const agent=new Agent(await store(),{env,fetcher:async()=>{calls++;return response({action:'select',id:'people',value:'99'});}});
  const {id}=await agent.start('one',{mode:'assist',goal:'Filter for three people'});
  const result=await agent.step('one',{id,observation:rooms});
  assert.equal(result.status,'error');assert.equal(result.action,null);assert.equal(calls,1);
  const trace=(await agent.read('one',id)).value;assert.ok(trace.steps[0].request&&trace.steps[0].response&&trace.steps[0].reservation);
  await assert.rejects(agent.step('one',{id,observation:rooms}));assert.equal(calls,1);
});

test('history discovers legacy and interrupted records, paginates and preserves null versus zero costs',async()=>{
  const s=await store(),agent=new Agent(s,{env,fetcher:async()=>response({action:'done',message:'Answer'})});
  const mine=[];
  for(let i=0;i<3;i++)mine.push((await agent.start('one',{mode:'chat',goal:'Question '+i})).id);
  const foreign=await agent.start('two',{mode:'chat',goal:'Private other user'});
  await agent.step('one',{id:mine[0],observation:shop});
  const pending=await agent.read('one',mine[1]);pending.value.status='pending';
  pending.value.steps=[{dispatch_at:new Date().toISOString(),usage:null}];
  await s.write('daylight/traces/one/'+mine[1]+'.json',pending.value,pending.etag);
  let cursor;const rows=[];
  do {const page=await agent.list('one',{cursor,limit:1});rows.push(...page.traces);cursor=page.cursor;}while(cursor);
  assert.deepEqual(rows.map(r=>r.id).sort(),mine.sort());assert.ok(!rows.some(r=>r.id===foreign.id));
  assert.equal(rows.find(r=>r.status==='complete').reported_cost_usd,0);
  const unknown=rows.find(r=>r.status==='pending');assert.equal(unknown.reported_cost_usd,null);assert.equal(unknown.unknown_cost_attempts,1);
  assert.ok(rows.every(r=>r.evaluation===null&&r.training_eligible===false));
  assert.ok(!JSON.stringify(rows).includes('request')); // summary does not expose model payloads
  await assert.rejects(agent.list('one',{limit:101}));
});

test('list distrusts foreign keys and mismatched owners even if storage returns them',async()=>{
  let reads=0;
  const good='11111111-1111-4111-8111-111111111111';
  const agent=new Agent({listKeys:async()=>({keys:['daylight/traces/two/'+good+'.json','daylight/traces/one/../../secret.json','daylight/traces/one/'+good+'.json'],cursor:null,has_more:false}),
    read:async()=>{reads++;return {value:{id:good,owner:'two'}};}},{env});
  assert.deepEqual((await agent.list('one')).traces,[]);assert.equal(reads,1);
});

test('Blob listing forwards only scoped pagination and returns no Blob URLs',async()=>{
  const calls=[];const s=new BlobStore({env:{BLOB_STORE_ID:'test'},sdk:{list:async options=>{
    calls.push(options);return {blobs:[{pathname:'daylight/traces/one/id.json',url:'private-url'}],cursor:'next',hasMore:true};
  }}});
  assert.deepEqual(await s.listKeys('daylight/traces/one/',{cursor:'opaque',limit:7}),
    {keys:['daylight/traces/one/id.json'],cursor:'next',has_more:true});
  assert.deepEqual(calls,[{prefix:'daylight/traces/one/',cursor:'opaque',limit:7,storeId:'test'}]);
});

test('history HTTP endpoint requires login and ignores attempts to select a different owner',async t=>{
  const s=await store(),agent=new Agent(s,{env});
  const mine=await agent.start('one',{mode:'chat',goal:'Mine'});
  await agent.start('two',{mode:'chat',goal:'Other'});
  const server=createServer(createHandler({store:s,env,local:true}));server.listen(0,'127.0.0.1');await once(server,'listening');t.after(()=>server.close());
  const origin='http://127.0.0.1:'+server.address().port;
  assert.equal((await fetch(origin+'/api/traces')).status,401);
  const login=await fetch(origin+'/login',{method:'POST',headers:{origin,'content-type':'application/json'},body:JSON.stringify({code:'a'.repeat(43)}),redirect:'manual'});
  const cookie=login.headers.get('set-cookie');
  const result=await (await fetch(origin+'/api/traces?owner=two',{headers:{cookie}})).json();
  assert.deepEqual(result.traces.map(t=>t.id),[mine.id]);
  assert.equal((await fetch(origin+'/api/traces?limit=1000',{headers:{cookie}})).status,400);
});

test('interrupt HTTP endpoint retains invitation ownership and same-origin protection',async t=>{
  const s=await store(),agent=new Agent(s,{env});
  const mine=await agent.start('one',{mode:'assist',goal:'Mine'}),other=await agent.start('two',{mode:'assist',goal:'Other'});
  const server=createServer(createHandler({store:s,env,local:true}));server.listen(0,'127.0.0.1');await once(server,'listening');t.after(()=>server.close());
  const origin='http://127.0.0.1:'+server.address().port;
  const headers={origin,'content-type':'application/json'};
  assert.equal((await fetch(origin+'/api/interrupt',{method:'POST',headers,body:JSON.stringify(mine)})).status,401);
  const login=await fetch(origin+'/login',{method:'POST',headers,body:JSON.stringify({code:'a'.repeat(43)}),redirect:'manual'});headers.cookie=login.headers.get('set-cookie');
  assert.equal((await fetch(origin+'/api/interrupt',{method:'POST',headers:{...headers,origin:'https://other.example'},body:JSON.stringify(mine)})).status,403);
  assert.equal((await fetch(origin+'/api/interrupt',{method:'POST',headers,body:JSON.stringify(other)})).status,404);
  assert.equal((await fetch(origin+'/api/interrupt',{method:'POST',headers,body:JSON.stringify({id:'invalid'})})).status,400);
  const response=await fetch(origin+'/api/interrupt',{method:'POST',headers,body:JSON.stringify(mine)});
  assert.equal(response.status,200);assert.equal((await response.json()).status,'interrupted');
  assert.equal((await agent.read('two',other.id)).value.status,'ready');
});
