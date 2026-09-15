// Portable, single-host persistence. No Blob dependency or network access.
import {DatabaseSync} from 'node:sqlite';
import {randomUUID} from 'node:crypto';
import {mkdirSync,chmodSync} from 'node:fs';
import path from 'node:path';

const validKey=key=>typeof key==='string'&&key.startsWith('daylight/')&&key.length<=1024&&
  !key.includes('\\')&&!key.includes('\0')&&!key.split('/').some(x=>x==='.'||x==='..');
export class SqliteStore {
  constructor(filename) {
    mkdirSync(path.dirname(filename),{recursive:true,mode:0o700});
    this.db=new DatabaseSync(filename);chmodSync(filename,0o600);
    this.db.exec('PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL; PRAGMA busy_timeout=5000;');
    this.db.exec('CREATE TABLE IF NOT EXISTS objects (key TEXT PRIMARY KEY, raw TEXT NOT NULL, etag TEXT NOT NULL)');
  }
  close() {this.db.close();}
  async read(key) {
    if(!validKey(key))throw Object.assign(Error('Invalid storage key'),{status:400});
    const row=this.db.prepare('SELECT raw,etag FROM objects WHERE key=?').get(key);
    return row?{value:JSON.parse(row.raw),etag:row.etag}:null;
  }
  async write(key,value,etag=null) {
    if(!validKey(key)||!(etag===null||typeof etag==='string'))throw Object.assign(Error('Invalid storage key or version'),{status:400});
    const raw=JSON.stringify(value);if(raw===undefined)throw Object.assign(Error('Missing storage value'),{status:400});
    const next=randomUUID();
    // A fresh version even when the payload is identical prevents ABA after interrupt/claim.
    this.db.exec('BEGIN IMMEDIATE');
    try {
      const prior=this.db.prepare('SELECT etag FROM objects WHERE key=?').get(key);
      if((prior?.etag??null)!==etag)throw Object.assign(Error('Storage conflict'),{status:409});
      this.db.prepare('INSERT INTO objects VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET raw=excluded.raw,etag=excluded.etag').run(key,raw,next);
      this.db.exec('COMMIT');return next;
    } catch(error) {this.db.exec('ROLLBACK');throw error;}
  }
  async listKeys(prefix,{cursor,limit=25}={}) {
    if(!validKey(prefix)||!Number.isInteger(limit)||limit<1||limit>1000||
       (cursor!==undefined&&typeof cursor!=='string'))throw Object.assign(Error('Invalid storage listing'),{status:400});
    const rows=this.db.prepare('SELECT key FROM objects WHERE substr(key,1,?)=? AND key>? ORDER BY key LIMIT ?')
      .all(prefix.length,prefix,cursor??'',limit+1);
    const keys=rows.slice(0,limit).map(x=>x.key),more=rows.length>limit;
    return {keys,cursor:more?keys.at(-1):null,has_more:more};
  }
}
