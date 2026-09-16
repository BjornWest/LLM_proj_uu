// Container-compatible scripted transport validation. No real model endpoint calls.
import {Manual,MANUAL_TASKS} from '../deploy/daylight/lib/manual.mjs';
import {SqliteStore} from '../deploy/daylight/lib/sqlite-store.mjs';
import {mkdir,readFile,writeFile} from 'node:fs/promises';
import {randomUUID,createHash} from 'node:crypto';
import path from 'node:path';
import assert from 'node:assert/strict';
const output=path.resolve(process.argv[2]);await mkdir(output,{recursive:false});
const store=new SqliteStore(output+'/state.sqlite'),counts=new Map(),checks=[],cases=[];
const hash=x=>createHash('sha256').update(x).digest('hex');
const env={DAYLIGHT_MANUAL_PACKAGE:process.env.MANUAL_TEST_PACKAGE||'/package',DAYLIGHT_MANUAL_ROOT:output+'/sessions',DAYLIGHT_MANUAL_DRIVER:process.env.MANUAL_TEST_DRIVER||'/app/scripts/manual_environment.py',DAYLIGHT_MANUAL_PYTHON:process.env.MANUAL_TEST_PYTHON||'/usr/local/bin/python',DAYLIGHT_MANUAL_ACTOR:'scripted_validation',OPENROUTER_API_KEY:'offline-key',DEMO_DAILY_BUDGET_USD:'5'};
const manual=new Manual(store,{env,fetcher:async(url,options)=>{
 const request=JSON.parse(options.body),n=(counts.get(request.session_id)||0)+1;counts.set(request.session_id,n);
 const action=n===1?'noop(0)':'send_msg_to_user("Observed this same session.")';
 return new Response(JSON.stringify({model:request.model,provider:'scripted',usage:{cost:0.0001},choices:[{message:{content:JSON.stringify({action})}}]}),{status:200});
}});
function check(name,value){assert(value,name);checks.push(name);}
try{
 for(const task of MANUAL_TASKS){
  let row=await manual.start('validation',{task:task.id,site_revision:task.site_revision}),id=row.id;
  row=await manual.command('validation',id,'action',{request_id:randomUUID(),frame_id:row.frame.id,action:{type:'press',key:'Tab'}});
  check(task.id+' human action succeeds',row.action_count===1&&!row.last_error);
  await manual.ask('validation',id,{request_id:randomUUID(),goal:'Inspect the current page without changing anything.'});await manual.live.get(id).work;row=await manual.read('validation',id);
  check(task.id+' same session resumes human control',row.id===id&&row.status==='ready'&&row.controller==='human');
  check(task.id+' agent noop and answer recorded',row.asks[0].status==='complete'&&row.action_count===2&&counts.get(id)===2);
  row=await manual.command('validation',id,'action',{request_id:randomUUID(),frame_id:row.frame.id,action:{type:'press',key:'Tab'}});
  check(task.id+' human can continue after agent',row.action_count===3&&!row.last_error);
  row=await manual.command('validation',id,'close',{request_id:randomUUID()});
  check(task.id+' diagnostic is separate',row.evaluation===null&&row.reference_evaluation!==null&&row.reference_evaluation.injection_exposed===null);
  const record=(await store.read('daylight/manual/'+id+'.json')).value;
  const episode=JSON.parse(await readFile(record.trace_directory+'/episode.json'));
  check(task.id+' combined trace identifies actual actor types',episode.driver==='shared-browser'&&episode.model_attempt_count===2);
  const meta=await manual.artifact('validation',id),parts=[];
  for(let i=0;i<meta.parts;i++)parts.push(Buffer.from((await manual.artifact('validation',id,null,i)).data,'base64'));
  const bytes=Buffer.concat(parts);await writeFile(output+'/'+id+'.zip',bytes);
  check(task.id+' archive complete size',bytes.length===meta.size);
  cases.push({task:task.id,id,asks:row.asks,trace:record.trace_directory,archive:id+'.zip',archive_sha256:hash(bytes)});
  console.log(task.id+' PASS');
 }
 const sources={};for(const f of ['scripts/manual_environment.py','scripts/shared_browser_policy.py','deploy/daylight/lib/manual.mjs','deploy/daylight/lib/manual-agent.mjs'])sources[f]=hash(await readFile('/app/'+f));
 await writeFile(output+'/report.json',JSON.stringify({passed:true,paid_calls:0,model_calls:0,mock_calls:[...counts.values()].reduce((n,v)=>n+v,0),checks,cases,sources},null,2));
 console.log('REPORT '+output+'/report.json');
}finally{manual.shutdown();store.close();}
