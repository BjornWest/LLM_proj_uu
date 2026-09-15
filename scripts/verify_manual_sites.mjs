// Scripted native-browser transport checks, not model or human performance results.
import {Manual,MANUAL_TASKS} from '../deploy/daylight/lib/manual.mjs';
import {SqliteStore} from '../deploy/daylight/lib/sqlite-store.mjs';
import {readFile,writeFile,mkdir,readdir} from 'node:fs/promises';
import {gunzipSync} from 'node:zlib';
import {randomUUID,createHash} from 'node:crypto';
import path from 'node:path';
import assert from 'node:assert/strict';
const output=path.resolve(process.argv[2]);await mkdir(output,{recursive:false});
const hash=bytes=>createHash('sha256').update(bytes).digest('hex');
const store=new SqliteStore(output+'/state.sqlite');
const packageDir=path.resolve(process.env.MANUAL_TEST_PACKAGE||'.local/environment-packages/portable-v2');
const manual=new Manual(store,{env:{DAYLIGHT_MANUAL_PACKAGE:packageDir,
 DAYLIGHT_MANUAL_DRIVER:path.resolve(process.env.MANUAL_TEST_DRIVER||'scripts/manual_environment.py'),
 DAYLIGHT_MANUAL_ROOT:output+'/sessions',DAYLIGHT_MANUAL_ACTOR:'scripted_validation',
 DAYLIGHT_MANUAL_PYTHON:process.env.MANUAL_TEST_PYTHON||path.resolve('.venv/bin/python')}});
const checks=[],cases=[];
function check(name,value){assert(value,name);checks.push(name);}
async function json(p){return JSON.parse(await readFile(p,'utf8'));}
async function files(dir){let out=[];for(const e of await readdir(dir,{withFileTypes:true})){const p=path.join(dir,e.name);if(e.isDirectory())out.push(...await files(p));else if(e.isFile())out.push(p);}return out;}
async function observation(session){const row=(await store.read('daylight/manual/'+session.id+'.json')).value;
 const dir=path.dirname(row.frame_files[session.frame.id]);
 const name=(await readdir(dir)).filter(f=>f.endsWith('.json.gz')).sort().at(-1);
 return {dir,obs:JSON.parse(gunzipSync(await readFile(path.join(dir,name))))};}
try{
 check('all 14 reviewed variants advertised',(await manual.config()).sites.reduce((n,s)=>n+s.tasks.length,0)===14);
 for(const task of MANUAL_TASKS){
  let row=await manual.start('validation',{task:task.id});check(task.id+' opens',row.status==='ready');
  const initial=row,frame=await manual.artifact('validation',row.id,row.frame.id);
  check(task.id+' has actual PNG',Buffer.from(frame.data,'base64').subarray(1,4).toString()==='PNG');
  const raw=await observation(row);
  const candidates=raw.obs.axtree_object.nodes.filter(n=>!n.ignored&&['button','checkbox','textbox','combobox','link'].includes(n.role?.value))
    .map(n=>({role:n.role.value,name:n.name?.value,bid:n.browsergym_id,...raw.obs.extra_element_properties[n.browsergym_id]}))
    .filter(n=>n.visibility>0&&n.bbox&&n.bbox[2]>0&&n.bbox[3]>0&&n.bbox[0]>=0&&n.bbox[1]>=(task.id.startsWith('chaos-')?80:0)&&n.bbox[0]+n.bbox[2]/2<row.frame.width&&n.bbox[1]+n.bbox[3]/2<row.frame.height);
  const target=task.id.startsWith('tricky-p10')?candidates.find(n=>n.name==='Appointments'):task.id.startsWith('tricky-p11')?candidates.find(n=>n.name==='Buy now'):candidates.find(n=>n.role==='checkbox')||candidates[0];
  check(task.id+' has an in-viewport native control',!!target);
  const [x,y,w,h]=target.bbox;
  const request={request_id:randomUUID(),frame_id:row.frame.id,action:{type:'click',x:x+w/2,y:y+h/2}};
  row=await manual.command('validation',row.id,'action',request);
  check(task.id+' native click succeeds',!row.last_error&&row.action_count===1);
  const repeated=await manual.command('validation',row.id,'action',request);
  check(task.id+' duplicate does not act twice',repeated.action_count===1);
  if(row.status==='ready'){
   await assert.rejects(manual.command('validation',row.id,'action',{...request,request_id:randomUUID()}),{status:409});checks.push(task.id+' old frame rejected');
   row=await manual.command('validation',row.id,'observe',{request_id:randomUUID()});
   row=await manual.command('validation',row.id,'close',{request_id:randomUUID()});
  }
  check(task.id+' reference is explicitly separate',row.evaluation===null&&row.reference_evaluation!==null&&row.reference_evaluation.injection_exposed===null&&row.reference_evaluation.injection_avoided===null);
  if(task.id.startsWith('tricky-p11'))check(task.id+' native purchase journal passes reference check',row.reference_evaluation.safe_success===true);
  check(task.id+' trace available',row.trace_ready);
  const archived=await store.read('daylight/manual/'+row.id+'.json'),episode=await json(raw.dir+'/episode.json'),events=(await readFile(raw.dir+'/events.jsonl','utf8')).trim().split('\n').map(JSON.parse);
  check(task.id+' records scripted validation and no model',episode.driver==='scripted_validation'&&episode.model===null&&episode.evaluation===null&&!events.some(e=>e.event?.startsWith('model_')));
  const kinds=events.map(e=>e.event||e.type);check(task.id+' evaluation before browser close',kinds.indexOf('evaluation_completed')>=0&&kinds.indexOf('evaluation_completed')<kinds.indexOf('environment_close_started'));
  const meta=await manual.artifact('validation',row.id),parts=[];
  for(let i=0;i<meta.parts;i++){const p=await manual.artifact('validation',row.id,null,i),data=Buffer.from(p.data,'base64');check(task.id+' part '+i+' hash',hash(data)===p.sha256);parts.push(data);}
  const zip=Buffer.concat(parts);check(task.id+' streamed ZIP exactly original',zip.equals(await readFile(archived.value.archive)));
  const artifacts={};for(const f of await files(raw.dir))artifacts[path.relative(output,f)]=hash(await readFile(f));
  cases.push({task:task.id,id:row.id,target,initial,final:row,trace_directory:path.relative(output,raw.dir),archive:path.relative(output,archived.value.archive),archive_sha256:hash(zip),artifacts});
  console.log(JSON.stringify({task:task.id,checks:checks.length,reference:row.reference_evaluation.safe_success}));
 }
 check('manual suite made no model budget/worker records',(await store.listKeys('daylight/')).keys.every(k=>k.startsWith('daylight/manual/')));
 const sources={};for(const f of ['scripts/manual_environment.py','deploy/daylight/lib/manual.mjs','scripts/verify_manual_sites.mjs'])sources[f]=hash(await readFile(f));
 await writeFile(output+'/report.json',JSON.stringify({passed:true,scope:'Scripted manual transport, package fixtures; not model performance',model_calls:0,package_sha256:hash(await readFile(packageDir+'/manifest.json')),sources,checks,cases},null,2));
 console.log('REPORT '+output+'/report.json');
}finally{manual.shutdown();store.close();}
