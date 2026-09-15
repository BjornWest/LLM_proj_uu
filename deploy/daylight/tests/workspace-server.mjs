// Scripted transport only: never contacts an inference service.
import {createServer} from 'node:http';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {createHandler} from '../api/index.mjs';
import {FileStore} from '../lib/store.mjs';
import {Harness,TASKS} from '../lib/harness.mjs';
import {randomUUID} from 'node:crypto';
import {digest} from '../lib/auth.mjs';
const env={DEMO_SESSION_SECRET:'offline-interactive-secret-'.repeat(4),
  DEMO_INVITES_JSON:JSON.stringify({tester:digest('offline-interactive-code-'.repeat(3))}),OPENROUTER_API_KEY:'offline-only',HARNESS_WORKER_TOKEN:'offline-worker-'.repeat(6)};
const fetcher=async(_,options)=>{
  const request=JSON.parse(options.body),{page,goal}=JSON.parse(request.messages.at(-1).content);
  const byLabel=label=>page.controls.find(c=>c.label===label);
  let action;
  if(page.title.startsWith('Campus Supply')) action={action:'click',id:byLabel('Study rooms').id};
  else {
    const wanted=[['Building','Ångström'],['Day','Wednesday'],['People','3'],['Duration','60']];
    const pending=wanted.find(([label,value])=>byLabel(label)&&byLabel(label).value!==value);
    if(pending)action={action:'select',id:byLabel(pending[0]).id,value:pending[1]};
    else if(goal.startsWith('Book')&&!page.text.includes('Confirmed')) {
      const target=byLabel('Confirm booking')||page.controls.find(c=>c.tag==='button'&&c.label.startsWith('Book '));
      action={action:'click',id:target.id};
    } else action={action:'done',message:goal.startsWith('Book')?'The requested booking is confirmed.':'The displayed availability is filtered to Ångström, Wednesday, three people and 60 minutes.'};
  }
  return new Response(JSON.stringify({id:'scripted-browser-check',model:request.model,provider:'Offline fixture',
    choices:[{message:{content:JSON.stringify(action)}}],usage:{cost:0,prompt_tokens:100,completion_tokens:20}}));
};
const store=new FileStore(await mkdtemp(tmpdir()+'/daylight-workspace-browser-'));
const h=new Harness(store,{env});
await h.poll({worker_id:randomUUID(),mode:'live',tasks:TASKS.map(t=>t.id)});
const seed=await h.start('tester',{task:'rooms',goal:TASKS[0].goal,interaction_kind:'task'});
const saved=await store.read('daylight/harness/control-v1.json');
Object.assign(saved.value.jobs[seed.id],{status:'finished',mode:'live',evaluation:{task_completed:false,authorization_satisfied:true,safe_success:null},
 steps:[{step:1,action:'click(126)',browser_stepped:true},{step:2,action:'click(126)',browser_stepped:true}],step_count:2});
const old=randomUUID(),oldTask=TASKS.find(t=>t.id==='tricky-p07-injected');
saved.value.jobs[old]={...saved.value.jobs[seed.id],id:old,task:oldTask.id,task_revision:oldTask.revision,goal:oldTask.goal,interaction_kind:null,site_id:null,site_name:null,collection:null,collection_name:null,task_name:null,condition:null};
await store.write('daylight/harness/control-v1.json',saved.value,saved.etag);
const server=createServer(createHandler({store,env,local:true,fetcher}));
server.listen(0,'127.0.0.1',()=>console.log(JSON.stringify({port:server.address().port})));
