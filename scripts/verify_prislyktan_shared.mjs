// Actual control -> pipe -> BrowserGym, offline model transport, no paid calls.
import {Manual} from '../deploy/daylight/lib/manual.mjs';
import {SqliteStore} from '../deploy/daylight/lib/sqlite-store.mjs';
import {mkdir,writeFile,readFile} from 'node:fs/promises';
import path from 'node:path';
import {randomUUID} from 'node:crypto';
import assert from 'node:assert/strict';
const output=path.resolve(process.argv[2]);await mkdir(output,{recursive:false});
const store=new SqliteStore(output+'/state.sqlite'),calls=[],counts=new Map();
let origins;
const env={DAYLIGHT_MANUAL_PACKAGE:process.env.MANUAL_TEST_PACKAGE,DAYLIGHT_MANUAL_ROOT:output+'/sessions',DAYLIGHT_MANUAL_DRIVER:process.env.MANUAL_TEST_DRIVER||path.resolve('scripts/manual_environment.py'),DAYLIGHT_MANUAL_PYTHON:process.env.MANUAL_TEST_PYTHON||path.resolve('.venv/bin/python'),DAYLIGHT_BROWSE_ENABLED:'1',OPENROUTER_API_KEY:'offline',DEMO_DAILY_BUDGET_USD:'1'};
const manual=new Manual(store,{env,pool:{status:async()=>({sites:[]})},fetcher:async(url,options)=>{
 const request=JSON.parse(options.body);calls.push(request);const n=(counts.get(request.session_id)||0)+1;counts.set(request.session_id,n);
 const found=request.tools.find(t=>t.function.name==='goto').function.description.match(/http:\/\/127\.0\.0\.1:\d+/g);
 assert.equal(new Set(found).size,4);origins??=[...new Set(found)];assert.deepEqual([...new Set(found)],origins);
 const name=n===1?'goto':'send_msg_to_user',args=n===1?{url:origins[1]+'/'}:{text:'Inspected the same retailer browser.'};
 return new Response(JSON.stringify({provider:'scripted',model:request.model,usage:{cost:0},choices:[{finish_reason:'tool_calls',message:{role:'assistant',content:null,tool_calls:[{id:'call'+n,type:'function',function:{name,arguments:JSON.stringify(args)}}]}}]}),{status:200});
}});
const checks=[];function check(label,value){assert(value,label);checks.push(label);}
try{
 const config=await manual.config();check('four-origin site advertised for manual/Ask',config.sites.some(s=>s.site_id==='prislyktan'&&s.available));
 let row=await manual.start('validation',{task:'browse.prislyktan'});const id=row.id,initial=row.frame.page_url;
 row=await manual.command('validation',id,'action',{request_id:randomUUID(),frame_id:row.frame.id,action:{type:'press',key:'Tab'}});
 check('human action before Ask',row.action_count===1&&!row.last_error);
 for(let i=0;i<2;i++){
  await manual.ask('validation',id,{request_id:randomUUID(),goal:'Inspect the retailer homepage without buying anything.'});await manual.live.get(id).work;row=await manual.read('validation',id);
  check('Ask '+i+' completes in existing browser',row.status==='ready'&&row.controller==='human'&&row.asks[i].status==='complete'&&row.frame.page_url===origins[1]+'/');
 }
 check('Ask turns have distinct inference sessions',counts.size===2&&calls.length===4);
 check('same original site lifetime and four-origin allowlist',initial===origins[0]+'/'&&row.action_count===3);
 const saved=(await store.read('daylight/manual/'+id+'.json')).value;
 check('native action evidence retained',row.asks.every(a=>a.steps.length===2&&a.steps[0].executed===true&&a.steps[1].executed===false));
 row=await manual.command('validation',id,'close',{request_id:randomUUID()});check('closed without task grading',row.status==='finished'&&row.evaluation===null&&row.reference_evaluation===null);
 await writeFile(output+'/report.json',JSON.stringify({passed:true,checks,model_calls:0,mock_calls:calls.length,trace:saved.trace_directory,session:row},null,2));
 console.log(JSON.stringify(checks));
}finally{manual.shutdown();store.close();}
