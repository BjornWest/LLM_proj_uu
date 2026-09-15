// One-time private export. Never deletes or writes Blob objects. Run only after
// the old deployment is in storage maintenance and the old worker is stopped.
import {mkdir,writeFile,readFile,lstat} from 'node:fs/promises';
import {openSync,closeSync} from 'node:fs';
import {createHash,randomUUID} from 'node:crypto';
import {pathToFileURL} from 'node:url';
import path from 'node:path';
import * as blob from '@vercel/blob';
import {SqliteStore} from './lib/sqlite-store.mjs';

const sha=raw=>createHash('sha256').update(raw).digest('hex');
const keyOK=key=>typeof key==='string'&&key.startsWith('daylight/')&&!key.split('/').some(x=>x==='..'||x==='.')&&!key.includes('\\');
export async function exportSnapshot(output,{sdk=blob,token=process.env.BLOB_READ_WRITE_TOKEN,maxObjects=1500}={}) {
  if(!token)throw Error('BLOB_READ_WRITE_TOKEN required');
  await mkdir(output,{mode:0o700}); // exclusive directory; never rewrite an older snapshot
  async function inventory(){
    let cursor;const rows=[];
    do {
      const page=await sdk.list({prefix:'daylight/',limit:1000,token,...(cursor?{cursor}: {})});
      rows.push(...page.blobs.map(x=>({key:x.pathname,size:x.size,uploaded_at:new Date(x.uploadedAt).toISOString()})));
      if(rows.length>maxObjects)throw Error('Object read budget exceeded; inspect inventory before increasing limit');
      cursor=page.hasMore?page.cursor:null;
      if(page.hasMore&&!cursor)throw Error('Invalid inventory cursor');
    }while(cursor);
    rows.sort((a,b)=>a.key.localeCompare(b.key));
    if(new Set(rows.map(x=>x.key)).size!==rows.length)throw Error('Duplicate keys');
    return rows;
  }
  const before=await inventory(),entries=[];
  for(const row of before){
    if(!keyOK(row.key))throw Error('Unexpected key');
    const result=await sdk.get(row.key,{access:'private',useCache:false,headers:{'accept-encoding':'identity'},token});
    if(!result||result.statusCode!==200)throw Error('Missing snapshot object');
    const raw=Buffer.from(await new Response(result.stream).arrayBuffer());
    const value=JSON.parse(raw.toString('utf8'));
    if(row.key==='daylight/harness/control-v1.json'&&Object.values(value.jobs??{}).some(j=>['queued','running'].includes(j.status)))throw Error('Pending worker jobs; finish or explicitly resolve them before cutover');
    if(row.key.startsWith('daylight/traces/')&&value.status==='pending')throw Error('Pending model response; wait for completion before cutover');
    const file=sha(row.key)+'.json';await writeFile(path.join(output,file),raw,{flag:'wx',mode:0o600});
    entries.push({...row,file,bytes:raw.length,sha256:sha(raw),etag:result.blob.etag});
  }
  if(JSON.stringify(before)!==JSON.stringify(await inventory()))throw Error('Source changed during export; snapshot incomplete and cannot be imported');
  const manifest={schema_version:1,kind:'daylight-storage-snapshot',created_at:new Date().toISOString(),
    writers_paused_required:true,blob_mutations:0,objects:entries.length,entries};
  await writeFile(path.join(output,'manifest.json'),JSON.stringify(manifest,null,2),{flag:'wx',mode:0o600});return manifest;
}
export async function importSnapshot(input,filename) {
  const manifest=JSON.parse(await readFile(path.join(input,'manifest.json'),'utf8'));
  if(manifest.schema_version!==1||manifest.kind!=='daylight-storage-snapshot'||manifest.objects!==manifest.entries.length)throw Error('Invalid snapshot');
  const rows=[],seen=new Set();
  for(const row of manifest.entries){
    if(!keyOK(row.key)||seen.has(row.key)||row.file!==sha(row.key)+'.json')throw Error('Invalid or duplicate snapshot entry');seen.add(row.key);
    const file=path.join(input,row.file);if(!(await lstat(file)).isFile())throw Error('Not a regular snapshot file');
    const raw=await readFile(file);if(raw.length!==row.bytes||sha(raw)!==row.sha256)throw Error('Snapshot checksum mismatch');
    JSON.parse(raw.toString('utf8'));rows.push({key:row.key,raw:raw.toString('utf8')});
  }
  await mkdir(path.dirname(filename),{recursive:true,mode:0o700});
  closeSync(openSync(filename,'wx',0o600)); // refuse existing DB including dangling links
  const store=new SqliteStore(filename);
  try{
    store.db.exec('BEGIN IMMEDIATE');
    for(const row of rows)store.db.prepare('INSERT INTO objects VALUES (?,?,?)').run(row.key,row.raw,randomUUID());
    store.db.exec('COMMIT');
    for(const row of manifest.entries){const saved=store.db.prepare('SELECT raw FROM objects WHERE key=?').get(row.key);if(sha(saved.raw)!==row.sha256)throw Error('Import verification failed');}
    store.db.exec('PRAGMA wal_checkpoint(TRUNCATE)');
  }catch(e){if(store.db.isTransaction)store.db.exec('ROLLBACK');throw e;}finally{store.close();}
  return {objects:rows.length,raw_bytes_verified:true,blob_mutations:0};
}
if(process.argv[1]&&import.meta.url===pathToFileURL(process.argv[1]).href){
  process.umask(0o077);const [command,source,target,confirmation]=process.argv.slice(2);
  if(command==='export'&&target==='--confirm-writers-paused')console.log(JSON.stringify({objects:(await exportSnapshot(source)).objects,blob_mutations:0}));
  else if(command==='import'&&source&&target)console.log(JSON.stringify(await importSnapshot(source,target)));
  else throw Error('Usage: migrate-storage.mjs export NEW_DIR --confirm-writers-paused | import SNAPSHOT NEW_DB');
}
