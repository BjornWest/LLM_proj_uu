// Local test-only handler with controlled inference gates. No external calls.
import {createServer} from 'node:http';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {createHandler} from '../api/index.mjs';
import {FileStore} from '../lib/store.mjs';
import {digest} from '../lib/auth.mjs';
const env={DEMO_SESSION_SECRET:'offline-interrupt-secret-'.repeat(4),DEMO_INVITES_JSON:JSON.stringify({tester:digest('offline-interactive-code-'.repeat(3))}),OPENROUTER_API_KEY:'offline-only'};
const calls=[],gates=new Map();
const fetcher=async(_,options)=>{
  const request=JSON.parse(options.body),{page,goal}=JSON.parse(request.messages.at(-1).content);
  calls.push({id:request.session_id,goal,page,conversation:request.messages});
  if(goal.startsWith('Wait for'))await new Promise(resolve=>gates.set(request.session_id,resolve));
  const target=page.controls.find(c=>c.label==='Study rooms');
  const action=goal.startsWith('Navigate')?{action:'click',id:target.id}:
    goal.startsWith('Wait for')?{action:'select',id:page.controls.find(c=>c.label==='People').id,value:'3'}:
    {action:'done',message:'Fresh answer for: '+goal};
  return new Response(JSON.stringify({provider:'Offline gate',choices:[{message:{content:JSON.stringify(action)}}],usage:{cost:0.0001}}));
};
const handler=createHandler({store:new FileStore(await mkdtemp(tmpdir()+'/daylight-interrupt-ui-')),env,local:true,fetcher});
createServer((req,res)=>{
  if(req.url==='/__test/state'){res.setHeader('Content-Type','application/json');res.end(JSON.stringify({calls,pending:[...gates.keys()]}));return;}
  if(req.url==='/__test/release'&&req.method==='POST'){for(const resolve of gates.values())resolve();gates.clear();res.end('{}');return;}
  return handler(req,res);
}).listen(0,'127.0.0.1',function(){console.log(JSON.stringify({port:this.address().port}));});
