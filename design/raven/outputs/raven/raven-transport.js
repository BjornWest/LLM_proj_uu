/* Raven backend contract v1. No model credentials belong in this client. */
(() => {
  'use strict';
  class RavenTransport {
    constructor({baseURL=''}={}) { this.baseURL=baseURL.replace(/\/$/,''); }
    async request(path,body) {
      const response=await fetch(this.baseURL+path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{})});
      if(!response.ok)throw new Error(`Backend request failed (${response.status})`);
      return response.json();
    }
    start(payload,{onEvent,onError}) {
      let stream=null,cancelled=false,closed=false;
      const session={
        runId:null,
        close:()=>{closed=true;stream?.close();},
        cancel:async()=>{cancelled=true;session.close();await session.ready;if(session.runId)return this.request(`/api/tasks/${encodeURIComponent(session.runId)}/cancel`);}
      };
      session.ready=this.request('/api/tasks',payload).then(({run_id})=>{
        session.runId=run_id;
        if(cancelled||closed)return;
        stream=new EventSource(this.baseURL+`/api/tasks/${encodeURIComponent(run_id)}/events`);
        stream.onmessage=message=>{
          if(closed)return;
          try {
            const event=JSON.parse(message.data);
            if(['final','error','done'].includes(event.type))session.close();
            onEvent(event);
          } catch(error) { session.cancel().catch(()=>{});onError(error); }
        };
        // Reconnection replays the whole run. Surface a dropped stream once,
        // instead of replaying site visits or appending a second answer.
        stream.onerror=()=>{if(closed)return;session.cancel().catch(()=>{});onError(new Error('Connection to Raven was interrupted. Please try again.'));};
      }).catch(error=>{if(!cancelled&&!closed){session.close();onError(error);}});
      return session;
    }
    focusTab(tabId){return this.request(`/api/tabs/${encodeURIComponent(tabId)}/focus`);}
    handback(runId,tabId,note=null){return this.request(`/api/tasks/${encodeURIComponent(runId)}/handback`,{tab_id:tabId,note});}
    async tabs(){const response=await fetch(this.baseURL+'/api/tabs');if(!response.ok)throw new Error('Could not list browser tabs');return response.json();}
  }
  window.RavenTransport=RavenTransport;
  window.ravenTransport=new RavenTransport();
})();
