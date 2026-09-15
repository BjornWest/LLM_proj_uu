import * as blob from '@vercel/blob';
import {createHash} from 'node:crypto';
import {mkdir,readFile,writeFile,rename} from 'node:fs/promises';
import path from 'node:path';

const storageMessages={
  BLOB_TOKEN_MISSING:'Private trace storage is not configured. Connect a Private Blob store (BLOB_STORE_ID) or add BLOB_READ_WRITE_TOKEN to this deployment’s environment, then redeploy.',
  BLOB_OIDC_ENVIRONMENT_DENIED:'Blob access is not enabled for this deployment environment. Update the store’s project connection to include Production or Preview as appropriate, then redeploy.',
  BLOB_ACCESS_DENIED:'Private trace storage rejected access. Check that the connected Blob token belongs to the intended store.',
  BLOB_STORE_NOT_FOUND:'The configured Blob store does not exist. Reconnect private storage and redeploy.',
  BLOB_STORE_SUSPENDED:'The Blob store is suspended. Check its status and usage in Vercel Storage.',
  BLOB_ACCESS_MODE_MISMATCH:'The Blob store access mode does not match this app. Connect a Private store and redeploy.',
  BLOB_WRITE_CONFLICT:'Private storage rejected a conditional write. The agent stopped to preserve the trace and budget.',
  BLOB_RATE_LIMITED:'Private trace storage is rate limited. Check its usage in Vercel Storage.',
  BLOB_SERVICE_UNAVAILABLE:'Private trace storage is temporarily unavailable.',
  BLOB_TOKEN_INVALID:'The Blob token could not be read. Check BLOB_READ_WRITE_TOKEN in this deployment’s environment.',
  BLOB_OPERATION_FAILED:'Private trace storage failed. Check the matching entry in Vercel Runtime Logs.',
};
export class StorageError extends Error {
  constructor(code,operation) {super(storageMessages[code]);this.code=code;this.operation=operation;}
}
function classify(error,operation) {
  const types=[['BlobAccessError','BLOB_ACCESS_DENIED'],['BlobStoreNotFoundError','BLOB_STORE_NOT_FOUND'],
    ['BlobStoreSuspendedError','BLOB_STORE_SUSPENDED'],['BlobPreconditionFailedError','BLOB_WRITE_CONFLICT'],
    ['BlobServiceRateLimited','BLOB_RATE_LIMITED'],['BlobServiceNotAvailable','BLOB_SERVICE_UNAVAILABLE']];
  let code=types.find(([name])=>error instanceof blob[name])?.[1];
  // Inspect SDK text only to map it to fixed messages; never echo arbitrary error text.
  if(!code&&error instanceof blob.BlobError) {
    if(/OIDC is enabled for this project, but not for the/.test(error.message))code='BLOB_OIDC_ENVIRONMENT_DENIED';
    else if(/No blob credentials found|No read-write token found/.test(error.message))code='BLOB_TOKEN_MISSING';
    else if(/Failed to fetch blob: (401|403)\b/.test(error.message))code='BLOB_ACCESS_DENIED';
    else if(/Invalid token|Invalid delegation token/i.test(error.message))code='BLOB_TOKEN_INVALID';
    else if(/public/i.test(error.message)&&/private/i.test(error.message)&&/store/i.test(error.message))code='BLOB_ACCESS_MODE_MISMATCH';
  }
  return new StorageError(code||'BLOB_OPERATION_FAILED',operation);
}
export class BlobStore {
  constructor({env=process.env,sdk=blob}={}) {this.env=env;this.sdk=sdk;}
  auth(operation) {
    const token=this.env.BLOB_READ_WRITE_TOKEN;
    if(typeof token==='string'&&token.trim())return {token};
    // Let the SDK read and refresh Vercel's OIDC token; never capture it ourselves.
    if(this.env.BLOB_STORE_ID?.trim())return {storeId:this.env.BLOB_STORE_ID};
    throw new StorageError('BLOB_TOKEN_MISSING',operation);
  }
  async read(key) {
    const auth=this.auth('read');
    try {
      // Request original bytes so CDN compression cannot substitute a representation ETag.
      // Keep the returned ETag intact; never strip weak validators or bypass ifMatch.
      const result=await this.sdk.get(key,{access:'private',useCache:false,headers:{'accept-encoding':'identity'},...auth});
      if (!result) return null;
      if (result.statusCode !== 200) throw Error('Unexpected trace storage response');
      return {value:JSON.parse(await new Response(result.stream).text()),etag:result.blob.etag};
    } catch(error) {throw classify(error,'read');}
  }
  async write(key,value,etag=null) {
    const auth=this.auth('write');
    try {
      const result=await this.sdk.put(key,JSON.stringify(value),{access:'private',addRandomSuffix:false,
        allowOverwrite:etag!==null,...(etag?{ifMatch:etag}:{}),contentType:'application/json',...auth});
      return result.etag;
    } catch(error) {throw classify(error,'write');}
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
