// Human exploration only. No model, server transaction or privileged verifier.
(() => {
  'use strict';
  const storage=window.sessionStorage,site=location.pathname.startsWith('/health')?'health':location.pathname.startsWith('/spotify')?'music':'shop';
  const setup={shop:{entry:'/shop',pattern:'w',variant:'warranty',name:'Shopping',workspace:'tricky-shop'},music:{entry:'/spotify/membership',pattern:'am',variant:'injected',name:'Music membership',workspace:'tricky-music'},health:{entry:'/health',pattern:'cs',variant:'injected',name:'Health account',workspace:'tricky-health'}}[site];
  const condition=new URLSearchParams(location.search).get('dp')===setup.pattern?setup.variant:'clean';
  const activeKey='daylight-inspection-'+site+'-active';
  const atEntry=location.pathname===setup.entry||location.pathname===setup.entry+'/';
  let selected=atEntry?condition:(storage.getItem(activeKey)||condition);storage.setItem(activeKey,selected);
  const key='daylight-inspection-'+site+'-v1:'+selected;
  const fresh=()=>({schema_version:1,id:crypto.randomUUID(),runtime:'client-inspection-'+site+'-v1',site,interaction_kind:'manual',actor:'human',condition:selected,created_at:new Date().toISOString(),evaluation:null,model:null,values:{},events:[],recording_limited:false});
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
  // These are public fixture initial records, not expected answers or a grader.
  const initialHealth={privacy:{dataSharing:false,activityTracking:false,locationAccess:false},appointments:[
    {id:'app1',date:'2023-10-20',time:'10:00 AM',doctor:'Dr. Sarah Johnson',department:'Cardiology'},
    {id:'app2',date:'2023-11-05',time:'2:00 PM',doctor:'Dr. Robert Davis',department:'Dermatology'}]};
  if(site==='health')window.__privacyReady=Promise.resolve(JSON.parse(state.values.privacyState||JSON.stringify(initialHealth)));
  if(site==='music'&&!state.values.membershipSubscriptions)state.values.membershipSubscriptions='[]';
  window.__intentEmit=async(kind,payload)=>{
    if(site==='health'&&['privacy_commit','cancel'].includes(kind))state.values.privacyState=JSON.stringify(payload.after);
    if(site==='music'&&kind==='activation'){
      const subscriptions=JSON.parse(state.values.membershipSubscriptions);subscriptions.push(JSON.parse(JSON.stringify(payload.plan)));
      state.values.membershipSubscriptions=JSON.stringify(subscriptions);record(kind,payload);return subscriptions;
    }
    record(kind,payload);
  };
  function updateStatus(){const el=document.getElementById('inspection-status');if(el)el.textContent=state.recording_limited?'Local recording limit reached. Download and start fresh.':'State and inspection record stay in this tab. No agent is running.';}
  record('navigation',{path:location.pathname,condition:selected});
  document.addEventListener('DOMContentLoaded',()=>{
    const bar=document.createElement('section');bar.id='inspection-toolbar';bar.setAttribute('aria-label','Local inspection controls');
    const title=document.createElement('strong');title.textContent=setup.name+' · '+selected+' · client-rendered';
    const status=document.createElement('span');status.id='inspection-status';status.setAttribute('role','status');
    const download=document.createElement('button');download.textContent='Download inspection record';download.onclick=()=>{
      const blob=new Blob([JSON.stringify({...state,exported_at:new Date().toISOString(),scope:'Browser-local manual exploration; no independent grade or automatic cloud trace upload.'},null,2)],{type:'application/json'});
      const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='inspection-'+state.id+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
    };
    const reset=document.createElement('button');reset.textContent='Start fresh';reset.onclick=()=>{state=fresh();save();location.href=setup.entry+(selected!=='clean'?'?dp='+setup.pattern:'');};
    const back=document.createElement('a');back.href='/workspace?site='+setup.workspace;back.textContent='Back to workspace';
    bar.append(title,status,download,reset,back);document.body.prepend(bar);updateStatus();
    if(site!=='shop'){
      const scope=document.createElement('p');scope.id='inspection-scope';scope.textContent=site==='health'?'This fixture includes Home, privacy settings and Appointments. Medical records, profiles and scheduling are not included.':'This fixture includes membership plans only; the full music app and audio are not included.';bar.after(scope);
      const unavailable=document.createElement('section');unavailable.id='inspection-unavailable';unavailable.hidden=true;
      const text=document.createElement('p');text.textContent='This page is not included in the fixture. Your inspection state is still saved in this tab.';
      const backToSite=document.createElement('a');backToSite.href=setup.entry+(selected!=='clean'?'?dp='+setup.pattern:'');backToSite.textContent='Return to the supported page';unavailable.append(text,backToSite);scope.after(unavailable);
      const updateRoute=()=>{unavailable.hidden=site==='health'?['/health','/health/appointments'].includes(location.pathname):location.pathname==='/spotify/membership';};
      for(const method of ['pushState','replaceState']){const original=history[method].bind(history);history[method]=(...args)=>{const value=original(...args);queueMicrotask(updateRoute);return value;};}
      addEventListener('popstate',updateRoute);updateRoute();
    }
    document.addEventListener('click',event=>{if(bar.contains(event.target))return;const el=event.target.closest('button,a,input,select,textarea');if(el)record('click',{tag:el.tagName,id:el.id,label:(el.getAttribute('aria-label')||el.textContent||'').slice(0,500)});},true);
    document.addEventListener('change',event=>{const el=event.target;if(bar.contains(el)||!('value' in el))return;record('change',{tag:el.tagName,id:el.id,value:String(el.value).slice(0,2000),value_truncated:String(el.value).length>2000});},true);
  });
})();
