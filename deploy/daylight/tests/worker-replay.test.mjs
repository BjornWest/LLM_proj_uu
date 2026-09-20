import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,readFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {createServer} from 'node:http';
import {WorkerReplay} from '../lib/worker-replay.mjs';
import {TraceLibrary} from '../lib/library.mjs';
import {SqliteStore} from '../lib/sqlite-store.mjs';
import {controlHandler} from '../control-server.mjs';
import {createHandler} from '../api/index.mjs';
import {config,digest,login} from '../lib/auth.mjs';
const id='11111111-1111-4111-a111-111111111111',hash=x=>createHash('sha256').update(x).digest('hex');
async function fixture(t){
 const root=await mkdtemp(tmpdir()+'/worker-replay-test-');t.after(()=>rm(root,{recursive:true,force:true}));
 const store=new SqliteStore(root+'/state.sqlite');t.after(()=>store.close());
 execFileSync('python3',['-c',`import json,zipfile,sys
with zipfile.ZipFile(sys.argv[1],'w') as z:
 for name,value in {'metadata.json':json.dumps({'episode_id':'episode','browsergym_version':'test'}),'episode.json':'{}','events.jsonl':'','evaluation.json':'{"safe_success":null}', 'steps.jsonl':json.dumps({'step':0,'model_response':{'choices':[{'finish_reason':'tool_calls','message':{'content':'','reasoning':'retained reasoning'}}]},'error':'Expected exactly one native tool call','browser_stepped':False,'observation':{'text':'observation-000.txt','screenshot':'observation-000.png'}})+'\\n','observation-000.txt':'Recorded page','observation-000.png':'saved image bytes'}.items(): z.writestr('episode/'+name,value)
`,root+'/trace.zip']);
 const raw=await readFile(root+'/trace.zip'),name='trace-000.part';
 const job={id,owner:'alice',status:'error',task:'webarena:145',goal:'Recorded goal',mode:'live',artifacts:{[name]:{sha256:hash(raw)}},trace_parts:[name],evaluation:{safe_success:null},error:'Missing action'};
 const state={version:1,jobs:{[id]:job},worker:null,active:null};
 await store.write('daylight/harness/control-v1.json',state);
 await store.write(`daylight/harness/artifacts/${id}/${name}.json`,{sha256:hash(raw),data:raw.toString('base64')});
 const env={DAYLIGHT_LIBRARY_ROOT:root+'/library',DAYLIGHT_CONTROL_TOKEN:'c'.repeat(64),HARNESS_WORKER_TOKEN:'w'.repeat(64),DEMO_SESSION_SECRET:'s'.repeat(64),DEMO_INVITES_JSON:JSON.stringify({alice:digest('alice-code'.repeat(5)),bob:digest('bob-code'.repeat(5))})};
 return {root,store,env,job,state,raw};
}
test('finished worker projection preserves raw malformed response, null verdict, owner scope, cache and no duplicate catalog entry',async t=>{
 const {root,store,env,job,state}=await fixture(t),replay=new WorkerReplay(store,{env,root:root+'/library'});
 const before=await store.read('daylight/harness/control-v1.json');
 const [a,b]=await Promise.all([replay.session('alice',id),replay.session('alice',id)]);
 assert.deepEqual(a,b);const session=JSON.parse(a.raw);assert.equal(session.id,id);assert.equal(session.library_metadata.site_id,null);assert.equal(session.library_metadata.evaluation.safe_success,null);
 const response=session.messages.find(m=>m.title==='Raw model response');assert.equal(JSON.parse(response.text).choices[0].message.reasoning,'retained reasoning');assert.equal(session.worker_trace.error,'Missing action');
 assert.deepEqual(await store.read('daylight/harness/control-v1.json'),before);
 assert.equal((await new TraceLibrary(store,{root:root+'/library'}).list('alice')).sessions.length,0);
 replay.build=()=>{throw Error('Cached projection must not rebuild');};assert.equal((await replay.session('alice',id)).etag,a.etag);
 await assert.rejects(replay.session('bob',id),{status:404});
 const asset=session.messages.flatMap(m=>m.attachments||[])[0];assert(asset);const key=asset.url.split('/').at(-1);
 assert.equal((await replay.asset('alice',id,key)).status,200);await assert.rejects(replay.asset('bob',id,key),{status:404});
 job.status='running';await store.write('daylight/harness/control-v1.json',state,before.etag);
 await assert.rejects(replay.session('alice',id),{status:409});
});
test('authenticated Vercel handler -> PC projection and assets: no inference, conditional owner checks, read-only routes',async t=>{
 const {store,env}=await fixture(t),block=()=>{throw Error('No inference permitted');};
 const handler=controlHandler({store,env,fetcher:block}),back=createServer(handler);await new Promise(r=>back.listen(0,'127.0.0.1',r));env.DAYLIGHT_CONTROL_URL='http://127.0.0.1:'+back.address().port;
 const front=createServer(createHandler({env,local:true}));await new Promise(r=>front.listen(0,'127.0.0.1',r));
 t.after(async()=>{handler.shutdown();for(const server of [front,back]){server.closeAllConnections();await new Promise(r=>server.close(r));}});
 const origin='http://127.0.0.1:'+front.address().port,route=`/api/harness/jobs/${id}/session`;
 const get=(url,who='alice',headers={})=>fetch(origin+url,{headers:{cookie:'daylight_session='+login((who+'-code').repeat(5),config(env)),...headers},redirect:'manual'});
 assert.equal((await fetch(origin+route)).status,401);
 const response=await get(route);assert.equal(response.status,200);const etag=response.headers.get('etag'),session=await response.json();
 assert.equal((await get(route,'alice',{'if-none-match':etag})).status,304);assert.equal((await get(route,'bob',{'if-none-match':etag})).status,404);
 const asset=session.messages.flatMap(m=>m.attachments||[])[0].url;
 assert.equal((await get(asset)).status,200);assert.equal((await get(asset,'bob')).status,404);assert.equal((await get(asset,'alice',{range:'bytes=0-2'})).status,206);
 assert.equal((await fetch(origin+route,{method:'POST',headers:{cookie:'daylight_session='+login('alice-code'.repeat(5),config(env)),origin},body:'{}'})).status,405);
});

