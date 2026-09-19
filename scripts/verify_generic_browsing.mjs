// Scripted actual BrowserGym checks; no model or shared benchmark state.
import {Manual,BROWSE_TASKS} from '../deploy/daylight/lib/manual.mjs';
import {SqliteStore} from '../deploy/daylight/lib/sqlite-store.mjs';
import {mkdir,readFile,writeFile} from 'node:fs/promises';
import {randomUUID} from 'node:crypto';
import path from 'node:path';
const output=path.resolve(process.argv[2]);await mkdir(output,{recursive:true});
async function run(task){
 const dir=output+'/'+task.site_id;await mkdir(dir);
 const store=new SqliteStore(dir+'/state.sqlite');
 const manual=new Manual(store,{env:{DAYLIGHT_BROWSE_ENABLED:'1',DAYLIGHT_MANUAL_PACKAGE:path.resolve('.local/environment-packages/portable-full-v2'),DAYLIGHT_MANUAL_ROOT:dir+'/sessions',DAYLIGHT_MANUAL_DRIVER:path.resolve('scripts/manual_environment.py'),DAYLIGHT_MANUAL_PYTHON:path.resolve('.venv/bin/python')},pool:{async status(){return {sites:[]};}}});
 let row;
 try{
  row=await manual.start('validation',{task:task.id,site_revision:task.site_revision});
  if(row.status!=='ready'||!row.browse_only||row.ask_enabled||row.reference_goal!==null)throw Error('Invalid generic session');
  await manual.read('validation',row.id);
  for(const type of ['reload','back','forward','scroll']){
   const action=type==='scroll'?{type,dx:0,dy:300}:{type};
   row=await manual.command('validation',row.id,'action',{request_id:randomUUID(),frame_id:row.frame.id,action});
   if(row.last_error||row.status!=='ready')throw Error(row.last_error||row.status);
  }
  row=await manual.command('validation',row.id,'close',{request_id:randomUUID()});
  if(row.evaluation!==null||row.reference_evaluation!==null||!row.trace_ready)throw Error('Browse mode incorrectly graded or trace missing');
  await writeFile(dir+'/report.json',JSON.stringify({passed:true,model_calls:0,session:row},null,2));
  return {site:task.site_id,passed:true,actions:row.action_count};
 }finally{manual.shutdown();store.close();}
}
const results=await Promise.allSettled(BROWSE_TASKS.filter(t=>t.site_id.startsWith('tricky-')).map(run));
await writeFile(output+'/report.json',JSON.stringify(results,null,2));console.log(results);
if(results.some(r=>r.status==='rejected'))process.exitCode=1;
