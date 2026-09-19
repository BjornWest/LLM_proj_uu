import {Manual,BROWSE_TASKS} from '../deploy/daylight/lib/manual.mjs';
import {SqliteStore} from '../deploy/daylight/lib/sqlite-store.mjs';
import {mkdir,readFile,readdir,writeFile} from 'node:fs/promises';
import {gunzipSync} from 'node:zlib';
import {randomUUID} from 'node:crypto';
import path from 'node:path';
const output=path.resolve(process.argv[2]);await mkdir(output,{recursive:true});
const store=new SqliteStore(output+'/state.sqlite');
const manual=new Manual(store,{env:{DAYLIGHT_BROWSE_ENABLED:'1',DAYLIGHT_MANUAL_PACKAGE:path.resolve('.local/environment-packages/portable-full-v2'),DAYLIGHT_MANUAL_ROOT:output+'/sessions',DAYLIGHT_MANUAL_DRIVER:path.resolve('scripts/manual_environment.py'),DAYLIGHT_MANUAL_PYTHON:path.resolve('.venv/bin/python')},pool:{async status(){return {sites:[]};}}});
const task=BROWSE_TASKS.find(t=>t.site_id==='tricky-shop'),checks=[];
const check=(name,value)=>{if(!value)throw Error(name);checks.push(name);};
async function obs(row){const saved=(await store.read('daylight/manual/'+row.id+'.json')).value;const files=(await readdir(saved.trace_directory)).filter(n=>/^observation-\d+\.json\.gz$/.test(n)).sort();return JSON.parse(gunzipSync(await readFile(saved.trace_directory+'/'+files.at(-1))));}
const act=(owner,row,action)=>manual.command(owner,row.id,'action',{request_id:randomUUID(),frame_id:row.frame.id,action});
async function click(owner,row,name){
 for(let i=0;i<5;i++){
  const o=await obs(row),n=o.axtree_object.nodes.find(n=>n.name?.value===name&&n.browsergym_id);
  if(!n)throw Error('Missing '+name);
  const [x,y,w,h]=o.extra_element_properties[n.browsergym_id].bbox;
  if(y+h/2>0&&y+h/2<row.frame.height)return act(owner,row,{type:'click',x:x+w/2,y:y+h/2});
  row=await act(owner,row,{type:'scroll',dx:0,dy:y<0?-500:500});
 }
 throw Error('Unreachable '+name);
}
try{
 let [a,b]=await Promise.all(['alice','bob'].map(owner=>manual.start(owner,{task:task.id,site_revision:task.site_revision})));
 a=await click('alice',a,'Add Oral-B Precision Clean Toothbrush to cart');
 a=await click('alice',a,'View Shopping Cart');b=await click('bob',b,'View Shopping Cart');
 const texts=async row=>(await obs(row)).axtree_object.nodes.map(n=>n.name?.value||'').join('\n');
 const at=await texts(a),bt=await texts(b);await writeFile(output+'/alice-cart.txt',at);await writeFile(output+'/bob-cart.txt',bt);
 check('Alice cart retains added product',at.includes('Oral-B Precision Clean Toothbrush'));
 check('Bob simultaneous cart excludes Alice product',!bt.includes('Oral-B Precision Clean Toothbrush'));
 a=await act('alice',a,{type:'reload'});check('Reload keeps same session cart',(await texts(a)).includes('Oral-B Precision Clean Toothbrush'));
 await Promise.all([manual.command('alice',a.id,'close',{request_id:randomUUID()}),manual.command('bob',b.id,'close',{request_id:randomUUID()})]);
 let c=await manual.start('alice',{task:task.id,site_revision:task.site_revision});c=await click('alice',c,'View Shopping Cart');
 check('Fresh same-owner session starts empty',!(await texts(c)).includes('Oral-B Precision Clean Toothbrush'));
 await manual.command('alice',c.id,'close',{request_id:randomUUID()});
 await writeFile(output+'/report.json',JSON.stringify({passed:true,checks,sessions:[a.id,b.id,c.id],model_calls:0},null,2));console.log(checks);
}finally{manual.shutdown();store.close();}
