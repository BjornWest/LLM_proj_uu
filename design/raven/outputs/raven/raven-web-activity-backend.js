/* Actual navigation only; no demo browsing schedule. */
(() => {
  'use strict';
  const activity=new RavenWebActivity({element:document.getElementById('web-activity')});
  const scene=document.getElementById('chat-scene'),visited=document.getElementById('visited-sites');
  const list=visited.querySelector('ul'),sites=new Map();
  scene.addEventListener('raven-chat-submit',()=>{activity.reset();sites.clear();list.replaceChildren();visited.hidden=true;visited.open=false;});
  document.addEventListener('raven-web-activity',({detail})=>{
    if(detail.status==='complete'||detail.active===false){activity.finish();return;}
    const url=RavenWebActivity.safePublicUrl(detail.url);if(!url)return;
    activity.start({...detail,demo:false});
    if(!sites.has(url)){
      sites.set(url,detail);
      const item=document.createElement('li'),link=document.createElement('a');
      link.href=url;link.textContent=detail.label||new URL(url).hostname;link.target='_blank';link.rel='noopener noreferrer';
      item.append(link);list.append(item);visited.hidden=false;
    }
  });
  // The site itself opens the page; the rest of the indicator opens the visit list.
  activity.element.addEventListener('click',event=>{if(!event.target.closest('a'))visited.open=!visited.open;});
  scene.addEventListener('raven-chat-reply',()=>activity.finish());
  scene.addEventListener('raven-conversation-change',()=>{activity.reset();sites.clear();list.replaceChildren();visited.hidden=true;});
  window.addEventListener('pagehide',()=>activity.dispose());
})();
