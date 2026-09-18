// Isolated review: real PC library and invitation API, only two explicitly selected
// historical bundles. No production database, budgets, workers or model access.
import {createServer} from 'node:http';
import {mkdtemp,writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {TraceLibrary} from '../lib/library.mjs';
import {SqliteStore} from '../lib/sqlite-store.mjs';
import {controlHandler} from '../control-server.mjs';
import {createHandler} from '../api/index.mjs';
import {config,digest,login} from '../lib/auth.mjs';
const repo=fileURLToPath(new URL('../../../',import.meta.url)),root=await mkdtemp(path.join(tmpdir(),'daylight-library-integrated-'));
const store=new SqliteStore(root+'/state.sqlite');
const env={DAYLIGHT_CONTROL_TOKEN:'local-library-control-'.repeat(4),DAYLIGHT_LIBRARY_ROOT:root+'/library',DEMO_SESSION_SECRET:'local-library-cookie-'.repeat(4),DEMO_INVITES_JSON:JSON.stringify({tester:digest('offline-library-code-'.repeat(3)),foreign:digest('offline-foreign-code-'.repeat(3))})};
const library=new TraceLibrary(store,{root:env.DAYLIGHT_LIBRARY_ROOT}),sessions=[];
for(const [bundle,site] of [['replay-privacy-failure-v2','tricky-health'],['replay-format-error-v2',null]]){
 sessions.push(await library.publish(path.join(repo,'.local/review',bundle),'tester',{site_id:site,collection:'trickyarena',condition:'injected',metadata_source:'explicit local review publication'}));
}
const stats={catalog:0,sessions:0,assets:0,writes:0,model_calls:0};
const blockFetch=()=>{stats.model_calls++;throw Error('No model access in local review');};
const backHandler=controlHandler({store,env,fetcher:blockFetch}),back=createServer(backHandler);
await new Promise(resolve=>back.listen(0,'127.0.0.1',resolve));env.DAYLIGHT_CONTROL_URL='http://127.0.0.1:'+back.address().port;
const handler=createHandler({store,env,local:true,fetcher:async(url,options)=>{if(!url.startsWith(env.DAYLIGHT_CONTROL_URL+'/internal/library/'))return blockFetch();return fetch(url,options);}});
const cookie='daylight_session='+login('offline-library-code-'.repeat(3),config(env));
const front=createServer((req,res)=>{
 if(process.env.LIBRARY_PREVIEW_AUTOLOGIN==='1')req.headers.cookie=cookie;
 if(req.url==='/__fixture/stats'){res.setHeader('content-type','application/json');return res.end(JSON.stringify(stats));}
 if(req.url.startsWith('/api/library/sessions')){if(req.url.includes('/assets/'))stats.assets++;else if(/^\/api\/library\/sessions(?:\?|$)/.test(req.url))stats.catalog++;else stats.sessions++;}
 if(req.method==='POST'&&!['/login','/logout'].includes(req.url)){stats.writes++;res.statusCode=403;return res.end('Read-only review');}
 return handler(req,res);
});
await new Promise(resolve=>front.listen(Number(process.env.LIBRARY_REVIEW_PORT||0),'127.0.0.1',resolve));
console.log(JSON.stringify({port:front.address().port,root,sessions:sessions.map(s=>s.id),metadata:sessions}));
for(const signal of ['SIGTERM','SIGINT'])process.on(signal,()=>{backHandler.shutdown();front.closeAllConnections();back.closeAllConnections();front.close();back.close();store.close();process.exit(0);});
