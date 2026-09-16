import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm,mkdir,writeFile} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {randomUUID} from 'node:crypto';
import {createServer} from 'node:http';
import {once} from 'node:events';
import {Harness,TASKS} from '../lib/harness.mjs';
import {Agent} from '../lib/agent.mjs';
import {FileStore} from '../lib/store.mjs';
import {createHandler} from '../api/index.mjs';
import {digest} from '../lib/auth.mjs';
const env={HARNESS_WORKER_TOKEN:'w'.repeat(64),DEMO_SESSION_SECRET:'s'.repeat(64),DEMO_INVITES_JSON:JSON.stringify({one:digest('a'.repeat(43))})};
async function fixture(t) {
  const dir=await mkdtemp(path.join(os.tmpdir(),'daylight-activity-'));t.after(()=>rm(dir,{recursive:true,force:true}));
  const store=new FileStore(dir);return {dir,store,h:new Harness(store,{env})};
}
test('new harness activity is explicit and classification comes from the registry',async t=>{
  const {h}=await fixture(t);await h.poll({worker_id:randomUUID(),mode:'live',tasks:TASKS.map(t=>t.id),task_revisions:Object.fromEntries(TASKS.map(t=>[t.id,t.revision]))});
  const task=TASKS.find(t=>t.id==='tricky-p07-injected');
  const saved=await h.start('one',{task:task.id,interaction_kind:'task',task_name:'spoofed',task_revision:task.revision});
  assert.equal(saved.interaction_kind,'task');assert.equal(saved.site_id,'tricky-shop');assert.equal(saved.collection,'trickyarena');
  assert.equal(saved.task_name,task.title);assert.equal(saved.task_id,task.id);assert.equal(saved.task_revision,task.revision);
  assert.equal(saved.condition,task.condition);assert.equal(saved.site_name,'Shop');
  assert.equal(saved.evaluation,null);assert.equal(saved.mode,undefined);
  assert.equal((await h.list('one')).jobs[0].interaction_kind,'task');
  for(const body of [{interaction_kind:'ask'},{interaction_kind:'replay'},{site_id:'campus'},{collection:'demo'}])await assert.rejects(h.start('one',{task:task.id,...body}));
  const ask=await h.start('one',{task:'rooms',goal:TASKS[0].goal,interaction_kind:'ask'});
  assert.equal(ask.interaction_kind,'ask');assert.equal(ask.site_id,'campus');assert.equal(ask.collection,'demo');
  const omitted=await h.start('one',{task:'rooms',goal:TASKS[0].goal});assert.equal(omitted.interaction_kind,null);
  assert.equal((await h.list('other')).jobs.length,0);
});
test('old jobs retain unknown metadata without rewriting storage or inferring from goals',async t=>{
  const {h,store}=await fixture(t),id=randomUUID();
  const old={id,owner:'one',task:'rooms',goal:TASKS[0].goal,mode:'live',status:'finished',evaluation:{task_completed:false,authorization_satisfied:true,safe_success:null},trace_parts:[]};
  await store.write('daylight/harness/control-v1.json',{version:1,worker:null,active:null,jobs:{[id]:old}});
  const saved=await h.read('one',id);for(const field of ['interaction_kind','site_id','collection','task_name'])assert.equal(saved[field],null);
  assert.equal(saved.mode,'live');assert.deepEqual(saved.evaluation,old.evaluation);
  assert.deepEqual((await store.read('daylight/harness/control-v1.json')).value.jobs[id],old);
});
test('new client traces keep explicit Ask and known site without inventing a reviewed task',async t=>{
  const {store}=await fixture(t);const agent=new Agent(store,{env});
  const {id}=await agent.start('one',{mode:'assist',goal:'Find a room',interaction_kind:'ask',site_id:'campus',task_name:'forged',evaluation:{safe_success:true}});
  const raw=(await agent.read('one',id)).value;
  assert.equal(raw.interaction_kind,'ask');assert.equal(raw.site_id,'campus');assert.equal(raw.collection,'demo');
  assert.equal(raw.task_id,null);assert.equal(raw.task_name,null);assert.equal(raw.task_revision,null);assert.equal(raw.evaluation,null);
  const item=(await agent.list('one')).traces[0];assert.equal(item.interaction_kind,'ask');assert.equal(item.site_id,'campus');
  for(const body of [{interaction_kind:'task'},{interaction_kind:'replay'},{site_id:'tricky-shop'},{collection:'trickyarena'}])await assert.rejects(agent.start('one',{mode:'assist',goal:'Find',...body}));
});
test('legacy client traces keep unknown classification and all independent outcome fields',async t=>{
  const {store}=await fixture(t);const agent=new Agent(store,{env}),id=randomUUID();
  const evaluation={task_completed:false,authorization_satisfied:true,safe_success:null};
  const old={id,owner:'one',mode:'assist',goal:'Book a room',runtime:'daylight-client-demo-v1',status:'error',steps:[],evaluation};
  await store.write('daylight/traces/one/'+id+'.json',old);
  const item=(await agent.list('one')).traces[0];for(const key of ['interaction_kind','site_id','collection','task_name'])assert.equal(item[key],null);
  assert.deepEqual(item.evaluation,evaluation);assert.equal(item.status,'error');assert.deepEqual((await agent.read('one',id)).value,old);
  assert.equal((await agent.list('other')).traces.length,0);
});
test('workspace routes stay authenticated; old demo and harness remain distinct',async t=>{
  const {dir,store}=await fixture(t),assetRoot=path.join(dir,'assets');await mkdir(assetRoot);
  for(const [file,text] of Object.entries({'workspace.html':'workspace','index.html':'old demo','harness.html':'harness','workspace.js':'workspace script','workspace.css':'workspace style'}))await writeFile(path.join(assetRoot,file),text);
  const server=createServer(createHandler({store,env,assetRoot,local:true}));server.listen(0,'127.0.0.1');await once(server,'listening');t.after(()=>server.close());
  const origin='http://127.0.0.1:'+server.address().port;
  const routes={'/':'workspace','/workspace':'workspace','/workspace/replays':'workspace','/demo':'old demo','/harness':'harness','/assets/workspace.js':'workspace script','/assets/workspace.css':'workspace style'};
  for(const route of Object.keys(routes))assert.equal((await fetch(origin+route,{redirect:'manual'})).status,303);
  const login=await fetch(origin+'/login',{method:'POST',headers:{origin,'content-type':'application/json'},body:JSON.stringify({code:'a'.repeat(43)}),redirect:'manual'});
  const cookie=login.headers.get('set-cookie');assert.equal(login.status,303);
  for(const [route,text] of Object.entries(routes)){const r=await fetch(origin+route,{headers:{cookie}});assert.equal(r.status,200);assert.equal(await r.text(),text);assert.equal(r.headers.get('cache-control'),'private, no-store');}
  for(const route of ['/assets/team_sites.json','/private-assets/workspace.html','/workspace/unsupported'])assert.equal((await fetch(origin+route,{headers:{cookie}})).status,404);
});
test('live-required queued jobs survive a rehearsal worker and can later be claimed live',async t=>{
  const {h,store}=await fixture(t),worker_id=randomUUID();
  await h.poll({worker_id,mode:'live',tasks:['rooms']});
  const job=await h.start('one',{task:'rooms',goal:TASKS[0].goal,interaction_kind:'task',required_execution_mode:'live'});
  const before=(await store.read('daylight/harness/control-v1.json')).value.jobs[job.id];
  assert.equal(job.required_execution_mode,'live');
  assert.deepEqual(await h.poll({worker_id,mode:'rehearsal',tasks:['rooms']}),{job:null});
  assert.deepEqual((await store.read('daylight/harness/control-v1.json')).value.jobs[job.id],before);
  const prior=(await store.read('daylight/harness/control-v1.json')).etag;
  assert.deepEqual(await h.poll({worker_id,mode:'rehearsal',tasks:['rooms']}),{job:null});
  assert.equal((await store.read('daylight/harness/control-v1.json')).etag,prior);
  const claimed=await h.poll({worker_id,mode:'live',tasks:['rooms']});
  assert.equal(claimed.job.id,job.id);assert.equal(claimed.job.mode,'live');
  const saved=await h.read('one',job.id);assert.equal(saved.required_execution_mode,'live');assert.equal(saved.mode,'live');
});
test('mode mismatch does not block eligible legacy jobs and requirements reject invalid values',async t=>{
  const {h,store}=await fixture(t),worker_id=randomUUID();await h.poll({worker_id,mode:'live',tasks:['rooms']});
  const goal=TASKS[0].goal;
  for(const value of ['rehearsal','unknown',true,1,{}])await assert.rejects(h.start('one',{task:'rooms',goal,required_execution_mode:value}),/required execution mode/);
  const live=await h.start('one',{task:'rooms',goal,required_execution_mode:'live'});
  const legacy=await h.start('one',{task:'rooms',goal});assert.equal(legacy.required_execution_mode,null);
  const claimed=(await h.poll({worker_id,mode:'rehearsal',tasks:['rooms']})).job;
  assert.equal(claimed.id,legacy.id);assert.equal(claimed.mode,'rehearsal');
  const queued=await h.read('one',live.id);assert.equal(queued.status,'queued');assert.equal(queued.mode,undefined);
  assert.equal((await store.read('daylight/harness/control-v1.json')).value.jobs[live.id].reservations.length,0);
});
