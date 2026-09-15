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
  const {remote,store,env}=await setup(t),front=new Harness(remote,{env}),back=new Harness(store,{env}),worker_id=randomUUID();
  await back.poll({worker_id,mode:'live',tasks:['rooms']});
  const created=await front.start('alice',{task:'rooms',goal:'Book a room'});
  const job=(await back.poll({worker_id,mode:'live',tasks:['rooms']})).job;
  assert.equal(created.id,job.id);assert.equal((await front.list('bob')).jobs.length,0);
  const reserved=await back.reserve({...job,step:0,input_bytes:100,request_sha256:'a'.repeat(64)});
  const next=await new Agent(remote,{env}).reserve(.01);
  assert.equal(next.daily_reserved_usd,reserved.amount_usd+.01);
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
