// Human exploration only. No model, server transaction or privileged verifier.
(() => {
  'use strict';
  const prefix='/sites/tricky', route=location.pathname.slice(prefix.length), storage=window.sessionStorage;
  const site=route.startsWith('/health')?'health':route.startsWith('/spotify')?'music':route.startsWith('/news')?'news':'shop';
  const revision=document.querySelector('meta[name="intent-site-revision"]')?.content;
  if(!revision)throw Error('Missing shared site revision');
  const setup={shop:{entry:'/shop',pattern:'w',name:'Shopping',workspace:'tricky-shop'},music:{entry:'/spotify',pattern:'am',name:'Music',workspace:'tricky-music'},health:{entry:'/health',pattern:'cs',name:'Health',workspace:'tricky-health'},news:{entry:'/news',name:'News',workspace:'tricky-news'}}[site];
  const condition=new URLSearchParams(location.search).get('dp')||'clean';
  const activeKey='daylight-full-inspection-active:'+revision;
  let selected=storage.getItem(activeKey)||condition;storage.setItem(activeKey,selected);
  const key='daylight-full-inspection:'+revision+':'+selected;
  const fresh=()=>({schema_version:1,id:crypto.randomUUID(),runtime:'client-inspection-complete-v1',site,site_revision:revision,interaction_kind:'manual',actor:'human',condition:selected,created_at:new Date().toISOString(),evaluation:null,model:null,values:{},events:[],recording_limited:false});
  let state=JSON.parse(storage.getItem(key)||'null')||fresh();
  const save=()=>storage.setItem(key,JSON.stringify(state));
  function record(kind,payload){
    if(state.events.length<1000)state.events.push({sequence:state.events.length,at:new Date().toISOString(),kind,payload:JSON.parse(JSON.stringify(payload)),url:location.pathname+location.search});
    else state.recording_limited=true;
    save();updateStatus();
  }
  // Preserve the components' storage API while keeping conditions and ordinary
  // tabs independent. An intentionally duplicated browser tab may copy its state.
  Object.defineProperty(window,'localStorage',{value:{getItem:k=>Object.hasOwn(state.values,String(k))?state.values[String(k)]:null,
    setItem:(k,v)=>{state.values[String(k)]=String(v);save();},removeItem:k=>{delete state.values[String(k)];save();},
    clear:()=>{state.values={};save();},key:i=>Object.keys(state.values)[i]??null,get length(){return Object.keys(state.values).length;}}});
  // The shared site runtime owns initialization and transitions in BOTH modes.
  // This wrapper only scopes storage and records, never supplies task state.
  window.__intentEmit=async(kind,payload)=>{record(kind,payload);};
  function updateStatus(){const el=document.getElementById('inspection-status');if(el)el.textContent=state.recording_limited?'Local recording limit reached. Download and start fresh.':'State and inspection record stay in this tab. No agent is running.';}
  record('navigation',{path:location.pathname,condition:selected});
  document.addEventListener('DOMContentLoaded',()=>{
    const bar=document.createElement('section');bar.id='inspection-toolbar';bar.setAttribute('aria-label','Local inspection controls');
    const title=document.createElement('strong');title.textContent=setup.name+' · '+selected+' · version '+revision.slice(0,12);
    const status=document.createElement('span');status.id='inspection-status';status.setAttribute('role','status');
    const download=document.createElement('button');download.textContent='Download inspection record';download.onclick=()=>{
      const blob=new Blob([JSON.stringify({...state,exported_at:new Date().toISOString(),scope:'Browser-local manual exploration; no independent grade or automatic cloud trace upload.'},null,2)],{type:'application/json'});
      const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='inspection-'+state.id+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
    };
    const reset=document.createElement('button');reset.textContent='Start fresh';reset.onclick=()=>{state=fresh();save();location.href=prefix+setup.entry+(selected!=='clean'?'?dp='+encodeURIComponent(selected):'');};
    const back=document.createElement('a');back.href='/workspace?site='+setup.workspace;back.textContent='Back to workspace';
    bar.append(title,status,download,reset,back);document.body.prepend(bar);updateStatus();
    document.addEventListener('click',event=>{if(bar.contains(event.target))return;const el=event.target.closest('button,a,input,select,textarea');if(el)record('click',{tag:el.tagName,id:el.id,label:(el.getAttribute('aria-label')||el.textContent||'').slice(0,500)});},true);
    document.addEventListener('change',event=>{const el=event.target;if(bar.contains(el)||!('value' in el))return;record('change',{tag:el.tagName,id:el.id,value:String(el.value).slice(0,2000),value_truncated:String(el.value).length>2000});},true);
  });
})();
