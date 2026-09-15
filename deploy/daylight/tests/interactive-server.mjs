// Scripted transport only: never contacts an inference service.
import {createServer} from 'node:http';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {createHandler} from '../api/index.mjs';
import {FileStore} from '../lib/store.mjs';
import {digest} from '../lib/auth.mjs';
const env={DEMO_SESSION_SECRET:'offline-interactive-secret-'.repeat(4),
  DEMO_INVITES_JSON:JSON.stringify({tester:digest('offline-interactive-code-'.repeat(3))}),OPENROUTER_API_KEY:'offline-only'};
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
const server=createServer(createHandler({store:new FileStore(await mkdtemp(tmpdir()+'/daylight-interactive-browser-')),env,local:true,fetcher}));
server.listen(0,'127.0.0.1',()=>console.log(JSON.stringify({port:server.address().port})));
