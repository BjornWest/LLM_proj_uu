/* Raven backend contract v1. No model credentials belong in this client. */
(() => {
  'use strict';
  class RavenTransport {
    constructor({baseURL=''}={}) {
      this.baseURL=baseURL.replace(/\/$/,'');this.demoMode=true;
      this.ready=fetch(this.baseURL+'/api/health').then(r=>r.json()).then(h=>{this.demoMode=h.demo_mode!==false;}).catch(()=>{});
    }
    errorMessage(error) {return this.demoMode ? "Sorry — I couldn't finish that. Could you try again or rephrase?" : (error.message || String(error));}
    events(runId,{onEvent,onError}) {
      const stream=new EventSource(this.baseURL+`/api/tasks/${encodeURIComponent(runId)}/events`);
      let closed=false,recovering=false,timer=null,lastId=0;
      const connection={close:()=>{closed=true;clearTimeout(timer);stream.close();}};
      const fail=error=>{if(closed)return;connection.close();onError(error);};
      stream.onmessage=message=>{
        if(closed)return;
        clearTimeout(timer);lastId=Number(message.lastEventId)||lastId;
        try {onEvent(JSON.parse(message.data));} catch(error) {fail(error);}
      };
      stream.onopen=()=>{recovering=false;};
      stream.onerror=()=>{
        if(closed||recovering)return;
        if(!this.demoMode){fail(new Error('Connection to Raven was interrupted. Please try again.'));return;}
        recovering=true;
        // EventSource reconnects using Last-Event-ID; the backend owns the one retry allowance.
        timer=setTimeout(()=>fail(new Error('Stream recovery timed out')),15000);
        this.request(`/api/tasks/${encodeURIComponent(runId)}/retry`,{after_event_id:lastId}).catch(fail);
      };
      return connection;
    }
    async request(path,body,{keepalive=false}={}) {
      await this.ready;
      const response=await fetch(this.baseURL+path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{}),keepalive});
      if(!response.ok){const data=await response.json();throw new Error(data.error || `Backend request failed (${response.status})`);}
      return response.json();
    }
    start(payload,{onEvent,onError}) {
      let stream=null,cancelled=false,closed=false;
      const session={
        runId:null,
        close:()=>{closed=true;stream?.close();},
        cancel:({keepalive=false}={})=>{
          cancelled=true;session.close();
          const send=()=>session.runId?this.request(`/api/tasks/${encodeURIComponent(session.runId)}/cancel`,{},{keepalive}):undefined;
          // Dispatch immediately when the ID is known, including during pagehide.
          return session.runId?send():session.ready.then(send);
        }
      };
      session.ready=this.request('/api/tasks',payload).then(({run_id})=>{
        session.runId=run_id;
        if(cancelled||closed)return;
        stream=this.events(run_id,{
          onEvent:event=>{
            if(closed)return;
            if(['final','error','done'].includes(event.type))session.close();
            onEvent(event);
          },
          onError:error=>{if(closed)return;session.cancel().catch(()=>{});onError(error);}
        });
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
