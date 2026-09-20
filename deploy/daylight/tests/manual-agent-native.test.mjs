import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {SqliteStore} from '../lib/sqlite-store.mjs';
import {modelRequest,infer} from '../lib/manual-agent.mjs';

const decision={protocol:'native-core-v1',session_id:'child-episode',native_options:{
  tools:[{type:'function',function:{name:'noop',parameters:{type:'object'}}}],tool_choice:'required',
  model:'untrusted-override',provider:{only:['unapproved']},max_tokens:1}};
test('native transport preserves fixed tools and child session, not runtime overrides',()=>{
 const request=modelRequest({MODEL_NAME:'qwen/qwen3.8-27b'},'outer-human-browser',[],decision);
 assert.equal(request.session_id,'child-episode');assert.equal(request.model,'qwen/qwen3.8-27b');
 assert.equal(request.max_tokens,4096);assert(!request.provider.only.includes('unapproved'));
 assert.deepEqual(request.tools,decision.native_options.tools);assert.equal(request.tool_choice,'required');
 assert(!Object.hasOwn(request,'response_format'));
});
test('transient native error returns exact evidence for core recovery with a fresh reservation each time',async t=>{
 const root=await mkdtemp(tmpdir()+'/native-transport-'),store=new SqliteStore(root+'/state.sqlite');
 t.after(async()=>{store.close();await rm(root,{recursive:true,force:true});});
 const steps=[],requests=[];
 for(let i=0;i<2;i++){
  const step={decision};steps.push(step);
  await infer({store,env:{OPENROUTER_API_KEY:'offline',DEMO_DAILY_BUDGET_USD:'1'},sessionID:'browser',messages:[],step,signal:new AbortController().signal,persist:async()=>{},fetcher:async(url,opts)=>{
   requests.push(JSON.parse(opts.body));return new Response(JSON.stringify({error:{message:'Busy'}}),{status:429,headers:{'retry-after':'3'}});
  }});
 }
 assert.equal(requests.length,2);
 for(const step of steps){assert.equal(step.http_status,429);assert.equal(step.retry_after,'3');assert.equal(step.response.error.message,'Busy');assert(step.reservation);assert(step.dispatch_at);assert(step.finished_at);}
 assert.equal(steps[0].error,'OpenRouter returned HTTP 429');
});
