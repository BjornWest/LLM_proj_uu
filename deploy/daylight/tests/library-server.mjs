// Local review fixture: exact saved projections, actual invitation handler, no model calls.
import {createServer} from 'node:http';
import {readFile,mkdtemp,cp,copyFile,writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {tmpdir} from 'node:os';
import {createHandler} from '../api/index.mjs';
import {FileStore} from '../lib/store.mjs';
import {authenticate,config,digest,login} from '../lib/auth.mjs';
import {prepareViewer} from '../prepare-viewer.mjs';
const root=fileURLToPath(new URL('../../../',import.meta.url));
const temporary=await mkdtemp(path.join(tmpdir(),'daylight-library-review-')),assetRoot=path.join(temporary,'assets');
await cp(path.join(root,'deploy/daylight/private-assets'),assetRoot,{recursive:true});
for(const name of ['workspace.js','workspace.html','workspace.css','tool-activity.js','tool-activity.css'])await copyFile(path.join(root,'deploy/daylight/client',name),path.join(assetRoot,name));
const viewerFiles=await prepareViewer(assetRoot);
const env={DEMO_SESSION_SECRET:'library-offline-secret-'.repeat(4),DEMO_INVITES_JSON:JSON.stringify({tester:digest('offline-library-code-'.repeat(3)),foreign:digest('offline-foreign-code-'.repeat(3))})};
const settings=config(env),autoCookie='daylight_session='+login('offline-library-code-'.repeat(3),settings);
const sessions=new Map(),assets=new Map();
for(const [bundle,site,condition] of [['replay-privacy-failure-v2','tricky-health','injected'],['replay-format-error-v2','tricky-shop','injected']]){
 const directory=path.join(root,'.local/review',bundle),session=JSON.parse(await readFile(path.join(directory,'session.json'),'utf8')),mapping=JSON.parse(await readFile(path.join(directory,'assets.json'),'utf8'));
 const manifest=JSON.parse(await readFile(path.join(directory,'manifest.json'),'utf8'));
 for(const message of session.messages)for(const asset of message.attachments||[]){
  const original=mapping[asset.url];if(!original)throw Error('Unmapped fixture asset');
  const id=createHash('sha256').update(asset.url).digest('hex');
  const raw=await readFile(path.join(directory,original.path));if(createHash('sha256').update(raw).digest('hex')!==original.sha256)throw Error('Fixture asset hash mismatch');
  assets.set(session.id+'/'+id,{raw,type:original.mime_type});asset.url='/api/library/sessions/'+session.id+'/assets/'+id;
 }
 // Explicit review-fixture publication metadata, separate from historical projection.
 session.library_metadata={site_id:site,collection:'trickyarena',condition,interaction_kind:null,metadata_source:'local-review-fixture-publication',evaluation:manifest.raw_outcomes};
 sessions.set(session.id,session);
}
const handler=createHandler({store:new FileStore(path.join(temporary,'store')),env,assetRoot,local:true,fetcher:async()=>{throw Error('Model calls are disabled in this viewer fixture');}});
const stats={catalog:0,sessions:0,assets:0,writes:0};
createServer(async(req,res)=>{
 if(process.env.LIBRARY_PREVIEW_AUTOLOGIN==='1')req.headers.cookie=autoCookie;
 const url=new URL(req.url,'http://localhost');
 const send=(status,body,type='application/json')=>{res.writeHead(status,{'content-type':type,'cache-control':'private, no-store','x-content-type-options':'nosniff','content-security-policy':"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-src 'self'; frame-ancestors 'self'"});res.end(type==='application/json'?JSON.stringify(body):body);};
 if(url.pathname==='/__fixture/stats')return send(200,stats);
 const viewer=url.pathname==='/trace-viewer'||viewerFiles.some(name=>url.pathname==='/assets/'+name),library=url.pathname.startsWith('/api/library/');
 if(viewer||library){
  const owner=authenticate(req.headers.cookie,settings);if(!owner)return send(401,{error:'Invitation required'});if(req.method!=='GET')return send(405,{error:'Read only'});
  if(viewer){const name=url.pathname==='/trace-viewer'?'trace-viewer.html':url.pathname.slice(8),type=name.endsWith('.html')?'text/html':name.endsWith('.css')?'text/css':name.endsWith('.js')?'text/javascript':'application/json';return send(200,await readFile(path.join(assetRoot,name)),type);}
  if(url.pathname==='/api/library/sessions'){stats.catalog++;const list=owner==='tester'?[...sessions.values()]:[];const offset=url.searchParams.get('cursor')==='fixture-page-2'?1:0;const values=list.slice(offset,offset+1).map(({messages,...s})=>({...s,...s.library_metadata,revision:createHash('sha256').update(JSON.stringify(s)).digest('hex')}));return send(200,{sessions:values,has_more:list.length>offset+1,cursor:list.length>offset+1?'fixture-page-2':null});}
  const match=url.pathname.match(/^\/api\/library\/sessions\/([^/]+)(?:\/assets\/([^/]+))?$/),session=match&&sessions.get(match[1]);
  if(owner!=='tester'||!session)return send(404,{error:'Saved session not found'});
  if(match[2]){const asset=assets.get(match[1]+'/'+match[2]);if(!asset)return send(404,{error:'Asset not found'});stats.assets++;return send(200,asset.raw,asset.type);}
  stats.sessions++;return send(200,session);
 }
 if(req.method==='POST'&&!['/login','/logout'].includes(url.pathname)){stats.writes++;return send(403,{error:'Local trace review is read only'});}
 if(url.pathname==='/'&&process.env.LIBRARY_PREVIEW_AUTOLOGIN==='1'){res.writeHead(302,{location:'/workspace/replays'});return res.end();}
 return handler(req,res);
}).listen(0,'127.0.0.1',function(){console.log(JSON.stringify({port:this.address().port,sessions:[...sessions.keys()]}));});
