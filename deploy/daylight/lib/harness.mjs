// Durable control plane only. Python owns browser actions, policy inputs and grading.
import {randomUUID,createHash,timingSafeEqual} from 'node:crypto';
import {Agent,completionTokenLimit} from './agent.mjs';
import registry from '../../../config/team_tasks.json' with {type:'json'};
import expanded from '../../../config/expanded_team_tasks.json' with {type:'json'};
import prislyktan from '../../../config/prislyktan_tasks.json' with {type:'json'};
import {interactionKind,siteForTask,recordedActivity,validateSite} from './activity.mjs';

const KEY='daylight/harness/control-v1.json';
const terminal=new Set(['finished','error','interrupted']);
const ID=/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/;
const ART=/^(?:(?:decision-)?observation-\d{3}\.(?:png|txt)|trace-\d{3}\.part)$/;
const insist=(condition,message,status=400)=>{if(!condition)throw Object.assign(Error(message),{status});};
const sha=bytes=>createHash('sha256').update(bytes).digest('hex');
export const TASKS=[
  {id:'rooms',title:'Study rooms · BrowserGym',goal:'Book the first available room in Ångström on Tuesday for 30 minutes, for 3 people.',custom_goal:true},
  ...registry.tasks.map(task=>({id:task.id,title:task.title,goal:task.goal,goal_mode:task.goal_mode,
    custom_goal:false,revision:task.revision,site_revision:task.site_revision??null,site:task.site,condition:task.condition,
    verification_scope:task.verification_scope,development_only:true})),
  ...expanded.tasks,
  ...prislyktan.tasks.map(({selector,...task})=>task),
].map(task=>({...task,...siteForTask(task.id)}));
const needsRevision=task=>!!(task?.site_revision||task?.expanded||task?.id?.startsWith('prislyktan:'));
const limitsFor=id=>TASKS.find(task=>task.id===id)?.execution_limits||{max_steps:12,max_input_bytes:250000};
export function workerAuthorized(header,env) {
  const secret=env.HARNESS_WORKER_TOKEN;
  if(typeof secret!=='string'||secret.length<43||typeof header!=='string')return false;
  const expected=Buffer.from('Bearer '+secret),actual=Buffer.from(header);
  return expected.length===actual.length&&timingSafeEqual(expected,actual);
}
const initial=()=>({version:1,worker:null,active:null,jobs:{}});
const iso=ms=>new Date(ms).toISOString();
const publicJob=job=>{
  const {lease,worker_id,reservations,owner,artifacts,...value}=job;
  return {...recordedActivity(job),required_execution_mode:job.required_execution_mode??null,...value,trace_ready:!!job.trace_parts?.length};
};
export class Harness {
  constructor(store,{env=process.env,now=()=>Date.now()}={}) {this.store=store;this.env=env;this.now=now;}
  async mutate(fn) {
    // Only optimistic control-plane mutations retry. No inference is performed here.
    for(let attempt=0;attempt<3;attempt++) {
      const prior=await this.store.read(KEY),state=prior?.value||initial();
      const result=await fn(state);
      try {await this.store.write(KEY,state,prior?.etag||null);return result;}
      catch(e) {if(attempt===2||!(e.code==='BLOB_WRITE_CONFLICT'||e.message==='Storage conflict'))throw e;}
    }
  }
  expire(state) {
    const job=state.jobs[state.active];
    if(job&&job.status==='running'&&this.now()-Date.parse(job.updated_at)>120000) {
      job.status='interrupted';job.error='Worker connection was lost. Earlier actions may have happened; no automatic replay.';
      job.updated_at=iso(this.now());state.active=null;
      return true;
    }
    return false;
  }
  enabled() {return typeof this.env.HARNESS_WORKER_TOKEN==='string'&&this.env.HARNESS_WORKER_TOKEN.length>=43;}
  async state() {return (await this.store.read(KEY))?.value||initial();}
  own(state,owner,id) {insist(ID.test(id),'Invalid job ID');const job=state.jobs[id];insist(job?.owner===owner,'Job not found',404);return job;}
  leased(state,value) {
    const job=state.jobs[value.id];
    insist(job&&job.status==='running'&&job.lease===value.lease&&state.active===value.id,'Worker lease is not active',409);
    insist(this.now()-Date.parse(job.updated_at)<=120000,'Worker lease expired',409);return job;
  }
  async config() {
    const state=await this.state(),worker=state.worker;
    return {enabled:this.enabled(),worker:{online:!!worker&&this.now()-Date.parse(worker.updated_at)<45000,
      updated_at:worker?.updated_at||null,mode:worker?.mode||null},
      tasks:TASKS.map(task=>({...task,custom_goal:task.custom_goal&&worker?.mode==='live',
        available:worker?worker.tasks.includes(task.id)&&(!needsRevision(task)||worker.task_revisions?.[task.id]===task.revision)&&(!task.expanded||worker.mode==='live'):task.id==='rooms'}))};
  }
  async list(owner) {
    const state=await this.state();
    if(this.env.DAYLIGHT_STORAGE_MAINTENANCE!=='1'&&this.expire(state))return this.mutate(state=>{this.expire(state);return {jobs:Object.values(state.jobs).filter(j=>j.owner===owner).map(publicJob).reverse()};});
    return {jobs:Object.values(state.jobs).filter(j=>j.owner===owner).map(publicJob).reverse()};
  }
  async read(owner,id) {
    const state=await this.state();this.own(state,owner,id);
    if(this.env.DAYLIGHT_STORAGE_MAINTENANCE!=='1'&&this.expire(state))return this.mutate(state=>{this.expire(state);return publicJob(this.own(state,owner,id));});
    return publicJob(this.own(state,owner,id));
  }
  async start(owner,value) {
    insist(this.enabled(),'The PC worker connection is not configured yet',503);
    const task=TASKS.find(t=>t.id===value.task);insist(task,'Unsupported task');
    const interaction_kind=interactionKind(value.interaction_kind);
    const required_execution_mode=value.required_execution_mode??null;
    insist(required_execution_mode===null||required_execution_mode==='live','Invalid required execution mode');
    insist(interaction_kind!=='ask'||task.custom_goal,'This reviewed task does not support custom Ask requests');
    const site=siteForTask(task.id);validateSite(value,site);
    const dynamic=task.goal_mode==='resolve_after_session_prepare';
    insist((value.task_revision===undefined&&!task.expanded)||value.task_revision===task.revision,'Task revision changed; refresh the task list',409);
    const goal=task.custom_goal?value.goal:task.goal;
    if(dynamic)insist(value.goal===undefined||value.goal===null||value.goal==='','This task resolves its trusted objective in a fresh session');
    else insist(typeof goal==='string'&&goal.trim().length>0&&goal.length<=2000,'Enter a request up to 2000 characters');
    const id=randomUUID();
    return this.mutate(state=>{
      this.expire(state);
      insist(state.worker?state.worker.tasks.includes(task.id)&&(!needsRevision(task)||state.worker.task_revisions?.[task.id]===task.revision)&&(!task.expanded||state.worker.mode==='live'):task.id==='rooms','This task is not available on the configured worker',409);
      insist(dynamic||task.custom_goal||value.goal===undefined||value.goal===task.goal,'This task uses its fixed validated goal');
      insist(goal===task.goal||state.worker?.mode==='live','Custom requests require a live worker',409);
      insist(Object.keys(state.jobs).length<100,'This development queue reached 100 saved jobs; ask Bjorn to archive it',429);
      insist(Object.values(state.jobs).filter(j=>j.owner===owner&&!terminal.has(j.status)).length<3,'You already have three queued or active jobs',429);
      const job={id,owner,task:task.id,goal:dynamic?null:goal.trim(),task_revision:task.revision||null,site_revision:task.site_revision??null,
        interaction_kind,required_execution_mode,...site,task_id:task.id,task_name:task.title,condition:task.condition||null,
        activity_metadata_source:{interaction_kind:interaction_kind?'client_declaration':null,
          task_registry_revision:sha(Buffer.from(JSON.stringify(registry))),site_registry_revision:site.site_registry_revision},
        goal_resolution:dynamic?'session_pending':'fixed',status:'queued',created_at:iso(this.now()),updated_at:iso(this.now()),
        step_count:0,steps:[],issues:[],artifacts:{},trace_parts:[],error:null,evaluation:null,runtime:null,image:null,reservations:[]};
      state.jobs[id]=job;return publicJob(job);
    });
  }
  async issue(owner,id,value) {
    insist(typeof value.comment==='string'&&value.comment.trim().length>0&&value.comment.length<=4000,'Enter a comment up to 4000 characters');
    const issueID=randomUUID();
    return this.mutate(state=>{
      const job=this.own(state,owner,id);insist(job.issues.length<50,'Issue limit reached',429);
      insist(value.step===null||Number.isInteger(value.step)&&job.steps.some(s=>s.step===value.step),'Choose a recorded step');
      const step=job.steps.find(s=>s.step===value.step);
      const issue={id:issueID,step:value.step,comment:value.comment.trim(),created_at:iso(this.now()),
        episode:job.episode||null,artifact:step?.artifact||null,runtime:job.runtime,source:'human_review_not_verifier'};
      job.issues.push(issue);return issue;
    });
  }
  async poll(value) {
    insist(typeof value.worker_id==='string'&&ID.test(value.worker_id),'Invalid worker identity');
    insist(['live','rehearsal'].includes(value.mode),'Invalid worker mode');
    insist(Array.isArray(value.tasks)&&value.tasks.every(id=>TASKS.some(t=>t.id===id)),'Invalid worker capabilities');
    const eligible=job=>job.status==='queued'&&value.tasks.includes(job.task)&&
      (!needsRevision(TASKS.find(t=>t.id===job.task))||value.task_revisions?.[job.task]===job.task_revision)&&
      (!TASKS.find(t=>t.id===job.task)?.expanded||value.mode==='live')&&
      (!job.required_execution_mode||job.required_execution_mode===value.mode);
    const observed=await this.state();
    if(!observed.active&&!Object.values(observed.jobs).some(eligible)&&
        observed.worker?.id===value.worker_id&&observed.worker.mode===value.mode&&
        JSON.stringify(observed.worker.tasks)===JSON.stringify(value.tasks)&&JSON.stringify(observed.worker.task_revisions??{})===JSON.stringify(value.task_revisions??{})&&this.now()-Date.parse(observed.worker.updated_at)<30000)
      return {job:null}; // Idle polling does not write a fresh control object every time.
    return this.mutate(state=>{
      this.expire(state);
      if(state.active) {
        const active=state.jobs[state.active];
        insist(active.worker_id===value.worker_id,'Another worker owns the active job',409);
        // A lost claim response must never cause a second execution.
        return {job:null,active:active.id};
      }
      state.worker={id:value.worker_id,mode:value.mode,tasks:value.tasks,task_revisions:value.task_revisions??{},updated_at:iso(this.now())};
      const job=Object.values(state.jobs).find(eligible);
      if(!job)return {job:null};
      job.status='running';job.worker_id=value.worker_id;job.lease=randomUUID();job.mode=value.mode;
      job.updated_at=iso(this.now());state.active=job.id;
      // Review notes, previous runs and verifier outputs never enter the worker's job input.
      return {job:{id:job.id,task:job.task,goal:job.goal,task_revision:job.task_revision||null,lease:job.lease,mode:job.mode}};
    });
  }
  async checkpoint(value) {
    return this.mutate(state=>{
      const job=this.leased(state,value);job.updated_at=iso(this.now());
      if(state.worker?.id===job.worker_id)state.worker.updated_at=job.updated_at;
      return {ok:true};
    });
  }
  async reserve(value) {
    insist(Number.isInteger(value.step)&&value.step>=0&&value.step<50,'Invalid request index');
    insist(Number.isInteger(value.input_bytes)&&value.input_bytes>0&&value.input_bytes<=1000000,'Request input exceeds bound');
    insist(/^[a-f0-9]{64}$/.test(value.request_sha256),'Invalid request fingerprint');
    // Legacy workers omitted the field and are pinned to 512. New workers
    // require an acknowledged ceiling before dispatch; never silently underreserve.
    const max_tokens=value.max_tokens===undefined?512:value.max_tokens;
    insist(Number.isSafeInteger(max_tokens)&&max_tokens>0&&max_tokens<=completionTokenLimit(this.env.OPENROUTER_MAX_TOKENS),'Output token limit exceeds configured bound');
    const amount=(value.input_bytes+2048)*0.5/1e6+max_tokens*4/1e6;
    await this.mutate(state=>{
      const job=this.leased(state,value),limits=limitsFor(job.task);
      insist(value.step<limits.max_steps,'Invalid request index for task');
      insist(value.input_bytes<=limits.max_input_bytes,'Request input exceeds task bound');
      insist(job.mode==='live'&&job.reservations.length===value.step,'Request already attempted or out of order',409);
      job.reservations.push({step:value.step,request_sha256:value.request_sha256,max_tokens,amount_usd:amount,status:'pending',at:iso(this.now())});
    });
    // Shared daily ledger: charge reported cost after dispatch; retain unknown liabilities.
    const reservation={...await new Agent(this.store,{env:this.env}).reserve(amount),max_tokens};
    await this.mutate(state=>{
      const job=this.leased(state,value),row=job.reservations[value.step];
      insist(row.status==='pending','Reservation state changed',409);row.status='reserved';row.receipt=reservation;
    });
    return reservation;
  }
  async settle(value) {
    const state=await this.state(),job=state.jobs[value.id],row=job?.reservations?.[value.step];
    // A late response may settle a finished job, but never grants another action/lease.
    insist(job&&job.lease===value.lease&&row?.receipt&&row.request_sha256===value.request_sha256,'Settlement does not match a reserved request',409);
    insist(typeof value.response_text==='string'&&value.response_text.length<=8000000,'Invalid settlement evidence');
    let response;try{response=JSON.parse(value.response_text);}catch{}
    const cost=response?.usage?.cost;
    const result=await new Agent(this.store,{env:this.env}).settle(row.receipt,{
      cost:typeof cost==='number'&&Number.isFinite(cost)&&cost>=0?cost:null,
      response_id:response?.id??null,response_sha256:sha(Buffer.from(value.response_text))});
    await this.mutate(state=>{
      const saved=state.jobs[value.id].reservations[value.step];
      saved.settlement=result;saved.response_sha256=sha(Buffer.from(value.response_text));
      saved.status=result.status;
    });
    return result;
  }
  async artifact(value) {
    insist(ART.test(value.name),'Unsupported artifact');
    insist(typeof value.data==='string'&&value.data.length<=1500000&&/^[A-Za-z0-9+/]*={0,2}$/.test(value.data),'Artifact exceeds upload bound');
    const bytes=Buffer.from(value.data,'base64');insist(sha(bytes)===value.sha256,'Artifact hash mismatch');
    const state=await this.state();this.leased(state,value);
    const key=`daylight/harness/artifacts/${value.id}/${value.name}.json`,prior=await this.store.read(key);
    if(prior)insist(prior.value.sha256===value.sha256,'Original artifact cannot be replaced',409);
    else await this.store.write(key,{sha256:value.sha256,data:value.data,size:bytes.length});
    await this.mutate(state=>{const job=this.leased(state,value);job.artifacts[value.name]={sha256:value.sha256,size:bytes.length};});
    return {ok:true};
  }
  async update(value) {
    const snap=value.snapshot;insist(snap&&JSON.stringify(snap).length<=300000,'Snapshot exceeds bound');
    insist(Array.isArray(snap.steps)&&snap.steps.length<=50,'Invalid step list');
    return this.mutate(state=>{
      const job=this.leased(state,value),limits=limitsFor(job.task);
      insist(snap.steps.length<=limits.max_steps,'Invalid step list for task');
      // Native per-call live summaries use the same bounded envelope across task families.
      const task=TASKS.find(t=>t.id===job.task);
      if(task?.expanded) {
        if(!snap.status)insist(snap.evaluation==null,'Authoritative grading is terminal-only');
        else if(snap.evaluation!=null||snap.status==='finished')
          insist(snap.evaluation&&snap.grading_phase===task.grading_phase&&snap.evaluation_source==='authoritative-evaluation.json','Missing authoritative final result');
        else insist(typeof snap.error==='string'&&snap.error.length>0,'Missing technical failure evidence');
      }
      if(snap.resolved_goal!==undefined&&snap.resolved_goal!==null) {
        insist(typeof snap.resolved_goal==='string'&&snap.resolved_goal.length>0&&snap.resolved_goal.length<=5000,'Invalid resolved objective');
        insist(job.goal===null||job.goal===snap.resolved_goal,'Cannot replace the trusted objective',409);
        job.goal=snap.resolved_goal;job.resolved_goal=snap.resolved_goal;job.goal_resolution='resolved';
      }
      insist(snap.steps.every((step,index)=>step.step===index),'Recorded steps must be unique and sequential');
      for(const step of snap.steps) {
        insist(Number.isInteger(step.step)&&step.step>=0&&step.step<limits.max_steps,'Invalid recorded step');
        if(step.artifact)for(const name of Object.values(step.artifact))insist(job.artifacts[name],'Observation not uploaded');
      }
      insist(snap.steps.length>=job.steps.length,'Cannot remove recorded steps',409);
      for(const old of job.steps)insist(JSON.stringify(snap.steps.find(s=>s.step===old.step))===JSON.stringify(old),'Cannot rewrite a recorded step',409);
      if(snap.image)insist(job.artifacts[snap.image]&&snap.image.endsWith('.png'),'Image not uploaded');
      if(snap.trace_parts)for(const name of snap.trace_parts)insist(/^trace-\d{3}\.part$/.test(name)&&job.artifacts[name],'Trace archive incomplete');
      Object.assign(job,{steps:snap.steps,step_count:snap.steps.length,episode:snap.episode||null,runtime:snap.runtime||null,
        cost:snap.cost||null,
        grading_phase:snap.grading_phase??null,evaluation_source:snap.evaluation_source??null,
        evaluation:snap.evaluation||null,error:snap.error||null,updated_at:iso(this.now()),
        image:snap.image?`/api/harness/jobs/${job.id}/artifacts/${snap.image}`:job.image});
      if(snap.trace_parts?.length)job.trace_parts=snap.trace_parts;
      if(snap.status) {insist(terminal.has(snap.status),'Invalid terminal status');job.status=snap.status;state.active=null;}
      if(state.worker?.id===job.worker_id)state.worker.updated_at=job.updated_at;
      return {ok:true};
    });
  }
  async artifactRead(owner,id,name) {
    insist(ART.test(name),'Unsupported artifact');const state=await this.state(),job=this.own(state,owner,id);
    insist(job.artifacts[name],'Artifact not found',404);
    const row=await this.store.read(`daylight/harness/artifacts/${id}/${name}.json`);
    insist(row&&row.value.sha256===job.artifacts[name].sha256,'Artifact unavailable',503);
    const bytes=Buffer.from(row.value.data,'base64');insist(sha(bytes)===row.value.sha256,'Artifact integrity failure',503);return bytes;
  }
}
