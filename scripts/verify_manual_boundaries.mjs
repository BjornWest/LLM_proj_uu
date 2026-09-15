// Additional native keyboard, isolation and error-publication checks. No model calls.
import {Manual} from '../deploy/daylight/lib/manual.mjs';
import {SqliteStore} from '../deploy/daylight/lib/sqlite-store.mjs';
import {mkdir,readFile,readdir,writeFile} from 'node:fs/promises';
import {gunzipSync} from 'node:zlib';
import {randomUUID,createHash} from 'node:crypto';
import path from 'node:path';
import assert from 'node:assert/strict';
const root=path.resolve(process.argv[2]);await mkdir(root,{recursive:false});
const store=new SqliteStore(root+'/state.sqlite');
const manual=new Manual(store,{env:{DAYLIGHT_MANUAL_PACKAGE:path.resolve(process.env.MANUAL_TEST_PACKAGE||'.local/environment-packages/portable-v2'),
 DAYLIGHT_MANUAL_DRIVER:path.resolve(process.env.MANUAL_TEST_DRIVER||'scripts/manual_environment.py'),DAYLIGHT_MANUAL_ROOT:root+'/sessions',DAYLIGHT_MANUAL_ACTOR:'scripted_validation',
 DAYLIGHT_MANUAL_PYTHON:process.env.MANUAL_TEST_PYTHON||path.resolve('.venv/bin/python')}});
const checks=[],cases=[];const check=(name,x)=>{assert(x,name);checks.push(name);};
async function obs(row){const saved=(await store.read('daylight/manual/'+row.id+'.json')).value,dir=path.dirname(saved.frame_files[row.frame.id]);
 const file=(await readdir(dir)).filter(n=>n.endsWith('.json.gz')).sort().at(-1);return {dir,value:JSON.parse(gunzipSync(await readFile(dir+'/'+file)))};}
async function click(owner,row,select){const {value}=await obs(row),node=value.axtree_object.nodes.find(select);assert(node,'Test control present');
 const [x,y,w,h]=value.extra_element_properties[node.browsergym_id].bbox;return manual.command(owner,row.id,'action',{request_id:randomUUID(),frame_id:row.frame.id,action:{type:'click',x:x+w/2,y:y+h/2}});}
async function act(owner,row,action){return manual.command(owner,row.id,'action',{request_id:randomUUID(),frame_id:row.frame.id,action});}
async function close(owner,row){return manual.command(owner,row.id,'close',{request_id:randomUUID()});}
async function retain(row){const {dir}=await obs(row),events=(await readFile(dir+'/events.jsonl','utf8')).trim().split('\n').map(JSON.parse),episode=JSON.parse(await readFile(dir+'/episode.json','utf8'));
 check(row.task+' no model and no human-performance claim',episode.model===null&&episode.driver==='scripted_validation'&&episode.evaluation===null&&!events.some(e=>e.event.startsWith('model_')));
 const artifacts={};for(const f of await readdir(dir))artifacts[path.relative(root,dir+'/'+f)]=createHash('sha256').update(await readFile(dir+'/'+f)).digest('hex');
 cases.push({id:row.id,task:row.task,final:row,trace_directory:path.relative(root,dir),artifacts});return {dir,events,episode};}
try{
 let health=await manual.start('tester',{task:'tricky-p10-clean'});
 health=await click('tester',health,n=>n.role?.value==='link'&&n.name?.value==='My Profile');
 check('Unsupported health route stops with recorded error',health.status==='error'&&health.error.includes('supported health routes'));
 check('Completed native action survives later grader-capture failure',health.action_count===1&&health.trace_ready&&health.evaluation===null);
 check('No safe-success inferred after scope error',health.reference_evaluation.safe_success===null);
 const h=await retain(health);check('Action row retained before failing state capture',JSON.parse((await readFile(h.dir+'/steps.jsonl','utf8')).trim()).action.startsWith('mouse_click'));
 await assert.rejects(close('tester',health),{status:409});checks.push('Closed scope-error session cannot dispatch again');
 let form=await manual.start('tester',{task:'chaos-transfer-by-not-clicking-save'});
 form=await click('tester',form,n=>n.role?.value==='textbox'&&!n.properties?.some(p=>p.name==='readonly'&&p.value?.value));
 form=await act('tester',form,{type:'press',key:'ControlOrMeta+a'});
 form=await act('tester',form,{type:'type',text:'Manual keyboard test'});
 form=await act('tester',form,{type:'press',key:'Tab'});
 check('Native typed input is visible in actual resulting AX',(await obs(form)).value.axtree_object.nodes.some(n=>n.value?.value==='Manual keyboard test'));
 check('Native text/key sequence has no action error',form.action_count===4&&!form.last_error);
 form=await close('tester',form);await retain(form);
 let a=await manual.start('tester',{task:'tricky-p11-clean'}),b=await manual.start('other',{task:'tricky-p11-clean'});
 check('Independent browser origins',a.frame.page_url!==b.frame.page_url);
 a=await click('tester',a,n=>n.role?.value==='button'&&n.name?.value==='Buy now');a=await close('tester',a);
 b=await manual.command('other',b.id,'observe',{request_id:randomUUID()});b=await close('other',b);
 check('One owner purchase does not enter another browser journal',a.reference_evaluation.safe_success===true&&b.reference_evaluation.task_completed===false);
 await retain(a);await retain(b);
 const sources={};for(const f of ['scripts/manual_environment.py','deploy/daylight/lib/manual.mjs','scripts/verify_manual_boundaries.mjs'])sources[f]=createHash('sha256').update(await readFile(f)).digest('hex');
 await writeFile(root+'/report.json',JSON.stringify({passed:true,scope:'Scripted real manual browser boundaries, not model performance',model_calls:0,sources,checks,cases},null,2));
 console.log(JSON.stringify({checks:checks.length,report:root+'/report.json'}));
}finally{manual.shutdown();store.close();}
