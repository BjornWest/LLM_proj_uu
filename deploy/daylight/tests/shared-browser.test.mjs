import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,mkdir,writeFile,readFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {randomUUID} from 'node:crypto';
import {Manual,MANUAL_TASKS} from '../lib/manual.mjs';
import {SqliteStore} from '../lib/sqlite-store.mjs';
const gate=()=>{let release;return {promise:new Promise(r=>release=r),release:(...args)=>release(...args)};};
const reply=action=>new Response(JSON.stringify({id:randomUUID(),model:'qwen',provider:'Parasail',usage:{cost:0.0001},choices:[{message:{content:JSON.stringify({action})}}]}),{status:200});
async function setup(t,{fetcher=async()=>reply('send_msg_to_user("Answer")'),driverHook,browse=false,pool}={}){
 const root=await mkdtemp(tmpdir()+'/shared-browser-'),store=new SqliteStore(root+'/store.sqlite');
 await mkdir(root+'/package/runtime/config',{recursive:true});
 await writeFile(root+'/package/manifest.json',JSON.stringify({datasets:[{tasks:MANUAL_TASKS.map(t=>t.id)}]}));
 await writeFile(root+'/package/runtime/config/team_tasks.json',JSON.stringify({tasks:MANUAL_TASKS}));
 const env={DAYLIGHT_MANUAL_ROOT:root+'/sessions',DAYLIGHT_MANUAL_PACKAGE:root+'/package',DAYLIGHT_MANUAL_DRIVER:'fake',OPENROUTER_API_KEY:'test-only',DEMO_DAILY_BUDGET_USD:'1'};
 const calls=[],drivers=[];
 if(browse)env.DAYLIGHT_BROWSE_ENABLED='1';
 const manual=new Manual(store,{env,pool,fetcher:async(...args)=>{calls.push(args);return fetcher(...args);},driverFactory:({directory})=>{
  const state=()=>({trace_directory:directory,reference_goal:'PRIVILEGED REFERENCE MUST NOT LEAK',action_count:driver.count,frame:{id:randomUUID(),width:800,height:600,page_url:'http://local',artifact:{screenshot:'frame.png'}}});
  const driver={count:0,commands:[],async ready(){await writeFile(directory+'/frame.png','image');return {kind:'ready',...state()};},
   async send(command){driver.commands.push(command);if(driverHook)await driverHook(command);
    const result={kind:'result',request_id:command.request_id,...state()};
    if(command.operation==='agent_observe')result.decision={id:randomUUID(),observation:{text:'obs.txt'},messages:[{role:'user',content:command.goal+' fresh page'}]};
    if(command.operation==='agent_action'){
      const a=JSON.parse(command.evidence.output).action;
      if(a.startsWith('send_msg_to_user'))result.answer='Answer';else{driver.count++;result.action_count=driver.count;}
    }
    if(command.operation==='action'){driver.count++;result.action_count=driver.count;}
    return result;
   },kill(){driver.killed=true;}};
  drivers.push(driver);return driver;
 }});
 t.after(async()=>{for(const l of manual.live.values())if(l.work)await l.work;manual.shutdown();store.close();await rm(root,{recursive:true,force:true});});
 const task=MANUAL_TASKS.find(t=>t.id==='tricky-p11-clean');const session=await manual.start('alice',{task:browse?'browse.webarena-shopping':task.id,site_revision:task.site_revision});
 return {manual,session,drivers,calls,env,store,root,async finish(){await manual.live.get(session.id)?.work;return manual.read('alice',session.id);},async evidence(id){return JSON.parse(await readFile(root+'/sessions/'+session.id+'/ask-'+id+'.json'));}};
}
test('same browser action, answer, human takeover and follow-up; exact request evidence and shared budget',async t=>{
 let n=0;const s=await setup(t,{fetcher:async()=>reply(++n===1?'click("7")':'send_msg_to_user("Answer")')});
 const req={request_id:randomUUID(),goal:'Inspect this page'};
 const row=await s.manual.ask('alice',s.session.id,req);assert.equal(row.controller,'agent');assert.equal(row.status,'busy');
 const done=await s.finish();assert.equal(done.status,'ready');assert.equal(done.controller,'human');assert.equal(done.asks[0].answer,'Answer');assert.equal(done.evaluation,null);assert.equal(s.drivers.length,1);assert.equal(done.action_count,1);
 const record=await s.evidence(req.request_id);assert.equal(record.steps.length,2);assert.equal(record.steps[0].result.action_count,1);
 for(const [url,options]of s.calls){const request=JSON.parse(options.body);assert.equal(request.session_id,s.session.id);assert.equal(request.max_tokens,4096);assert.deepEqual(request.reasoning,{enabled:true});assert(!options.body.includes('PRIVILEGED'));}
 assert.equal(record.steps[0].request.session_id,s.session.id);assert.equal(record.steps[0].usage.cost,0.0001);assert(record.steps[0].reservation);
 await s.manual.command('alice',s.session.id,'action',{request_id:randomUUID(),frame_id:done.frame.id,action:{type:'press',key:'Tab'}});
 await s.manual.ask('alice',s.session.id,{request_id:randomUUID(),goal:'Now explain'});await s.finish();assert.equal(s.drivers.length,1);assert.equal(s.drivers[0].count,2);
});
test('busy control, ownership and duplicate ask IDs block all extra dispatch',async t=>{
 const waiting=gate(),started=gate();const s=await setup(t,{fetcher:async()=>{started.release();await waiting.promise;return reply('send_msg_to_user("Answer")');}});
 const req={request_id:randomUUID(),goal:'Question'};await s.manual.ask('alice',s.session.id,req);await started.promise;
 for(const op of ['action','observe','close'])await assert.rejects(s.manual.command('alice',s.session.id,op,{request_id:randomUUID(),frame_id:s.session.frame.id}),{status:409});
 await s.manual.ask('alice',s.session.id,req);assert.equal(s.calls.length,1);
 await assert.rejects(s.manual.ask('bob',s.session.id,{request_id:randomUUID(),goal:'Bad'}),{status:404});
 await assert.rejects(s.manual.ask('alice',s.session.id,{...req,goal:'Changed'}),{status:409});
 await assert.rejects(s.manual.ask('alice',s.session.id,{request_id:randomUUID(),goal:'Another'}),{status:409});
 waiting.release();await s.finish();
});
test('interrupt invalidates late model result, retains cost and exact response, never executes or resurrects',async t=>{
 const waiting=gate(),started=gate();const s=await setup(t,{fetcher:async()=>{started.release();await waiting.promise;return reply('click("7")');}});
 const req={request_id:randomUUID(),goal:'Click'};await s.manual.ask('alice',s.session.id,req);await started.promise;
 await s.manual.interrupt('alice',s.session.id,{ask_id:req.request_id});waiting.release();const row=await s.finish();
 assert.equal(row.status,'ready');assert.equal(row.asks[0].status,'interrupted');assert.equal(row.action_count,0);assert(!s.drivers[0].commands.some(c=>c.operation==='agent_action'));
 const saved=await s.evidence(req.request_id);assert.equal(saved.steps[0].usage.cost,0.0001);assert(saved.steps[0].response_text);assert(saved.steps[0].reservation);assert.equal(s.calls.length,1);
});
test('interrupt waits for already dispatched browser action and retains its receipt without replay',async t=>{
 const held=gate(),started=gate();const s=await setup(t,{fetcher:async()=>reply('click("7")'),driverHook:async c=>{if(c.operation==='agent_action'){started.release();await held.promise;}}});
 const req={request_id:randomUUID(),goal:'Click'};await s.manual.ask('alice',s.session.id,req);await started.promise;
 await s.manual.interrupt('alice',s.session.id,{ask_id:req.request_id});assert.equal((await s.manual.read('alice',s.session.id)).controller,'agent');
 held.release();const row=await s.finish();assert.equal(row.action_count,1);assert.equal(row.asks[0].status,'interrupted');assert.equal(row.asks[0].steps[0].executed,true);assert.equal(s.calls.length,1);
});
test('transport error preserves unknown cost and reservation; no retry, browser stays available',async t=>{
 const s=await setup(t,{fetcher:async()=>{throw Error('timeout');}}),id=randomUUID();
 await s.manual.ask('alice',s.session.id,{request_id:id,goal:'Question'});const row=await s.finish();assert.equal(row.status,'ready');assert.equal(row.asks[0].status,'error');assert.equal(row.asks[0].unknown_cost_attempts,1);
 const saved=await s.evidence(id);assert(saved.steps[0].request);assert(saved.steps[0].reservation);assert.equal(s.calls.length,1);assert.equal(row.action_count,0);
});
test('budget rejects before network; uncertainty during browser dispatch closes instead of replaying',async t=>{
 const s=await setup(t);s.env.DEMO_DAILY_BUDGET_USD='0.000001';await s.manual.ask('alice',s.session.id,{request_id:randomUUID(),goal:'Question'});assert.equal((await s.finish()).asks[0].status,'error');assert.equal(s.calls.length,0);
 s.env.DEMO_DAILY_BUDGET_USD='1';s.drivers[0].send=async()=>{throw Error('pipe broken');};await s.manual.ask('alice',s.session.id,{request_id:randomUUID(),goal:'Question'});await new Promise(r=>setTimeout(r,20));const row=await s.manual.read('alice',s.session.id);assert.equal(row.status,'interrupted');assert(s.drivers[0].killed);
});
test('failed durable Ask claim sends no browser or model request',async t=>{
 const s=await setup(t),write=s.store.write.bind(s.store);s.store.write=async()=>{throw Error('disk');};await assert.rejects(s.manual.ask('alice',s.session.id,{request_id:randomUUID(),goal:'Question'}));assert.equal(s.drivers[0].commands.length,0);assert.equal(s.calls.length,0);s.store.write=write;
});
test('abort-aware HTTP failure retains dispatch/reservation and releases control without model action',async t=>{
 const started=gate();const s=await setup(t,{fetcher:async(url,{signal})=>{started.release();return new Promise((resolve,reject)=>{signal.addEventListener('abort',()=>reject(Error('aborted')),{once:true});});}});
 const id=randomUUID();await s.manual.ask('alice',s.session.id,{request_id:id,goal:'Wait'});await started.promise;await s.manual.interrupt('alice',s.session.id,{ask_id:id});
 const row=await s.finish(),saved=await s.evidence(id);assert.equal(row.controller,'human');assert.equal(row.asks[0].status,'interrupted');assert.equal(row.asks[0].unknown_cost_attempts,1);assert(saved.steps[0].dispatch_at);assert(saved.steps[0].reservation);assert.equal(row.action_count,0);
});
test('full 12-step cap and session action cap do not silently restart or retry',async t=>{
 const s=await setup(t,{fetcher:async()=>reply('click("7")')});await s.manual.ask('alice',s.session.id,{request_id:randomUUID(),goal:'Continue'});
 const row=await s.finish();assert.equal(row.asks[0].status,'step_limit');assert.equal(s.calls.length,12);assert.equal(row.action_count,12);assert.equal(s.drivers.length,1);
 const saved=await s.store.read('daylight/manual/'+row.id+'.json');saved.value.action_count=100;await s.store.write('daylight/manual/'+row.id+'.json',saved.value,saved.etag);
 await assert.rejects(s.manual.ask('alice',row.id,{request_id:randomUUID(),goal:'More'}),{status:429});assert.equal(s.calls.length,12);
});
test('native driver finalization exports late caller evidence from current originals',async t=>{
 const s=await setup(t,{fetcher:async()=>reply('click("7")')});s.env.DAYLIGHT_MANUAL_PYTHON='python3';
 const send=s.drivers[0].send.bind(s.drivers[0]);s.drivers[0].send=async c=>{
  const result=await send(c);
  if(c.operation==='agent_action'){await writeFile(s.root+'/sessions/'+s.session.id+'/trace.zip','old archive');return {...result,kind:'finished',archive:s.root+'/sessions/'+s.session.id+'/trace.zip',error:'Native browser error',reference_evaluation:{safe_success:null}};}
  return result;
 };
 const id=randomUUID();await s.manual.ask('alice',s.session.id,{request_id:id,goal:'Click'});const work=s.manual.live.get(s.session.id).work;await work;
 const row=await s.manual.read('alice',s.session.id);assert.equal(row.status,'error');assert.equal(row.asks[0].status,'error');assert.equal(row.evaluation,null);
 // Fake driver uses the session root as trace directory; real driver uses runs/id.
 // Enforce the stricter nested directory used by production exports.
 const record=await s.store.read('daylight/manual/'+row.id+'.json'),traceDir=s.root+'/sessions/'+row.id+'/runs/episode';await mkdir(traceDir,{recursive:true});
 await writeFile(traceDir+'/ask-'+id+'.json',JSON.stringify(await s.evidence(id)));record.value.trace_directory=traceDir;await s.store.write('daylight/manual/'+row.id+'.json',record.value,record.etag);
 const meta=await s.manual.artifact('alice',row.id);assert(meta.size>0);const data=await s.manual.artifact('alice',row.id,null,0);assert.equal(Buffer.from(data.data,'base64').subarray(0,2).toString(),'PK');
});
test('service restart does not leave a dead session claiming agent control',async t=>{
 const s=await setup(t),saved=await s.store.read('daylight/manual/'+s.session.id+'.json');
 saved.value.controller='agent';saved.value.status='busy';saved.value.process_token='previous-process';saved.value.asks=[{id:randomUUID(),goal:'Old request',status:'running'}];
 await s.store.write('daylight/manual/'+s.session.id+'.json',saved.value,saved.etag);
 const row=await s.manual.read('alice',s.session.id);assert.equal(row.controller,'human');assert.equal(row.status,'interrupted');assert.equal(row.asks[0].status,'interrupted');assert.equal(s.calls.length,0);
});
test('answer may explain an earlier action error without misattributing it to this reply',async t=>{
 const s=await setup(t),send=s.drivers[0].send.bind(s.drivers[0]);s.drivers[0].send=async c=>({...await send(c),last_error:'Old click failed'});
 await s.manual.ask('alice',s.session.id,{request_id:randomUUID(),goal:'What happened?'});const row=await s.finish();assert.equal(row.asks[0].status,'complete');assert.equal(row.asks[0].error,null);assert.equal(row.asks[0].answer,'Answer');
});

