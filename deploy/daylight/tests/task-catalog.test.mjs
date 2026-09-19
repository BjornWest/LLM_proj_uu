import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {createHandler} from '../api/index.mjs';
import {config,digest,login,sessionCookie} from '../lib/auth.mjs';
const env={DEMO_SESSION_SECRET:'s'.repeat(64),DEMO_INVITES_JSON:JSON.stringify({test:digest('a'.repeat(43))}),DAYLIGHT_STORAGE_MAINTENANCE:'1'};
const cookie=sessionCookie(login('a'.repeat(43),config(env)));
const handler=createHandler({env,store:new Proxy({},{get(){throw Error('Catalog must not access storage');}}),fetcher(){throw Error('Catalog must not access network');}});
async function request(method='GET',authenticated=true){
 const headers={};let value;
 const res={setHeader(k,v){headers[k]=v;},end(v){value=v;}};
 await handler({method,url:'/api/task-catalog',headers:{host:'demo.example',origin:'https://demo.example',...(authenticated?{cookie}:{})}},res);
 return {status:res.statusCode,headers,body:String(value)};
}
test('catalog is authenticated and read-only',async()=>{
 assert.equal((await request('GET',false)).status,401);
 assert.equal((await request('POST')).status,405);
});
test('catalog serves exact frozen bytes without PC, storage or inference, including maintenance',async()=>{
 const result=await request();assert.equal(result.status,200);
 assert.equal(result.headers['Cache-Control'],'private, no-store');
 const source=await readFile(new URL('../../../data/curation/expansion/hosted-review-catalog.json',import.meta.url),'utf8');
 assert.equal(result.body,source);
 assert.equal(createHash('sha256').update(result.body).digest('hex'),'ff5dc3550ed053a9f8c3c7bdd7fe3b375416a219c49fef9c52d58994edbe97f4');
 const catalog=JSON.parse(result.body);assert.equal(catalog.tasks.length,203);
 assert.ok(catalog.tasks.every(t=>t.execution_available===false));
 const provenance=JSON.parse(await readFile(new URL('../private-assets/provenance.json',import.meta.url)));
 assert.equal(provenance.assets['task-catalog.json'],createHash('sha256').update(source).digest('hex'));
});
