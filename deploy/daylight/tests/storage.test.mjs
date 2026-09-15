import test from 'node:test';
import assert from 'node:assert/strict';
import * as blob from '@vercel/blob';
import {BlobStore,StorageError} from '../lib/store.mjs';
import {createHandler} from '../api/index.mjs';
import {config,digest,login,sessionCookie} from '../lib/auth.mjs';

const token='fake-secret-never-logged';
test('missing Blob configuration fails before any SDK request',async()=>{
  let calls=0;
  const store=new BlobStore({env:{},sdk:{get(){calls++;},put(){calls++;}}});
  for(const [operation,args] of [['read',['key']],['write',['key',{}]]])
    await assert.rejects(store[operation](...args),e=>e instanceof StorageError&&e.code==='BLOB_TOKEN_MISSING'&&e.operation===operation);
  assert.equal(calls,0);
});
test('SDK errors map to fixed diagnostics without leaking messages or retrying',async()=>{
  const cases=[
    [new blob.BlobAccessError(),'BLOB_ACCESS_DENIED'],
    [new blob.BlobStoreNotFoundError(),'BLOB_STORE_NOT_FOUND'],
    [new blob.BlobStoreSuspendedError(),'BLOB_STORE_SUSPENDED'],
    [new blob.BlobPreconditionFailedError(),'BLOB_WRITE_CONFLICT'],
    [new blob.BlobServiceRateLimited(10),'BLOB_RATE_LIMITED'],
    [new blob.BlobServiceNotAvailable(),'BLOB_SERVICE_UNAVAILABLE'],
    [new blob.BlobError('Failed to fetch blob: 403 Forbidden'),'BLOB_ACCESS_DENIED'],
    [new blob.BlobError('Invalid token: unable to extract store ID'),'BLOB_TOKEN_INVALID'],
    [new blob.BlobError('Cannot use private access on a public store'),'BLOB_ACCESS_MODE_MISMATCH'],
    [new Error(token),'BLOB_OPERATION_FAILED'],
  ];
  for(const [failure,code] of cases) {
    let calls=0;
    const fail=async()=>{calls++;throw failure;};
    const store=new BlobStore({env:{BLOB_READ_WRITE_TOKEN:token},sdk:{get:fail,put:fail}});
    for(const [operation,args] of [['read',['key']],['write',['key',{}]]])
      await assert.rejects(store[operation](...args),e=>e.code===code&&!e.message.includes(token));
    assert.equal(calls,2);
  }
});
test('Blob reads retain ETags and conditional writes remain private',async()=>{
  const calls=[];
  const store=new BlobStore({env:{BLOB_READ_WRITE_TOKEN:token},sdk:{
    async get(key,options){calls.push(options);return {statusCode:200,stream:new Response('{"ok":true}').body,blob:{etag:'original'}};},
    async put(key,value,options){calls.push(options);assert.deepEqual(JSON.parse(value),{ok:true});return {etag:'next'};},
  }});
  const prior=await store.read('key');assert.equal(prior.etag,'original');
  assert.equal(await store.write('key',prior.value,prior.etag),'next');
  assert.equal(calls[0].useCache,false);assert.equal(calls[1].ifMatch,'original');assert.equal(calls[1].allowOverwrite,true);
  for(const options of calls){assert.equal(options.access,'private');assert.equal(options.token,token);}
});
test('missing storage at API start gives actionable response and fixed runtime log',async()=>{
  const env={DEMO_SESSION_SECRET:'s'.repeat(64),DEMO_INVITES_JSON:JSON.stringify({test:digest('a'.repeat(43))})};
  let inference=0,body,status;const logs=[];
  const handler=createHandler({env,fetcher:async()=>{inference++;}});
  const cookie=sessionCookie(login('a'.repeat(43),config(env)));
  const original=console.error;console.error=line=>logs.push(JSON.parse(line));
  try {
    await handler({method:'POST',url:'/api/start',headers:{host:'demo.example',origin:'https://demo.example',cookie},
      body:{mode:'chat',goal:'What is here?'}},{setHeader(){},set statusCode(value){status=value;},end(value){body=JSON.parse(value);}});
  } finally {console.error=original;}
  assert.equal(status,503);assert.equal(body.code,'BLOB_TOKEN_MISSING');assert.match(body.error,/BLOB_READ_WRITE_TOKEN/);
  assert.equal(inference,0);assert.deepEqual(logs,[{event:'daylight_request_failed',code:'BLOB_TOKEN_MISSING',stage:'agent_storage',operation:'start',storage_operation:'write'}]);
});

test('connected OIDC store delegates token refresh to the SDK',async()=>{
  const calls=[];
  const store=new BlobStore({env:{BLOB_STORE_ID:'store_example'},sdk:{
    async get(key,options){calls.push(options);return null;},
    async put(key,value,options){calls.push(options);return {etag:'created'};},
  }});
  assert.equal(await store.read('missing'),null);
  assert.equal(await store.write('key',{}),'created');
  for(const options of calls){assert.equal(options.storeId,'store_example');assert.ok(!('token' in options));assert.ok(!('oidcToken' in options));}
});
