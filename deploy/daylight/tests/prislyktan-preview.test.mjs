import test from 'node:test';
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {readFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {createHandler} from '../api/index.mjs';
import {digest} from '../lib/auth.mjs';
import {prislyktanAsset} from '../lib/prislyktan-preview.mjs';

test('original preview assets are hashed, protected before cache validation and read-only',async t=>{
 const root=new URL('../private-assets/',import.meta.url).pathname;
 const manifest=JSON.parse(await readFile(root+'prislyktan/manifest.json'));
 for(const [name,sha] of Object.entries(manifest.output_files)){
  const asset=await prislyktanAsset(root,'/environments/prislyktan/'+name);
  assert.equal(createHash('sha256').update(asset.raw).digest('hex'),sha);
 }
 for(const path of ['../manifest.json','manifest.json','%2e%2e/manifest.json','missing.js'])assert.equal(await prislyktanAsset(root,'/environments/prislyktan/'+path),null);
 const code='preview-test-invitation-'.repeat(3);
 const env={DEMO_SESSION_SECRET:'preview-test-secret-'.repeat(4),DEMO_INVITES_JSON:JSON.stringify({reviewer:digest(code)})};
 const server=createServer(createHandler({env,local:true}));
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 t.after(()=>new Promise(r=>{server.closeAllConnections();server.close(r);}));
 const origin='http://127.0.0.1:'+server.address().port,url=origin+'/environments/prislyktan';
 const anon=await fetch(url,{redirect:'manual'});assert.equal(anon.status,303);
 const login=await fetch(origin+'/login',{method:'POST',headers:{origin,'Content-Type':'application/json'},body:JSON.stringify({code}),redirect:'manual'});
 assert.equal(login.status,303);const cookie=login.headers.get('set-cookie').split(';')[0];
 const response=await fetch(url,{headers:{cookie}});assert.equal(response.status,200);
 assert.match(response.headers.get('content-security-policy'),/connect-src 'none'/);
 assert.match(response.headers.get('cache-control'),/^private/);
 const etag=response.headers.get('etag');assert(etag);
 assert.equal((await fetch(url,{headers:{cookie,'If-None-Match':etag}})).status,304);
 assert.equal((await fetch(url,{headers:{'If-None-Match':etag},redirect:'manual'})).status,303);
 assert.equal((await fetch(url,{method:'POST',headers:{cookie,origin}})).status,405);
 assert.equal((await fetch(origin+'/environments/prislyktan/retailers/nordbyte',{headers:{cookie}})).status,200);
});
