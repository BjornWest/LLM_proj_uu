// Owner-scoped access to human-only BrowserGym processes. No model or Blob calls.
import {spawn} from 'node:child_process';
import {createInterface} from 'node:readline';
import {mkdir,readFile,appendFile,realpath,stat,open} from 'node:fs/promises';
import path from 'node:path';
import {randomUUID,createHash} from 'node:crypto';
import {TASKS} from './harness.mjs';

const prefix='daylight/manual/',ID=/^[a-f0-9-]{36}$/;
const terminal=new Set(['finished','error','interrupted']);
const assert=(ok,message,status=400)=>{if(!ok)throw Object.assign(Error(message),{status});};
const stamp=()=>new Date().toISOString();
const key=id=>prefix+id+'.json';
export const MANUAL_TASKS=TASKS.filter(t=>t.id!=='rooms');
const publicSession=row=>{
  const {owner,directory,frame_files,commands,process_token,archive,...out}=row;
  return {...out,frame:row.frame?{...row.frame,url:`/api/manual/sessions/${row.id}/frame/${row.frame.id}`}:null};
};

class Driver {
  constructor({python,script,packageDir,directory,task,actor='human',timeout=24000}) {
    this.timeout=timeout;this.waiter=null;this.last=null;this.exited=false;this.logBytes=0;
    // The browser process gets no control token, model key or invitation secret.
    const env={PATH:process.env.PATH,HOME:'/tmp',PYTHONUNBUFFERED:'1',PYTHONDONTWRITEBYTECODE:'1',
      PYTHONPATH:path.join(packageDir,'runtime'),PLAYWRIGHT_BROWSERS_PATH:process.env.PLAYWRIGHT_BROWSERS_PATH||'/opt/playwright'};
    if(process.env.LD_LIBRARY_PATH)env.LD_LIBRARY_PATH=process.env.LD_LIBRARY_PATH;
    this.child=spawn(python,[script,'--package',packageDir,'--output',directory,'--task',task,'--actor',actor],
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
  constructor(store,{env=process.env,driverFactory=args=>new Driver(args)}={}){
    this.store=store;this.env=env;this.driverFactory=driverFactory;this.live=new Map();this.ownerLocks=new Set();this.reserved=0;
    this.processToken=randomUUID();
    this.root=path.resolve(env.DAYLIGHT_MANUAL_ROOT||'/manual');
    this.timer=setInterval(()=>this.expire().catch(()=>{}),10000);this.timer.unref();
  }
  async config(){
    let available=false;
    if(this.env.DAYLIGHT_MANUAL_PACKAGE&&this.env.DAYLIGHT_MANUAL_DRIVER){
      try{const m=JSON.parse(await readFile(path.join(this.env.DAYLIGHT_MANUAL_PACKAGE,'manifest.json')));available=MANUAL_TASKS.every(t=>m.datasets.some(d=>d.tasks.includes(t.id)));}catch{}
    }
    const sites=[];
    for(const t of MANUAL_TASKS){let s=sites.find(s=>s.site_id===t.site_id);if(!s){s={site_id:t.site_id,default_task:t.id,tasks:[]};sites.push(s);}s.tasks.push({id:t.id,title:t.title,condition:t.condition});}
    return {enabled:available,sites,limits:{max_sessions:2,idle_seconds:300,max_seconds:900,max_actions:100}};
  }
  async record(owner,id){
    assert(typeof owner==='string'&&/^[a-z0-9-]{1,40}$/.test(owner),'Invalid owner');assert(ID.test(id),'Invalid session ID');
    let saved=await this.store.read(key(id));assert(saved?.value.owner===owner,'Manual session not found',404);
    if(!terminal.has(saved.value.status)&&saved.value.process_token!==this.processToken){
      saved.value.status='interrupted';saved.value.error='The manual browser service restarted. Earlier page changes may have happened; no actions were replayed.';
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
  async start(owner,{task}={}){
    assert((await this.config()).enabled,'Manual environments are not configured on this worker',503);
    assert(typeof owner==='string'&&/^[a-z0-9-]{1,40}$/.test(owner),'Invalid owner');
    assert(!this.ownerLocks.has(owner),'Another manual session is starting',409);this.ownerLocks.add(owner);
    try{
      const selected=MANUAL_TASKS.find(t=>t.id===task);assert(selected,'Unsupported manual task');
      assert(!(await this.list(owner)).sessions.some(s=>!terminal.has(s.status)),'Close your current manual session before opening another',409);
      assert(this.live.size+this.reserved<2,'Both manual browser slots are in use; close a session or try later',429);
      const id=randomUUID(),directory=path.join(this.root,id),now=stamp();
      const row={id,owner,task,site_id:selected.site_id,collection:selected.collection,condition:selected.condition??null,
        task_name:selected.title,interaction_kind:'manual',runtime:'BrowserGym',status:'starting',created_at:now,updated_at:now,
        reference_goal:null,frame:null,action_count:0,last_action:null,last_error:null,evaluation:null,
        reference_evaluation:null,trace_ready:false,error:null,directory,commands:[],frame_files:{},process_token:this.processToken};
      let driver;this.reserved++;
      try{
        await mkdir(directory,{recursive:true,mode:0o700});
        await this.store.write(key(id),row);
        driver=this.driverFactory({python:this.env.DAYLIGHT_MANUAL_PYTHON||'python',script:this.env.DAYLIGHT_MANUAL_DRIVER,
          packageDir:this.env.DAYLIGHT_MANUAL_PACKAGE,directory,task,
          actor:this.env.DAYLIGHT_MANUAL_ACTOR==='scripted_validation'?'scripted_validation':'human'});
        this.live.set(id,{driver,owner,lastActive:Date.now(),started:Date.now(),busy:true});
        const result=await driver.ready();assert(['ready','finished'].includes(result.kind),'Invalid browser startup',503);
        await this.apply(row,result);const live=this.live.get(id);if(live)live.busy=false;
        return publicSession(row);
      }catch(error){driver?.kill();this.live.delete(id);row.status='error';row.error='Manual browser setup failed; no model was called.';row.updated_at=stamp();try{await this.save(row);}catch{};throw Object.assign(Error(row.error),{status:503});}
      finally{this.reserved--;}
    }finally{this.ownerLocks.delete(owner);}
  }
  async apply(row,result){
    if(result.frame){
      const file=path.resolve(result.trace_directory,result.frame.artifact.screenshot);
      assert(file.startsWith(row.directory+path.sep),'Invalid frame artifact',503);
      row.frame_files[result.frame.id]=file;
      row.frame={id:result.frame.id,width:result.frame.width,height:result.frame.height,page_url:result.frame.page_url};
    }
    row.reference_goal=result.reference_goal??row.reference_goal;row.action_count=result.action_count??row.action_count;
    row.last_error=result.last_error??null;row.updated_at=stamp();
    row.status=result.kind==='finished'?(result.error?'error':'finished'):'ready';
    if(result.kind==='finished'){
      row.error=result.error??null;row.reference_evaluation=result.reference_evaluation??null;
      row.trace_ready=!!result.archive;row.archive=result.archive;row.stop_reason=result.stop_reason;this.live.delete(row.id);
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
      live.driver.kill();this.live.delete(id);row.status='interrupted';row.error='Manual command did not complete reliably. Earlier page changes may have happened; no automatic replay.';
      row.updated_at=stamp();row.last_error=row.error;try{await this.save(row);}catch{}
      throw Object.assign(Error(row.error),{status:503});
    }finally{live.busy=false;}
  }
  async artifact(owner,id,frameID,part){
    const row=(await this.record(owner,id)).value;
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
  shutdown(){clearInterval(this.timer);for(const live of this.live.values())live.driver.kill();this.live.clear();}
}
