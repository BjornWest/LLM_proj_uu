// Private, revocable WebArena leases. No Docker privileges in this process.
export class BrowsePool {
  constructor(env,fetcher=fetch){this.origin=env.DAYLIGHT_BROWSE_POOL_URL;this.token=env.DAYLIGHT_BROWSE_POOL_TOKEN;this.fetcher=fetcher;}
  async call(operation,value={}){
    if(!this.origin||!this.token)throw Object.assign(Error('Browsing pool unavailable'),{status:503});
    const response=await this.fetcher(this.origin+'/_control/'+operation,{method:'POST',redirect:'error',
      headers:{authorization:'Bearer '+this.token,'content-type':'application/json'},body:JSON.stringify(value),signal:AbortSignal.timeout(3000)});
    if(!response.ok)throw Object.assign(Error('Browsing pool unavailable or busy'),{status:[409,429].includes(response.status)?429:503});
    return response.json();
  }
  status(){return this.call('status');}
  acquire(site,id){return this.call('acquire',{site_id:site,session_id:id});}
  release(lease){return this.call('release',{lease_token:lease.lease_token});}
}
