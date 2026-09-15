import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm,mkdir,writeFile,symlink} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {randomUUID} from 'node:crypto';
import {Manual,MANUAL_TASKS} from '../lib/manual.mjs';
import {SqliteStore} from '../lib/sqlite-store.mjs';
import {createServer} from 'node:http';
import {controlHandler} from '../control-server.mjs';
import {createHandler} from '../api/index.mjs';
import {digest,login,config,sessionCookie} from '../lib/auth.mjs';

async function setup(t){
  const root=await mkdtemp(tmpdir()+'/manual-test-'),store=new SqliteStore(root+'/state.sqlite');
  await mkdir(root+'/package/runtime/config',{recursive:true});await writeFile(root+'/package/runtime/config/team_tasks.json',JSON.stringify({tasks:MANUAL_TASKS}));await writeFile(root+'/package/manifest.json',JSON.stringify({datasets:[{tasks:MANUAL_TASKS.map(t=>t.id)}]}));
  const env={DAYLIGHT_MANUAL_ROOT:root+'/sessions',DAYLIGHT_MANUAL_PACKAGE:root+'/package',DAYLIGHT_MANUAL_DRIVER:'offline-fake'};
  const drivers=[];let gate=null,fail=false;
  const make=({directory})=>{
    const state=()=>({trace_directory:directory,reference_goal:'Exact reference goal',action_count:driver.count,
      frame:{id:randomUUID(),width:1280,height:720,page_url:'http://fixture.local',artifact:{screenshot:'frame.png'}}});
    const driver={count:0,sends:[],killed:false,async ready(){await writeFile(directory+'/frame.png','png');return {kind:'ready',...state()};},
      async send(value){driver.sends.push(value);if(gate)await gate;if(fail)throw Error('transport failed');
        if(value.operation==='action')driver.count++;
        if(value.operation==='close'){await writeFile(directory+'/trace.zip',Buffer.alloc(1048576+23,17));return {kind:'finished',request_id:value.request_id,...state(),archive:directory+'/trace.zip',reference_evaluation:{safe_success:null},stop_reason:'user_close'};}
        return {kind:'result',request_id:value.request_id,...state()};},kill(){driver.killed=true;}};
    drivers.push(driver);return driver;
  };
  const manual=new Manual(store,{env,driverFactory:make});
  t.after(async()=>{manual.shutdown();store.close();await rm(root,{recursive:true,force:true});});
  return {manual,store,env,root,drivers,hold(p){gate=p;},fail(){fail=true;}};
}
const request=(frame,action={type:'click',x:10,y:10})=>({request_id:randomUUID(),frame_id:frame.id,action});

