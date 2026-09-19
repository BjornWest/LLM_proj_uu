// Owner-scoped access to shared BrowserGym processes. No Blob calls.
import {spawn,execFile} from 'node:child_process';
import {createInterface} from 'node:readline';
import {mkdir,readFile,appendFile,realpath,stat,open,writeFile,rename} from 'node:fs/promises';
import path from 'node:path';
import {randomUUID,createHash} from 'node:crypto';
import {infer} from './manual-agent.mjs';
import {BrowsePool} from './browse-pool.mjs';
import {TASKS} from './harness.mjs';

const prefix='daylight/manual/',ID=/^[a-f0-9-]{36}$/;
const terminal=new Set(['finished','error','interrupted']);
const assert=(ok,message,status=400)=>{if(!ok)throw Object.assign(Error(message),{status});};
const stamp=()=>new Date().toISOString();
const key=id=>prefix+id+'.json';
// Expanded benchmark tasks run through their reset/grading worker lifecycle;
// they are not manual fixture selectors. Generic browse.* sessions stay separate.
export const MANUAL_TASKS=TASKS.filter(t=>t.id!=='rooms'&&!t.expanded);

const SITE_REVISION=MANUAL_TASKS.find(t=>t.site_revision)?.site_revision;
export const BROWSE_TASKS=[['tricky-shop','Shop'],['tricky-health','Health'],['tricky-news','News'],['tricky-music','Music'],['webarena-shopping','WebArena shopping'],['webarena-forum','WebArena forum']].map(([site_id,title])=>({id:'browse.'+site_id,site_id,title:'Browse '+title,collection:site_id.startsWith('tricky-')?'trickyarena':'webarena-verified',condition:null,browse_only:true,ask_enabled:true,site_revision:site_id.startsWith('tricky-')?SITE_REVISION:null}));
const publicSession=row=>{
  const {owner,directory,frame_files,commands,process_token,archive,trace_directory,browse_lease,...out}=row;
  return {...out,frame:row.frame?{...row.frame,url:`/api/manual/sessions/${row.id}/frame/${row.frame.id}`}:null};
};

class Driver {
  constructor({python,script,packageDir,directory,task,actor='human',browseConfig=null,timeout=24000}) {
    this.timeout=timeout;this.waiter=null;this.last=null;this.exited=false;this.logBytes=0;
    // The browser process gets no control token, model key or invitation secret.
    const env={PATH:process.env.PATH,HOME:'/tmp',PYTHONUNBUFFERED:'1',PYTHONDONTWRITEBYTECODE:'1',
      PYTHONPATH:path.join(packageDir,'runtime'),PLAYWRIGHT_BROWSERS_PATH:process.env.PLAYWRIGHT_BROWSERS_PATH||'/opt/playwright'};
    if(process.env.LD_LIBRARY_PATH)env.LD_LIBRARY_PATH=process.env.LD_LIBRARY_PATH;
    this.child=spawn(python,[script,'--package',packageDir,'--output',directory,'--task',task,'--actor',actor,...(browseConfig?['--browse-config',browseConfig]:[])],
      {env,detached:true,stdio:['ignore','pipe','pipe','pipe','pipe']});
    // Dataset CLIs may inspect/change stdin. Keep commands on a private descriptor.
    this.commands=this.child.stdio[4];
    for(const stream of [this.child.stdout,this.child.stderr])stream.on('data',chunk=>{
      this.logBytes+=chunk.length;if(this.logBytes<=1024*1024)appendFile(path.join(directory,'driver.log'),chunk).catch(()=>{});
    });
    const lines=createInterface({input:this.child.stdio[3]});
    lines.on('line',line=>{
      try {const result=JSON.parse(line);this.last=result;if(this.waiter){const waiter=this.waiter;this.waiter=null;clearTimeout(waiter.timer);waiter.resolve(result);}}
      catch{this.fail(Error('Invalid browser driver response'));}
    });
    this.child.on('error',()=>this.fail(Error('Browser driver failed to start')));
    this.commands.on('error',()=>this.fail(Error('Browser command pipe closed')));
    this.child.on('exit',()=>{this.exited=true;if(this.waiter)this.fail(Error('Browser process ended before acknowledging the command'));});
  }
  fail(error){if(this.waiter){const w=this.waiter;this.waiter=null;clearTimeout(w.timer);w.reject(error);}}
  wait(){
    if(this.exited)return Promise.reject(Error('Browser process is no longer running'));
    assert(!this.waiter,'Another browser command is pending',409);
    return new Promise((resolve,reject)=>{this.waiter={resolve,reject,timer:setTimeout(()=>{this.fail(Error('Browser response timed out; no automatic replay'));this.kill();},this.timeout)};});
  }
  ready(){return this.last?Promise.resolve(this.last):this.wait();}
  send(value){const result=this.wait();this.commands.write(JSON.stringify(value)+'\n');return result;}
  kill(){try{process.kill(-this.child.pid,'SIGTERM');}catch{};const t=setTimeout(()=>{try{process.kill(-this.child.pid,'SIGKILL');}catch{}},2000);t.unref();}
}

