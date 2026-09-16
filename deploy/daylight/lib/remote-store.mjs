import {BlobStore,StorageError} from './store.mjs';

// This token is server-only. Never use a browser-supplied origin or credentials.
export class RemoteStore {
  constructor({env=process.env,fetcher=fetch}={}) {
    this.fetcher=fetcher;
    try {
      const url=new URL(env.DAYLIGHT_CONTROL_URL);
      if((url.protocol!=='https:'&&!(url.protocol==='http:'&&['127.0.0.1','localhost'].includes(url.hostname)))||
          url.username||url.password||url.search||url.hash||url.pathname!=='/')throw Error();
      if(typeof env.DAYLIGHT_CONTROL_TOKEN!=='string'||env.DAYLIGHT_CONTROL_TOKEN.length<43)throw Error();
      this.origin=url.origin;this.token=env.DAYLIGHT_CONTROL_TOKEN;
    } catch {throw new StorageError('CONTROL_CONFIGURATION','configure');}
  }
  async request(operation,args) {
    try {
      const result=await this.fetcher(this.origin+'/internal/store/'+operation,{method:'POST',redirect:'error',
        headers:{authorization:'Bearer '+this.token,'content-type':'application/json'},
        body:JSON.stringify(args),signal:AbortSignal.timeout(25000)});
      if(result.status===409)throw new StorageError('BLOB_WRITE_CONFLICT',operation);
      if(!result.ok)throw new StorageError('CONTROL_UNAVAILABLE',operation);
      return await result.json();
    } catch(error) {
      if(error instanceof StorageError)throw error;
      throw new StorageError('CONTROL_UNAVAILABLE',operation);
    }
  }
  read(key) {return this.request('read',{key});}
  write(key,value,etag=null) {return this.request('write',{key,value,etag});}
  listKeys(prefix,{cursor,limit=25}={}) {return this.request('list',{prefix,cursor,limit});}
  listTraces(owner,{cursor,limit=25}={}) {return this.request('trace-list',{owner,cursor,limit});}
}

export function configuredStore(env=process.env) {
  // A broken remote configuration must never fall back to a second live budget/queue.
  return env.DAYLIGHT_CONTROL_URL||env.DAYLIGHT_CONTROL_TOKEN?new RemoteStore({env}):new BlobStore({env});
}
