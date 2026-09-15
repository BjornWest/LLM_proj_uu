import {readFile} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {config,login,authenticate,sessionCookie} from '../lib/auth.mjs';
import {BlobStore,StorageError} from '../lib/store.mjs';
import {Agent} from '../lib/agent.mjs';
import {checkStorage} from '../lib/storage-check.mjs';
import {Harness,workerAuthorized} from '../lib/harness.mjs';
// Resolve beside this module, including when the function starts at the monorepo root.
const assets=fileURLToPath(new URL('../private-assets/',import.meta.url));
const TYPES={html:'text/html; charset=utf-8',css:'text/css',js:'text/javascript',json:'application/json; charset=utf-8'};
const allowed=new Set(['style.css','site.html','site.js','rooms.js','dashboard.js','world.js','observation.js','fixture.json','harness.js','harness.css','workspace.js','workspace.css','tool-activity.js','tool-activity.css']);
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
        stage='agent_storage';
        const harness=new Harness(store||new BlobStore({env}),{env});
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
      if(url.pathname.startsWith('/api/harness/')) {
        stage='agent_storage';const harness=new Harness(store||new BlobStore({env}),{env});
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
        return send(200,await checkStorage(store||new BlobStore({env}),owner));
      }
      if(url.pathname==='/logout') {res.setHeader('Set-Cookie',sessionCookie('',local));return redirect('/login');}
      if(url.pathname.startsWith('/api/')) {
        const activeStore=store||new BlobStore({env});
        stage='private_assets';
        const provenance=JSON.parse(await readFile(path.join(assetRoot,'provenance.json'),'utf8'));
        stage='agent_storage';
        const agent=new Agent(activeStore,{env,fetcher,provenance});
        if(url.pathname==='/api/config'&&req.method==='GET')return send(200,{owner,live_available:!!env.OPENROUTER_API_KEY,
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
      let file=['/','/workspace','/workspace/replays'].includes(url.pathname)?'workspace.html':url.pathname==='/demo'?'index.html':url.pathname==='/harness'?'harness.html':url.pathname.startsWith('/assets/')?url.pathname.slice(8):null;
      if(/^\/world\/[a-z0-9-]+\/(shop|booking|preferences)$/.test(url.pathname))file='site.html';
      if(!['index.html','harness.html','workspace.html'].includes(file)&&!allowed.has(file))return send(404,{error:'Not found'});
      stage='private_assets';
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
