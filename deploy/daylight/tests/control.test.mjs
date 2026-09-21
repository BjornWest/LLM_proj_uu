import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm} from 'node:fs/promises';
import {createServer} from 'node:http';
import {tmpdir} from 'node:os';
import {SqliteStore} from '../lib/sqlite-store.mjs';
import {RemoteStore,configuredStore} from '../lib/remote-store.mjs';
import {controlHandler} from '../control-server.mjs';
import {Harness} from '../lib/harness.mjs';
import {Agent} from '../lib/agent.mjs';
import {randomUUID} from 'node:crypto';
import {createHandler} from '../api/index.mjs';
import {digest,config,login,sessionCookie} from '../lib/auth.mjs';

const secret='c'.repeat(64),worker='w'.repeat(64);
async function setup(t) {
  const dir=await mkdtemp(tmpdir()+'/daylight-control-');
  const store=new SqliteStore(dir+'/state.sqlite');
  const env={DAYLIGHT_CONTROL_TOKEN:secret,HARNESS_WORKER_TOKEN:worker,DEMO_DAILY_BUDGET_USD:'1'};
  const server=createServer(controlHandler({store,env}));
  await new Promise(r=>server.listen(0,'127.0.0.1',r));
  const origin='http://127.0.0.1:'+server.address().port;
  t.after(async()=>{server.closeAllConnections();await new Promise(r=>server.close(r));store.close();await rm(dir,{recursive:true,force:true});});
  return {store,env,origin,remote:new RemoteStore({env:{...env,DAYLIGHT_CONTROL_URL:origin}}),dir};
}
test('SQLite CAS persists across connections, rejects competing/stale creates and ABA',async t=>{
  const {store,dir}=await setup(t),other=new SqliteStore(dir+'/state.sqlite');t.after(()=>other.close());
  const key='daylight/test.json',first=await store.write(key,{x:1});
  assert.deepEqual((await other.read(key)).value,{x:1});
  await assert.rejects(other.write(key,{x:2}),{status:409});
  const next=await other.write(key,{x:1},first);assert.notEqual(next,first);
  await assert.rejects(store.write(key,{x:3},first),{status:409});
  await store.write(key,{x:2},next);
  assert.deepEqual((await other.read(key)).value,{x:2});
});
test('remote storage roundtrip, stable bounded pagination, conflict and bad key validation',async t=>{
  const {remote}=await setup(t);
  assert.equal(await remote.read('daylight/missing'),null);
  for(const key of ['b','a','c'])await remote.write('daylight/'+key,{key});
  const page=await remote.listKeys('daylight/',{limit:2});assert.deepEqual(page.keys,['daylight/a','daylight/b']);
  assert.deepEqual((await remote.listKeys('daylight/',{limit:2,cursor:page.cursor})).keys,['daylight/c']);
  await assert.rejects(remote.write('daylight/a',{}),{code:'BLOB_WRITE_CONFLICT'});
  for(const key of ['../secret','daylight/../../secret','other/key'])await assert.rejects(remote.read(key));
});
test('service rejects anonymous, wrong role, redirects and malformed origin configuration',async t=>{
  const {origin}=await setup(t);
  for(const token of ['',worker])assert.equal((await fetch(origin+'/internal/store/read',{method:'POST',headers:{authorization:'Bearer '+token},body:'{"key":"daylight/x"}'})).status,401);
  assert.equal((await fetch(origin+'/api/harness/worker/poll',{method:'POST',headers:{authorization:'Bearer '+secret},body:'{}'})).status,401);
  for(const url of ['http://example.com','https://x.test/path','https://user:pass@x.test','https://x.test?key=value'])assert.throws(()=>configuredStore({DAYLIGHT_CONTROL_URL:url,DAYLIGHT_CONTROL_TOKEN:secret}));
  assert.throws(()=>configuredStore({DAYLIGHT_CONTROL_TOKEN:secret}));
});
test('unavailable remote never retries or falls back to Blob',async()=>{
  let calls=0;const remote=new RemoteStore({env:{DAYLIGHT_CONTROL_URL:'https://control.example',DAYLIGHT_CONTROL_TOKEN:secret},fetcher:async()=>{calls++;throw Error(secret);}});
  await assert.rejects(remote.write('daylight/x',{}),e=>e.code==='CONTROL_UNAVAILABLE'&&!e.message.includes(secret));assert.equal(calls,1);
});
test('direct local worker and remote frontend share owner isolation, lease and budget',async t=>{
  const {remote,store,env,origin}=await setup(t),front=new Harness(remote,{env}),back=new Harness(store,{env}),worker_id=randomUUID();
  await back.poll({worker_id,mode:'live',tasks:['rooms']});
  const created=await front.start('alice',{task:'rooms',goal:'Book a room'});
  const job=(await back.poll({worker_id,mode:'live',tasks:['rooms']})).job;
  assert.equal(created.id,job.id);assert.equal((await front.list('bob')).jobs.length,0);
  const reserved=await back.reserve({...job,step:0,input_bytes:100,max_tokens:4096,request_sha256:'a'.repeat(64)});
  assert.equal(reserved.max_tokens,4096);
  assert.equal(reserved.amount_usd,(100+2048)*.5/1e6+4096*4/1e6);
  const next=await new Agent(remote,{env}).reserve(.01);
  assert.equal(next.daily_reserved_usd,reserved.amount_usd+.01);
  const result=await fetch(origin+'/api/harness/worker/settle',{method:'POST',headers:{authorization:'Bearer '+worker,'content-type':'application/json'},body:JSON.stringify({...job,step:0,request_sha256:'a'.repeat(64),response_text:JSON.stringify({id:'settle1',usage:{cost:.001}})})});
  assert.equal(result.status,200);assert.equal((await result.json()).actual_spent_usd,.001);
  const settled=(await store.read('daylight/budgets/'+reserved.date+'.json')).value;assert.equal(settled.outstanding_usd,.01);
  const stale=await remote.read('daylight/budgets/'+reserved.date+'.json');stale.value.calls++;stale.value.reserved_usd+=.02;
  await assert.rejects(remote.write('daylight/budgets/'+reserved.date+'.json',stale.value,stale.etag),e=>e.code==='BLOB_WRITE_CONFLICT');
  assert.equal((await back.poll({worker_id,mode:'live',tasks:['rooms']})).job,null);
});
test('interrupt pending response through remote SQLite retains cost and never revives trace',async t=>{
  const {remote}=await setup(t);let release,started;const gate=new Promise(r=>release=r),sent=new Promise(r=>started=r);let calls=0;
  const agent=new Agent(remote,{env:{OPENROUTER_API_KEY:'offline'},fetcher:async()=>{calls++;started();await gate;return new Response(JSON.stringify({choices:[{message:{content:'{"action":"click","id":"buy"}'}}],usage:{cost:.0001}}));}});
  const {id}=await agent.start('alice',{mode:'assist',goal:'Buy one'});
  const pending=agent.step('alice',{id,observation:{text:'Buy',controls:[{id:'buy',tag:'button',label:'Buy'}]}});
  await sent;await agent.interrupt('alice',{id});release();
  const reply=await pending;assert.equal(reply.status,'interrupted');assert.equal(reply.action,null);assert.equal(calls,1);
  const trace=(await agent.read('alice',id)).value;assert.equal(trace.steps[0].usage.cost,.0001);assert.equal(trace.status,'interrupted');
});
test('maintenance blocks authenticated mutations and GET does not expire/write old leases',async t=>{
  const {store,env}=await setup(t),h=new Harness(store,{env,now:()=>1000}),worker_id=randomUUID();
  await h.poll({worker_id,mode:'live',tasks:['rooms']});await h.start('alice',{task:'rooms',goal:'Book'});
  const job=(await h.poll({worker_id,mode:'live',tasks:['rooms']})).job;
  const old=await store.read('daylight/harness/control-v1.json');
  const settings={...env,DAYLIGHT_STORAGE_MAINTENANCE:'1',DEMO_SESSION_SECRET:'s'.repeat(64),DEMO_INVITES_JSON:JSON.stringify({alice:digest('a'.repeat(43))})};
  const handler=createHandler({store,env:settings,fetcher:()=>{throw Error('No inference');}});
  const cookie=sessionCookie(login('a'.repeat(43),config(settings)));
  async function call(url,method='GET',extra={}){let status,body;await handler({url,method,headers:{host:'demo.example',origin:'https://demo.example',cookie,...extra},body:{}},{setHeader(){},set statusCode(v){status=v;},end(v){body=JSON.parse(v);}});return {status,body};}
  for(const url of ['/api/start','/api/step','/api/interrupt','/api/event','/api/harness/jobs','/storage-check'])assert.equal((await call(url,'POST')).status,503);
  assert.equal((await call('/api/harness/worker/poll','POST',{authorization:'Bearer '+worker})).status,503);
  assert.equal((await call('/api/harness/jobs')).body.jobs[0].status,'running');
  assert.equal((await call('/api/harness/jobs/'+job.id)).status,200);
  assert.deepEqual(await store.read('daylight/harness/control-v1.json'),old);
});
test('trace summaries use one remote request per page and preserve local projection/owner isolation',async t=>{
  const {store,env,origin}=await setup(t),local=new Agent(store,{env});
  const first=await local.start('alice',{mode:'assist',goal:'First question'});
  const row=await local.read('alice',first.id);row.value.status='complete';row.value.evaluation={task_completed:true,authorization_satisfied:false,safe_success:null};
  row.value.steps=[{dispatch_at:'2026-01-01T00:00:00Z',request:{private_payload:'large observation '.repeat(1000)},usage:{cost:.01}},{dispatch_at:'2026-01-01T00:00:01Z',usage:null}];
  await store.write('daylight/traces/alice/'+first.id+'.json',row.value,row.etag);
  await local.start('alice',{mode:'assist',goal:'Follow up',continuation_of:first.id});
  const foreign=await local.start('bob',{mode:'assist',goal:'Private other owner'});
  let calls=0;const remote=new RemoteStore({env:{...env,DAYLIGHT_CONTROL_URL:origin},fetcher:(...args)=>{calls++;return fetch(...args);}}),front=new Agent(remote,{env});
  const before=await store.read('daylight/traces/alice/'+first.id+'.json');
  let cursor,pages=0,seen=[];
  do{
    const options={limit:1,...(cursor?{cursor}:{})},actual=await front.list('alice',options);
    assert.deepEqual(actual,await local.list('alice',options));assert.equal(calls,++pages);
    assert.ok(!JSON.stringify(actual).includes('large observation'));assert.ok(!JSON.stringify(actual).includes(foreign.id));
    seen.push(...actual.traces);cursor=actual.has_more?actual.cursor:null;
  }while(cursor);
  assert.equal(seen.length,2);assert.equal(seen.find(x=>x.id===first.id).unknown_cost_attempts,1);
  assert.equal(seen.find(x=>x.id===first.id).evaluation.safe_success,null);
  assert.equal(seen.find(x=>x.id!==first.id).previous_trace_id,first.id);
  assert.deepEqual(await store.read('daylight/traces/alice/'+first.id+'.json'),before);
});
test('trace summary endpoint rejects bad owners and foreign/broken conversation links',async t=>{
  const {store,origin,env,remote}=await setup(t),local=new Agent(store,{env});
  const foreign=await local.start('bob',{mode:'assist',goal:'Secret'}),own=await local.start('alice',{mode:'assist',goal:'Public to Alice'});
  const saved=await local.read('alice',own.id);saved.value.continuation_of=foreign.id;await store.write('daylight/traces/alice/'+own.id+'.json',saved.value,saved.etag);
  assert.equal((await new Agent(remote).list('alice')).traces[0].previous_trace_id,null);
  for(const body of [{owner:'../bob'},{owner:'alice',limit:101},{owner:'alice',cursor:42}]){
    const r=await fetch(origin+'/internal/store/trace-list',{method:'POST',headers:{authorization:'Bearer '+secret},body:JSON.stringify(body)});assert.equal(r.status,400);
  }
  const r=await fetch(origin+'/internal/store/trace-list',{method:'POST',headers:{authorization:'Bearer '+worker},body:'{"owner":"alice"}'});assert.equal(r.status,401);
});
