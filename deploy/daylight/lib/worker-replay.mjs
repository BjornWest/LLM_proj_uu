// Lazy read-only rendering of existing owner-scoped worker archives. No inference.
import {createHash} from 'node:crypto';
import {mkdtemp,readFile,open,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {TraceLibrary} from './library.mjs';
import {Harness} from './harness.mjs';
const execute=promisify(execFile),sha=raw=>createHash('sha256').update(raw).digest('hex');
const repo=fileURLToPath(new URL('../../../',import.meta.url));
const fail=(message,status)=>{throw Object.assign(Error(message),{status});};
class PrivateReplayLibrary extends TraceLibrary {
  prefix(owner){return super.prefix(owner).replace('daylight/library/','daylight/worker-replay/');}
}
export class WorkerReplay {
  constructor(store,{env=process.env,root}={}){
    this.store=store;this.env=env;this.harness=new Harness(store,{env});
    this.library=new PrivateReplayLibrary(store,{root});this.pending=new Map();
  }
  async resolve(owner,id){
    // Ownership is checked even for cached results and conditional/asset reads.
    if(!/^[a-f0-9-]{36}$/.test(id||''))fail('Run not found',404);
    const state=await this.harness.state(),job=this.harness.own(state,owner,id);
    if(!['finished','error','interrupted'].includes(job.status)||!job.trace_parts?.length)fail('Original trace is not available yet',409);
    if(job.trace_parts.length>200||new Set(job.trace_parts).size!==job.trace_parts.length)fail('Invalid archive parts',503);
    const parts=job.trace_parts.map((name,i)=>{
      if(name!==`trace-${String(i).padStart(3,'0')}.part`||!job.artifacts?.[name]?.sha256)fail('Invalid archive parts',503);
      return [name,job.artifacts[name].sha256];
    });
    const source=await readFile(path.join(repo,'deploy/daylight/vendor/agent_trace/projection-provenance.json'));
    const script=await readFile(path.join(repo,'scripts/project_worker_trace.py'));
    const revision=sha(JSON.stringify([parts,sha(source),sha(script)]));
    const key='daylight/worker-replay-index/'+sha(owner)+'/'+id+'/'+revision;
    const cached=await this.store.read(key);
    if(cached)return {job,...cached.value};
    if(!this.pending.has(key)){
      // Bound global cold projection concurrency; repeated opens share work.
      if(this.pending.size>=2)fail('Trace projection busy; try again shortly',429);
      this.pending.set(key,this.build(owner,job,key).finally(()=>this.pending.delete(key)));
    }
    return {job,...await this.pending.get(key)};
  }
  async build(owner,job,key){
    const temp=await mkdtemp(path.join(tmpdir(),'daylight-worker-replay-'));
    try{
      const archive=path.join(temp,'trace.zip'),fd=await open(archive,'wx',0o600);let bytes=0;
      try{for(const name of job.trace_parts){const raw=await this.harness.artifactRead(owner,job.id,name);bytes+=raw.length;if(bytes>200*1024*1024)fail('Archive too large',413);await fd.writeFile(raw);}}finally{await fd.close();}
      // execFile (no shell), fixed trusted script; archive data cannot select code.
      try{await execute(this.env.DAYLIGHT_REPLAY_PYTHON||'python3',[path.join(repo,'scripts/project_worker_trace.py'),archive,path.join(temp,'bundle')],{timeout:20000,maxBuffer:65536,env:{...process.env,PYTHONDONTWRITEBYTECODE:'1'}});}catch{fail('Saved archive cannot be projected',503);}
      const metadata={};
      for(const field of ['site_id','collection','interaction_kind','task_name','condition','task_revision','goal'])metadata[field]=job[field]??null;
      Object.assign(metadata,{task_id:job.task??null,execution_status:job.status,execution_mode:job.mode??null,metadata_source:'Recorded worker job; no current-registry inference'});
      const family=JSON.parse(await readFile(path.join(temp,'bundle/family.json'))),members={},assets={};
      for(const [episode,relative] of Object.entries(family.members)){
        if(!/^[a-f0-9]{20}$/.test(episode)||!(relative==='.'||relative==='family/'+episode))fail('Invalid family projection',503);
        const row=await this.library.publish(path.join(temp,'bundle',relative),owner,
          episode===family.root?metadata:{...metadata,task_id:'delegated-task',task_name:'Helper conversation',goal:null,metadata_source:'Nested recorded conversation; no independent task grading'});
        members[episode]=row.id;
        const record=await this.library.record(owner,row.id);
        for(const attachment of Object.keys(record.assets)){
          if(assets[attachment]&&assets[attachment]!==row.id)fail('Ambiguous family asset',503);
          assets[attachment]=row.id;
        }
      }
      const record={projection:members[family.root],root:family.root,members,assets};
      try{await this.store.write(key,record);}catch(error){const prior=await this.store.read(key);if(JSON.stringify(prior?.value)!==JSON.stringify(record))throw error;}
      return record;
    }finally{await rm(temp,{recursive:true,force:true});}
  }
  async session(owner,id,episode=null){
    const family=await this.resolve(owner,id),{job}=family;
    if(episode!==null&&(!/^[a-f0-9]{20}$/.test(episode)||!Object.hasOwn(family.members,episode)))fail('Conversation not found',404);
    const selected=episode||family.root,projection=family.members[selected],value=JSON.parse((await this.library.session(owner,projection)).raw);
    value.id=id;
    if(selected===family.root)value.library_metadata.evaluation=job.evaluation??null;
    value.family_sessions=Object.keys(family.members).map(member=>({episode_id:member,relationship:member===family.root?'root':'helper',selected:member===selected}));
    value.library_metadata.execution_status=job.status;
    value.worker_trace={id,original_url:'/api/harness/jobs/'+id+'/trace',error:job.error??null,grader_recomputed:false};
    for(const message of value.messages)for(const attachment of message.attachments||[]){
      const key=attachment.url.split('/').at(-1);attachment.url='/api/harness/jobs/'+id+'/replay-assets/'+key;
    }
    const raw=Buffer.from(JSON.stringify(value));return {raw,etag:'"'+sha(raw)+'"'};
  }
  async asset(owner,id,attachment,range){const family=await this.resolve(owner,id),projection=family.assets[attachment];if(!projection)fail('Asset not found',404);return this.library.asset(owner,projection,attachment,range);}
}
