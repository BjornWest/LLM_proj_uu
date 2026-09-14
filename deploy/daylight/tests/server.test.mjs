import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,readFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {createServer} from 'node:http';
import {once} from 'node:events';
import {config,digest,login,authenticate,sessionCookie} from '../lib/auth.mjs';
import {FileStore} from '../lib/store.mjs';
import {Agent,parseAction} from '../lib/agent.mjs';
import {createHandler} from '../api/index.mjs';
import {World} from '../client/world.js';
const code='a'.repeat(43),other='b'.repeat(43);
const env={DEMO_SESSION_SECRET:'s'.repeat(64),DEMO_INVITES_JSON:JSON.stringify({one:digest(code),two:digest(other)}),OPENROUTER_API_KEY:'test-not-a-real-key'};
const obs={text:'Your page',controls:[{id:'b1',tag:'button',label:'Buy'}]};
const response=output=>new Response(JSON.stringify({id:'response-test',model:'qwen/qwen3.8-27b',provider:'Cloudflare',
  choices:[{message:{content:output}}],usage:{cost:0.0001,prompt_tokens:150,completion_tokens:10,prompt_tokens_details:{cached_tokens:0}}}),{status:200});
const store=async()=>new FileStore(await mkdtemp(tmpdir()+'/daylight-test-'));
test('signed invitations expire, reject tampering and revoke already signed cookies',()=>{
  const settings=config(env),token=login(code,settings,100);
  assert.equal(authenticate(sessionCookie(token),settings,101),'one');
  assert.equal(authenticate(sessionCookie(token),settings,100+8*86400000),null);
  assert.equal(authenticate(sessionCookie(token+'x'),settings,101),null);
  assert.equal(authenticate(sessionCookie(token),{...settings,invites:{two:digest(other)}},101),null);
  assert.equal(login('bad',settings),null);assert.throws(()=>config({}));
});
test('request persisted before dispatch; response before action; duplicate dispatch blocked',async()=>{
  const s=await store();let calls=0;let id;
  const agent=new Agent(s,{env,fetcher:async(url,request)=>{
    calls++;const row=(await agent.read('one',id)).value;
    assert.equal(row.status,'pending');assert.deepEqual(row.steps[0].request,JSON.parse(request.body));
    assert.ok(row.steps[0].reservation.amount_usd>0);assert.ok(!JSON.stringify(row).includes(env.OPENROUTER_API_KEY));
    return response('{"action":"click","id":"b1"}');
  }});
  ({id}=await agent.start('one',{mode:'task',goal:'Buy one'}));
  const result=await agent.step('one',{id,observation:obs});assert.equal(result.action.id,'b1');assert.equal(calls,1);
  await assert.rejects(agent.step('one',{id,observation:obs}));assert.equal(calls,1);
  await assert.rejects(agent.read('two',id));
  const row=(await agent.read('one',id)).value;assert.equal(row.steps[0].routing.resolved_provider,'Cloudflare');assert.equal(row.evaluation,null);
  assert.equal((await agent.event('one',{id,result:{stop:true,state_after:{orders:[1]}}})).status,'complete');
  assert.equal((await agent.read('one',id)).value.steps[0].client_result.evidence_source,'untrusted_browser_client');
});
test('simultaneous requests claim the trace once before inference',async()=>{
  let calls=0;const agent=new Agent(await store(),{env,fetcher:async()=>{calls++;await new Promise(r=>setTimeout(r,10));return response('{"action":"done"}');}});
  const {id}=await agent.start('one',{mode:'task',goal:'Finish'});
  const results=await Promise.allSettled([agent.step('one',{id,observation:obs}),agent.step('one',{id,observation:obs})]);
  assert.equal(calls,1);assert.equal(results.filter(x=>x.status==='rejected').length,1);
});
test('HTTP errors and timeouts retain reservations and exact attempted requests; no retry',async()=>{
  for(const failure of ['http','timeout']) {
    let calls=0;const s=await store(),agent=new Agent(s,{env,fetcher:async()=>{calls++;if(failure==='timeout')throw Error('Timed out');return new Response('{"error":{"message":"limited"}}',{status:429,headers:{'retry-after':'60'}});}});
    const {id}=await agent.start('one',{mode:'task',goal:'Do a thing'}),out=await agent.step('one',{id,observation:obs});
    assert.equal(out.status,'error');assert.equal(calls,1);
    const row=(await agent.read('one',id)).value.steps[0];assert.ok(row.reservation.amount_usd>0);assert.equal(row.request.session_id,id);
    assert.equal(row.http_status,failure==='http'?429:null);assert.equal(row.response_text,failure==='http'?'{"error":{"message":"limited"}}':null);
  }
});
test('budget exhaustion and failed storage prevent model dispatch',async()=>{
  let calls=0;const s=await store();
  const agent=new Agent(s,{env:{...env,DEMO_DAILY_BUDGET_USD:'0.000001'},fetcher:async()=>{calls++;return response('x');}});
  const {id}=await agent.start('one',{mode:'task',goal:'Do'});assert.equal((await agent.step('one',{id,observation:obs})).status,'error');assert.equal(calls,0);
  const broken=new Agent({read:s.read.bind(s),write:async()=>{throw Error('Storage unavailable');}},{env,fetcher:async()=>{calls++;}});
  await assert.rejects(broken.start('one',{mode:'chat',goal:'Hi'}));assert.equal(calls,0);
});
test('chat cannot execute actions; malformed actions and unreported costs fail closed',async()=>{
  const s=await store(),agent=new Agent(s,{env,fetcher:async()=>response('{"action":"click","id":"b1"}')});
  const {id}=await agent.start('one',{mode:'chat',goal:'What is here?'}),out=await agent.step('one',{id,observation:obs});
  assert.equal(out.action,null);assert.equal(out.status,'complete');assert.ok(out.answer.includes('click'));
  assert.throws(()=>parseAction('{"action":"script","value":"evil"}',obs.controls));
  assert.throws(()=>parseAction('{"action":"click","id":"missing"}',obs.controls));
  assert.throws(()=>parseAction('{"action":"select","id":"b1","value":"x"}',obs.controls));
  const bad=new Agent(await store(),{env,fetcher:async()=>new Response(JSON.stringify({choices:[{message:{content:'{"action":"done"}'}}]}))});
  const next=await bad.start('one',{mode:'task',goal:'Finish'});assert.match((await bad.step('one',{...next,observation:obs})).error,/cost/);
});
test('all UI/assets/API paths require login; POST origin is checked; no secret or raw file exposure',async t=>{
  const s=await store(),server=createServer(createHandler({store:s,env,local:true}));
  server.listen(0,'127.0.0.1');await once(server,'listening');t.after(()=>server.close());
  const origin='http://127.0.0.1:'+server.address().port;
  for(const route of ['/','/assets/site.js','/assets/fixture.json','/private-assets/index.html','/world/test/booking'])
    assert.equal((await fetch(origin+route,{redirect:'manual'})).status,303);
  assert.equal((await fetch(origin+'/api/config')).status,401);
  assert.equal((await fetch(origin+'/login',{method:'POST',body:'{}',headers:{'content-type':'application/json',origin:'https://evil.example'}})).status,403);
  const logged=await fetch(origin+'/login',{method:'POST',headers:{origin,'content-type':'application/json'},body:JSON.stringify({code}),redirect:'manual'});
  assert.equal(logged.status,303);const cookie=logged.headers.get('set-cookie');assert.ok(cookie.includes('HttpOnly'));assert.ok(cookie.includes('SameSite=Strict'));
  const fixture=await fetch(origin+'/assets/fixture.json',{headers:{cookie}});assert.ok((await fixture.json()).rooms.length);
  for(const route of ['/private-assets/index.html','/.env','/assets/../package.json','/api/traces/bad'])assert.ok((await fetch(origin+route,{headers:{cookie}})).status>=400);
  const status=await (await fetch(origin+'/api/config',{headers:{cookie}})).json();assert.equal(status.owner,'one');assert.ok(!JSON.stringify(status).includes(env.OPENROUTER_API_KEY));
});
test('fictional worlds isolate users and validate complete booking intervals and orders',async()=>{
  const fixture=JSON.parse(await readFile('client/fixture.json','utf8')),one=new World(fixture),two=new World(fixture);
  one.action({type:'book',room_id:'a101',day:'Tuesday',time:'09:00',duration:30,people:3});assert.equal(two.state.bookings.length,0);
  assert.throws(()=>one.action({type:'book',room_id:'a101',day:'Tuesday',time:'09:00',duration:60,people:3}));
  assert.throws(()=>one.action({type:'book',room_id:'e203',day:'Tuesday',time:'09:00',duration:30,people:3}));
  one.action({type:'cart',product:'notebook',delta:1});one.action({type:'cart',product:'notebook',delta:1});one.action({type:'shipping',value:'pickup'});one.action({type:'checkout'});
  assert.equal(one.state.orders[0].total,118);assert.equal(two.state.orders.length,0);
});
