import test from 'node:test';
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {readFile} from 'node:fs/promises';
import {createHandler} from '../api/index.mjs';
import {digest} from '../lib/auth.mjs';
const code='offline-inspection-code-'.repeat(3);
async function fixture(t){
 const accesses=[];const store=new Proxy({},{get:(_,op)=>()=>{accesses.push(op);throw Error('Inspection must not use cloud/control storage');}});
 const server=createServer(createHandler({local:true,store,env:{DEMO_SESSION_SECRET:'offline-secret-'.repeat(5),DEMO_INVITES_JSON:JSON.stringify({tester:digest(code)})},fetcher:()=>{throw Error('No inference');}}));
 await new Promise(r=>server.listen(0,'127.0.0.1',r));t.after(()=>new Promise(r=>server.close(r)));
 const origin='http://127.0.0.1:'+server.address().port;
 const login=await fetch(origin+'/login',{method:'POST',headers:{Origin:origin,'Content-Type':'application/json'},body:JSON.stringify({code}),redirect:'manual'});
 const cookie=login.headers.get('set-cookie').split(';')[0];return {origin,cookie,accesses,get:(url,headers={})=>fetch(origin+url,{headers:{Cookie:cookie,...headers},redirect:'manual'})};
}
test('inspection HTML requires invitation, forbids embedding/network and adds bootstrap only',async t=>{
 const f=await fixture(t);assert.equal((await fetch(f.origin+'/shop',{redirect:'manual'})).status,303);
 const r=await f.get('/shop?dp=w');assert.equal(r.status,200);assert.equal(r.headers.get('x-frame-options'),'DENY');assert.match(r.headers.get('content-security-policy'),/connect-src 'none'/);
 assert.match(r.headers.get('content-security-policy'),/frame-ancestors 'none'/);assert.match(await r.text(),/inspection.js/);
 assert.equal((await f.get('/shop?dp=s')).status,400);assert.deepEqual(f.accesses,[]);
});
test('all exact dataset assets authenticate and use private caching, with no store operations',async t=>{
 const f=await fixture(t),manifest=JSON.parse(await readFile('private-assets/inspection-shop/manifest.json','utf8'));
 for(const [name,hash] of Object.entries(manifest.files)){
  if(name==='index.html')continue;
  const r=await f.get('/'+name);assert.equal(r.status,200,name);assert.equal(digest(Buffer.from(await r.arrayBuffer())),hash,name);
  assert.equal(r.headers.get('cache-control'),'private, max-age=86400, immutable');assert.equal(r.headers.get('vercel-cdn-cache-control'),'no-store');
 }
 const name=Object.keys(manifest.files).find(x=>x.endsWith('.js')),etag='"'+manifest.files[name]+'"';
 assert.equal((await f.get('/'+name,{'If-None-Match':etag})).status,304);
 assert.equal((await fetch(f.origin+'/'+name,{headers:{'If-None-Match':etag},redirect:'manual'})).status,303);
 assert.equal((await f.get('/assets/manifest.json')).status,404);assert.equal((await f.get('/inspection-shop/manifest.json')).status,404);
 assert.deepEqual(f.accesses,[]);
});
