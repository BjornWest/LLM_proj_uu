/* Example browsing activity and a small event bridge for a real agent. */
(function(host,factory){
  'use strict';
  const Driver=factory();
  if(typeof module!=='undefined'&&module.exports)module.exports=Driver;
  host.RavenWebActivityDriver=Driver;
  if(host.document){
    const scene=host.document.getElementById('chat-scene'),element=host.document.getElementById('web-activity');
    if(scene&&element&&host.RavenWebActivity){
      const driver=new Driver({activity:new host.RavenWebActivity({element})});
      scene.addEventListener('raven-chat-submit',e=>driver.beginDemo(e.detail?.replyMs));
      scene.addEventListener('raven-chat-reply',()=>driver.finish());
      host.document.addEventListener('raven-web-activity',e=>driver.fromAgent(e.detail));
      host.addEventListener('pagehide',()=>driver.dispose());
    }
  }
})(typeof globalThis!=='undefined'?globalThis:this,function(){
  'use strict';
  const sites=[
    {url:'https://www.blender.org/',label:'Blender'},
    {url:'https://developer.mozilla.org/',label:'MDN Web Docs'},
    {url:'https://en.wikipedia.org/wiki/Common_raven',label:'Wikipedia'}
  ];
  class ActivityDriver{
    constructor({activity,schedule=(fn,ms)=>setTimeout(fn,ms),cancel=id=>clearTimeout(id)}){
      this.activity=activity;this.schedule=(fn,ms)=>schedule(fn,ms);this.cancel=id=>cancel(id);this.timers=[];this.revision=0;this.disposed=false;
    }
    clearDemo(){this.revision++;for(const timer of this.timers)this.cancel(timer);this.timers.length=0;}
    beginDemo(replyMs=10000){
      if(this.disposed)return;
      this.clearDemo();const revision=this.revision,duration=Number.isFinite(replyMs)&&replyMs>0?replyMs:10000;
      this.activity.start({...sites[0],demo:true});
      for(let i=1;i<sites.length;i++)this.timers.push(this.schedule(()=>{
        if(this.disposed||revision!==this.revision)return;
        this.activity.start({...sites[i],demo:true});
      },duration*[0,.32,.65][i]));
    }
    fromAgent(detail){
      if(this.disposed||!detail||typeof detail!=='object')return;
      this.clearDemo();
      if(detail.status==='complete'||detail.active===false){this.activity.finish();return;}
      if(typeof detail.url==='string')this.activity.start({url:detail.url,label:detail.label,demo:false});
    }
    finish(){this.clearDemo();this.activity.finish();}
    dispose(){if(this.disposed)return;this.disposed=true;this.clearDemo();this.activity.dispose?.();}
  }
  return ActivityDriver;
});
