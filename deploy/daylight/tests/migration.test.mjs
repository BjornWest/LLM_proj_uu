import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,readFile,writeFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {exportSnapshot,importSnapshot} from '../migrate-storage.mjs';
import {SqliteStore} from '../lib/sqlite-store.mjs';

async function fixture(t){const dir=await mkdtemp(tmpdir()+'/storage-migrate-');t.after(()=>rm(dir,{recursive:true,force:true}));return dir;}
const raws={'daylight/traces/old.json':'{ "evaluation": null, "status": "error", "steps": [] }\n',
 'daylight/harness/artifacts/id/trace-000.part.json':'{"data":"AAECAw==","sha256":"saved"}',
 'daylight/budget.json':'{"reserved":0.5}'};
const sdk={async list(){return {blobs:Object.entries(raws).map(([pathname,raw])=>({pathname,size:Buffer.byteLength(raw),uploadedAt:new Date(0)})),hasMore:false};},
 async get(key){return {statusCode:200,stream:new Response(raws[key]).body,blob:{etag:'old'}};}};
test('migration preserves exact raw bytes/nulls/budget/archive and refuses overwrite or corruption',async t=>{
 const dir=await fixture(t);await exportSnapshot(dir+'/snapshot',{sdk,token:'fake'});
 const report=await importSnapshot(dir+'/snapshot',dir+'/state.sqlite');assert.equal(report.objects,3);
 const db=new SqliteStore(dir+'/state.sqlite');for(const [key,raw]of Object.entries(raws))assert.equal(db.db.prepare('SELECT raw FROM objects WHERE key=?').get(key).raw,raw);db.close();
 await assert.rejects(importSnapshot(dir+'/snapshot',dir+'/state.sqlite'),{code:'EEXIST'});
 const manifest=JSON.parse(await readFile(dir+'/snapshot/manifest.json'));
 await writeFile(dir+'/snapshot/'+manifest.entries[0].file,'{}');
 await assert.rejects(importSnapshot(dir+'/snapshot',dir+'/bad.sqlite'),/checksum/);
 await assert.rejects(exportSnapshot(dir+'/snapshot',{sdk,token:'fake'}),{code:'EEXIST'});
});
test('changed source and read-budget overflow never produce a complete snapshot',async t=>{
 const dir=await fixture(t);let n=0;
 const changed={...sdk,async list(){const v=await sdk.list();if(n++)v.blobs.pop();return v;}};
 await assert.rejects(exportSnapshot(dir+'/changed',{sdk:changed,token:'fake'}),/changed/);
 await assert.rejects(readFile(dir+'/changed/manifest.json'),{code:'ENOENT'});
 let gets=0;await assert.rejects(exportSnapshot(dir+'/limited',{sdk:{...sdk,get(){gets++;}},token:'fake',maxObjects:1}),/budget/);assert.equal(gets,0);
});
