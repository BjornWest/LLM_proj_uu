// Actual authenticated app + BrowserGym; scripted HTTP responses only, no external inference.
import {createServer} from 'node:http';
import {mkdir,appendFile} from 'node:fs/promises';
import path from 'node:path';
import {randomUUID} from 'node:crypto';
import {SqliteStore} from '../lib/sqlite-store.mjs';
import {controlHandler} from '../control-server.mjs';
import {createHandler} from '../api/index.mjs';
import {digest} from '../lib/auth.mjs';
const root=path.resolve(process.env.SHARED_TEST_OUTPUT);await mkdir(root,{recursive:true});
const store=new SqliteStore(root+'/store.sqlite');let count=0;
const env={DAYLIGHT_MANUAL_PACKAGE:path.resolve('../../.local/environment-packages/portable-full-v2'),DAYLIGHT_MANUAL_DRIVER:path.resolve('../../scripts/manual_environment.py'),DAYLIGHT_MANUAL_PYTHON:path.resolve('../../.venv/bin/python'),DAYLIGHT_MANUAL_ROOT:root+'/sessions',DAYLIGHT_MANUAL_ACTOR:'scripted_validation',DAYLIGHT_CONTROL_TOKEN:randomUUID().repeat(2),DEMO_SESSION_SECRET:randomUUID().repeat(2),DEMO_INVITES_JSON:JSON.stringify({tester:digest('offline-shared-browser-code-'.repeat(3))}),OPENROUTER_API_KEY:'fake-never-sent-externally',DEMO_DAILY_BUDGET_USD:'1'};
const fake=async(url,options)=>{
 if(url!=='https://openrouter.ai/api/v1/chat/completions')throw Error('Unexpected model URL');
 const request=JSON.parse(options.body),text=request.messages.at(-1).content;
 await appendFile(root+'/requests.jsonl',JSON.stringify(request)+'\n');count++;
 let action='send_msg_to_user("This is the same browser, and your earlier navigation is preserved.")';
 const goal=text.split('\n')[0];
 if(goal.includes('Show subscriptions')&&!text.split('Accessibility tree:').at(-1).includes("button 'Buy now'")){
  const bid=text.split('Accessibility tree:').at(-1).match(/\[([^\]]+)\] link 'Navigate to Membership'/)?.[1];
  if(!bid)throw Error('Subscriptions control missing');action=`click(${JSON.stringify(bid)})`;
 }
 if(goal.includes('Slow answer'))await new Promise(r=>setTimeout(r,1800)); // Deliberately ignore abort: late-result test.
 if(goal.includes('Malformed'))return new Response(JSON.stringify({usage:{cost:0.0001},choices:[{message:{content:'I have all the information'}}]}),{status:200});
 return new Response(JSON.stringify({id:'offline-'+count,model:request.model,provider:'offline-mock',usage:{cost:0.0001},choices:[{message:{content:JSON.stringify({action})}}]}),{status:200});
};
const control=controlHandler({store,env,fetcher:fake}),back=createServer(control);await new Promise(r=>back.listen(0,'127.0.0.1',r));env.DAYLIGHT_CONTROL_URL='http://127.0.0.1:'+back.address().port;
const front=createServer(createHandler({store,env,local:true,fetcher:()=>{throw Error('Campus inference forbidden');}}));await new Promise(r=>front.listen(0,'127.0.0.1',r));console.log(JSON.stringify({port:front.address().port}));
for(const sig of ['SIGTERM','SIGINT'])process.on(sig,()=>{control.shutdown();front.closeAllConnections();back.closeAllConnections();front.close(()=>back.close(()=>{store.close();process.exit(0);}));});