test('manual ownership, durable one-dispatch claims, stale frame and payload collision rejection',async t=>{
  const {manual,store,drivers}=await setup(t),first=await manual.start('alice',{task:'tricky-p11-clean',site_revision:MANUAL_TASKS.find(t=>t.id==='tricky-p11-clean').site_revision});
  assert.equal(first.evaluation,null);assert.equal(first.interaction_kind,'manual');
  assert(!('directory' in first));assert(!('owner' in first));
  await assert.rejects(manual.read('bob',first.id),{status:404});assert.equal((await manual.list('bob')).sessions.length,0);
  const value=request(first.frame),next=await manual.command('alice',first.id,'action',value);
  const claim=(await store.read('daylight/manual/'+first.id+'.json')).value.commands[0];assert.equal(claim.status,'complete');
  await manual.command('alice',first.id,'action',value);assert.equal(drivers[0].sends.length,1);
  await assert.rejects(manual.command('alice',first.id,'action',{...value,action:{type:'click',x:11,y:10}}),{status:409});
  await assert.rejects(manual.command('alice',first.id,'action',request(first.frame)),{status:409});assert.equal(drivers[0].sends.length,1);
  assert.notEqual(next.frame.id,first.frame.id);
  assert.equal((await store.listKeys('daylight/budget')).keys.length,0);
});
test('pending command is persisted and blocks duplicate/new dispatch and owner replacement',async t=>{
  const s=await setup(t),first=await s.manual.start('alice',{task:'tricky-p11-clean',site_revision:MANUAL_TASKS.find(t=>t.id==='tricky-p11-clean').site_revision});
  let release;s.hold(new Promise(r=>release=r));const value=request(first.frame),pending=s.manual.command('alice',first.id,'action',value);
  while(!s.drivers[0].sends.length)await new Promise(r=>setTimeout(r,1));
  assert.equal((await s.store.read('daylight/manual/'+first.id+'.json')).value.commands[0].status,'pending');
  for(const v of [value,request(first.frame)])await assert.rejects(s.manual.command('alice',first.id,'action',v),{status:409});
  await assert.rejects(s.manual.start('alice',{task:'tricky-p11-clean',site_revision:MANUAL_TASKS.find(t=>t.id==='tricky-p11-clean').site_revision}),{status:409});
  release();await pending;assert.equal(s.drivers[0].sends.length,1);
});
test('uncertain driver failure is terminal, keeps claim and never replays',async t=>{
  const s=await setup(t),first=await s.manual.start('alice',{task:'tricky-p11-clean',site_revision:MANUAL_TASKS.find(t=>t.id==='tricky-p11-clean').site_revision}),value=request(first.frame);s.fail();
  await assert.rejects(s.manual.command('alice',first.id,'action',value),{status:503});
  assert.equal((await s.manual.read('alice',first.id)).status,'interrupted');
  assert.equal(s.drivers[0].killed,true);await assert.rejects(s.manual.command('alice',first.id,'action',value),{status:409});
  assert.equal(s.drivers[0].sends.length,1);assert.equal((await s.store.read('daylight/manual/'+first.id+'.json')).value.commands[0].status,'pending');
});
test('failed durable claim never reaches browser; service restart never resumes an old browser',async t=>{
  const s=await setup(t),first=await s.manual.start('alice',{task:'tricky-p11-clean',site_revision:MANUAL_TASKS.find(t=>t.id==='tricky-p11-clean').site_revision}),write=s.store.write.bind(s.store);
  s.store.write=async()=>{throw Error('disk unavailable');};await assert.rejects(s.manual.command('alice',first.id,'action',request(first.frame)),{status:503});
  assert.equal(s.drivers[0].sends.length,0);s.store.write=write;
  const other=new Manual(s.store,{env:s.env,driverFactory:()=>{throw Error('Must not start');}});t.after(()=>other.shutdown());
  const row=await other.read('alice',first.id);assert.equal(row.status,'interrupted');assert.equal(row.evaluation,null);
});
test('two-browser cap, failed setup releases reservation, private immutable frame and chunked archive',async t=>{
  const s=await setup(t),a=await s.manual.start('alice',{task:'tricky-p11-clean',site_revision:MANUAL_TASKS.find(t=>t.id==='tricky-p11-clean').site_revision}),b=await s.manual.start('bob',{task:'tricky-p11-clean',site_revision:MANUAL_TASKS.find(t=>t.id==='tricky-p11-clean').site_revision});
  await assert.rejects(s.manual.start('carol',{task:'tricky-p11-clean',site_revision:MANUAL_TASKS.find(t=>t.id==='tricky-p11-clean').site_revision}),{status:429});
  await assert.rejects(s.manual.artifact('bob',a.id,a.frame.id),{status:404});
  assert.equal(Buffer.from((await s.manual.artifact('alice',a.id,a.frame.id)).data,'base64').toString(),'png');
  const closed=await s.manual.command('alice',a.id,'close',{request_id:randomUUID()});assert.equal(closed.trace_ready,true);assert(!('archive' in closed));
  const meta=await s.manual.artifact('alice',a.id);assert.deepEqual(meta,{size:1048599,parts:2});
  const parts=await Promise.all([0,1].map(part=>s.manual.artifact('alice',a.id,null,part)));
  assert.equal(Buffer.concat(parts.map(p=>Buffer.from(p.data,'base64'))).length,meta.size);
  await assert.rejects(s.manual.artifact('alice',a.id,null,2),{status:400});
  await rm(s.env.DAYLIGHT_MANUAL_ROOT,{recursive:true,force:true});await writeFile(s.env.DAYLIGHT_MANUAL_ROOT,'file');
  await assert.rejects(s.manual.start('carol',{task:'tricky-p11-clean',site_revision:MANUAL_TASKS.find(t=>t.id==='tricky-p11-clean').site_revision}),{status:503});assert.equal(s.manual.reserved,0);
});
test('artifact symlink cannot escape a private session directory',async t=>{
  const s=await setup(t),row=await s.manual.start('alice',{task:'tricky-p11-clean',site_revision:MANUAL_TASKS.find(t=>t.id==='tricky-p11-clean').site_revision});
  const file=s.env.DAYLIGHT_MANUAL_ROOT+'/'+row.id+'/frame.png';await rm(file);await symlink(s.root+'/state.sqlite',file);
  await assert.rejects(s.manual.artifact('alice',row.id,row.frame.id),{status:404});
});
test('actual authenticated proxy derives owner, rejects foreign origin and cannot use worker token for manual RPC',async t=>{
  const s=await setup(t),token='c'.repeat(64),worker='w'.repeat(64);
  const env={DAYLIGHT_CONTROL_TOKEN:token,HARNESS_WORKER_TOKEN:worker,DEMO_SESSION_SECRET:'s'.repeat(64),DEMO_INVITES_JSON:JSON.stringify({alice:digest('a'.repeat(43)),bob:digest('b'.repeat(43))})};
  // Config disabled, but owner checks against existing persisted sessions use actual service.
  const control=controlHandler({store:s.store,env}),server=createServer(control);await new Promise(r=>server.listen(0,'127.0.0.1',r));
  t.after(async()=>{control.shutdown();server.closeAllConnections();await new Promise(r=>server.close(r));});
  env.DAYLIGHT_CONTROL_URL='http://127.0.0.1:'+server.address().port;
  const row=await s.manual.start('alice',{task:'tricky-p11-clean',site_revision:MANUAL_TASKS.find(t=>t.id==='tricky-p11-clean').site_revision});await s.manual.command('alice',row.id,'close',{request_id:randomUUID()});
  const handler=createHandler({store:s.store,env,local:true});
  async function call(owner,url,method='GET',body={},origin='http://example.test'){
    let status,value;await handler({url,method,body,headers:{host:'example.test',origin,cookie:sessionCookie(login((owner==='alice'?'a':'b').repeat(43),config(env)),true)}},
      {setHeader(){},set statusCode(v){status=v;},end(v){value=JSON.parse(v);}});return {status,value};
  }
  assert.equal((await call('alice','/api/manual/sessions/'+row.id)).status,200);
  assert.equal((await call('bob','/api/manual/sessions/'+row.id)).status,404);
  assert.equal((await call('bob','/api/manual/sessions/'+row.id+'/close','POST',{owner:'alice',request_id:randomUUID()})).status,404);
  assert.equal((await call('alice','/api/manual/sessions','POST',{},'https://foreign.test')).status,403);
  assert.equal((await fetch(env.DAYLIGHT_CONTROL_URL+'/internal/manual/list',{method:'POST',headers:{authorization:'Bearer '+worker},body:'{}'})).status,401);
});
test('manual history exhausts storage pages and preserves owner filtering',async t=>{
  const s=await setup(t),ids=[randomUUID(),randomUUID()],original=s.store.listKeys.bind(s.store);
  for(const [i,id]of ids.entries())await s.store.write('daylight/manual/'+id+'.json',{id,owner:'alice',status:'finished',created_at:'2026-09-15T00:00:0'+i+'Z'});
  let page=0;s.store.listKeys=async()=>({keys:['daylight/manual/'+ids[page++]+'.json'],has_more:page===1,cursor:page===1?'second':null});
  assert.deepEqual((await s.manual.list('alice')).sessions.map(s=>s.id),[ids[1],ids[0]]);assert.equal(page,2);s.store.listKeys=original;
});
test('action cap rejects before dispatch and still allows explicit close',async t=>{
  const s=await setup(t),row=await s.manual.start('alice',{task:'tricky-p11-clean',site_revision:MANUAL_TASKS.find(t=>t.id==='tricky-p11-clean').site_revision}),saved=await s.store.read('daylight/manual/'+row.id+'.json');
  saved.value.action_count=100;await s.store.write('daylight/manual/'+row.id+'.json',saved.value,saved.etag);
  await assert.rejects(s.manual.command('alice',row.id,'action',request(row.frame)),{status:429});assert.equal(s.drivers[0].sends.length,0);
  assert.equal((await s.manual.command('alice',row.id,'close',{request_id:randomUUID()})).status,'finished');
});
test('manual client version mismatch refuses a browser before any dispatch',async t=>{
 const s=await setup(t),task=MANUAL_TASKS.find(t=>t.site_revision);
 for(const site_revision of [undefined,'old'])await assert.rejects(s.manual.start('alice',{task:task.id,site_revision}),/versions differ/);
 assert.equal(s.drivers.length,0);assert.equal((await s.manual.list('alice')).sessions.length,0);
 await writeFile(s.root+'/package/runtime/config/team_tasks.json',JSON.stringify({tasks:[]}));
 assert.equal((await s.manual.config()).enabled,false);
});
test('new frontend refuses an old control service before starting a mismatched browser',async t=>{
 const calls=[];
 const server=createServer((req,res)=>{calls.push(req.url);res.setHeader('content-type','application/json');res.end(JSON.stringify({enabled:true,sites:[{tasks:[{id:'tricky-p11-clean'}]}]}));});
 await new Promise(r=>server.listen(0,'127.0.0.1',r));t.after(()=>new Promise(r=>server.close(r)));
 const env={DEMO_SESSION_SECRET:'s'.repeat(64),DEMO_INVITES_JSON:JSON.stringify({alice:digest('a'.repeat(43))}),DAYLIGHT_CONTROL_URL:'http://127.0.0.1:'+server.address().port,DAYLIGHT_CONTROL_TOKEN:'c'.repeat(64)};
 const handler=createHandler({env,local:true});let status,text;
 await handler({method:'POST',url:'/api/manual/sessions',body:{task:'tricky-p11-clean'},headers:{host:'example.test',origin:'http://example.test',cookie:sessionCookie(login('a'.repeat(43),config(env)),true)}},
 {setHeader(){},set statusCode(v){status=v;},end(v){text=v;}});
 assert.equal(status,409);assert.match(text,/site versions differ/);assert.deepEqual(calls,['/internal/manual/config']);
});