test('generic Ask retains the same exclusive lease and null grades; uncertain command releases once',async t=>{
 let acquired=0,released=0;const pool={async status(){return {sites:[{site_id:'webarena-shopping',status:'ready'}]};},async acquire(){acquired++;return {lease_token:'lease-secret',site_id:'webarena-shopping',origin:'http://private.local'};},async release(){released++;}};
 const s=await setup(t,{browse:true,pool});assert(s.session.ask_enabled);assert(s.session.browse_only);
 await s.manual.ask('alice',s.session.id,{request_id:randomUUID(),goal:'Question'});const done=await s.finish();
 assert.equal(done.asks[0].status,'complete');assert.equal(done.evaluation,null);assert.equal(done.reference_goal,null);assert.equal(acquired,1);assert.equal(released,0);assert.equal(s.drivers.length,1);assert(!JSON.stringify(done).includes('lease-secret'));assert(!JSON.stringify(s.calls).includes('lease-secret'));
 s.drivers[0].send=async()=>{throw Error('uncertain browser pipe');};await s.manual.ask('alice',s.session.id,{request_id:randomUUID(),goal:'Question again'});const work=s.manual.live.get(s.session.id).work;await work;
 const failed=await s.manual.read('alice',s.session.id);assert.equal(failed.status,'interrupted');assert.equal(failed.asks[1].status,'error');assert.equal(released,1);assert.equal(s.calls.length,1);assert.equal(s.manual.live.size,0);
});
test('historical explicitly disabled Ask is not silently enabled',async t=>{
 const s=await setup(t),saved=await s.store.read('daylight/manual/'+s.session.id+'.json');saved.value.ask_enabled=false;saved.value.browse_only=true;await s.store.write('daylight/manual/'+s.session.id+'.json',saved.value,saved.etag);
 await assert.rejects(s.manual.ask('alice',s.session.id,{request_id:randomUUID(),goal:'Question'}),{status:409});assert.equal(s.calls.length,0);
});
