import {RemoteStore} from './remote-store.mjs';

export class ManualClient extends RemoteStore {
  async call(operation,value){
    let response;
    try{
      response=await this.fetcher(this.origin+'/internal/manual/'+operation,{method:'POST',redirect:'error',
        headers:{authorization:'Bearer '+this.token,'content-type':'application/json'},body:JSON.stringify(value),signal:AbortSignal.timeout(28000)});
    }catch{throw Object.assign(Error('The manual browser connection was interrupted. Earlier actions may have happened; no automatic replay.'),{status:503});}
    const result=await response.json().catch(()=>null);
    if(!response.ok)throw Object.assign(Error(({400:'Unsupported manual request.',401:'Manual browser connection is not configured correctly.',
      404:'Manual session or artifact not found.',409:'A manual command is pending, stale, or already attempted. Refresh the session; no action was replayed.',
      429:'Manual browser capacity or session limit reached. Close an old session before continuing.'})[response.status]||'Manual browser service unavailable. No automatic retry.'),{status:[400,404,409,429].includes(response.status)?response.status:503});
    if(result===null)throw Object.assign(Error('Invalid manual browser response; no automatic retry.'),{status:503});
    return result;
  }
}
