/* Website identity for explicit agent activity; local metadata, passive favicons. */
(function(host,factory){
  'use strict';
  const Activity=factory(host);
  if(typeof module!=='undefined'&&module.exports)module.exports=Activity;
  host.RavenWebActivity=Activity;
})(typeof globalThis!=='undefined'?globalThis:this,function(host){
  'use strict';
  const MAX_CACHE=32,OK_TTL=15*60*1000,ERROR_TTL=60000,TIMEOUT=6700;
  const clean=(value,limit=100)=>typeof value==='string'?value.replace(/[\u0000-\u001f\u007f]/g,' ').replace(/\s+/g,' ').trim().slice(0,limit):'';
  function safePublicUrl(value){
    if(typeof value!=='string'||value.length>2048||/[\u0000-\u0020\u007f\\]/.test(value)||!/^https?:\/\//i.test(value))return null;
    try{
      const url=new URL(value),hostname=url.hostname.replace(/^\[|\]$/g,'').replace(/\.$/,'').toLowerCase();
      if(!['http:','https:'].includes(url.protocol)||url.username||url.password||!hostname||url.port)return null;
      if(hostname==='localhost'||/\.(?:localhost|local|internal|home|lan|onion|test|invalid)$/.test(hostname))return null;
      if(hostname.includes(':')){
        const first=parseInt(hostname.split(':')[0],16);
        if(!(first>=0x2000&&first<=0x3fff)||/^2001:(?:db8|0)(?::|$)/.test(hostname)||/^2002:/.test(hostname))return null;
      }else if(/^\d+\.\d+\.\d+\.\d+$/.test(hostname)){
        const [a,b,c]=hostname.split('.').map(Number);
        if(a===0||a===10||a===127||a>=224||a===169&&b===254||a===172&&b>=16&&b<=31||
          a===192&&(b===168||b===0||b===88&&c===99)||a===100&&b>=64&&b<=127||
          a===198&&(b===18||b===19||b===51&&c===100)||a===203&&b===0&&c===113)return null;
      }else if(!hostname.includes('.')||!/^([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(hostname))return null;
      return url.href;
    }catch{return null;}
  }
  class RavenWebActivity{
    constructor({element,fetcher=host.fetch?.bind(host),imageFactory}={}){
      if(!element||typeof element.querySelector!=='function')throw new TypeError('A website activity element is required.');
      this.element=element;this.dot=element.querySelector('[data-activity-dot]');this.icon=element.querySelector('[data-activity-icon]');
      this.site=element.querySelector('[data-activity-site]');this.label=element.querySelector('[data-activity-label]');
      if(!this.icon||!this.site||!this.label)throw new TypeError('Website activity needs icon, site and label elements.');
      this.globe=element.querySelector('[data-activity-globe]');
      if(!this.globe){this.globe=element.ownerDocument.createElement('span');this.globe.textContent='🌐';this.globe.setAttribute('data-activity-globe','');this.icon.insertAdjacentElement('afterend',this.globe);}
      this.fetcher=fetcher;this.imageFactory=imageFactory||(()=>new (element.ownerDocument?.defaultView?.Image||host.Image)());
      this.cache=new Map();this.revision=0;this.disposed=false;this.loader=null;this.current=null;
      element.setAttribute('role','status');element.setAttribute('aria-live','polite');element.setAttribute('aria-atomic','true');
      this.dot?.setAttribute('aria-hidden','true');this.globe.setAttribute('aria-hidden','true');
      this.icon.alt='';this.icon.referrerPolicy='no-referrer';this.icon.draggable=false;this.icon.setAttribute('aria-hidden','true');
      this.reset();
    }
    valid(revision){return !this.disposed&&this.current!==null&&this.revision===revision&&this.element.dataset.active==='true';}
    cancelIcon(){
      if(this.loader){this.loader.onload=null;this.loader.onerror=null;this.loader.removeAttribute?.('src');this.loader=null;}
      this.icon.onload=null;this.icon.onerror=null;this.icon.hidden=true;this.icon.removeAttribute('src');this.globe.hidden=false;
      this.element.dataset.icon='globe';
    }
    updateSite(value){
      const name=clean(value)||this.current.hostname;this.current.siteName=name;this.site.textContent=name;
      this.element.dataset.site=name;this.element.dataset.siteName=name;
      this.element.setAttribute('aria-label',this.label.textContent+' '+name);
    }
    metadata(url){
      const origin=new URL(url).origin,old=this.cache.get(origin);
      if(old&&old.expires>Date.now()){this.cache.delete(origin);this.cache.set(origin,old);return old.promise;}
      if(old){old.controller.abort();clearTimeout(old.timer);this.cache.delete(origin);}
      const entry={controller:new AbortController(),expires:Date.now()+OK_TTL,timer:null,promise:null};
      entry.promise=(async()=>{
        entry.timer=setTimeout(()=>entry.controller.abort(),TIMEOUT);
        try{
          if(typeof this.fetcher!=='function')return {status:'unavailable'};
          const response=await this.fetcher('/api/link-preview?url='+encodeURIComponent(url),{credentials:'omit',signal:entry.controller.signal});
          if(!response.ok)throw new Error('Website metadata unavailable');
          const result=await response.json();return result&&typeof result==='object'?result:{status:'unavailable'};
        }catch{return {status:'unavailable'};}finally{clearTimeout(entry.timer);}
      })();
      this.cache.set(origin,entry);
      entry.promise.then(result=>{if(this.cache.get(origin)===entry)entry.expires=Date.now()+(result.status==='ok'?OK_TTL:ERROR_TTL);});
      while(this.cache.size>MAX_CACHE){const key=this.cache.keys().next().value,victim=this.cache.get(key);victim.controller.abort();clearTimeout(victim.timer);this.cache.delete(key);}
      return entry.promise;
    }
    loadIcon(candidates,revision,index=0){
      if(!this.valid(revision)||index>=candidates.length){if(this.valid(revision))this.element.dataset.icon='globe';return;}
      const src=candidates[index];let loader;
      try{loader=this.imageFactory();}catch{this.element.dataset.icon='globe';return;}
      this.loader=loader;this.element.dataset.icon='loading';loader.referrerPolicy='no-referrer';loader.decoding='async';
      const next=()=>{
        if(!this.valid(revision)||this.loader!==loader)return;
        loader.onload=null;loader.onerror=null;this.loader=null;this.icon.hidden=true;this.icon.removeAttribute('src');this.globe.hidden=false;
        this.loadIcon(candidates,revision,index+1);
      };
      loader.onerror=next;
      loader.onload=()=>{
        if(!this.valid(revision)||this.loader!==loader)return;
        loader.onload=null;loader.onerror=null;this.loader=null;
        const current=()=>this.valid(revision)&&this.icon.getAttribute('src')===src&&(!this.icon.currentSrc||this.icon.currentSrc===this.icon.src);
        this.icon.onload=()=>{if(current()){this.icon.hidden=false;this.globe.hidden=true;this.element.dataset.icon='favicon';}};
        this.icon.onerror=()=>{if(current()){this.icon.onload=null;this.icon.onerror=null;this.icon.hidden=true;this.icon.removeAttribute('src');this.globe.hidden=false;this.loadIcon(candidates,revision,index+1);}};
        this.icon.src=src;
        // The independent loader succeeded; the visible image uses the same
        // cached resource. A later image error still restores the globe.
        this.icon.hidden=false;this.globe.hidden=true;this.element.dataset.icon='favicon';
      };
      loader.src=src;
    }
    async start({url,label,favicon,demo=false}={}){
      if(this.disposed)return false;
      const safe=safePublicUrl(url);if(!safe){this.finish();return false;}
      const parsed=new URL(safe),hostname=parsed.hostname.replace(/\.$/,''),fallback=clean(label)||hostname;
      const revision=++this.revision;this.cancelIcon();this.current={url:safe,hostname,siteName:fallback,fallback,demo:!!demo};
      this.element.hidden=false;Object.assign(this.element.dataset,{active:'true',activity:'exploring',hostname,url:safe,demo:String(!!demo)});
      this.label.textContent=demo?'Demo · Exploring':'Exploring';this.element.title=demo?'Example browsing activity in this chat demo.':'Current website activity';
      this.site.setAttribute('href',safe);this.site.setAttribute('target','_blank');this.site.setAttribute('rel','noopener noreferrer');this.site.setAttribute('referrerpolicy','no-referrer');
      this.updateSite(fallback);
      const capturedIcon=safePublicUrl(favicon);
      if(capturedIcon){this.loadIcon(['/api/link-preview-image?url='+encodeURIComponent(capturedIcon)],revision);return true;}
      const result=await this.metadata(safe);if(!this.valid(revision))return false;
      const resultUrl=safePublicUrl(result.url),resultHost=resultUrl?new URL(resultUrl).hostname:hostname;
      const name=result.status==='ok'?clean(result.siteName):'';
      this.updateSite(!name||name.toLowerCase()===hostname.toLowerCase()||name.toLowerCase()===resultHost.toLowerCase()?fallback:name);
      const declared=result.status==='ok'?safePublicUrl(result.favicon):null,candidates=[];
      if(declared){
        // Same-site icons are passive image documents, including SVG served
        // at an .ico path. Foreign raster assets use the guarded local proxy.
        const sameSite=new URL(declared).origin===new URL(resultUrl||safe).origin;
        candidates.push(sameSite||/\.svg$/i.test(new URL(declared).pathname)?declared:'/api/link-preview-image?url='+encodeURIComponent(declared));
      }
      const ico=safePublicUrl(new URL('/favicon.ico',resultUrl||safe).href);
      if(ico)candidates.push('/api/link-preview-image?url='+encodeURIComponent(ico));
      this.loadIcon([...new Set(candidates)],revision);return true;
    }
    finish(){
      ++this.revision;this.current=null;this.cancelIcon();this.element.hidden=true;
      Object.assign(this.element.dataset,{active:'false',activity:'idle',hostname:'',url:'',site:'',siteName:'',demo:'false'});
      this.site.textContent='';this.site.removeAttribute('href');this.label.textContent='';this.element.title='';this.element.setAttribute('aria-label','Website activity idle');
      return this;
    }
    reset(){return this.finish();}
    dispose(){
      if(this.disposed)return;this.finish();this.disposed=true;
      for(const entry of this.cache.values()){entry.controller.abort();clearTimeout(entry.timer);}this.cache.clear();
    }
    getState(){return {active:!!this.current,demo:this.current?.demo??false,url:this.current?.url??'',hostname:this.current?.hostname??'',siteName:this.current?.siteName??'',icon:this.element.dataset.icon,revision:this.revision,cacheSize:this.cache.size,disposed:this.disposed};}
  }
  RavenWebActivity.safePublicUrl=safePublicUrl;RavenWebActivity.version=39;
  return RavenWebActivity;
});
