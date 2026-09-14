import {get,put} from '@vercel/blob';
import {createHash} from 'node:crypto';
import {mkdir,readFile,writeFile,rename} from 'node:fs/promises';
import path from 'node:path';

export class BlobStore {
  async read(key) {
    const result=await get(key,{access:'private',useCache:false,token:process.env.BLOB_READ_WRITE_TOKEN});
    if (!result) return null;
    if (result.statusCode !== 200) throw Error('Unexpected trace storage response');
    return {value:JSON.parse(await new Response(result.stream).text()),etag:result.blob.etag};
  }
  async write(key,value,etag=null) {
    const result=await put(key,JSON.stringify(value),{access:'private',addRandomSuffix:false,
      allowOverwrite:etag!==null,...(etag?{ifMatch:etag}:{}),contentType:'application/json',
      token:process.env.BLOB_READ_WRITE_TOKEN});
    return result.etag;
  }
}
// Local development only, serialized writes. Never selected inside Vercel.
export class FileStore {
  constructor(root) {this.root=root;this.tail=Promise.resolve();}
  async read(key) {
    try {const raw=await readFile(path.join(this.root,key),'utf8');return {value:JSON.parse(raw),etag:createHash('sha256').update(raw).digest('hex')};}
    catch(e) {if(e.code==='ENOENT')return null;throw e;}
  }
  async write(key,value,etag=null) {
    const operation=this.tail.then(async()=>{
      const prior=await this.read(key);
      if ((prior?.etag||null)!==etag) throw Error('Storage conflict');
      const file=path.join(this.root,key),raw=JSON.stringify(value);
      await mkdir(path.dirname(file),{recursive:true});await writeFile(file+'.tmp',raw,{mode:0o600});await rename(file+'.tmp',file);
      return createHash('sha256').update(raw).digest('hex');
    });
    this.tail=operation.catch(()=>{});return operation;
  }
}