export class Manual {
  constructor(store,{env=process.env,driverFactory=args=>new Driver(args),fetcher=fetch,pool=null}={}){
    this.pool=pool||new BrowsePool(env,fetcher);
    this.store=store;this.env=env;this.fetcher=fetcher;this.driverFactory=driverFactory;this.live=new Map();this.ownerLocks=new Set();this.reserved=0;
    this.processToken=randomUUID();
    this.root=path.resolve(env.DAYLIGHT_MANUAL_ROOT||'/manual');
    this.timer=setInterval(()=>this.expire().catch(()=>{}),10000);this.timer.unref();
  }
  async config(){
    let available=false;
    if(this.env.DAYLIGHT_MANUAL_PACKAGE&&this.env.DAYLIGHT_MANUAL_DRIVER){
      try{const m=JSON.parse(await readFile(path.join(this.env.DAYLIGHT_MANUAL_PACKAGE,'manifest.json')));available=MANUAL_TASKS.every(t=>m.datasets.some(d=>d.tasks.includes(t.id)));
        if(available&&MANUAL_TASKS.some(t=>t.site_revision)){const registry=JSON.parse(await readFile(path.join(this.env.DAYLIGHT_MANUAL_PACKAGE,'runtime/config/team_tasks.json')));available=MANUAL_TASKS.every(t=>!t.site_revision||registry.tasks.some(r=>r.id===t.id&&r.revision===t.revision&&r.site_revision===t.site_revision));}}catch{}
    }
    let poolStatus={sites:[]};
    if(this.env.DAYLIGHT_BROWSE_ENABLED==='1')try{poolStatus=await this.pool.status();}catch{}
    const browsing=this.env.DAYLIGHT_BROWSE_ENABLED==='1'?BROWSE_TASKS.map(t=>{
      const slot=poolStatus.sites.find(s=>s.site_id===t.site_id);
      const local=t.site_id.startsWith('tricky-');
      return {...t,available:available&&(local||slot?.status==='ready'),
        unavailable_reason:!available?'service_unavailable':local?null:slot?.status==='leased'?'pool_busy':slot?.status==='resetting'?'resetting':slot?.status==='ready'?null:'service_unavailable'};
    }):[];
    const sites=[];
    for(const t of [...browsing,...MANUAL_TASKS]){let s=sites.find(s=>s.site_id===t.site_id);if(!s){s={site_id:t.site_id,default_task:t.id,tasks:[]};sites.push(s);}s.tasks.push({id:t.id,title:t.title,condition:t.condition,site_revision:t.site_revision??null,browse_only:!!t.browse_only,ask_enabled:t.ask_enabled!==false,available:t.available??available,unavailable_reason:t.unavailable_reason??null});s.available=s.tasks.some(t=>t.available);s.unavailable_reason=s.available?null:t.unavailable_reason??'service_unavailable';}
    return {enabled:available,ask_enabled:available&&!!this.env.OPENROUTER_API_KEY,sites,limits:{max_sessions:2,idle_seconds:300,max_seconds:900,max_actions:100,max_ask_turns:30,max_model_calls_per_turn:12}};
  }
  async record(owner,id){
    assert(typeof owner==='string'&&/^[a-z0-9-]{1,40}$/.test(owner),'Invalid owner');assert(ID.test(id),'Invalid session ID');
    let saved=await this.store.read(key(id));assert(saved?.value.owner===owner,'Manual session not found',404);
    if(!terminal.has(saved.value.status)&&saved.value.process_token!==this.processToken){
      await this.releaseLease(saved.value);
      saved.value.status='interrupted';saved.value.controller='human';
      for(const ask of saved.value.asks||[])if(['running','stopping'].includes(ask.status)){ask.status='interrupted';ask.error='Browser service restarted; consult original request records. Pending billing may be unknown.';}
      saved.value.error='The manual browser service restarted. Earlier page changes may have happened; no actions were replayed.';
      saved.value.updated_at=stamp();await this.store.write(key(id),saved.value,saved.etag);saved=await this.store.read(key(id));
    }
    return saved;
  }
  async list(owner){
    const rows=[];let cursor;
    do{
      const page=await this.store.listKeys(prefix,{limit:1000,cursor});
      for(const k of page.keys){const row=(await this.store.read(k)).value;if(row.owner===owner)rows.push(publicSession((await this.record(owner,row.id)).value));}
      cursor=page.has_more?page.cursor:undefined;
    }while(cursor);
    return {sessions:rows.sort((a,b)=>b.created_at.localeCompare(a.created_at))};
  }
  async read(owner,id){return publicSession((await this.record(owner,id)).value);}
  async save(row){const prior=await this.store.read(key(row.id));await this.store.write(key(row.id),row,prior?.etag??null);}
  async start(owner,{task,site_revision}={}){
    assert((await this.config()).enabled,'Manual environments are not configured on this worker',503);
    assert(typeof owner==='string'&&/^[a-z0-9-]{1,40}$/.test(owner),'Invalid owner');
    assert(!this.ownerLocks.has(owner),'Another manual session is starting',409);this.ownerLocks.add(owner);
    try{
      const selected=[...MANUAL_TASKS,...(this.env.DAYLIGHT_BROWSE_ENABLED==='1'?BROWSE_TASKS:[])].find(t=>t.id===task);assert(selected,'Unsupported manual task');
      assert(!selected.site_revision||site_revision===selected.site_revision,'Client and remote site versions differ; refresh after deployment',409);
      assert(!(await this.list(owner)).sessions.some(s=>!terminal.has(s.status)),'Close your current manual session before opening another',409);
      assert(this.live.size+this.reserved<2,'Both manual browser slots are in use; close a session or try later',429);
      const id=randomUUID(),directory=path.join(this.root,id),now=stamp();
      const row={id,owner,task,site_revision:selected.site_revision??null,site_id:selected.site_id,collection:selected.collection,condition:selected.condition??null,
        task_name:selected.title,interaction_kind:'manual',runtime:'BrowserGym',status:'starting',created_at:now,updated_at:now,
        browse_only:!!selected.browse_only,ask_enabled:selected.ask_enabled!==false,reference_goal:null,asks:[],controller:'human',frame:null,action_count:0,last_action:null,last_error:null,evaluation:null,
        reference_evaluation:null,trace_ready:false,error:null,directory,commands:[],frame_files:{},process_token:this.processToken};
      let driver;this.reserved++;
      try{
        await mkdir(directory,{recursive:true,mode:0o700});
        await this.store.write(key(id),row);
        let browseConfig=null;
        if(selected.browse_only&&selected.site_id.startsWith('webarena-')){
          row.browse_lease=await this.pool.acquire(selected.site_id,id);
          await this.save(row);
          browseConfig=path.join(directory,'browser-launch.json');
          await writeFile(browseConfig,JSON.stringify(row.browse_lease),{mode:0o600,flag:'wx'});
        }
        driver=this.driverFactory({python:this.env.DAYLIGHT_MANUAL_PYTHON||'python',script:this.env.DAYLIGHT_MANUAL_DRIVER,
          packageDir:this.env.DAYLIGHT_MANUAL_PACKAGE,directory,task,browseConfig,
          actor:this.env.DAYLIGHT_MANUAL_ACTOR==='scripted_validation'?'scripted_validation':'human'});
        this.live.set(id,{driver,owner,row,lastActive:Date.now(),started:Date.now(),busy:true});
        const result=await driver.ready();assert(['ready','finished'].includes(result.kind),'Invalid browser startup',503);
        await this.apply(row,result);const live=this.live.get(id);if(live)live.busy=false;
        return publicSession(row);
      }catch(error){driver?.kill();await this.releaseLease(row);this.live.delete(id);row.status='error';row.error='Manual browser setup failed; no model was called.';row.updated_at=stamp();try{await this.save(row);}catch{};throw Object.assign(Error(row.error),{status:error.status===429?429:503});}
      finally{this.reserved--;}
    }finally{this.ownerLocks.delete(owner);}
  }
  async releaseLease(row){
    if(!row.browse_lease)return;
    try{await this.pool.release(row.browse_lease);row.browse_lease=null;}catch{/* Failed release stays leased until expiry; never locally reuse a slot. */}
  }
  async apply(row,result){
    if(result.trace_directory){const directory=path.resolve(result.trace_directory);assert(directory===row.directory||directory.startsWith(row.directory+path.sep),'Invalid trace directory',503);row.trace_directory=directory;}
    row.environment_finished=!!(result.terminated||result.truncated);
    if(result.frame){
      const file=path.resolve(result.trace_directory,result.frame.artifact.screenshot);
      assert(file.startsWith(row.directory+path.sep),'Invalid frame artifact',503);
      row.frame_files[result.frame.id]=file;
      row.frame={id:result.frame.id,width:result.frame.width,height:result.frame.height,page_url:result.frame.page_url};
    }
    row.reference_goal=row.browse_only?null:result.reference_goal??row.reference_goal;row.action_count=result.action_count??row.action_count;
    row.last_error=result.last_error??null;row.updated_at=stamp();
    row.status=result.kind==='finished'?(result.error?'error':'finished'):row.controller==='agent'?'busy':'ready';
    if(result.kind==='finished'){
      row.error=result.error??null;row.reference_evaluation=row.browse_only?null:result.reference_evaluation??null;
      row.trace_ready=!!result.archive;row.archive=result.archive;row.stop_reason=result.stop_reason;await this.releaseLease(row);this.live.delete(row.id);
    }
    await this.save(row);
  }
  async command(owner,id,operation,value={}){
    const row=(await this.record(owner,id)).value;
    assert(ID.test(value.request_id),'A fresh request UUID is required');
    const prior=row.commands.find(c=>c.id===value.request_id);
    if(prior){assert(prior.operation===operation&&prior.frame_id===(value.frame_id??null)&&JSON.stringify(prior.action)===JSON.stringify(value.action??null),'Request ID was already used for a different command',409);assert(prior.status==='complete','The command was already attempted; its result is uncertain. No replay.',409);return publicSession(row);}
    assert(!terminal.has(row.status),'Manual session is closed',409);
    const live=this.live.get(id);assert(live&&!live.busy,'Another browser command is pending',409);
    assert(['action','observe','close'].includes(operation),'Unsupported manual command');
    if(operation==='action')assert(value.frame_id===row.frame?.id,'The displayed frame changed; refresh before acting',409);
    if(operation==='action')assert(row.action_count<100,'Manual action limit reached; close this session',429);
    assert(row.commands.length<500,'Manual command limit reached',429);
    live.busy=true;live.lastActive=Date.now();
    const claim={id:value.request_id,status:'pending',operation,frame_id:value.frame_id??null,action:value.action??null,at:stamp()};
    row.commands.push(claim);row.status='busy';row.updated_at=stamp();
    try{
      await this.save(row); // durable claim before exactly one browser dispatch
      const result=await live.driver.send({request_id:value.request_id,operation,frame_id:value.frame_id,action:value.action,reason:value.reason});
      assert(result.request_id===value.request_id,'Browser acknowledgment mismatch',503);
      claim.status='complete';claim.completed_at=stamp();
      if(result.kind==='rejected'){row.status='ready';row.last_error=result.error;await this.save(row);throw Object.assign(Error(result.error),{status:409,manualRejected:true});}
      if(operation==='action')row.last_action=value.action;
      await this.apply(row,result);return publicSession(row);
    }catch(error){
      if(error.manualRejected)throw error;
      live.driver.kill();await this.releaseLease(row);this.live.delete(id);row.status='interrupted';row.error='Manual command did not complete reliably. Earlier page changes may have happened; no automatic replay.';
      row.updated_at=stamp();row.last_error=row.error;try{await this.save(row);}catch{}
      throw Object.assign(Error(row.error),{status:503});
    }finally{live.busy=false;}
  }
  async persistAsk(row,ask){
    const directory=row.trace_directory;assert(directory,'Trace directory unavailable',503);
    const name=path.join(directory,'ask-'+ask.id+'.json'),temporary=name+'.'+randomUUID()+'.tmp';
    await writeFile(temporary,JSON.stringify(ask,null,2),{mode:0o600,flag:'wx'});await rename(temporary,name);
  }
  async publishAsk(row,ask){
    const costSteps=ask.steps.filter(s=>typeof s.usage?.cost==='number');
    const summary={id:ask.id,goal:ask.goal,status:ask.status,answer:ask.answer??null,error:ask.error??null,
      created_at:ask.created_at,finished_at:ask.finished_at??null,evaluation:null,
      reported_cost_usd:costSteps.length?costSteps.reduce((n,s)=>n+s.usage.cost,0):null,
      unknown_cost_attempts:ask.steps.filter(s=>s.dispatch_at&&typeof s.usage?.cost!=='number').length,
      alerts:ask.steps.flatMap(s=>s.alerts||[]),
      steps:ask.steps.map(s=>({index:s.index,action:s.action??null,error:s.error??null,executed:s.executed??null}))};
    row.asks=row.asks||[];const i=row.asks.findIndex(a=>a.id===ask.id);if(i<0)row.asks.push(summary);else row.asks[i]=summary;
    row.updated_at=stamp();await this.save(row);
  }
  async ask(owner,id,{request_id,goal}={}){
    assert(ID.test(request_id),'A fresh request UUID is required');
    assert(typeof goal==='string'&&goal.trim()&&goal.length<=2000,'Provide a request up to 2000 characters');
    assert(this.env.OPENROUTER_API_KEY,'Remote inference is not configured',503);
    const row=(await this.record(owner,id)).value;
    assert(row.ask_enabled!==false,'This session supports manual browsing only',409);
    const prior=row.asks?.find(a=>a.id===request_id);if(prior){assert(prior.goal===goal,'Request ID already used',409);return publicSession(row);}
    const live=this.live.get(id);assert(live&&!live.busy&&row.status==='ready','Browser is already controlled or closed',409);
    assert(!row.environment_finished,'The environment has ended; open a new session',409);
    assert((row.asks?.length||0)<30&&row.action_count<100,'Session limit reached',429);
    live.busy=true;live.lastActive=Date.now();live.cancel=new AbortController();live.row=row;
    const ask={schema_version:1,id:request_id,session_id:id,goal,status:'running',created_at:stamp(),steps:[],evaluation:null,training_eligible:false};
    live.ask=ask;row.controller='agent';row.status='busy';
    try{await this.persistAsk(row,ask);await this.publishAsk(row,ask);}
    catch(error){live.busy=false;live.ask=null;throw error;}
    live.work=this.runAsk(row,live,ask).catch(()=>{});
    return publicSession(row);
  }
  async interrupt(owner,id,{ask_id}={}){
    const saved=(await this.record(owner,id)).value,live=this.live.get(id);
    const current=live?.ask;
    assert(ID.test(ask_id),'An Ask ID is required');
    if(!current||current.id!==ask_id){assert(saved.asks?.some(a=>a.id===ask_id),'Ask not found',404);return publicSession(saved);}
    current.status='stopping';current.interrupted_at=stamp();live.cancel.abort();
    await writeFile(path.join(live.row.trace_directory,'interrupt-'+ask_id+'.json'),JSON.stringify({ask_id,at:current.interrupted_at}),{mode:0o600});
    // The run owns persistence. It will finish any dispatched browser action,
    // retain its receipt, and release control; no second row writer races it.
    return {...publicSession(live.row),interrupt_requested:true};
  }
  async runAsk(row,live,ask){
    const cancelled=()=>live.cancel.signal.aborted;
    const persist=()=>this.persistAsk(row,ask);
    let browserPending=false;
    try{
      for(let i=0;i<12&&!cancelled();i++){
        if(row.action_count>=100){ask.status='session_action_limit';break;}
        live.lastActive=Date.now();
        const captureID=randomUUID();ask.pending_browser_command={id:captureID,operation:'agent_observe'};await persist();
        if(cancelled())break;
        browserPending=true;
        const observation=await live.driver.send({request_id:captureID,operation:'agent_observe',ask_id:ask.id,goal:ask.goal});
        browserPending=false;
        assert(observation.request_id===captureID&&observation.decision,'Invalid policy observation',503);
        await this.apply(row,observation);row.status='busy';await this.publishAsk(row,ask);
        const step={index:i,decision:observation.decision,request:null,response:null,output:null,usage:null};ask.steps.push(step);delete ask.pending_browser_command;await persist();
        if(cancelled())break;
        await infer({store:this.store,env:this.env,fetcher:this.fetcher,sessionID:row.id,messages:observation.decision.messages,signal:live.cancel.signal,step,persist});
        if(cancelled())break;
        step.alerts=[];const prior=ask.steps.slice(0,-1),costs=prior.map(s=>s.usage?.cost).filter(c=>typeof c==='number').sort((a,b)=>a-b);
        if(costs.length>=3&&step.usage.cost>0.005&&step.usage.cost>3*costs[Math.floor(costs.length/2)])step.alerts.push('Inference cost increased above three times the recent median.');
        const provider=prior.at(-1)?.routing?.resolved_provider;
        if(provider&&step.routing?.resolved_provider&&provider!==step.routing.resolved_provider)step.alerts.push('Provider changed within this browser session; caching is not guaranteed.');
        const actionID=randomUUID();ask.pending_browser_command={id:actionID,operation:'agent_action'};await persist();
        if(cancelled())break;
        browserPending=true;
        const result=await live.driver.send({request_id:actionID,operation:'agent_action',ask_id:ask.id,decision_id:observation.decision.id,evidence:step});
        browserPending=false;assert(result.request_id===actionID,'Browser acknowledgment mismatch',503);
        step.result=result;delete ask.pending_browser_command;
        try{step.action=JSON.parse(step.output).action;}catch{}
        step.error=result.agent_error||result.error||(result.answer===undefined?result.last_error:null)||null;
        step.executed=result.kind==='rejected'?false:result.agent_error?false:result.answer!==undefined?false:step.error?null:true;
        await persist();await this.apply(row,result);row.status=result.kind==='finished'?row.status:'busy';await this.publishAsk(row,ask);
        if(cancelled())break;
        if(result.kind==='rejected'||step.error)throw Error(step.error||result.error||'Action rejected');
        if(result.answer!==undefined){ask.answer=result.answer;ask.status='complete';break;}
        if(result.kind==='finished'||result.terminated||result.truncated){ask.status='environment_ended';break;}
      }
      if(ask.status==='running')ask.status='step_limit';
    }catch(error){
      ask.error=String(error.message);ask.status='error';
      if(browserPending){live.driver.kill();await this.releaseLease(row);this.live.delete(row.id);row.status='interrupted';row.error='Browser command outcome uncertain; no action was retried.';}
    }finally{
      if(cancelled())ask.status='interrupted';
      ask.finished_at=stamp();row.controller='human';
      if(!terminal.has(row.status))row.status='ready';
      try{await persist();await this.publishAsk(row,ask);}catch{row.status='interrupted';live.driver.kill();await this.releaseLease(row);this.live.delete(row.id);}
      live.busy=false;live.ask=null;live.lastActive=Date.now();
    }
  }
  async artifact(owner,id,frameID,part){
    const row=(await this.record(owner,id)).value;
    if(!frameID&&row.trace_ready&&row.asks?.length){
      assert(row.controller!=='agent','Agent evidence is still being saved',409);
      // A native browser failure can close the driver before its caller records
      // the final receipt. Export current original files, including that receipt.
      const destination=path.join(row.directory,'shared-trace.zip');
      if(part===undefined){
        const source=await realpath(row.trace_directory);assert(source.startsWith(row.directory+path.sep),'Invalid trace directory',404);
        const script=`import os,sys,zipfile
from pathlib import Path
from uuid import uuid4
root=Path(sys.argv[1]);dest=Path(sys.argv[2]);tmp=dest.with_name(dest.name+'.'+uuid4().hex+'.tmp')
with zipfile.ZipFile(tmp,'x',compression=zipfile.ZIP_DEFLATED) as z:
 for p in sorted(root.rglob('*')):
  if p.is_file() and not p.is_symlink() and not p.name.endswith('.tmp'):z.write(p,str(p.relative_to(root.parent)))
os.replace(tmp,dest)`;
        await new Promise((resolve,reject)=>execFile(this.env.DAYLIGHT_MANUAL_PYTHON||'python',['-c',script,source,destination],{env:{PATH:process.env.PATH},timeout:20000},error=>error?reject(Error('Shared trace export failed')):resolve()));
      }
      row.archive=destination;
    }
    const file=frameID?row.frame_files[frameID]:row.trace_ready?row.archive:null;
    assert(file,'Manual artifact is not available',404);
    const actual=await realpath(file);assert(actual.startsWith(row.directory+path.sep),'Invalid artifact path',404);
    if(!frameID){
      const size=(await stat(actual)).size;
      if(part===undefined)return {size,parts:Math.ceil(size/1048576)};
      assert(Number.isInteger(part)&&part>=0&&part<Math.ceil(size/1048576),'Invalid archive part');
      const handle=await open(actual,'r');
      try{
        const bytes=Buffer.alloc(Math.min(1048576,size-part*1048576));
        const result=await handle.read(bytes,0,bytes.length,part*1048576);assert(result.bytesRead===bytes.length,'Incomplete archive read',503);
        return {data:bytes.toString('base64'),sha256:createHash('sha256').update(bytes).digest('hex')};
      }finally{await handle.close();}
    }
    const bytes=await readFile(actual);return {data:bytes.toString('base64'),sha256:createHash('sha256').update(bytes).digest('hex')};
  }
  async expire(){for(const [id,live]of this.live){if(!live.busy&&(Date.now()-live.lastActive>300000||Date.now()-live.started>900000)){
    try{await this.command(live.owner,id,'close',{request_id:randomUUID(),reason:'manual_session_timeout'});}catch{}
  }}}
  shutdown(){clearInterval(this.timer);for(const live of this.live.values()){live.cancel?.abort();live.driver.kill();if(live.row)this.releaseLease(live.row).catch(()=>{});}this.live.clear();}
}
