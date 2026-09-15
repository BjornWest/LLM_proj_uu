import test from 'node:test';
import assert from 'node:assert/strict';
import {gzipSync} from 'node:zlib';
import {MockAgent,getGlobalDispatcher,setGlobalDispatcher} from 'undici';
import * as blob from '@vercel/blob';
import {BlobStore} from '../lib/store.mjs';
import {Agent} from '../lib/agent.mjs';

test('actual SDK GET plus agent lifecycle: compressed representation conflicts; identity preserves CAS',async()=>{
  const previous=getGlobalDispatcher();
  try {
    for(const legacy of [true,false]) {
      const transport=new MockAgent();transport.disableNetConnect();setGlobalDispatcher(transport);
      try {
      const objects=new Map();let revision=0,modelCalls=0;const encodings=[];
      const origin=transport.get('https://teststore.private.blob.vercel-storage.com');
      origin.intercept({path:/.*/,method:'GET'}).reply(options=>{
        const key=new URL(options.path,'https://fixture.test').pathname.slice(1),saved=objects.get(key);
        if(!saved)return {statusCode:404,data:''};
        const headers=new Headers(options.headers),encoding=headers.get('accept-encoding');encodings.push(encoding);
        const compress=encoding!=='identity'&&saved.body.length>1000;
        return {statusCode:200,data:compress?gzipSync(saved.body):saved.body,responseOptions:{headers:{
          'content-type':'application/json',etag:(compress?'W/':'')+saved.etag,...(compress?{'content-encoding':'gzip'}:{})}}};
      }).persist();
      const sdk={
        get:async(key,options)=>{
          if(legacy){options={...options};delete options.headers;}
          return blob.get(key,options); // Real SDK and HTTP decoding; network is intercepted.
        },
        put:async(key,body,options)=>{
          const previous=objects.get(key);
          assert.equal(options.access,'private');
          if(previous&&(options.ifMatch!==previous.etag||options.allowOverwrite!==true))throw new blob.BlobPreconditionFailedError();
          assert.ok(previous||!options.ifMatch);
          const etag=`"revision-${++revision}"`;objects.set(key,{body,etag});return {etag};
        },
      };
      const store=new BlobStore({env:{BLOB_READ_WRITE_TOKEN:'vercel_blob_rw_teststore_fake'},sdk});
      const agent=new Agent(store,{env:{OPENROUTER_API_KEY:'test-not-real'},provenance:{fixture:'trace-sized-data '.repeat(300)},fetcher:async()=>{
        modelCalls++;
        return new Response(JSON.stringify({choices:[{message:{content:'{"action":"done"}'}}],usage:{cost:0},provider:'offline'}));
      }});
      const {id}=await agent.start('test',{mode:'task',goal:'Finish this fictional test'});
      if(legacy) {
        await assert.rejects(agent.step('test',{id,observation:{text:'Page',controls:[]}}),error=>error.code==='BLOB_WRITE_CONFLICT');
        assert.equal(modelCalls,0);
      } else {
        const result=await agent.step('test',{id,observation:{text:'Page',controls:[]}});
        assert.equal(result.status,'awaiting_client');assert.equal(result.error,null);assert.equal(modelCalls,1);
        assert.equal((await agent.event('test',{id,result:{stop:true,description:'Done'}})).status,'complete');
        const saved=(await agent.read('test',id)).value;
        assert.equal(saved.steps[0].request.session_id,id);assert.equal(saved.steps[0].usage.cost,0);
        assert.ok(saved.steps[0].reservation.amount_usd>0);assert.equal(saved.status,'complete');
        assert.ok(encodings.every(value=>value==='identity'));
      }
      } finally {await transport.close();}
    }
  } finally {setGlobalDispatcher(previous);}
});
