// Isolated real BrowserGym service + actual invitation handler. No inference keys.
import {createServer} from 'node:http';
import {mkdtemp,mkdir} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {randomUUID} from 'node:crypto';
import {SqliteStore} from '../lib/sqlite-store.mjs';
import {controlHandler} from '../control-server.mjs';
import {createHandler} from '../api/index.mjs';
import {digest} from '../lib/auth.mjs';
const root=path.resolve(process.env.MANUAL_TEST_OUTPUT||await mkdtemp(tmpdir()+'/manual-browser-'));
await mkdir(root,{recursive:true});
const store=new SqliteStore(root+'/state.sqlite');
const env={DAYLIGHT_MANUAL_PACKAGE:path.resolve(process.env.MANUAL_TEST_PACKAGE||'../../.local/environment-packages/portable-v2'),
  DAYLIGHT_MANUAL_DRIVER:path.resolve(process.env.MANUAL_TEST_DRIVER||'../../scripts/manual_environment.py'),
  DAYLIGHT_MANUAL_PYTHON:process.env.MANUAL_TEST_PYTHON||path.resolve('../../.venv/bin/python'),
  DAYLIGHT_MANUAL_ROOT:root+'/sessions',DAYLIGHT_MANUAL_ACTOR:'scripted_validation',
  DAYLIGHT_CONTROL_TOKEN:randomUUID().repeat(2),DEMO_SESSION_SECRET:randomUUID().repeat(2),
  DEMO_INVITES_JSON:JSON.stringify({tester:digest('offline-interactive-code-'.repeat(3)),other:digest('offline-other-code-'.repeat(3))})};
const control=controlHandler({store,env}),back=createServer(control);
await new Promise(r=>back.listen(0,'127.0.0.1',r));env.DAYLIGHT_CONTROL_URL='http://127.0.0.1:'+back.address().port;
const handler=createHandler({store,env,local:true,fetcher:()=>{throw Error('Inference forbidden in manual validation');}});
const front=createServer(handler);await new Promise(r=>front.listen(0,'127.0.0.1',r));
console.log(JSON.stringify({port:front.address().port,output:root}));
for(const sig of ['SIGTERM','SIGINT'])process.on(sig,()=>{
  control.shutdown();front.closeAllConnections();back.closeAllConnections();
  front.close(()=>back.close(()=>{store.close();process.exit(0);}));
});
