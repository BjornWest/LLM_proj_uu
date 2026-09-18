import {RemoteStore} from './remote-store.mjs';
export class LibraryClient extends RemoteStore {
  async call(operation,value){
    let response;try{response=await this.fetcher(this.origin+'/internal/library/'+operation,{method:'POST',redirect:'error',headers:{authorization:'Bearer '+this.token,'content-type':'application/json'},body:JSON.stringify(value),signal:AbortSignal.timeout(25000)});}catch{throw Object.assign(Error('Trace library is unavailable'),{status:503});}
    if(!response.ok&&response.status!==206)throw Object.assign(Error(response.status===404?'Saved session or asset not found':'Trace library request failed'),{status:[400,404,416].includes(response.status)?response.status:503});
    return response;
  }
}
