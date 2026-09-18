// Read-only HTTP library; publication is a separate explicit local operation.
import {createHash,randomUUID} from 'node:crypto';
import {mkdir,readFile,writeFile,lstat,link,unlink} from 'node:fs/promises';
import path from 'node:path';
const sha=raw=>createHash('sha256').update(raw).digest('hex');
const fail=(message,status=400)=>{throw Object.assign(Error(message),{status});};
const idOK=id=>typeof id==='string'&&/^[a-f0-9]{20}$/.test(id);
const hashOK=id=>typeof id==='string'&&/^[a-f0-9]{64}$/.test(id);
const ownerKey=owner=>{if(typeof owner!=='string'||!owner||owner.length>200)fail('Invalid owner');return sha(owner);};
const metadataFields=['site_id','collection','interaction_kind','task_id','task_name','condition','task_revision','execution_status','execution_mode','goal','metadata_source'];
const safeMimes=new Set(['image/png','image/jpeg','image/webp','video/webm','text/plain; charset=utf-8','application/json','application/gzip','application/octet-stream']);
export class TraceLibrary {
  constructor(store,{root}={}){this.store=store;this.root=path.resolve(root||'.local/control/library');}
  prefix(owner){return 'daylight/library/'+ownerKey(owner)+'/';}
  async record(owner,id){if(!idOK(id))fail('Saved session not found',404);const row=await this.store.read(this.prefix(owner)+id);if(!row)fail('Saved session not found',404);return JSON.parse(await this.bytes(row.value.descriptor_sha256));}
  async list(owner,{cursor,limit=25}={}){
    const prefix=this.prefix(owner);
    if(!Number.isInteger(limit)||limit<1||limit>100||(cursor!=null&&!idOK(cursor)))fail('Invalid library page');
    const page=await this.store.listKeys(prefix,{limit,...(cursor?{cursor:prefix+cursor}:{})});
    const rows=await Promise.all(page.keys.map(key=>this.store.read(key)));
    return {sessions:rows.map(row=>row.value.summary),has_more:page.has_more,cursor:page.cursor?.slice(prefix.length)||null};
  }
  object(hash){if(!hashOK(hash))fail('Invalid object');return path.join(this.root,'objects',hash.slice(0,2),hash);}
  async bytes(hash){const raw=await readFile(this.object(hash));if(sha(raw)!==hash)fail('Library object damaged',503);return raw;}
  async session(owner,id){const row=await this.record(owner,id);return {raw:await this.bytes(row.projection_sha256),etag:'"'+row.projection_sha256+'"'};}
  async asset(owner,id,attachment,range){
    const row=await this.record(owner,id);
    if(!hashOK(attachment)||!Object.hasOwn(row.assets,attachment))fail('Asset not found',404);
    const asset=row.assets[attachment];
    let start=0,end=asset.bytes-1,status=200;
    if(range){const m=/^bytes=(\d*)-(\d*)$/.exec(range);if(!m||(!m[1]&&!m[2]))fail('Invalid range',416);
      if(!m[1])start=Math.max(0,asset.bytes-Number(m[2]));else{start=Number(m[1]);if(m[2])end=Math.min(end,Number(m[2]));}
      if(!Number.isSafeInteger(start)||!Number.isSafeInteger(end)||start>end||start>=asset.bytes)fail('Invalid range',416);status=206;
    }
    return {file:this.object(asset.sha256),type:safeMimes.has(asset.mime_type)?asset.mime_type:'application/octet-stream',etag:'"'+asset.sha256+'"',size:asset.bytes,start,end,status};
  }
  async put(raw){
    const hash=sha(raw),file=this.object(hash);await mkdir(path.dirname(file),{recursive:true,mode:0o700});
    const tmp=file+'.'+randomUUID();await writeFile(tmp,raw,{flag:'wx',mode:0o600});
    try{try{await link(tmp,file);}catch(e){if(e.code!=='EEXIST')throw e;await this.bytes(hash);}}finally{await unlink(tmp);}
    return hash;
  }
  async publish(directory,owner,metadata={}){
    // The caller must review confidentiality before publication. This is not a sanitizer.
    this.prefix(owner);directory=path.resolve(directory);
    const read=async name=>{
      if(typeof name!=='string'||!name||name.includes('\\')||name.split('/').some(p=>!p||p==='.'||p==='..')||path.isAbsolute(name))fail('Invalid bundle path');
      let file=directory;for(const part of name.split('/')){file=path.join(file,part);if((await lstat(file)).isSymbolicLink())fail('Bundle symlinks are not accepted');}
      const stat=await lstat(file);if(!stat.isFile())fail('Bundle entry is not a file');if(stat.size>64*1024*1024)fail('Bundle file exceeds 64 MiB import limit',413);return readFile(file);
    };
    const manifestRaw=await read('manifest.json'),manifest=JSON.parse(manifestRaw);
    if(manifest.schema_version!==1||manifest.kind!=='browsergym-saved-replay-v1'||manifest.read_only!==true||manifest.grader_recomputed!==false||!manifest.files)fail('Unsupported replay bundle');
    const verified=new Map();let totalBytes=0;
    for(const [name,info] of Object.entries(manifest.files)){
      const raw=await read(name);totalBytes+=raw.length;if(totalBytes>512*1024*1024)fail('Bundle exceeds 512 MiB import limit',413);if(!hashOK(info.sha256)||sha(raw)!==info.sha256||raw.length!==info.bytes)fail('Bundle hash or size mismatch');verified.set(name,raw);
    }
    if(!verified.has('session.json')||!verified.has('assets.json'))fail('Missing projection or asset mapping');
    const session=JSON.parse(verified.get('session.json')),mapping=JSON.parse(verified.get('assets.json'));
    if(session.id!==manifest.viewer_session_id||!Array.isArray(session.messages)||session.environment!=='browsergym')fail('Invalid BrowserGym projection');
    const selected={};for(const key of metadataFields){const value=metadata[key]??null;if(value!==null&&(typeof value!=='string'||value.length>10000))fail('Invalid publication metadata');selected[key]=value;}
    if(selected.interaction_kind!==null&&!['task','ask'].includes(selected.interaction_kind))fail('Invalid interaction kind');
    selected.metadata_source??='explicit local bundle publication';
    selected.evaluation=manifest.raw_outcomes??null;
    selected.original_session_id=session.id;selected.manifest_sha256=sha(manifestRaw);
    const id=sha(JSON.stringify([owner,sha(manifestRaw),selected])).slice(0,20),assets={};
    for(const message of session.messages)for(const asset of message.attachments||[]){
      const source=mapping[asset.url];if(!source||!verified.has(source.path))fail('Unmapped attachment');
      const raw=verified.get(source.path);if(sha(raw)!==source.sha256||raw.length!==source.bytes)fail('Attachment hash mismatch');
      const key=sha(asset.url);assets[key]={sha256:source.sha256,bytes:source.bytes,mime_type:source.mime_type};
      asset.url='/api/library/sessions/'+id+'/assets/'+key;
    }
    session.id=id;session.library_metadata=selected;
    const summary={id,revision:sha(manifestRaw),...selected};
    for(const key of ['title','state','environment','message_count','decision_count','started_at','updated_at'])summary[key]=session[key]??null;
    // Copy original evidence too, without exposing source HTML as executable assets.
    const originals={};for(const [name,raw] of verified)originals[name]=await this.put(raw);
    const projection_sha256=await this.put(Buffer.from(JSON.stringify(session)));
    const record={summary,projection_sha256,assets,originals,manifest_sha256:await this.put(manifestRaw)};
    const catalogRecord={summary,descriptor_sha256:await this.put(Buffer.from(JSON.stringify(record)))};
    const key=this.prefix(owner)+id,prior=await this.store.read(key);
    if(prior){if(JSON.stringify(prior.value)!==JSON.stringify(catalogRecord))fail('Publication conflict',409);return summary;}
    try{await this.store.write(key,catalogRecord);}catch(e){const concurrent=await this.store.read(key);if(!concurrent||JSON.stringify(concurrent.value)!==JSON.stringify(catalogRecord))throw e;}
    return summary;
  }
}
