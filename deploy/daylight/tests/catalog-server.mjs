// UI contract fixture only. Actual invitation handler and complete Tricky assets;
// frozen answer-free catalog served without enabling any model or browser jobs.
import {createServer} from 'node:http';
import {mkdtemp,cp,copyFile,readFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
import {createHandler} from '../api/index.mjs';
import {FileStore} from '../lib/store.mjs';
import {authenticate,config,digest,login} from '../lib/auth.mjs';
const root=fileURLToPath(new URL('../../../',import.meta.url));
const temporary=await mkdtemp(path.join(tmpdir(),'daylight-catalog-ui-')),assetRoot=path.join(temporary,'assets');
await cp(path.join(root,'deploy/daylight/private-assets'),assetRoot,{recursive:true});
for(const name of ['workspace.js','workspace.html','workspace.css','inspection.js'])await copyFile(path.join(root,'deploy/daylight/client',name),path.join(assetRoot,name));
const catalog=await readFile(path.join(root,'data/curation/expansion/hosted-review-catalog.json'));
const env={DEMO_SESSION_SECRET:'catalog-review-secret-'.repeat(4),DEMO_INVITES_JSON:JSON.stringify({tester:digest('offline-catalog-code-'.repeat(3))})},settings=config(env),cookie='daylight_session='+login('offline-catalog-code-'.repeat(3),settings);
const stats={writes:0,model_calls:0};
const handler=createHandler({store:new FileStore(path.join(temporary,'store')),env,assetRoot,local:true,fetcher:()=>{stats.model_calls++;throw Error('No inference in catalog review');}});
createServer((req,res)=>{
 if(process.env.CATALOG_PREVIEW_AUTOLOGIN==='1')req.headers.cookie=cookie;
 if(req.url==='/__fixture/stats'){res.setHeader('content-type','application/json');return res.end(JSON.stringify(stats));}
 if(req.method==='POST'&&!['/login','/logout'].includes(req.url)){stats.writes++;res.statusCode=403;return res.end('Read-only catalog review');}
 if(req.url==='/api/task-catalog'){
  res.setHeader('content-type','application/json');res.setHeader('cache-control','private, no-store');
  if(!authenticate(req.headers.cookie,settings)){res.statusCode=401;return res.end(JSON.stringify({error:'Invitation required'}));}
  return res.end(catalog);
 }
 return handler(req,res);
}).listen(0,'127.0.0.1',function(){console.log(JSON.stringify({port:this.address().port}));});
