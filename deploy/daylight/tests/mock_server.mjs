// Scripted browser integration test only. Not an inference backend or deployment entry point.
import {createServer} from 'node:http';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {createHandler} from '../api/index.mjs';
import {FileStore} from '../lib/store.mjs';
import {digest} from '../lib/auth.mjs';
const env={DEMO_SESSION_SECRET:'offline-test-secret-'.repeat(4),DEMO_INVITES_JSON:JSON.stringify({tester:digest('offline-test-code-'.repeat(4))}),OPENROUTER_API_KEY:'offline-only'};
const sequences={
  shop:[['click','Add A5 notebook'],['click','Add A5 notebook'],['select','Get it by','pickup'],['click','Place demo order'],['done']],
  booking:[['select','Building','Ångström'],['select','People','3'],['click','Book Å101 Tuesday 09:00'],['click','Confirm booking']],
  preferences:[['select','Email updates','monthly'],['check','Product tips',false],['click','Save preferences'],['done']],
};
const fetcher=async(url,options)=>{
  const request=JSON.parse(options.body),data=JSON.parse(request.messages.at(-1).content);
  let output='The recorded page is a fictional campus demo.';
  if(request.messages[0].content.includes('Take exactly ONE action')) {
    const kind=data.goal.includes('notebook')?'shop':data.goal.includes('room')?'booking':'preferences';
    const [action,label,value]=sequences[kind][data.activity.length];
    const control=data.page.controls.find(c=>c.label===label||c.label.startsWith(label+' '));
    if(action!=='done'&&!control)throw Error('Mock could not find '+label);
    output=JSON.stringify({action,id:control?.id,value,message:'Scripted test step'});
  }
  return new Response(JSON.stringify({id:'offline',model:request.model,provider:'Offline fixture',choices:[{message:{content:output}}],
    usage:{cost:0,prompt_tokens:100,completion_tokens:10,prompt_tokens_details:{cached_tokens:0}}}));
};
createServer(createHandler({store:new FileStore(await mkdtemp(tmpdir()+'/daylight-browser-')),env,local:true,fetcher}))
  .listen(8881,'127.0.0.1',()=>console.log('Offline browser test server ready'));
