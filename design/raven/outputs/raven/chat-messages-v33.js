/* Local Marked + DOMPurify renderer; website previews use the local guarded API. */
(() => {
  'use strict';
  const settings={previewEndpoint:'/api/link-preview',imageEndpoint:'/api/link-preview-image',hoverDelay:260};
  const allowedTags=['p','h1','h2','h3','h4','h5','h6','ul','ol','li','blockquote','hr','pre','code','em','strong','del','s','a','table','thead','tbody','tfoot','tr','th','td','br','span','kbd','samp','input','img'];
  const allowedAttrs=['href','title','align','colspan','rowspan','class','checked','type','disabled','start','alt','src'];
  const cache=new Map();let serial=0,portal=null,active=null,requestId=0,showTimer=null,hideTimer=null,installed=false;
  const text=(node,value)=>{node.textContent=String(value??'');return node;};
  const make=(tag,className,value)=>{const node=document.createElement(tag);if(className)node.className=className;if(value!==undefined)text(node,value);return node;};
  function safeUrl(value) {
    if(typeof value!=='string'||value.length>2048||/[\u0000-\u0020\u007f\\]/.test(value))return null;
    if(value.startsWith('#'))return value;
    if(/^mailto:/i.test(value)){
      try{const decoded=decodeURIComponent(value.slice(7));return /^[^\s<>?@]+@[^\s<>?@]+\.[^\s<>?@]+$/.test(decoded)?value:null;}catch{return null;}
    }
    if(!/^https?:\/\//i.test(value))return null;
    try{const url=new URL(value);if(!['http:','https:'].includes(url.protocol)||!url.hostname||url.username||url.password)return null;return url.href;}catch{return null;}
  }
  const slug=value=>String(value).toLowerCase().normalize('NFKD').replace(/[\u0300-\u036f]/g,'').replace(/[^\p{L}\p{N}_-]+/gu,'-').replace(/^-|-$/g,'')||'section';
  function configure(options={}) {
    for(const name of ['previewEndpoint','imageEndpoint'])if(typeof options[name]==='string'&&/^\/[A-Za-z0-9/_-]+$/.test(options[name]))settings[name]=options[name];
    if(Number.isFinite(options.hoverDelay))settings.hoverDelay=Math.max(0,Math.min(1000,options.hoverDelay));
    return {...settings};
  }
  function renderMessage(container,value) {
    if(!container||typeof container.replaceChildren!=='function')throw new TypeError('A message container is required');
    if(active&&container.contains(active))hidePreview();
    const source=String(value??'');container.classList.add('raven-markdown');
    if(!window.marked?.parse||!window.DOMPurify?.sanitize||source.length>100000){text(container,source);container.dataset.messageFormat='plain';return container;}
    try{
      const html=window.marked.parse(source.replace(/^[\u200B-\u200F\uFEFF]+/,''),{gfm:true,breaks:true,async:false});
      const fragment=window.DOMPurify.sanitize(html,{ALLOWED_TAGS:allowedTags,ALLOWED_ATTR:allowedAttrs,ALLOW_DATA_ATTR:false,
        ALLOW_ARIA_ATTR:false,FORBID_TAGS:['style','script','svg','math','iframe','object','embed','form','button','textarea','select'],RETURN_DOM_FRAGMENT:true});
      container.replaceChildren(fragment);container.dataset.messageFormat='markdown';
      const prefix='raven-message-'+(++serial)+'-',headings=new Map(),duplicates=new Map();
      for(const node of container.querySelectorAll('[class]')){
        const language=node.tagName==='CODE'?[...node.classList].find(name=>/^language-[\w-]{1,32}$/.test(name)):null;
        node.removeAttribute('class');if(language)node.className=language;
      }
      for(const heading of container.querySelectorAll('h1,h2,h3,h4,h5,h6')){
        const base=slug(heading.textContent),count=duplicates.get(base)||0;duplicates.set(base,count+1);
        const name=base+(count?'-'+count:'');heading.id=prefix+name;if(!headings.has(base))headings.set(base,heading.id);headings.set(name,heading.id);
      }
      for(const input of container.querySelectorAll('input')){
        if(input.getAttribute('type')!=='checkbox'){input.remove();continue;}input.disabled=true;input.tabIndex=-1;input.className='raven-markdown-checkbox';
      }
      for(const cell of container.querySelectorAll('th[align],td[align]')){
        const align=cell.getAttribute('align');cell.removeAttribute('align');if(['left','center','right'].includes(align))cell.style.textAlign=align;
      }
      for(const table of container.querySelectorAll('table')){
        const wrapper=make('div','raven-markdown-table');wrapper.tabIndex=0;wrapper.setAttribute('role','region');wrapper.setAttribute('aria-label','Message table');
        table.before(wrapper);wrapper.append(table);
      }
      for(const image of container.querySelectorAll('img')){
        const url=safeUrl(image.getAttribute('src'));if(!url||!/^https?:/.test(url)){image.remove();continue;}
        image.src=settings.imageEndpoint+'?url='+encodeURIComponent(url);image.loading='lazy';image.referrerPolicy='no-referrer';
        image.addEventListener('error',()=>image.replaceWith(make('span','raven-markdown-image-fallback',image.alt||'Image unavailable')),{once:true});
      }
      for(const anchor of container.querySelectorAll('a')){
        const href=safeUrl(anchor.getAttribute('href'));if(!href){anchor.removeAttribute('href');continue;}
        if(href.startsWith('#')){
          let id;try{id=headings.get(decodeURIComponent(href.slice(1)));}catch{}
          if(id)anchor.href='#'+id;else anchor.removeAttribute('href');continue;
        }
        anchor.href=href;
        if(/^https?:/.test(href)){
          anchor.target='_blank';anchor.rel='noopener noreferrer';anchor.dataset.ravenPreviewUrl=href;
          anchor.setAttribute('aria-label',anchor.textContent+' (opens in a new tab)');
        }
      }
      install();return container;
    }catch{container.replaceChildren(document.createTextNode(source));container.dataset.messageFormat='plain';return container;}
  }
  function ensurePortal() {
    if(portal)return portal;
    portal=make('div','raven-link-preview');portal.id='raven-link-preview-v33';portal.hidden=true;portal.setAttribute('role','tooltip');
    const image=make('img','raven-link-preview-image');image.hidden=true;image.alt='';image.referrerPolicy='no-referrer';
    const content=make('div','raven-link-preview-content'),site=make('div','raven-link-preview-site'),favicon=make('img','raven-link-preview-favicon');
    favicon.hidden=true;favicon.alt='';favicon.referrerPolicy='no-referrer';site.append(favicon,make('span','raven-link-preview-domain'));
    content.append(site,make('strong','raven-link-preview-title'),make('p','raven-link-preview-description'),make('span','raven-link-preview-status'));
    portal.append(image,content);document.body.append(portal);
    portal.addEventListener('pointerenter',()=>clearTimeout(hideTimer));portal.addEventListener('pointerleave',()=>scheduleHide());
    return portal;
  }
  function positionPreview() {
    if(!active||!portal||portal.hidden)return;
    const anchor=active.getBoundingClientRect(),vw=window.innerWidth,vh=window.innerHeight;
    if(!active.isConnected||anchor.bottom<0||anchor.top>vh||anchor.right<0||anchor.left>vw){hidePreview();return;}
    portal.style.position='fixed';portal.style.width=Math.min(320,vw-24)+'px';portal.style.maxHeight=Math.max(80,vh-24)+'px';portal.style.overflow='auto';
    const box=portal.getBoundingClientRect();let top=anchor.bottom+9;
    if(top+box.height>vh-12&&anchor.top-box.height-9>=12)top=anchor.top-box.height-9;
    portal.style.top=Math.max(12,Math.min(top,vh-box.height-12))+'px';portal.style.left=Math.max(12,Math.min(anchor.left,vw-box.width-12))+'px';
  }
  function hidePreview() {
    clearTimeout(showTimer);clearTimeout(hideTimer);requestId++;
    if(active){active.removeAttribute('aria-describedby');active=null;}
    if(portal)portal.hidden=true;
  }
  function scheduleHide(){clearTimeout(hideTimer);hideTimer=setTimeout(hidePreview,160);}
  async function metadata(url) {
    const entry=cache.get(url);if(entry&&entry.expires>Date.now())return entry.promise;
    const promise=(async()=>{
      const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),6700);
      try{
        const response=await fetch(settings.previewEndpoint+'?url='+encodeURIComponent(url),{credentials:'omit',signal:controller.signal});
        if(!response.ok)throw new Error('No preview');const result=await response.json();return result&&typeof result==='object'?result:{status:'unavailable'};
      }catch{return {status:'unavailable'};}finally{clearTimeout(timer);}
    })();
    cache.delete(url);cache.set(url,{promise,expires:Date.now()+15*60*1000});
    promise.then(result=>{const current=cache.get(url);if(current?.promise===promise)current.expires=Date.now()+(result.status==='ok'?15*60*1000:60000);});
    while(cache.size>96)cache.delete(cache.keys().next().value);return promise;
  }
  function init(root=document) {
    for(const container of root.querySelectorAll('.message-copy[data-markdown]')){
      if(container.dataset.messageFormat)continue;
      const value=container.getAttribute('data-markdown');renderMessage(container,value&&value!=='true'?value:container.textContent);
    }
  }
  async function showPreview(anchor) {
    if(!anchor.isConnected)return;clearTimeout(hideTimer);
    if(active===anchor&&portal&&!portal.hidden)return;
    hidePreview();active=anchor;const id=++requestId,box=ensurePortal(),url=anchor.dataset.ravenPreviewUrl,host=new URL(url).hostname;
    anchor.setAttribute('aria-describedby',box.id);box.hidden=false;
    text(box.querySelector('.raven-link-preview-domain'),host);text(box.querySelector('.raven-link-preview-title'),anchor.textContent||host);
    text(box.querySelector('.raven-link-preview-description'),'');text(box.querySelector('.raven-link-preview-status'),'Loading preview…');
    box.querySelector('.raven-link-preview-image').hidden=true;box.querySelector('.raven-link-preview-favicon').hidden=true;positionPreview();
    const result=await metadata(url);if(requestId!==id||active!==anchor)return;
    const ok=result.status==='ok';text(box.querySelector('.raven-link-preview-title'),ok?String(result.title||host).slice(0,180):(anchor.textContent||host));
    text(box.querySelector('.raven-link-preview-description'),ok?String(result.description||'').slice(0,420):'');
    text(box.querySelector('.raven-link-preview-domain'),ok?String(result.siteName||host).slice(0,100):host);
    text(box.querySelector('.raven-link-preview-status'),ok?'Website preview':'Preview unavailable');
    for(const [selector,value] of [['.raven-link-preview-image',result.image],['.raven-link-preview-favicon',result.favicon]]){
      const image=box.querySelector(selector),safe=safeUrl(value);image.hidden=true;image.removeAttribute('src');
      if(ok&&safe&&/^https?:/.test(safe)&&!/\.svgz?$/i.test(new URL(safe).pathname)){
        image.onload=()=>{if(requestId===id){image.hidden=false;positionPreview();}};image.onerror=()=>{image.hidden=true;positionPreview();};
        image.src=settings.imageEndpoint+'?url='+encodeURIComponent(safe);
      }
    }
    positionPreview();
  }
  function install() {
    if(installed)return;installed=true;
    const link=target=>target?.closest?.('.raven-markdown a[data-raven-preview-url]');
    document.addEventListener('pointerover',event=>{
      if(event.pointerType==='touch')return;const anchor=link(event.target);if(!anchor||anchor.contains(event.relatedTarget))return;
      clearTimeout(showTimer);clearTimeout(hideTimer);showTimer=setTimeout(()=>showPreview(anchor),settings.hoverDelay);
    });
    document.addEventListener('pointerout',event=>{
      const anchor=link(event.target);if(!anchor||anchor.contains(event.relatedTarget))return;
      clearTimeout(showTimer);if(portal?.contains(event.relatedTarget))return;scheduleHide();
    });
    document.addEventListener('focusin',event=>{const anchor=link(event.target);if(anchor){clearTimeout(showTimer);showPreview(anchor);}});
    document.addEventListener('focusout',event=>{if(link(event.target))scheduleHide();});
    document.addEventListener('keydown',event=>{if(event.key==='Escape')hidePreview();});
    document.addEventListener('pointerdown',event=>{if(active&&!active.contains(event.target)&&!portal?.contains(event.target))hidePreview();});
    document.addEventListener('visibilitychange',()=>{if(document.hidden)hidePreview();});
    window.addEventListener('resize',positionPreview);window.addEventListener('scroll',positionPreview,true);
  }
  const examples=Object.freeze({
    welcome:'## Your raven companion\n\nSend a message and I’ll keep watch while the raven patrols. **Markdown works here**, including lists, code and tables.\n\n| State | What the raven does |\n| --- | --- |\n| Ready | Perches on Send |\n| Working | Scans the ground |\n| Reply | Returns and caws |\n\nVisit [Blender](https://www.blender.org/) or [MDN Web Docs](https://developer.mozilla.org/en-US/) — hover or focus a link for a website preview.',
    response:'## Caw caw!\n\nYour raven has finished its patrol.\n\n- **Looked around** from different angles\n- Kept an eye on the ground\n- Returned to the blue **Send** button\n\n| Next | Try it |\n| --- | --- |\n| Pet the raven | Click its head |\n| Send another task | Type a new message |\n\n```js\nconst reply = "caw caw";\n```\n\nExplore [Blender](https://www.blender.org/) or [MDN Web Docs](https://developer.mozilla.org/en-US/).'
  });
  window.RavenMessages=Object.freeze({renderMessage,configure,safeUrl,hidePreview,init,examples,demoReply:examples.response,version:33});
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',()=>init(),{once:true});else queueMicrotask(()=>init());
})();
