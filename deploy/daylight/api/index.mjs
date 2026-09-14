import {readFile} from 'node:fs/promises';
import path from 'node:path';
import {config,login,authenticate,sessionCookie} from '../lib/auth.mjs';
import {BlobStore} from '../lib/store.mjs';
import {Agent} from '../lib/agent.mjs';
const assets=path.resolve('private-assets');
const TYPES={html:'text/html; charset=utf-8',css:'text/css',js:'text/javascript',json:'application/json; charset=utf-8'};
const allowed=new Set(['style.css','site.html','site.js','rooms.js','dashboard.js','world.js','observation.js','fixture.json']);
const loginHTML=`<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Daylight · Private demo</title><body style="font:17px system-ui;background:#f3f1f8;color:#292638;max-width:420px;margin:15vh auto;padding:24px"><h1>✳ Daylight</h1><p>A private demo for our project team.</p><form method="post" action="/login"><label for="code">Your invitation code</label><input id="code" name="code" type="password" required autocomplete="current-password" maxlength="200" style="display:block;width:100%;box-sizing:border-box;padding:14px;margin:12px 0"><button style="padding:12px 24px">Open demo</button></form><p style="font-size:14px">Ask Bjorn for your code. No model account needed.</p></body></html>`;
async function body(req) {
  if(req.body && typeof req.body==='object') {
    if(JSON.stringify(req.body).length>75000)throw Object.assign(Error('Request too large'),{status:413});return req.body;
  }
  let raw=typeof req.body==='string'?req.body:'';
  if(!raw)for await (const chunk of req) {raw+=chunk;if(Buffer.byteLength(raw)>75000)throw Object.assign(Error('Request too large'),{status:413});}
  if(Buffer.byteLength(raw)>75000)throw Object.assign(Error('Request too large'),{status:413});
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
    try {
      const settings=config(env);
      const url=new URL(req.url,'https://'+req.headers.host);
      if(!['GET','POST'].includes(req.method))return send(405,{error:'Method not allowed'});
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
      if(url.pathname==='/logout') {res.setHeader('Set-Cookie',sessionCookie('',local));return redirect('/login');}
      if(url.pathname.startsWith('/api/')) {
        const activeStore=store||new BlobStore();
        const provenance=JSON.parse(await readFile(path.join(assetRoot,'provenance.json'),'utf8'));
        const agent=new Agent(activeStore,{env,fetcher,provenance});
        if(url.pathname==='/api/config'&&req.method==='GET')return send(200,{owner,live_available:!!env.OPENROUTER_API_KEY,
          daily_budget_usd:Number(env.DEMO_DAILY_BUDGET_USD||1),runtime:'daylight-client-demo-v1'});
        if(url.pathname.startsWith('/api/traces/')&&req.method==='GET') {
          const trace=(await agent.read(owner,url.pathname.split('/').at(-1))).value;
          res.setHeader('Content-Disposition',`attachment; filename="daylight-${trace.id}.json"`);return send(200,trace);
        }
        if(req.method!=='POST')return send(405,{error:'Method not allowed'});
        const value=await body(req);
        if(url.pathname==='/api/start')return send(200,await agent.start(owner,value));
        if(url.pathname==='/api/step')return send(200,await agent.step(owner,value));
        if(url.pathname==='/api/event')return send(200,await agent.event(owner,value));
        return send(404,{error:'Not found'});
      }
      if(req.method!=='GET')return send(405,{error:'Method not allowed'});
      let file=url.pathname==='/'?'index.html':url.pathname.startsWith('/assets/')?url.pathname.slice(8):null;
      if(/^\/world\/[a-z0-9-]+\/(shop|booking|preferences)$/.test(url.pathname))file='site.html';
      if(file!=='index.html'&&!allowed.has(file))return send(404,{error:'Not found'});
      return send(200,await readFile(path.join(assetRoot,file)),TYPES[file.split('.').at(-1)]);
    } catch(error) {
      // Never log request headers or secret configuration. Detailed inference errors live in private traces.
      send(error.status||503,{error:error.status?error.message:'Demo unavailable. Check access, private storage and server configuration.'});
    }
  };
}
export default createHandler();
