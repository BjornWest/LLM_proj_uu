import {readFile} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {config,login,authenticate,sessionCookie} from '../lib/auth.mjs';
import {StorageError} from '../lib/store.mjs';
import {configuredStore} from '../lib/remote-store.mjs';
import {ManualClient} from '../lib/manual-client.mjs';
import {LibraryClient} from '../lib/library-client.mjs';
import {Readable} from 'node:stream';
import {pipeline} from 'node:stream/promises';
import {inspectionAsset,inspectionHTML,inspectionCSP,inspectionRevision} from '../lib/inspection.mjs';
import {createHash} from 'node:crypto';
import {Agent,completionTokenLimit} from '../lib/agent.mjs';
import {checkStorage} from '../lib/storage-check.mjs';
import {Harness,workerAuthorized} from '../lib/harness.mjs';
// Resolve beside this module, including when the function starts at the monorepo root.
const assets=fileURLToPath(new URL('../private-assets/',import.meta.url));
const TYPES={html:'text/html; charset=utf-8',css:'text/css',js:'text/javascript',json:'application/json; charset=utf-8'};
const allowed=new Set(['style.css','site.html','site.js','rooms.js','dashboard.js','world.js','observation.js','fixture.json','harness.js','harness.css','workspace.js','workspace.css','tool-activity.js','tool-activity.css','inspection.js','inspection.css','trace-viewer.js','trace-viewer.css','trace-viewer-source.json','trace-browser.js','trace-browser.css']);
const loginHTML=`<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Daylight · Private demo</title><body style="font:17px system-ui;background:#f3f1f8;color:#292638;max-width:420px;margin:15vh auto;padding:24px"><h1>✳ Daylight</h1><p>A private demo for our project team.</p><form method="post" action="/login"><label for="code">Your invitation code</label><input id="code" name="code" type="password" required autocomplete="current-password" maxlength="200" style="display:block;width:100%;box-sizing:border-box;padding:14px;margin:12px 0"><button style="padding:12px 24px">Open demo</button></form><p style="font-size:14px">Ask Bjorn for your code. No model account needed.</p></body></html>`;
async function body(req,limit=75000) {
  if(req.body && typeof req.body==='object') {
    if(Buffer.byteLength(JSON.stringify(req.body))>limit)throw Object.assign(Error('Request too large'),{status:413});return req.body;
  }
  let raw=typeof req.body==='string'?req.body:'';
  if(!raw)for await (const chunk of req) {raw+=chunk;if(Buffer.byteLength(raw)>limit)throw Object.assign(Error('Request too large'),{status:413});}
  if(Buffer.byteLength(raw)>limit)throw Object.assign(Error('Request too large'),{status:413});
  return (req.headers['content-type']||'').includes('application/x-www-form-urlencoded')?Object.fromEntries(new URLSearchParams(raw)):JSON.parse(raw||'{}');
}
export function createHandler({store,env=process.env,fetcher=fetch,assetRoot=assets,local=false}={}) {
  return async function handler(req,res) {
    res.setHeader('Cache-Control','private, no-store');res.setHeader('X-Content-Type-Options','nosniff');
    // Same-origin preserves the Origin header on HTML login POSTs; no-referrer can make it "null".
    res.setHeader('Referrer-Policy','same-origin');res.setHeader('X-Frame-Options','SAMEORIGIN');
    res.setHeader('X-Robots-Tag','noindex, nofollow');
    res.setHeader('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; frame-src 'self'; frame-ancestors 'self'; form-action 'self'; base-uri 'none'");
    const send=(status,value,type='application/json')=>{res.statusCode=status;res.setHeader('Content-Type',type);res.end(type==='application/json'?JSON.stringify(value):value);};
    const redirect=url=>{res.statusCode=303;res.setHeader('Location',url);res.end();};
    let stage='access_configuration',operation=null;
    try {
      const settings=config(env);
      stage='request';
      const url=new URL(req.url,'https://'+req.headers.host);
      if(!['GET','POST'].includes(req.method))return send(405,{error:'Method not allowed'});
      // Machine-only outward worker connection. It accepts no browser cookies.
      if(url.pathname.startsWith('/api/harness/worker/')) {
        if(req.method!=='POST'||!workerAuthorized(req.headers.authorization,env))return send(401,{error:'Worker authentication required'});
        operation=url.pathname.split('/').at(-1);
        if(!['poll','checkpoint','reserve','artifact','update'].includes(operation))return send(404,{error:'Not found'});
        if(env.DAYLIGHT_STORAGE_MAINTENANCE==='1')return send(503,{error:'Storage maintenance; worker paused.'});
        stage='agent_storage';
        const harness=new Harness(store||configuredStore(env),{env});
        return send(200,await harness[operation](await body(req,1600000)));
      }
      if(req.method==='POST') {
        const expected=(local?'http':'https')+'://'+req.headers.host;
        if(req.headers.origin!==expected)return send(403,{error:'Invalid request origin'});
      }
      if(url.pathname==='/login') {
        if(req.method==='GET')return send(200,loginHTML,'text/html; charset=utf-8');
        const token=login((await body(req)).code,settings);
        if(!token)return send(401,loginHTML.replace('Ask Bjorn for your code.','That code did not work. Ask Bjorn for your code.'),'text/html; charset=utf-8');
        res.setHeader('Set-Cookie',sessionCookie(token,local));return redirect('/');
      }
      const owner=authenticate(req.headers.cookie,settings);
      if(!owner)return url.pathname.startsWith('/api/')?send(401,{error:'Please sign in'}):redirect('/login');
      if(req.method==='GET'&&/^\/(shop|health|spotify)(\/|$)/.test(url.pathname)){
        res.statusCode=307;res.setHeader('Location','/sites/tricky'+url.pathname+url.search);return res.end();
      }
      if(req.method==='GET'&&(url.pathname==='/sites/tricky'||url.pathname.startsWith('/sites/tricky/'))){
        stage='private_assets';res.setHeader('Content-Security-Policy',inspectionCSP);res.setHeader('X-Frame-Options','DENY');res.setHeader('X-Site-Revision',inspectionRevision);
        return send(200,await inspectionHTML(assetRoot),'text/html; charset=utf-8');
      }
      if(req.method==='GET'&&(url.pathname.startsWith('/assets/')||url.pathname.startsWith('/external-assets/')||url.pathname==='/darkpattern.svg')&&!allowed.has(url.pathname.slice(8))){
        stage='private_assets';const asset=await inspectionAsset(assetRoot,url.pathname);
        if(!asset)return send(404,{error:'Not found'});
        // Auth is checked above even for conditional requests. Browser-private
        // cache only: no CDN-shared personalized/cookie-bearing responses.
        res.setHeader('Cache-Control','private, max-age=86400, immutable');res.setHeader('ETag',asset.etag);
        res.setHeader('Vercel-CDN-Cache-Control','no-store');
        if(req.headers['if-none-match']===asset.etag){res.statusCode=304;return res.end();}
        return send(200,asset.raw,asset.type);
      }
      if(req.method==='POST'&&env.DAYLIGHT_STORAGE_MAINTENANCE==='1')return send(503,{error:'Storage maintenance. Please try again after the migration.'});
      if(url.pathname.startsWith('/api/library/')){
        if(req.method!=='GET')return send(405,{error:'Read only'});
        if(!env.DAYLIGHT_CONTROL_URL){if(url.pathname==='/api/library/sessions')return send(200,{sessions:[],has_more:false,cursor:null});return send(404,{error:'Saved session not found'});}
        const library=new LibraryClient({env,fetcher});stage='trace_library';
        if(url.pathname==='/api/library/sessions'){
          const result=await library.call('list',{owner,cursor:url.searchParams.get('cursor')||undefined,limit:url.searchParams.has('limit')?Number(url.searchParams.get('limit')):25});
          return send(200,await result.json());
        }
        const match=url.pathname.match(/^\/api\/library\/sessions\/([a-f0-9]{20})(?:\/assets\/([a-f0-9]{64}))?$/);
        if(!match)return send(404,{error:'Saved session not found'});
        const [,id,attachment]=match,result=await library.call(attachment?'asset':'session',{owner,id,...(attachment?{attachment,range:req.headers.range}: {})});
        // Authorization occurs upstream before any conditional response. Revalidate on
        // each access so logging out or changing owner never exposes cached evidence.
        const etag=result.headers.get('etag');res.setHeader('Cache-Control','private, no-cache');res.setHeader('Vercel-CDN-Cache-Control','no-store');
        if(etag)res.setHeader('ETag',etag);
        if(etag&&req.headers['if-none-match']===etag){await result.body?.cancel();res.statusCode=304;return res.end();}
        res.statusCode=result.status;
        for(const name of ['content-type','content-length','content-range','accept-ranges'])if(result.headers.has(name))res.setHeader(name,result.headers.get(name));
        if(attachment)res.setHeader('Content-Disposition','inline');
        await pipeline(Readable.fromWeb(result.body),res);return;
      }
      if(url.pathname.startsWith('/api/manual/')){
        if(!env.DAYLIGHT_CONTROL_URL){if(url.pathname==='/api/manual/config'&&req.method==='GET')return send(200,{enabled:false,sites:[]});return send(503,{error:'Manual environments are not configured.'});}
        const manual=new ManualClient({env});stage='manual_browser';
        if(url.pathname==='/api/manual/config'&&req.method==='GET')return send(200,await manual.call('config',{}));
        if(url.pathname==='/api/manual/sessions'){
          if(req.method==='GET')return send(200,await manual.call('list',{owner}));
          const input=await body(req);
          const config=await manual.call('config',{}),selected=config.sites?.flatMap(s=>s.tasks).find(t=>t.id===input.task);
          if((input.task?.startsWith('tricky-')||input.task==='synthetic-dev-w01')&&selected?.site_revision!==inspectionRevision)
            return send(409,{error:'The client and worker site versions differ. Please wait for deployment to finish and refresh.'});
          return send(200,await manual.call('start',{...input,owner,site_revision:inspectionRevision}));
        }
        const m=url.pathname.match(/^\/api\/manual\/sessions\/([a-f0-9-]{36})(?:\/(action|observe|close|frame|trace|ask|interrupt)(?:\/([a-f0-9-]{36}))?)?$/);
        if(!m)return send(404,{error:'Not found'});const [,id,op,frame_id]=m;
        if(!op&&req.method==='GET')return send(200,await manual.call('read',{owner,id}));
        if(['action','observe','close','ask','interrupt'].includes(op)&&req.method==='POST')return send(200,await manual.call(op,{...(await body(req)),owner,id}));
        if(['frame','trace'].includes(op)&&req.method==='GET'){
          if(op==='frame'&&!frame_id)return send(404,{error:'Frame not found'});
          const artifact=await manual.call('artifact',{owner,id,...(op==='frame'?{frame_id}:{})});
          if(op==='trace'){
            res.statusCode=200;res.setHeader('Content-Type','application/zip');res.setHeader('Content-Disposition',`attachment; filename="manual-${id}.zip"`);
            for(let part=0;part<artifact.parts;part++)res.write(Buffer.from((await manual.call('artifact',{owner,id,part})).data,'base64'));
            return res.end();
          }
          return send(200,Buffer.from(artifact.data,'base64'),'image/png');
        }
        return send(405,{error:'Method not allowed'});
      }
      if(url.pathname.startsWith('/api/harness/')) {
        stage='agent_storage';const harness=new Harness(store||configuredStore(env),{env});
        if(url.pathname==='/api/harness/config'&&req.method==='GET')return send(200,await harness.config());
        if(url.pathname==='/api/harness/jobs')return send(200,req.method==='GET'?await harness.list(owner):await harness.start(owner,await body(req)));
        const match=url.pathname.match(/^\/api\/harness\/jobs\/([a-f0-9-]{36})(?:\/(issues|trace|artifacts)(?:\/([^/]+))?)?$/);
        if(!match)return send(404,{error:'Not found'});
        const [,id,action,name]=match;
        if(!action&&req.method==='GET')return send(200,await harness.read(owner,id));
        if(action==='issues'&&req.method==='POST')return send(200,await harness.issue(owner,id,await body(req)));
        if(action==='artifacts'&&req.method==='GET'&&name)return send(200,await harness.artifactRead(owner,id,name),name.endsWith('.png')?'image/png':name.endsWith('.txt')?'text/plain; charset=utf-8':'application/octet-stream');
        if(action==='trace'&&req.method==='GET') {
          const job=await harness.read(owner,id);
          if(!job.trace_parts?.length)return send(409,{error:'The original trace archive is not available yet'});
          // Stream bounded parts; never build a second trace or expose a public Blob URL.
          res.statusCode=200;res.setHeader('Content-Type','application/zip');
          res.setHeader('Content-Disposition',`attachment; filename="browsergym-${id}.zip"`);
          for(const part of job.trace_parts)res.write(await harness.artifactRead(owner,id,part));
          return res.end();
        }
        return send(405,{error:'Method not allowed'});
      }
      if(url.pathname==='/storage-check') {
        if(req.method==='GET')return send(200,'<!doctype html><meta charset="utf-8"><title>Daylight storage check</title><h1>Check private storage</h1><p>Creates one isolated diagnostic object. No model calls or trace/budget changes.</p><form method="post"><button>Run storage check</button></form>','text/html; charset=utf-8');
        return send(200,await checkStorage(store||configuredStore(env),owner));
      }
      if(url.pathname==='/logout') {res.setHeader('Set-Cookie',sessionCookie('',local));return redirect('/login');}
      if(url.pathname.startsWith('/api/')) {
        const activeStore=store||configuredStore(env);
        stage='private_assets';
        const provenance=JSON.parse(await readFile(path.join(assetRoot,'provenance.json'),'utf8'));
        stage='agent_storage';
        const agent=new Agent(activeStore,{env,fetcher,provenance});
        if(url.pathname==='/api/config'&&req.method==='GET')return send(200,{owner,live_available:!!env.OPENROUTER_API_KEY,
          generation:{reasoning:{enabled:true},max_tokens:completionTokenLimit(env.OPENROUTER_MAX_TOKENS)},
          daily_budget_usd:Number(env.DEMO_DAILY_BUDGET_USD||1),runtime:'daylight-client-demo-v1',
          capabilities:{interactive_actions:'assist',interrupt:'/api/interrupt',trace_list:'/api/traces',max_steps:12}});
        if(url.pathname==='/api/traces'&&req.method==='GET') {
          operation='trace_list';
          return send(200,await agent.list(owner,{cursor:url.searchParams.get('cursor')||undefined,
            limit:url.searchParams.has('limit')?Number(url.searchParams.get('limit')):25}));
        }
        if(url.pathname.startsWith('/api/traces/')&&req.method==='GET') {
          operation='trace_read';
          const trace=(await agent.read(owner,url.pathname.split('/').at(-1))).value;
          res.setHeader('Content-Disposition',`attachment; filename="daylight-${trace.id}.json"`);return send(200,trace);
        }
        if(req.method!=='POST')return send(405,{error:'Method not allowed'});
        stage='request';
        const value=await body(req);
        stage='agent_storage';
        if(url.pathname==='/api/start') {operation='start';return send(200,await agent.start(owner,value));}
        if(url.pathname==='/api/step') {operation='step';return send(200,await agent.step(owner,value));}
        if(url.pathname==='/api/event') {operation='event';return send(200,await agent.event(owner,value));}
        if(url.pathname==='/api/interrupt') {operation='interrupt';return send(200,await agent.interrupt(owner,value));}
        return send(404,{error:'Not found'});
      }
      if(req.method!=='GET')return send(405,{error:'Method not allowed'});
      let file=['/','/workspace','/workspace/replays'].includes(url.pathname)?'workspace.html':url.pathname==='/demo'?'index.html':url.pathname==='/harness'?'harness.html':url.pathname==='/trace-viewer'?'trace-viewer.html':url.pathname.startsWith('/assets/')?url.pathname.slice(8):null;
      if(/^\/world\/[a-z0-9-]+\/(shop|booking|preferences)$/.test(url.pathname))file='site.html';
      if(!['index.html','harness.html','workspace.html','trace-viewer.html'].includes(file)&&!allowed.has(file))return send(404,{error:'Not found'});
      stage='private_assets';
      if(file==='inspection.js'||file==='inspection.css'){
        const raw=await readFile(path.join(assetRoot,file)),etag='"'+createHash('sha256').update(raw).digest('hex')+'"';
        res.setHeader('Cache-Control','private, no-cache');res.setHeader('ETag',etag);
        if(req.headers['if-none-match']===etag){res.statusCode=304;return res.end();}
        return send(200,raw,TYPES[file.split('.').at(-1)]);
      }
      return send(200,await readFile(path.join(assetRoot,file)),TYPES[file.split('.').at(-1)]);
    } catch(error) {
      if(res.headersSent){res.destroy();return;}
      if(error instanceof StorageError) {
        console.error(JSON.stringify({event:'daylight_request_failed',code:error.code,stage,
          operation,storage_operation:error.operation}));
        return send(error.code==='BLOB_WRITE_CONFLICT'?409:503,{error:error.message,code:error.code});
      }
      if(error.status)return send(error.status,{error:error.message});
      const code=({access_configuration:'ACCESS_CONFIGURATION',private_assets:'PRIVATE_ASSETS_UNAVAILABLE',
        agent_storage:'AGENT_STORAGE_UNAVAILABLE'})[stage]||'REQUEST_FAILED';
      // Fixed labels only: never log request headers, bodies, secrets or arbitrary exception messages.
      console.error(JSON.stringify({event:'daylight_request_failed',code,stage,...(operation?{operation}:{}),
        missing_file:error.code==='ENOENT'}));
      send(503,{error:'Demo unavailable. Check Vercel Runtime Logs for '+code+'.',code});
    }
  };
}
export default createHandler();
