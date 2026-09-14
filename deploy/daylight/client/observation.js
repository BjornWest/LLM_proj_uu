let sequence=0;
const identifiers=new WeakMap();
export function snapshot(doc) {
  const modal=doc.querySelector('dialog[open]'),root=modal||doc.body;
  const elements=[...root.querySelectorAll('button,a[href],input,select,textarea')].filter(e=>e.getClientRects().length && e.type!=='hidden'&&e.type!=='password');
  const map=new Map();
  const controls=elements.map(e=>{
    if(!identifiers.has(e))identifiers.set(e,'c'+(++sequence));
    const id=identifiers.get(e);map.set(id,e);
    return {id,tag:e.tagName.toLowerCase(),type:e.type||'',label:(e.getAttribute('aria-label')||
      [...(e.labels||[])].map(l=>{const clone=l.cloneNode(true);clone.querySelectorAll('select,input,textarea').forEach(n=>n.remove());return clone.textContent.trim();}).join(' ')||e.textContent.trim()).slice(0,250),
      disabled:!!e.disabled,...(e.tagName==='SELECT'?{value:e.value,options:[...e.options].map(o=>({value:o.value,label:o.textContent,disabled:o.disabled}))}:
      e.type==='checkbox'?{checked:e.checked}:e.tagName==='INPUT'||e.tagName==='TEXTAREA'?{value:e.value}:{})};
  });
  return {observation:{captured_at:new Date().toISOString(),title:doc.title,text:root.innerText.slice(0,18000),controls},map};
}
export function fingerprint(obs) {return JSON.stringify({title:obs.title,text:obs.text,controls:obs.controls});}
export function execute(action,captured,doc) {
  if(action.action==='done')return;
  const fresh=snapshot(doc);
  if(fingerprint(captured.observation)!==fingerprint(fresh.observation))throw Error('The page changed while the agent was deciding. Stopped without clicking a stale control.');
  const element=captured.map.get(action.id);
  if(!element?.isConnected||element.disabled)throw Error('That control is no longer available');
  element.scrollIntoView({block:'center',behavior:'instant'});
  if(action.action==='click') {
    if(element.tagName==='A') {
      const url=new URL(element.href);
      if(url.origin!==location.origin||!/^\/world\/[a-z0-9-]+\/(shop|booking|preferences)$/.test(url.pathname))throw Error('Navigation is limited to demo pages');
    }
    element.click();
  } else if(action.action==='select') {element.value=action.value;element.dispatchEvent(new doc.defaultView.Event('change',{bubbles:true}));}
  else if(action.action==='check') {if(element.checked!==action.value)element.click();}
  else if(action.action==='fill') {element.value=action.value;element.dispatchEvent(new doc.defaultView.Event('input',{bubbles:true}));}
  else throw Error('Unsupported action');
}