test('nested helpers have separate owner-scoped views and assets without inheriting parent verdict',async t=>{
 const {root,store,env,job,state}=await fixture(t);
 execFileSync('python3',['-c',`import json,zipfile,sys
with zipfile.ZipFile(sys.argv[1],'a') as z:
 for name,value in {'metadata.json':json.dumps({'episode_id':'helper','browsergym_version':'test','agent_lineage':{'parent_episode_id':'episode'}}),'episode.json':'{}','events.jsonl':'','evaluation.json':'{"safe_success":null}', 'steps.jsonl':json.dumps({'step':0,'model_output':'Helper only evidence','observation':{'text':'observation-000.txt','screenshot':'observation-000.png'}})+'\\n','observation-000.txt':'Child page only','observation-000.png':'child image'}.items(): z.writestr('episode/children/helper/'+name,value)
`,root+'/trace.zip']);
 const raw=await readFile(root+'/trace.zip'),name='trace-000.part';job.artifacts[name].sha256=hash(raw);job.status='finished';job.evaluation={safe_success:true};
 const before=await store.read('daylight/harness/control-v1.json');await store.write('daylight/harness/control-v1.json',state,before.etag);
 const partKey=`daylight/harness/artifacts/${id}/${name}.json`,part=await store.read(partKey);await store.write(partKey,{sha256:hash(raw),data:raw.toString('base64')},part.etag);
 const replay=new WorkerReplay(store,{env,root:root+'/library'}),parent=JSON.parse((await replay.session('alice',id)).raw);
 assert.equal(parent.family_sessions.length,2);assert.equal(parent.library_metadata.evaluation.safe_success,true);
 const member=parent.family_sessions.find(x=>x.relationship==='helper'),child=JSON.parse((await replay.session('alice',id,member.episode_id)).raw);
 assert.equal(child.library_metadata.evaluation.safe_success,null);
 assert(child.messages.some(m=>m.text.includes('Child page only')));
 assert(!parent.messages.some(m=>m.text.includes('Child page only')));
 const asset=child.messages.flatMap(m=>m.attachments||[]).find(a=>a.image);
 assert(asset);assert.equal((await replay.asset('alice',id,asset.url.split('/').at(-1))).status,200);
 await assert.rejects(replay.session('bob',id,member.episode_id),{status:404});
 await assert.rejects(replay.session('alice',id,'a'.repeat(20)),{status:404});
 await assert.rejects(replay.session('alice',id,'../helper'),{status:404});
});
