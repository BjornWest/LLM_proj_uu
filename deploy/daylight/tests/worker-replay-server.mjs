// Isolated saved-evidence UI check. No model, browser-agent, or production writes.
import {createServer} from 'node:http';
import {mkdtemp,readFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {SqliteStore} from '../lib/sqlite-store.mjs';
import {controlHandler} from '../control-server.mjs';
import {createHandler} from '../api/index.mjs';
import {digest} from '../lib/auth.mjs';
const directory=process.env.REPLAY_EPISODE;if(!directory)throw Error('Explicit saved episode required');
const root=await mkdtemp(tmpdir()+'/worker-replay-ui-'),store=new SqliteStore(root+'/state.sqlite');
execFileSync('python3',['-c',`from pathlib import Path
import sys,zipfile
p=Path(sys.argv[1])
with zipfile.ZipFile(sys.argv[2],'w',zipfile.ZIP_DEFLATED) as z:
 for f in sorted(p.rglob('*')):
  if f.is_symlink(): raise ValueError('Symlink')
  if f.is_file(): z.write(f,p.name+'/'+str(f.relative_to(p)))
`,directory,root+'/trace.zip']);
const raw=await readFile(root+'/trace.zip'),sha=createHash('sha256').update(raw).digest('hex'),id='ce2b89a8-9e5e-4d11-aa52-29a0d0b2898f',name='trace-000.part';
const episode=JSON.parse(await readFile(directory+'/episode.json')),metadata=JSON.parse(await readFile(directory+'/metadata.json'));
const job={id,owner:'tester',status:episode.error?'error':'finished',task:episode.task||'saved-task',mode:'live',goal:episode.resolved_goal||metadata.goal,site_id:'webarena-shopping',collection:'webarena',interaction_kind:'task',task_name:'Saved task 145',created_at:'2026-09-20T07:15:45.810Z',artifacts:{[name]:{sha256:sha}},trace_parts:[name],evaluation:episode.evaluation??null,error:episode.error||null,steps:[]};
await store.write('daylight/harness/control-v1.json',{version:1,jobs:{[id]:job},active:null,worker:null});
await store.write(`daylight/harness/artifacts/${id}/${name}.json`,{sha256:sha,data:raw.toString('base64')});
const env={DAYLIGHT_CONTROL_TOKEN:'local-replay-control-'.repeat(4),DAYLIGHT_LIBRARY_ROOT:root+'/library',DEMO_SESSION_SECRET:'local-replay-cookie-'.repeat(4),DEMO_INVITES_JSON:JSON.stringify({tester:digest('local-replay-code-'.repeat(3))})};
const backHandler=controlHandler({store,env,fetcher:()=>{throw Error('Model access blocked');}}),back=createServer(backHandler);await new Promise(r=>back.listen(0,'127.0.0.1',r));env.DAYLIGHT_CONTROL_URL='http://127.0.0.1:'+back.address().port;
const front=createServer(createHandler({store,env,local:true}));await new Promise(r=>front.listen(0,'127.0.0.1',r));
console.log(JSON.stringify({port:front.address().port,id,root}));
for(const signal of ['SIGTERM','SIGINT'])process.on(signal,()=>{backHandler.shutdown();front.closeAllConnections();back.closeAllConnections();front.close();back.close();store.close();process.exit(0);});
