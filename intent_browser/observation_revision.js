// Experimental public-page revision tracker. Not a general completeness claim.
(() => {
  if (globalThis.__intentObservationRevision) return;
  let revision = 0, pending = 0, unsupported = false;
  const documentId = Array.from(crypto.getRandomValues(new Uint32Array(4)),
    x => x.toString(16)).join('-');
  const bump = () => { revision++; };
  const observer = new MutationObserver(bump);
  observer.observe(document, {subtree:true, childList:true, attributes:true, characterData:true});
  // Native interactions, including CSS :focus/:hover/:checked and details state.
  for (const event of ['input','change','focus','blur','focusin','focusout','pointerover','pointerout',
    'pointerdown','pointerup','keydown','keyup',
    'scroll','resize','toggle','load','error','transitionrun','transitionend',
    'transitioncancel','animationstart','animationend','animationcancel','reset',
    'pageshow','hashchange','popstate']) addEventListener(event,bump,true);
  for (const event of ['loading','loadingdone','loadingerror']) document.fonts.addEventListener(event,bump);
  // Direct property assignments do not necessarily emit DOM/input events.
  const setter = (proto, key) => {
    const d = Object.getOwnPropertyDescriptor(proto,key);
    if (!d?.set || !d.configurable) { unsupported=true; return; }
    Object.defineProperty(proto,key,{...d,set(value) { d.set.call(this,value); bump(); }});
  };
  for (const [proto, keys] of [
    [HTMLInputElement.prototype,['value','checked','indeterminate']],
    [HTMLTextAreaElement.prototype,['value']],
    [HTMLSelectElement.prototype,['value','selectedIndex']],
    [HTMLOptionElement.prototype,['selected']],
  ]) for (const key of keys) setter(proto,key);
  const method = (proto, name, asynchronous=false) => {
    const original=proto[name];
    if (typeof original!=='function') { unsupported=true; return; }
    proto[name]=function(...args) {
      const result=original.apply(this,args); bump();
      if (asynchronous) {
        pending++;
        // Observe settlement without replacing the site's returned Promise.
        result.then(()=>{pending--;bump();},()=>{pending--;bump();});
      }
      return result;
    };
  };
  for (const key of Object.getOwnPropertyNames(CSSStyleDeclaration.prototype)) {
    if (Object.getOwnPropertyDescriptor(CSSStyleDeclaration.prototype,key)?.set)
      setter(CSSStyleDeclaration.prototype,key);
  }
  for (const name of ['setProperty','removeProperty']) method(CSSStyleDeclaration.prototype,name);
  for (const name of ['insertRule','deleteRule','replaceSync']) method(CSSStyleSheet.prototype,name);
  method(CSSStyleSheet.prototype,'replace',true);
  for (const name of ['pushState','replaceState']) method(History.prototype,name);
  const attachShadow=Element.prototype.attachShadow;
  Element.prototype.attachShadow=function(...args) {
    const result=attachShadow.apply(this,args);unsupported=true;bump();return result;
  };
  const read = () => {
    if (observer.takeRecords().length) bump();
    // CSS declarations can be exposed through native named-property interceptors
    // rather than prototype setters. Compare stylesheet contents as well; never
    // assume wrapping CSSStyleDeclaration catches rule.style.display writes.
    let styleSignature;
    const rules = sheet => [...sheet.cssRules].map(rule=>[
      rule.cssText, rule instanceof CSSMediaRule ? matchMedia(rule.conditionText).matches : null,
      rule.cssRules ? rules(rule) : null]);
    try { styleSignature=[...document.styleSheets,...document.adoptedStyleSheets]
      .map(s=>[s.disabled,s.media.mediaText,
        s.media.mediaText?matchMedia(s.media.mediaText).matches:null,rules(s)]); }
    catch { unsupported=true;styleSignature=null; }
    const resourcesPending=document.readyState!=='complete' || pending>0 ||
      document.fonts.status!=='loaded' || [...document.images].some(i=>!i.complete);
    const animations=document.getAnimations().some(a=>a.playState==='running'||a.pending);
    return {document:documentId,revision,url:location.href,resourcesPending,animations,styleSignature,
      unsupported:unsupported || !!document.querySelector('iframe,frame,object,embed,marquee,video,audio,canvas,svg animate,svg animateTransform')};
  };
  Object.defineProperty(globalThis,'__intentObservationRevision',{value:Object.freeze({read})});
})();
