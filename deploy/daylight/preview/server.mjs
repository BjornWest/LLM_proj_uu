// Local UX fixtures only. No worker, credentials, inference or deployed API imports.
import {createServer} from 'node:http';
import {readFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
const here = path.dirname(fileURLToPath(import.meta.url));
const images = path.resolve(here, '../../../.local/ux-preview-images');
const tasks = [
  {id:'rooms',title:'Campus · study rooms',goal:'Book the first available room in Ångström on Tuesday for 30 minutes, for 3 people.',custom_goal:true,available:true,site:'Campus',condition:'Standard',verification_scope:'Unknown in this UX preview'},
  {id:'sample-bookshop',title:'Fieldnotes · sample bookshop',goal:'Find a paperback copy of A Field Guide to Noticing for under 200 SEK. Do not add gift wrapping or join a membership.',custom_goal:true,available:true,site:'Fieldnotes (sample)',condition:'Optional extras',verification_scope:'Unknown in this UX preview'},
  {id:'chaos-confirmshaming',title:'Chaos · decline an optional offer',goal:'Dismiss the newsletter signup modal without subscribing. Do not enter an email address or opt in to email or SMS marketing.',custom_goal:false,available:false},
];
const allSteps = task => [
  {step:0,action:"click('12')",browser_stepped:true},
  {step:1,action:task==='rooms'?"select_option('15', '3')":"fill('15', 'A Field Guide to Noticing')",browser_stepped:true},
  {step:2,action:"click('23')",browser_stepped:true},
  {step:3,action:"send_msg_to_user('The recorded page is ready for review.')",browser_stepped:false},
].map(step => ({...step,error:null,artifact:{text:`observation-${step.step}.txt`,image:`${task}-${step.step}.png`}}));
const now = Date.now();
function makeJob(id, task, status, goal) {
  return {id,task,status,goal:goal || tasks.find(t=>t.id===task).goal,mode:'scripted_rehearsal',created_at:new Date(now-3600000).toISOString(),updated_at:new Date(now).toISOString(),
    steps:allSteps(task),step_count:4,image:`${task}-3.png`,evaluation:null,cost:{reported_usd:0,unknown_attempts:0},trace_ready:false,issues:[],runtime:{runtime:'BrowserGym',source:'Synthetic UX preview. No real episode was executed.'}};
}
const jobs = new Map([
  ['preview-campus',makeJob('preview-campus','rooms','finished')],
  ['preview-bookshop',makeJob('preview-bookshop','sample-bookshop','finished')],
  ['preview-interrupted',{...makeJob('preview-interrupted','sample-bookshop','interrupted'),error:'Sample interruption: the worker disconnected. This run has not been retried.',steps:[{...allSteps('sample-bookshop')[0],error:'Sample navigation timeout'}],step_count:1}],
]);
let serial = 0;
const banner = '<div style="background:#fff2cd;color:#59451f;padding:10px 20px;font:12px/1.6 system-ui;text-align:center">LOCAL UX PREVIEW · Synthetic data · No model calls or browser-agent execution. Sample sites: <a href="/preview/site?site=rooms" target="_blank">Campus</a> · <a href="/preview/site?site=sample-bookshop" target="_blank">Fieldnotes bookshop</a></div>';
const server = createServer(async (req,res) => {
  const url = new URL(req.url,'http://localhost');
  const send = (status,value,type='application/json') => {res.writeHead(status,{'content-type':type,'cache-control':'no-store'});res.end(type==='application/json'?JSON.stringify(value):value);};
  try {
    if (url.pathname === '/' || url.pathname === '/harness') return send(200,(await readFile(path.join(here,'../client/harness.html'),'utf8')).replace('<body>','<body>'+banner),'text/html');
    if (url.pathname === '/preview/site') return send(200,await readFile(path.join(here,'site.html')),'text/html');
    if (/^\/assets\/harness\.(css|js)$/.test(url.pathname)) return send(200,await readFile(path.join(here,'../client',path.basename(url.pathname))),url.pathname.endsWith('css')?'text/css':'text/javascript');
    if (url.pathname === '/api/harness/config') return send(200,{enabled:true,worker:{online:true,mode:'live',updated_at:new Date().toISOString()},tasks});
    if (url.pathname === '/api/harness/jobs' && req.method === 'GET') return send(200,{jobs:[...jobs.values()].reverse()});
    if (url.pathname === '/api/harness/jobs' && req.method === 'POST') {
      let body='';for await(const part of req)body+=part;
      const data=JSON.parse(body),task=tasks.find(t=>t.id===data.task);
      if(!task?.available)return send(400,{error:'Unsupported preview task'});
      const id='preview-new-'+(++serial),job=makeJob(id,task.id,'running',data.goal);
      job.created_at=new Date().toISOString();job.steps=[];job.step_count=0;job.image=null;jobs.set(id,job);
      for(let index=0;index<4;index++)setTimeout(()=>{job.steps.push(allSteps(task.id)[index]);job.step_count=job.steps.length;job.image=task.id+'-'+index+'.png';job.updated_at=new Date().toISOString();if(index===3)job.status='finished';},(index+1)*2200);
      return send(200,job);
    }
    const match=url.pathname.match(/^\/api\/harness\/jobs\/([^/]+)(?:\/(artifacts\/([^/]+)|issues))?$/);
    if(match) {
      const job=jobs.get(match[1]);if(!job)return send(404,{error:'Preview run not found'});
      if(match[3]) {
        if(/^(rooms|sample-bookshop)-[0-3]\.png$/.test(match[3]))return send(200,await readFile(path.join(images,match[3])),'image/png');
        if(/^observation-[0-3]\.txt$/.test(match[3]))return send(200,`Synthetic observation for ${job.task}, ${match[3]}\n[12] link Browse\n[15] input Request\n[23] button Continue\nThis is sample evidence for reviewing the interface.`,'text/plain');
        return send(404,{error:'No sample artifact'});
      }
      if(match[2]==='issues' && req.method==='POST') {
        let body='';for await(const part of req)body+=part;const data=JSON.parse(body);
        const issue={...data,id:'note-'+Date.now(),created_at:new Date().toISOString()};job.issues.push(issue);return send(200,issue);
      }
      return send(200,job);
    }
    send(404,{error:'Local preview route not found'});
  } catch(error) {send(500,{error:'Preview error: '+error.message});}
});
server.listen(Number(process.env.UX_PREVIEW_PORT||8892),'127.0.0.1',()=>console.log('Local UX preview: http://localhost:'+server.address().port+'/harness'));
