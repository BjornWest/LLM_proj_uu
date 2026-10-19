/* Full-page chat shell; shared v40 raven assets and flight choreography. */
(() => {
  'use strict';
  const CACHE_QUERY='v=42-flock-1', MAX_MOTION_STEP=250, HEAD_RESPONSE_MS=119.067789;
  const clamp=(v,a=0,b=1)=>Math.max(a,Math.min(b,v));
  const mix=(a,b,t)=>a+(b-a)*t;
  const smooth=t=>{t=clamp(t);return t*t*(3-2*t);};
  const between=(a,b)=>a+Math.random()*(b-a);
  const bezier=(a,b,c,d,t)=>{const s=1-t;return {x:s*s*s*a.x+3*s*s*t*b.x+3*s*t*t*c.x+t*t*t*d.x,y:s*s*s*a.y+3*s*s*t*b.y+3*s*t*t*c.y+t*t*t*d.y};};
  const seededRandom=seed=>{let state=2166136261;for(const c of String(seed)){state^=c.charCodeAt(0);state=Math.imul(state,16777619);}return ()=>{state+=0x6D2B79F5;let t=state;t=Math.imul(t^t>>>15,t|1);t^=t+Math.imul(t^t>>>7,t|61);return ((t^t>>>14)>>>0)/4294967296;};};
  const jsonFrom=src=>fetch(src).then(r=>{if(!r.ok)throw new Error('Could not load '+src);return r.json();});
  class RavenChatDemo {
    constructor() {
      this.scene=document.getElementById('chat-scene');this.canvas=document.getElementById('raven-canvas');this.soundCanvas=document.getElementById('raven-sounds');this.ctx=this.soundCanvas.getContext('2d');this.stats={draws:0,skips:0,clearPixels:0,drawMs:0,maxDrawMs:0,misses:0};this.rafIntervals=[];
      this.sky=document.getElementById('sky');this.form=document.getElementById('chat-form');this.input=document.getElementById('message-input');this.send=document.getElementById('send-button');
      this.messages=document.getElementById('messages');for(const node of document.querySelectorAll?.('[data-markdown]')||[])if(!node.dataset.messageFormat)window.RavenMessages?.renderMessage(node,node.textContent);
      this.newReply=document.getElementById('new-reply');
      this.newReply?.addEventListener('click',()=>this.followLatest());
      this.messages.addEventListener('scroll',()=>{if(this.isNearBottom()&&this.newReply)this.newReply.hidden=true;},{passive:true});
      this.status=document.getElementById('raven-status');this.countdown=document.getElementById('countdown');
      this.tracking=document.getElementById('mouse-tracking');this.darker=document.getElementById('dark-palette');this.petButton=document.getElementById('pet-raven');this.frameRate=document.getElementById('frame-rate');this.models=new Map();
      this.pathToggle=document.getElementById('show-flight-path');this.guideCanvas=document.getElementById('flight-guides');this.guideCtx=this.guideCanvas?.getContext('2d');this.flightSeed=new URLSearchParams(window.location?.search||'').get('seed');this.flightStarts=0;
      this.motion=matchMedia('(prefers-reduced-motion: reduce)');this.state='loading';this.ready=false;this.started=null;this.taskGeneration=0;this.lastDrawKey='';this.motionClock=0;this.motionLast=null;this.assetGeneration=0;
      this.trackingZone=document.getElementById('tracking-zone');this.pointer=null;this.circle=null;this.headPose=[0,0,0];this.headTick=-1;this.orbitStart=null;this.orbitCooldown=0;this.attentionReturning=false;this.gesture=null;this.settling=null;
      this.input.addEventListener('input',()=>this.onTyping());this.form.addEventListener('submit',e=>{e.preventDefault();this.start();});
      document.addEventListener('pointermove',e=>this.trackPointer(e),{passive:true});document.addEventListener('pointerleave',()=>{this.clearPointer();this.scene.style.cursor='';});window.addEventListener('blur',()=>{this.clearPointer();this.scene.style.cursor='';});
      document.addEventListener('visibilitychange',()=>{this.motionLast=null;this.clearPointer();});
      document.addEventListener('click',e=>{if(this.opaqueHit(e))this.pet();});this.petButton?.addEventListener('click',()=>this.pet());
      this.tracking.addEventListener('change',()=>{if(!this.tracking.checked)this.clearPointer();this.draw(performance.now(),true);});this.darker.addEventListener('change',()=>{this.invalidateBuffer();this.forecastKey=null;this.draw(performance.now(),true);});
      this.frameRate?.addEventListener('change',()=>this.setFrameRate(Number(this.frameRate.value)));
      this.pathToggle?.addEventListener('change',()=>{this.guideLast=null;this.drawGuides(performance.now(),true);});
      this.motion.addEventListener?.('change',()=>{this.clearPointer();if(this.motion.matches){this.gesture=null;this.settling=null;if(this.state==='petting'||this.state==='settling')this.setState('idle');}this.draw(performance.now(),true);});
      this.resizeObserver=new ResizeObserver(()=>this.resize());this.resizeObserver.observe(this.scene);this.resizeObserver.observe(this.form);window.addEventListener('resize',()=>this.resize());
      window.addEventListener('pagehide',()=>this.cancelTask({keepalive:true}));
      this.tick=this.tick.bind(this);this.raf=requestAnimationFrame(this.tick);this.load();
    }
    async modelAssets(rate){
      this.nativeAssets??=Promise.all(['live-actions-meta-v34.json','live-idle-meta-v34.json','live-flight-meta-v34.json'].map(src=>jsonFrom(src+'?'+CACHE_QUERY)));
      const [source,idleSource,flightSource]=await this.nativeAssets;
      const profile=meta=>rate===60?meta:{...meta,fps:rate,sourceFps:meta.fps,timeline:meta.timeline?Object.fromEntries(Object.entries(meta.timeline).map(([k,v])=>[k,k.endsWith('Frame')?Math.round(v*rate/meta.fps):v])):undefined,clips:Object.fromEntries(Object.entries(meta.clips).map(([name,c])=>{
        const frames=Math.max(1,Math.round(c.frames*rate/(c.fps||meta.fps))),indices=Array.from({length:frames},(_,i)=>i===frames-1?c.frames-1:Math.min(c.frames-1,Math.round(i*(c.fps||meta.fps)/rate)));
        if(c.landingFrame!==undefined)indices[Math.min(frames-1,Math.round(c.landingFrame*rate/(c.fps||meta.fps)))]=c.landingFrame;
        return [name,{...c,frames,fps:rate,poses:indices.map(f=>c.poses?.[f]),nativeSampleFrames:indices,landingFrame:c.landingFrame===undefined?undefined:Math.round(c.landingFrame*rate/(c.fps||meta.fps)),pauseFrames:c.pauseFrames?.map(f=>Math.round(f*rate/(c.fps||meta.fps))),sections:c.sections?.map(s=>({...s,start:Math.round(s.start*rate/(c.fps||meta.fps)),callFrames:Math.round(s.callFrames*rate/(c.fps||meta.fps)),hopFrames:Math.round(s.hopFrames*rate/(c.fps||meta.fps))}))}];
      }))};
      return {manifest:profile(source),idle:profile(idleSource),flight:profile(flightSource),pages:[]};
    }
    async setFrameRate(rate){
      if(![8,24,60,120,144].includes(rate))throw new RangeError('Choose 8, 24, 60, 120 or 144 frames per second.');
      const poseRate=Math.min(rate,60);
      if(this.ready&&!this.loading&&!this.preparing&&poseRate===this.activeFps){
        this.renderFps=rate;this.renderLast=undefined;this.rafLast=undefined;this.rafIntervals=[];this.metricsLast=-Infinity;
        this.scene.dataset.fps=String(rate);if(this.frameRate)this.frameRate.value=String(rate);this.updateControls();return true;
      }
      if(this.loading||this.preparing||this.started!==null||this.gesture||this.settling||this.flock?.birds.length){if(this.frameRate)this.frameRate.value=String(this.renderFps||this.activeFps||120);return false;}
      return this.load(rate);
    }
    async load(rate=Number(this.frameRate?.value)||120) {
      const previous={};for(const key of ['ready','manifest','atlasPages','path','attentionMeta','renderFps','activeFps','timing','course','courseBounds','idleManifest','flightManifest'])previous[key]=this[key];this.invalidateBuffer();this.ready=false;this.loading=true;this.clearPointer();this.setState('loading');this.updateControls();
      try {
        this.commonAssets??=Promise.all([jsonFrom('patrol-path.json?'+CACHE_QUERY),jsonFrom('live-attention-meta-v34.json?'+CACHE_QUERY)]).catch(e=>{this.commonAssets=null;throw e;});
        const [assets,[path,attentionMeta]]=await Promise.all([this.modelAssets(Math.min(rate,60)),this.commonAssets]);const {manifest}=assets;
        for(const name of ['perch','idle','pet','caw','takeoff','glide','glide_right','patrol','patrol_roll','diving'])if(!manifest.clips[name])throw new Error('Missing chat clip '+name);
        this.manifest=manifest;this.atlasPages=assets.pages;this.idleManifest=assets.idle;this.flightManifest=assets.flight;this.path=path;this.attentionMeta=attentionMeta;this.activeFps=Math.min(rate,60);this.renderFps=rate;
        const m=manifest.timeline||{};this.timing={takeoffMs:this.duration('takeoff'),braceThroughFrame:m.braceThroughFrame??0,outsideMs:m.outsideMs??375,enterMs:m.enterMs??875,patrolStartFrame:m.patrolStartFrame??0,diveStartPatrolFrame:m.diveStartPatrolFrame??0,diveMs:this.duration('diving')};
        this.timing.patrolStartMs=this.timing.takeoffMs+this.timing.outsideMs+this.timing.enterMs;
        this.course=this.clip('patrol').poses.map((p,i)=>p.path||{x:path.screen[i][0]/256,y:path.screen[i][1]/256});
        this.courseBounds={left:Math.min(...this.course.map(p=>p.x)),right:Math.max(...this.course.map(p=>p.x)),top:Math.min(...this.course.map(p=>p.y)),bottom:Math.max(...this.course.map(p=>p.y))};
        if(!this.live){
          const library=await import('./raven-live-v42.js?'+CACHE_QUERY);
          const factory=library.RavenLive||window.RavenLive||library.default;
          this.live=await factory.load({canvas:this.canvas,url:'live-raven-v34.json?'+CACHE_QUERY});
        }
        this.ready=true;this.loading=false;this.gesture=null;this.settling=null;this.resetIdle();this.setState('idle');if(this.frameRate)this.frameRate.value=String(rate);this.scene.dataset.fps=String(rate);this.updateHint();this.resize();return true;
      } catch(e) {Object.assign(this,previous);this.loading=false;if(this.ready){this.resetIdle();this.setState('idle');if(this.frameRate)this.frameRate.value=String(this.renderFps||this.activeFps);}else this.setState('error');this.status.textContent='Live 3D could not start. Use Compare sprites to return to the Blender version.';this.updateControls();console.error(e);return false;}
    }
    metaForClip(name){if(name==='idle')return this.idleManifest||this.manifest;return this.flightManifest?.clips[name]?this.flightManifest:this.manifest;}
    clip(name){return this.metaForClip(name).clips[name]||this.manifest.clips.perch;}
    frameMs(name){return 1000/(this.clip(name).fps||this.manifest.fps||8);}
    tickMs(){return 1000/(this.manifest.fps||this.clip('idle').fps||8);}
    frameAt(ms,name){const f=Math.max(0,ms)/this.frameMs(name);return this.activeFps===60?f:Math.floor(f+1e-6);}
    landingFrame(){return this.clip('diving').landingFrame??this.manifest.timeline?.landingFrame??Math.round(3500/this.frameMs('diving'));}
    duration(name){const c=this.clip(name);return this.flightManifest?.clips[name]&&Number.isFinite(c.duration)?c.duration*1000:c.frames*1000/(c.fps||this.manifest.fps||8);}
    pose(name,frame){const c=this.clip(name),f=clamp(frame,0,c.frames-1),a=Math.floor(f),b=Math.min(c.frames-1,a+1);return this.mixPose(c.poses?.[a]||c.pose,c.poses?.[b]||c.pose,f-a);}
    mixPose(a,b,t){if(typeof a==='number'&&typeof b==='number')return mix(a,b,t);if(!a||typeof a!=='object')return a;if(Array.isArray(a))return a.map((v,i)=>this.mixPose(v,b?.[i],t));const out={...a};for(const k of Object.keys(a))if(k in (b||{}))out[k]=this.mixPose(a[k],b[k],t);return out;}
    nativeFrame(name,frame){const c=this.clip(name),f=clamp(frame,0,c.frames-1);if(!c.nativeSampleFrames)return f;const a=Math.floor(f),b=Math.min(c.frames-1,a+1);return mix(c.nativeSampleFrames[a],c.nativeSampleFrames[b],f-a);}

    clipRefs(){return [];}
    warmRefs(){return Promise.resolve([]);}
    refsReady(){return true;}
    getStats(){const live=this.live?.getStats?.()||{};return Object.freeze({...live,...this.stats,fps:this.renderFps||this.activeFps,sourceFps:this.activeFps,buffering:false,preparing:!!this.preparing});}
    scaleFor(name,frame,sample=null){
      const g=this.geometry;
      if(name==='takeoff'){const u=smooth((frame-this.timing.braceThroughFrame)/(this.clip(name).frames-1-this.timing.braceThroughFrame));return mix(g.worldScale,g.flightScale*(this.director?.entranceDepthScale??1),u);}
      if(name==='diving'){const land=this.landingFrame();return mix(g.flightScale*(this.diveStartDepthScale??1),g.worldScale,smooth(frame/land));}
      return this.flightManifest?.clips[name]||['patrol','patrol_roll','glide','glide_right'].includes(name)?g.flightScale*(sample?.depthScale??1):g.worldScale;
    }
    cellSize(pose,scale=this.geometry.worldScale){return scale*(pose.orthoScale||3.75);}
    anchor(pose,name){return pose[name]||pose.contact||pose.foot||pose.root;}
    resize(){
      const s=this.scene.getBoundingClientRect(),c=this.canvas.getBoundingClientRect(),b=this.send.getBoundingClientRect(),sky=this.sky.getBoundingClientRect();
      const world=Math.min(window.innerHeight<=800?26:s.width<580?31:38,s.width/16);
      let up=1.8,down=1.2,left=2.3,right=2.3;
      let motionTop=0,motionBottom=0;
      if(this.ready)for(const clip of Object.values(this.flightManifest.clips))for(const p of clip.poses){const q=p.bounds;if(q){up=Math.max(up,(p.root.y-q.top)*p.orthoScale);down=Math.max(down,(q.bottom-p.root.y)*p.orthoScale);left=Math.max(left,(p.root.x-q.left)*p.orthoScale);right=Math.max(right,(q.right-p.root.x)*p.orthoScale);}motionTop=Math.min(motionTop,p.motion?.y||0);motionBottom=Math.max(motionBottom,p.motion?.y||0);}
      const flightScale=world;
      this.geometry={width:c.width||s.width,height:c.height||s.height,ratio:Math.min(window.devicePixelRatio||1,2),left:c.left,top:c.top,worldScale:world,flightScale,
        button:{x:b.left+b.width*.5-c.left,y:b.top-c.top+1},sky:{left:sky.left-c.left,top:sky.top-c.top,width:sky.width,height:sky.height},flightExtents:{up:up*flightScale,down:down*flightScale,left:left*flightScale,right:right*flightScale}};
      const area=this.geometry.sky;this.geometry.director={left:area.left,top:area.top,width:area.width,height:area.height,scale:flightScale,pad:2,topPad:0,preferredSideWidth:70};
      if(this.director){this.director.configure(this.geometry.director);if(!this.director.blocked){this.geometry.flightScale=this.director.geometry.scale;this.configureEntrance(true);}}
      if(this.director&&this.diveStartClock!==null&&this.diveStartWorld){this.diveStartPoint=this.director.project(this.diveStartWorld);this.diveStartDepthScale=this.director.depthScale(this.diveStartWorld.z);}
      this.flock?.resize();
      this.live?.resize?.(this.geometry.width,this.geometry.height,this.geometry.ratio);this.soundCanvas.width=Math.max(1,Math.round(this.geometry.width*this.geometry.ratio));this.soundCanvas.height=Math.max(1,Math.round(this.geometry.height*this.geometry.ratio));this.dirtyRect=null;this.lastDrawKey='';if(this.ready)this.draw(performance.now(),true);
      if(this.guideCanvas){this.guideCanvas.width=Math.max(1,Math.round(area.width*this.geometry.ratio));this.guideCanvas.height=Math.max(1,Math.round(area.height*this.geometry.ratio));this.guideLast=null;this.drawGuides(performance.now(),true);}
    }
    configureEntrance(preserveDuration=false){
      if(!this.director||!this.geometry)return;
      const target=this.director.entrancePoint,v=this.director.entranceVelocity||{x:-this.director.geometry.unitWidth,y:0};
      const durationMs=preserveDuration&&this.entranceMotion?this.entranceMotion.durationMs:1100;
      this.timing.outsideMs=0;this.timing.enterMs=durationMs;
      this.timing.patrolStartMs=this.timing.takeoffMs+durationMs;
      const braceMs=this.timing.braceThroughFrame*this.frameMs('takeoff'),from=this.groundedRoot('takeoff',this.timing.braceThroughFrame);
      const riseMs=this.timing.patrolStartMs-braceMs,seconds=riseMs/1000,dx=target.x-from.x,dy=target.y-from.y;
      // Give spreading wings room beside the send button; keep the final join and velocity unchanged.
      const rightClearance=this.geometry.width-this.geometry.button.x;
      const ascentInset=Math.max(0,30+Math.max(0,this.geometry.worldScale-24)*12-Math.max(0,rightClearance-53)*5);
      const first={x:from.x+Math.sign(dx)*Math.min(8,Math.abs(dx)*.15)-ascentInset,y:from.y+dy*.66};
      const second={x:target.x-v.x*seconds/3,y:target.y-v.y*seconds/3};
      this.entranceMotion={from,first,second,target:{...target},velocity:{...v},durationMs,braceMs,riseMs};
      Object.assign(this.canvas.dataset,{ascent:'direct',entranceDurationMs:durationMs.toFixed(1),patrolPixelSpeed:Math.abs(v.x).toFixed(1),entranceDistancePx:Math.hypot(dx,dy).toFixed(1)});
    }
    ascentPoint(elapsed){const e=this.entranceMotion;return bezier(e.from,e.first,e.second,e.target,clamp((elapsed-e.braceMs)/e.riseMs));}
    groundedRoot(name,frame,scale=this.scaleFor(name,frame)){
      const p=this.pose(name,frame),a=this.anchor(p,'contact'),z=this.cellSize(p,scale),b=this.geometry.button;return {x:b.x+(p.root.x-a.x)*z,y:b.y+(p.root.y-a.y)*z};
    }
    patrolPoint(frame){
      const p=this.course[(frame+this.course.length)%this.course.length],q=this.courseBounds,g=this.geometry,s=g.sky,e=g.flightExtents;
      const lx=s.left+e.left+7,rx=s.left+s.width-e.right-7;
      const sway=Math.max(0,Math.min(34,s.height-e.up-e.down-14));const center=s.top+e.up+7+sway*.5;
      return {x:mix(lx,Math.max(lx,rx),clamp((p.x-q.left)/(q.right-q.left))),y:center+((p.y-q.top)/(q.bottom-q.top)-.5)*sway};
    }
    flightPoint(name,frame,point){
      const p=this.pose(name,frame),b=p.bounds;if(!b)return point;
      const size=this.cellSize(p,this.scaleFor(name,frame)),s=this.geometry.sky,pad=7;
      const left=s.left+pad+(p.root.x-b.left)*size,right=s.left+s.width-pad-(b.right-p.root.x)*size;
      const top=s.top+pad+(p.root.y-b.top)*size,bottom=s.top+s.height-pad-(b.bottom-p.root.y)*size;
      return {x:clamp(point.x,left,Math.max(left,right)),y:clamp(point.y,top,Math.max(top,bottom))};
    }
    isNearBottom(){return this.messages.scrollHeight-this.messages.clientHeight-this.messages.scrollTop<=48;}
    followLatest(){window.RavenCitations?.hide?.();this.messages.scrollTop=this.messages.scrollHeight;if(this.newReply)this.newReply.hidden=true;}
    cancelTask({announce=true,keepalive=false}={}){
      const task=this.task;this.task=null;const generation=++this.taskGeneration;this.assetGeneration++;task?.transport?.cancel({keepalive}).catch(error=>{if(generation===this.taskGeneration)this.countdown.textContent='Could not confirm cancellation: '+error.message;});
      this.started=null;this.director=null;this.preparing=false;this.pendingReturn=false;
      this.gesture=null;this.settling=null;this.diveStartClock=null;this.diveStartPoint=null;
      this.diveStartWorld=null;this.diveStartDepthScale=1;this.lastFlightAction=null;this.replyAdded=false;
      this.invalidateBuffer();this.lastSample=null;this.drawBounds=null;this.head=null;
      this.wasTypingAfterReply=false;this.clearPointer();this.lastDrawKey='';
      this.flock?.clear();
      window.RavenCitations?.hide?.();window.RavenMessages?.hidePreview?.();
      document.dispatchEvent(new CustomEvent('raven-web-activity',{detail:{status:'complete'}}));
      if(this.ready){this.resetIdle();this.setState('idle');this.updateHint();this.draw(performance.now(),true);}
      if(announce)this.scene.dispatchEvent(new CustomEvent('raven-chat-cancel',{bubbles:true}));
    }
    setConversation(messages,{title='New conversation'}={}){
      this.cancelTask({announce:false});this.messages.replaceChildren();this.input.value='';
      for(const item of messages||[]){if(typeof item?.text!=='string')continue;this.appendMessage(item.text,item.who==='You'?'You':'Raven',{sources:Array.isArray(item.sources)?item.sources:[],follow:true});}
      if(this.newReply)this.newReply.hidden=true;
      this.scene.dispatchEvent(new CustomEvent('raven-conversation-change',{detail:{title,messageCount:this.messages.children.length},bubbles:true}));
      this.resize();
    }
    appendMessage(text,who,{sources=[],follow=who==='You'}={}){
      const previousTop=this.messages.scrollTop,shouldFollow=follow||this.isNearBottom();
      const a=document.createElement('article');a.className='message'+(who==='You'?' user':'');
      const l=document.createElement('span');l.className='message-label';l.textContent=who;
      const t=document.createElement('div');t.className='message-copy';
      if(window.RavenMessages)window.RavenMessages.renderMessage(t,text);else t.textContent=text;
      if(sources.length){
        window.RavenCitations?.enhance(t,sources);
        const cited=new Set([...t.querySelectorAll('button.raven-citation')].map(button=>button.dataset.sourceId));
        const uncited=sources.filter(source=>!cited.has(source.id));
        if(uncited.length){const footer=document.createElement('div');footer.className='message-sources';window.RavenMessages.renderMessage(footer,'Sources: '+uncited.map(source=>'[['+source.id+']]').join(' '));window.RavenCitations?.enhance(footer,sources);t.append(footer);}
      }
      a.append(l,t);this.messages.append(a);
      if(shouldFollow){this.messages.scrollTop=this.messages.scrollHeight;if(this.newReply)this.newReply.hidden=true;}
      else {this.messages.scrollTop=previousTop;if(this.newReply)this.newReply.hidden=false;}
      return a;
    }
    updateHint(){if(!this.ready)return;if(this.started===null&&this.state==='idle')this.countdown.textContent='Ready for your question';}
    start(){
      if(!this.ready||this.loading||this.preparing||this.started!==null||!this.input.value.trim()){this.input.focus();return false;}
      const context=window.RavenConversations.getContext();
      const task={text:this.input.value.trim(),conversationId:context.conversation_id,history:context.history};
      const rng=this.flightSeed===null?Math.random:seededRandom(this.flightSeed+':'+this.flightStarts++);
      try{this.director=new ChatFlightDirector({manifest:this.flightManifest,geometry:this.geometry.director,rng,knownReplyMs:null});}catch(e){this.director=null;this.assetError=e;if(/more room|in this sky/.test(e.message))this.status.textContent='The raven needs a little more room. Widen the window to start.';else {this.status.textContent='The flight could not start. Refresh and try again.';console.error(e);}return false;}
      this.geometry.flightScale=this.director.geometry.scale;this.configureEntrance();this.diveStartClock=null;this.diveStartPoint=null;this.diveStartDepthScale=1;this.diveStartWorld=null;
      this.appendMessage(task.text,'You');this.input.value='';this.clearPointer();this.gesture=null;this.settling=null;
      const refs=this.motion.matches?[]:this.clipRefs('takeoff',0,this.clip('takeoff').frames).concat(this.clipRefs('glide_right',0,1),this.clipRefs(this.director.current,0,Math.ceil(2000/this.frameMs(this.director.current))));
      if(!this.refsReady(refs)){const generation=++this.assetGeneration;this.preparing=true;this.setState('preparing');this.warmRefs(refs,true).then(()=>{if(generation!==this.assetGeneration)return;this.preparing=false;this.launch(task);}).catch(e=>{if(generation!==this.assetGeneration)return;this.preparing=false;this.started=null;this.assetError=e;this.setState('idle');this.status.textContent='The flight could not load. Please try again.';});return true;}
      this.launch(task);return true;
    }
    launch(task){
      this.taskGeneration++;
      this.started=performance.now();this.stepMotion(this.started);this.taskStartClock=this.motionClock;this.replyAdded=false;this.pendingReturn=false;this.wasTypingAfterReply=false;this.rollStartRaw=null;this.lastPatrolRaw=null;this.rollQueued=false;this.nextRollAt=Infinity;
      this.send.disabled=true;this.setState(this.motion.matches?'working':'takeoff');
      this.task=task;
      this.scene.dispatchEvent(new CustomEvent('raven-chat-submit',{detail:{text:task.text,conversationId:task.conversationId},bubbles:true}));
      task.transport=window.ravenTransport.start({text:task.text,conversation_id:task.conversationId,mode:'background',history:task.history},{
        onEvent:event=>{if(this.task!==task)return;this.handleTaskEvent(event);},
        onError:error=>{if(this.task===task)this.completeTask({markdown:'I couldn’t finish that: '+error.message,sources:[]});}
      });
      this.draw(this.started,true);
    }
    submit(){return this.start();}
    handleTaskEvent(event){
      if(event.type==='site')document.dispatchEvent(new CustomEvent('raven-web-activity',{detail:{...event,label:event.title}}));
      else if(event.type==='step')this.countdown.textContent=event.summary;
      else if(event.type==='status')this.countdown.textContent=event.state==='starting'?'Starting research…':event.state==='finishing'?'Preparing your answer…':'Researching…';
      else if(event.type==='final')this.completeTask(event);
      else if(event.type==='error')this.completeTask({markdown:'I couldn’t finish that: '+event.message,sources:[]});
      else if(event.type==='done')this.completeTask({markdown:event.stop_reason==='cancelled'?'Research stopped.':'I couldn’t finish that: '+({max_total_input_tokens:'the research budget was reached.',max_total_output_tokens:'the answer budget was reached.',max_input_tokens:'the conversation became too long.'}[event.stop_reason]||'the task ended before an answer was ready.'),sources:[]});
    }
    completeTask({markdown,sources=[]}){if(this.started===null||this.replyAdded)return;this.stepMotion(performance.now());this.replyAdded=true;
      this.task?.transport?.close();this.task=null;
      const message=markdown;
      this.appendMessage(message,'Raven',{sources});this.countdown.textContent='Response ready · coming down';
      if(this.motion.matches){this.setState('cawing');this.land(performance.now());}else {const patrolElapsed=this.motionClock-this.taskStartClock-this.timing.patrolStartMs;this.pendingReturn=patrolElapsed<0;const refs=this.pendingReturn?[]:this.director?.requestReturn(Math.max(0,patrolElapsed))||[];this.forecastKey=null;const preload=refs.flatMap(r=>this.clipRefs(r.clip,r.frame,1));preload.push(...this.clipRefs('diving',0,this.clip('diving').frames));this.warmRefs(preload).catch(()=>{});}
      this.scene.dispatchEvent(new CustomEvent('raven-chat-reply',{detail:{message},bubbles:true}));}
    land(now){this.started=null;this.director=null;this.send.disabled=false;this.resetIdle();this.cawStarted=this.motionClock;this.setState(this.wasTypingAfterReply||this.input.value.length?'idle':'cawing');this.countdown.textContent='Ready for another message';this.scene.dispatchEvent(new CustomEvent('raven-chat-land',{bubbles:true}));}
    stepMotion(now){if(document.hidden||this.buffering||this.preparing||this.director?.blocked){this.motionLast=null;return;}const dt=this.motionLast===null?0:clamp(now-this.motionLast,0,MAX_MOTION_STEP);this.motionLast=now;this.motionClock+=dt;}
    resetIdle(options={}){
      const now=this.motionClock;this.clearPointer();
      const frame=Number.isFinite(options.idleFrame)?options.idleFrame:0;
      this.idleFrame=Math.floor(frame);this.idleAccumulator=(frame-this.idleFrame)*this.frameMs('idle');
      this.idleLast=now;this.pauseSeen=-1;this.idleHoldUntil=0;
      this.nextBlink=now+between(3500,8500);this.blinkUntil=0;
      this.idleGaze??=new window.RavenIdleGaze({rng:this.flightSeed?seededRandom(this.flightSeed+':idle'):Math.random});
      this.headPose=this.idleGaze.reset(now,options.headPose||[0,0,0]);this.headTick=-1;this.headClock=now;this.attentionReturning=false;
    }
    advanceIdle(now){
      let delta=Math.max(0,Math.min(now-(this.idleLast??now),MAX_MOTION_STEP));this.idleLast=now;
      if(now<this.idleHoldUntil)delta=0;
      this.idleAccumulator+=delta;const step=this.frameMs('idle');
      const pauses=this.clip('idle').pauseFrames||[4.5,9.5,14.5,19.5,24.5].map(seconds=>Math.round(seconds*1000/step));
      while(this.idleAccumulator+1e-6>=step){this.idleAccumulator=Math.max(0,this.idleAccumulator-step);this.idleFrame++;const f=this.idleFrame%this.clip('idle').frames;
        if(pauses.includes(f)&&this.pauseSeen!==this.idleFrame){this.pauseSeen=this.idleFrame;if(Math.random()<.65){this.idleHoldUntil=now+between(400,1600);this.idleAccumulator=0;break;}}}
      if(now>=this.nextBlink){this.blinkUntil=now+250;this.nextBlink=now+between(3500,8500);}
      return (this.idleFrame+(this.activeFps===60?this.idleAccumulator/step:0))%this.clip('idle').frames;
    }
    updateControls(){const busy=this.loading||this.preparing||this.started!==null;this.send.disabled=!this.ready||busy;this.darker.disabled=!!this.loading||!!this.preparing;if(this.frameRate){const inMotion=busy||!!this.gesture||!!this.settling||!!this.flock?.birds.length;this.frameRate.disabled=!!this.loading||!!this.preparing||(this.activeFps<60&&inMotion);for(const option of this.frameRate.options)option.disabled=inMotion&&Number(option.value)<60;}if(this.petButton)this.petButton.disabled=!this.ready||busy||this.motion.matches||!['idle','cawing','petting'].includes(this.state);this.flock?.updateControls();}
    setState(state){if(this.state!==state){this.state=state;this.scene.dataset.state=state;const labels={loading:'Loading raven…',preparing:'Preparing to take off',idle:'Ready when you are',petting:'A little affection',settling:'Settling back into idle',takeoff:'Taking off',entering:'Coming in over the conversation',working:'Patrolling above the conversation',diving:'Returning to the send button',cawing:'Caw caw — your response is ready'};this.status.textContent=labels[state]||state;this.canvas.setAttribute('aria-label',state==='idle'?'Raven perched on the send button':labels[state]||'Raven');}this.updateControls();if(state!=='idle'&&this.trackingZone)this.trackingZone.hidden=true;}
    onTyping(){
      if(this.replyAdded)this.wasTypingAfterReply=true;
      if(this.gesture){this.gesture.returnState='idle';return;}
      if(this.settling){this.settling.petReturn='idle';return;}
      if(this.state==='cawing')this.stopCaw('idle');
    }
    birdPoint(e){
      if(!this.ready||this.loading||this.preparing||this.buffering||!['idle','cawing','petting'].includes(this.state)||this.started!==null)return null;
      if(e.target?.closest?.('button,textarea,input,select,a,label,.raven-citation-card'))return null;
      const b=this.send.getBoundingClientRect();if(e.clientX>=b.left&&e.clientX<=b.right&&e.clientY>=b.top&&e.clientY<=b.bottom)return false;
      const rect=this.canvas.getBoundingClientRect(),x=e.clientX-rect.left,y=e.clientY-rect.top,q=this.drawBounds;if(!q||x<q.x||y<q.y||x>=q.x+q.width||y>=q.y+q.height)return null;return {x,y};
    }
    opaqueHit(e){const point=this.birdPoint(e);return !!point&&!!this.live?.hitTest?.(point.x,point.y);}
    pet(){
      if(!this.ready||this.loading||this.preparing||this.started!==null||this.motion.matches||!['idle','cawing','petting'].includes(this.state))return false;
      if(this.state==='cawing'){this.stopCaw('pet');return true;}
      this.beginPet(this.gesture?.returnState||'idle',performance.now());return true;
    }
    beginPet(returnState,now){
      const refs=this.clipRefs('pet',0,this.clip('pet').frames);
      if(!this.refsReady(refs)){this.preparing=true;this.updateControls();this.warmRefs(refs,true).then(()=>{this.preparing=false;this.beginPet(this.wasTypingAfterReply||this.input.value.length?'idle':returnState,performance.now());}).catch(e=>{this.preparing=false;this.assetError=e;this.updateControls();});return;}
      this.stepMotion(now);
      const previous=this.gesture,shown=this.lastSample;
      // A repeated click extends petting using the original resting head pose.
      // Wait for a short restart blend to finish before accepting another restart.
      if(previous?.from&&this.motionClock-previous.start<120)return;
      const idleFrame=previous?.idleFrame??(shown?.clip==='idle'?shown.frame:0);
      const headPose=(previous?.headPose??(shown?.clip==='idle'?this.headPose:this.live.lastResult?.pose.headTilt)??[0,0,0]).slice();
      const startBlink=this.live.lastResult?.pose.eyeClosure??previous?.startBlink??(this.motionClock<this.blinkUntil?1:0);
      const nativeIdleFrame=previous?.nativeIdleFrame??this.nativeFrame('idle',idleFrame);
      const from=previous&&shown?.clip==='pet'?{...shown,blendFrom:undefined,blendWeight:undefined}:null;
      this.clearPointer();this.settling=null;
      this.gesture={start:this.motionClock,returnState,headPose,idleFrame,nativeIdleFrame,startBlink,from};
      this.setState('petting');this.draw(now,true);this.scene.dispatchEvent(new CustomEvent('raven-chat-pet',{bubbles:true}));
    }
    cawSections(){const c=this.clip('caw'),section=c.frames/4,callFrames=Math.round(3000/this.frameMs('caw'));return c.sections||Array.from({length:4},(_,i)=>({start:i*section,callFrames,hopFrames:section-callFrames,heading:this.pose('caw',i*section).heading}));}
    stopCaw(after='idle'){
      const now=performance.now();this.stepMotion(now);if(this.motion.matches){this.resetIdle();this.setState('idle');this.draw(now,true);return;}
      const c=this.clip('caw'),f=Math.floor(this.frameAt(this.motionClock-this.cawStarted,'caw'))%c.frames,sections=this.cawSections(),current=sections.find((s,i)=>f>=s.start&&f<(sections[i+1]?.start??c.frames))||sections[0];
      const edges=sections.map((s,i)=>({from:s.heading,to:sections[(i+1)%sections.length].heading,start:s.start+s.callFrames,count:s.hopFrames}));
      const initial=edges.find(e=>e.from===current.heading&&e.start===current.start+current.callFrames);let frames=[],heading=current.heading;
      if(f>=initial.start){for(let j=f;j<initial.start+initial.count;j++)frames.push(j);heading=initial.to;}else frames.push(current.start);
      const target=sections[0].heading;const same=(a,b)=>Math.abs(Math.atan2(Math.sin(a-b),Math.cos(a-b)))<.02;
      const queue=[{heading,path:[]}];let route=[];const seen=[];
      while(queue.length){const item=queue.shift();if(same(item.heading,target)){route=item.path;break;}if(seen.some(v=>same(v,item.heading)))continue;seen.push(item.heading);for(const edge of edges)if(same(edge.from,item.heading))queue.push({heading:edge.to,path:[...item.path,edge]});}
      for(const edge of route)for(let j=0;j<edge.count;j++)frames.push(edge.start+j);
      if(frames.length===1&&same(heading,target)&&after==='idle'){this.resetIdle(now);this.setState('idle');this.draw(now,true);return;}
      this.clearPointer();this.settling={start:this.motionClock,frames,after,petReturn:this.wasTypingAfterReply?'idle':'cawing'};this.setState('settling');this.draw(now,true);
    }
    restSample(now){
      const b=this.geometry.button,clock=this.motionClock;
      if(this.gesture){
        const g=this.gesture,elapsed=clock-g.start,frame=this.frameAt(elapsed,'pet');
        if(frame<this.clip('pet').frames){
          const blending=!!g.from&&elapsed<120;
          return {clip:'pet',frame,anchor:'contact',point:b,petHeadPose:g.headPose.slice(),petStartBlink:g.startBlink,petIdleFrame:g.nativeIdleFrame,
            blendFrom:blending?{...g.from,point:{...b}}:undefined,blendWeight:blending?smooth(elapsed/120):1};
        }
        const next=g.returnState;this.gesture=null;
        this.resetIdle({headPose:g.headPose,idleFrame:g.idleFrame});
        if(next==='cawing')this.cawStarted=clock;this.setState(next);
      }
      if(this.settling){const s=this.settling,index=this.frameAt(clock-s.start,'caw'),i=Math.floor(index),fraction=index-i;if(index<s.frames.length)return {clip:'caw',frame:s.frames[i]+(s.frames[i+1]===s.frames[i]+1?fraction:0),anchor:'contact',point:b,silent:true};this.settling=null;if(s.after==='pet'){this.beginPet(s.petReturn,now);return this.restSample(now);}this.resetIdle();this.setState('idle');}
      if(this.state==='cawing'&&!this.motion.matches)return {clip:'caw',frame:this.frameAt(clock-this.cawStarted,'caw')%this.clip('caw').frames,anchor:'contact',point:b};
      return {clip:'idle',frame:this.motion.matches?0:this.advanceIdle(clock),anchor:'contact',point:b};
    }
    sample(now){
      this.stepMotion(now);if(this.started===null||this.motion.matches)return this.restSample(now);
      const m=this.timing,elapsed=Math.max(0,this.motionClock-this.taskStartClock),tick=this.tickMs(),t=this.activeFps===60?elapsed:Math.floor((elapsed+1e-6)/tick)*tick;
      const last=this.clip('takeoff').frames-1;
      if(t<m.takeoffMs){
        this.setState('takeoff');const f=Math.min(last,this.frameAt(t,'takeoff'));if(f<=m.braceThroughFrame)return {clip:'takeoff',frame:f,anchor:'contact',point:this.geometry.button};
        const turn=smooth((this.nativeFrame('takeoff',f)-55)/(this.nativeFrame('takeoff',last)-55));
        return {clip:'takeoff',frame:f,anchor:'root',point:this.ascentPoint(t),flightRotation:{yaw:-Math.PI*turn,bank:-.12*Math.sin(Math.PI*turn)}};
      }
      if(t<m.patrolStartMs){
        this.setState('entering');const point=this.ascentPoint(t),weight=smooth((t-m.takeoffMs)/420),initial=this.director.sample(0);
        return {...initial,entrance:true,point,blendFrom:weight<1?{clip:'glide_right',frame:0,anchor:'root',point:{...point},depthScale:this.director.entranceDepthScale??1,flightRotation:{yaw:-Math.PI,bank:0}}:undefined,blendWeight:weight};
      }
      if(this.diveStartClock===null){
        if(this.pendingReturn){this.pendingReturn=false;this.director.requestReturn(t-m.patrolStartMs);}const sample=this.director.sample(t-m.patrolStartMs),stats=this.director.getStats();
        this.canvas.dataset.flightAction=stats.action;this.canvas.dataset.flightQueued=stats.queued||'';this.canvas.dataset.flightDirection=String(stats.direction);this.canvas.dataset.flightPositionSteps=String(stats.positionSteps??sample.world?.x??'');this.canvas.dataset.flightJoins=String(stats.joins);
        if(this.lastFlightAction!==sample.clip){this.lastFlightAction=sample.clip;if(sample.action==='roll')this.scene.dispatchEvent(new CustomEvent('raven-chat-roll',{bubbles:true}));if(sample.action==='turn')this.scene.dispatchEvent(new CustomEvent('raven-chat-turn',{detail:{direction:sample.direction},bubbles:true}));this.forecastKey=null;}
        if(!sample.done){this.setState(sample.action==='exit'?'diving':'working');if(this.replyAdded&&sample.action!=='exit')this.status.textContent='Response ready · gliding back';return sample;}
        this.diveStartClock=this.taskStartClock+m.patrolStartMs+this.director.completedAtMs;this.diveStartPoint={...sample.point};this.diveStartDepthScale=sample.depthScale??1;this.diveStartWorld=sample.world?{...sample.world}:null;
      }
      const diveElapsed=Math.max(0,this.motionClock-this.diveStartClock);if(diveElapsed+1e-6>=m.diveMs){this.land(now);return this.restSample(now);}
      this.setState('diving');const dive=this.clip('diving'),f=Math.min(dive.frames-1,this.frameAt(diveElapsed,'diving')),land=this.landingFrame();
      if(f>=land)return {clip:'diving',frame:f,anchor:'contact',point:this.geometry.button,depthScale:1};
      const target=this.groundedRoot('diving',land),start=this.diveStartPoint,landingMs=land*this.frameMs('diving');
      const first={x:start.x,y:start.y};
      return {clip:'diving',frame:f,anchor:'root',point:bezier(start,first,target,target,clamp(diveElapsed/landingMs)),depthScale:mix(this.diveStartDepthScale,1,smooth(f/land)),world:this.diveStartWorld};
    }
    tick(now){
      if(this.ready&&!document.hidden){const interval=1000/(this.renderFps||120),elapsed=now-(this.renderLast??-Infinity);
        if(elapsed+1e-4>=interval){this.renderLast=Number.isFinite(elapsed)?this.renderLast+Math.max(1,Math.floor((elapsed+1e-4)/interval))*interval:now;
          if(this.rafLast!==undefined){const delta=now-this.rafLast;if(delta>0&&delta<1000){this.rafIntervals.push(delta);if(this.rafIntervals.length>180)this.rafIntervals.shift();}}
          this.rafLast=now;this.draw(now);this.publishMetrics(now);
        }
      }else {this.motionLast=null;this.rafLast=undefined;this.renderLast=undefined;}
      this.raf=requestAnimationFrame(this.tick);
    }
    publishMetrics(now){if(now-(this.metricsLast??-Infinity)<250)return;this.metricsLast=now;const s=this.getStats(),intervals=this.rafIntervals.slice().sort((a,b)=>a-b),d=this.canvas.dataset;
      Object.assign(d,{drawCount:String(s.draws),drawSubmitAvgMs:(s.drawMs/Math.max(1,s.draws)).toFixed(3),drawSubmitMaxMs:s.maxDrawMs.toFixed(3),rafIntervalAvgMs:(intervals.reduce((a,b)=>a+b,0)/Math.max(1,intervals.length)).toFixed(3),rafIntervalP95Ms:(intervals[Math.min(intervals.length-1,Math.floor(intervals.length*.95))]||0).toFixed(3),renderEngine:'WebGL2 live mesh',drawCalls:String(s.drawCalls||0),triangles:String(s.triangles||0),meshBytes:String(s.assetBytes||s.binaryBytes||s.bufferBytes||0),spriteFetches:'0'});
      const measured=intervals.length?1000/(intervals.reduce((a,b)=>a+b,0)/intervals.length):0;d.targetFps=String(this.renderFps||120);d.measuredFps=measured.toFixed(1);d.flightZoneWidth=String(this.director?.getStats?.().projectedPlaneWidth??'');const el=document.getElementById('live-render-info');if(el)el.textContent=(this.renderFps||120)+' fps target · '+measured.toFixed(0)+' observed · '+d.drawSubmitAvgMs+' ms CPU.';
    }
    drawGuides(now,force=false){
      if(!this.guideCanvas||!this.guideCtx||!this.geometry)return;
      const visible=!!this.pathToggle?.checked;this.guideCanvas.hidden=!visible;if(!visible)return;
      if(!force&&now-(this.guideLast??-Infinity)<100)return;this.guideLast=now;
      const ctx=this.guideCtx,g=this.geometry,s=g.sky,guide=this.director?.getGuide?.();
      ctx.setTransform(g.ratio,0,0,g.ratio,0,0);ctx.clearRect(0,0,s.width,s.height);if(!guide)return;
      ctx.save();ctx.translate(-s.left,-s.top);ctx.lineWidth=1;
      const line=points=>{if(!points?.length)return;ctx.beginPath();points.forEach((p,i)=>i?ctx.lineTo(p.x,p.y):ctx.moveTo(p.x,p.y));ctx.stroke();};
      ctx.strokeStyle='#a3b4c7';ctx.setLineDash([4,5]);line(guide.boundary);ctx.setLineDash([]);
      for(const path of guide.paths||[]){ctx.strokeStyle=path.current?'#3377ed88':'#819bb64d';line(path.points);}
      if(this.lastSample?.world&&this.lastSample.point){const p=this.lastSample.point;ctx.fillStyle='#3377ed';ctx.beginPath();ctx.arc(p.x,p.y,2,0,Math.PI*2);ctx.fill();}
      ctx.restore();
    }
    clearPointer(){
      if(this.pointer||this.orbitStart!==null)this.idleGaze?.release(this.motionClock);
      this.pointer=null;this.circle=null;this.orbitStart=null;
    }
    trackPointer(e){
      if(this.ready)this.scene.style.cursor=this.birdPoint(e)?'pointer':'';
      if(!this.ready||this.state!=='idle'||!this.tracking.checked||this.motion.matches||e.pointerType==='touch'||!this.trackingCenter){this.clearPointer();return;}
      const rect=this.canvas.getBoundingClientRect(),x=e.clientX-rect.left-this.trackingCenter.x,y=e.clientY-rect.top-this.trackingCenter.y,radius=this.trackingCenter.radius,distance=Math.hypot(x,y);
      if(distance>radius){this.clearPointer();return;}
      const vertical=clamp(y/radius,-1,1);
      this.pointer=[-.08*clamp(x/radius,-1,1),(vertical<0?.40:.20)*vertical,-.60+.60*clamp(x/radius,-1,1)];
      const angle=Math.atan2(y,x),now=e.timeStamp,old=this.circle;
      if(distance/radius<.18||!old||now-old.time>500)this.circle={angle,time:now,total:0,direction:0};
      else {const delta=Math.atan2(Math.sin(angle-old.angle),Math.cos(angle-old.angle));if(Math.abs(delta)>.65){this.circle={angle,time:now,total:0,direction:0};return;}const direction=Math.sign(delta);if(Math.abs(delta)>.012&&old.direction&&direction!==old.direction)old.total=0;if(Math.abs(delta)>.012)old.direction=direction;old.total+=delta;old.angle=angle;old.time=now;if(Math.abs(old.total)>5.2&&this.motionClock>=this.orbitCooldown){this.orbitStart=this.motionClock;this.orbitBase=this.headPose.slice();this.orbitDirection=Math.sign(old.total);this.orbitCooldown=this.orbitStart+2500;old.total=0;}}
    }
    updateTrackingGuide(sample){
      const show=this.ready&&this.state==='idle'&&this.tracking.checked&&!this.motion.matches&&!this.preparing;
      if(!show){this.trackingCenter=null;if(this.trackingZone)this.trackingZone.hidden=true;return;}
      const p=this.pose('idle',sample.frame),size=this.cellSize(p),anchor=this.anchor(p,'contact'),x=this.head?.x??sample.point.x+(p.head.x-anchor.x)*size,y=this.head?.y??sample.point.y+(p.head.y-anchor.y)*size,radius=clamp(size*.38,36,60);
      this.trackingCenter={x,y,radius};if(this.trackingZone)this.trackingZone.hidden=false;const key=[x,y,radius,!!this.pointer].join('|');
      if(this.trackingZone&&key!==this.trackingZoneKey){this.trackingZoneKey=key;this.trackingZone.hidden=false;this.trackingZone.style.left=(x-this.geometry.sky.left)+'px';this.trackingZone.style.top=y+'px';this.trackingZone.style.width=radius*2+'px';this.trackingZone.style.height=radius*2+'px';this.trackingZone.dataset.active=String(!!this.pointer);}
      Object.assign(this.canvas.dataset,{trackingX:x.toFixed(2),trackingY:y.toFixed(2),trackingRadius:radius.toFixed(2),trackingActive:String(!!this.pointer)});
    }
    attentionFrame(now,sample){
      let orbitTarget=null;const u=(now-(this.orbitStart??-10000))/1800;
      if(u>=0&&u<1){const a=u*Math.PI*2*this.orbitDirection,g=Math.sin(Math.PI*u);orbitTarget=[this.orbitBase[0]+.24*Math.sin(a)*g,this.orbitBase[1]+.18*Math.sin(a)*g,this.orbitBase[2]+.24*(Math.cos(a)-1)*g];}
      else if(u>=1)this.orbitStart=null;
      this.headPose=this.idleGaze.sample(now,this.pointer,orbitTarget);
      const state=this.idleGaze.getState();
      Object.assign(this.canvas.dataset,{headTilt:String(this.headPose[0]),headPitch:String(this.headPose[1]),headYaw:String(this.headPose[2]),headNextTurnMs:String(state.nextTurnAt),headTurnCount:String(state.chosenTurns),idleHeadMode:state.tracking?'tracking':state.turnStartedAt!==null?'turning':'holding'});
      const grid=this.attentionMeta.grid||this.attentionMeta,nearest=(v,values)=>values.reduce((best,n,i)=>Math.abs(n-v)<Math.abs(values[best]-v)?i:best,0),blink=now<this.blinkUntil;
      const ny=grid.yaw.length,np=grid.pitch.length,[tilt,pitch,yaw]=this.headPose;
      return (blink?ny*np*grid.tilt.length:0)+nearest(tilt,grid.tilt)*np*ny+nearest(pitch,grid.pitch)*ny+nearest(yaw,grid.yaw);
    }
    invalidateBuffer(){this.assetGeneration++;this.buffering=false;this.motionLast=null;this.lastDrawKey='';}
    draw(now,force=false){
      if(!this.ready||!this.geometry||this.preparing||!this.live)return;
      if(this.director?.blocked){this.motionLast=null;this.status.textContent='The raven needs a little more room. Widen the window to continue.';return;}
      const began=performance.now(),sample=this.sample(now),renderedScale=this.scaleFor(sample.clip,sample.frame,sample),pose=this.pose(sample.clip,sample.frame),size=this.cellSize(pose,renderedScale);
      const attention=sample.clip==='idle'&&!this.motion.matches?this.attentionFrame(this.motionClock,sample):null;
      const old=sample.blendFrom,blendFrom=old?{...old,frame:this.nativeFrame(old.clip,old.frame),size:this.cellSize(this.pose(old.clip,old.frame),this.scaleFor(old.clip,old.frame,old)),anchor:old.anchor||'root'}:null;
      try{
        const options={clip:sample.clip,frame:this.nativeFrame(sample.clip,sample.frame),attentionPose:attention===null?null:this.headPose.slice(),flightRotation:sample.flightRotation,petHeadPose:sample.petHeadPose,petStartBlink:sample.petStartBlink,petIdleFrame:sample.petIdleFrame,blink:this.motionClock<this.blinkUntil,size,anchor:sample.anchor,point:sample.point,darker:this.darker.checked,blendFrom,blendWeight:sample.blendWeight??1};
        const helpers=this.flock?.samples(this.motionClock)||[];
        const result=helpers.length?this.live.renderBatch([options,...helpers])[0]:this.live.render(options);
        Object.assign(this.canvas.dataset,{helperCount:String(helpers.length),renderContexts:'1',mainLeft:String(result.bounds.left),mainRight:String(result.bounds.right),mainTop:String(result.bounds.top),mainBottom:String(result.bounds.bottom)});
        const anchor=this.anchor(pose,sample.anchor),x=sample.point.x-anchor.x*size,y=sample.point.y-anchor.y*size,box=result?.bounds||pose.bounds;
        this.drawBounds=result?.bounds?{x:box.left,y:box.top,width:box.right-box.left,height:box.bottom-box.top,size}:{x:x+box.left*size,y:y+box.top*size,width:(box.right-box.left)*size,height:(box.bottom-box.top)*size,size};
        if(sample.clip==='pet'&&result?.pose.headTilt)this.headPose=result.pose.headTilt.slice();this.head=result?.markers?.head||{x:x+pose.head.x*size,y:y+pose.head.y*size,size};
        this.updateTrackingGuide(sample);this.ctx.setTransform(this.geometry.ratio,0,0,this.geometry.ratio,0,0);this.ctx.clearRect(0,0,this.geometry.width,this.geometry.height);
        if(sample.clip==='caw'&&!sample.silent&&pose.cawOpen>=.25&&!this.motion.matches)this.soundMarks(result?.markers?.beak||{x:x+pose.beak.x*size,y:y+pose.beak.y*size},pose,size);
        Object.assign(this.canvas.dataset,{clip:sample.clip,frame:String(sample.frame),nativeFrame:String(this.nativeFrame(sample.clip,sample.frame)),fps:String(this.renderFps||this.activeFps),attention:attention===null?'':String(attention),anchorX:sample.point.x.toFixed(2),anchorY:sample.point.y.toFixed(2),promptReturn:String(!!sample.promptReturn),returnBlend:String(sample.blendWeight??''),depthScale:String(sample.depthScale??1),worldX:sample.world?String(sample.world.x):'',worldZ:sample.world?String(sample.world.z):'',heading:sample.heading??'',petBaseYaw:sample.petHeadPose?String(sample.petHeadPose[2]):'',petNeckStretch:String(result?.pose.neckStretch??0),petEyeClosure:String(result?.pose.eyeClosure??0),flightFamily:sample.family??'',flightBank:String(sample.flightRotation?.bank??0),flightYaw:String(sample.flightRotation?.yaw??0),routeYaw:Number.isFinite(sample.routeYaw)?String(sample.routeYaw):'',renderedScale:String(renderedScale),flightScale:String(this.geometry.flightScale)});
        this.lastSample=sample;this.drawGuides(now,force);
        const elapsed=performance.now()-began;this.stats.draws++;this.stats.drawMs+=elapsed;this.stats.maxDrawMs=Math.max(this.stats.maxDrawMs,elapsed);
      }catch(e){this.ready=false;this.assetError=e;this.setState('error');this.status.textContent='Live 3D stopped. Compare sprites opens the preserved Blender version.';console.error(e);}
    }
    soundMarks(beak,pose,size){
      const amount=Math.max(.4,pose.cawOpen),unit=size/512;this.ctx.strokeStyle='#303b47';this.ctx.lineWidth=Math.max(1.3,2.2*unit);this.ctx.lineCap='round';
      const line=(x1,y1,x2,y2)=>{this.ctx.beginPath();this.ctx.moveTo(x1,y1);this.ctx.lineTo(x2,y2);this.ctx.stroke();};
      if((pose.frontness||0)>.78){for(const side of [-1,1])for(const offset of [-10,10])line(beak.x+side*37*unit,beak.y+offset*unit,beak.x+side*(37+15*amount)*unit,beak.y+offset*1.5*unit);}
      else {const d=pose.soundDirection||{x:1,y:0},a=Math.atan2(d.y,d.x);for(const offset of [-.43,0,.43]){const angle=a+offset,start=21*unit,end=(21+23*amount)*unit;line(beak.x+Math.cos(angle)*start,beak.y+Math.sin(angle)*start,beak.x+Math.cos(angle)*end,beak.y+Math.sin(angle)*end);}}
    }
  }
  window.addEventListener('DOMContentLoaded',()=>{const controller=window.ravenChatDemo=new RavenChatDemo();controller.flock=new window.RavenFlock({controller,button:document.getElementById('spawn-raven'),clearButton:document.getElementById('clear-ravens'),status:document.getElementById('flock-status')});});
})();

