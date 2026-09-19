"""Bounded, context-wide browser evidence. No website or verifier knowledge.

DOM events stream to Python, so delivered events survive document destruction.
CDP dialog observation deliberately avoids installing a Playwright dialog handler:
doing that would change the browser's automatic dialog-dismissal behavior.
"""
import json
import time
from uuid import uuid4


INSTALL = r"""(() => {
  const key = __KEY__, binding = __BINDING__;
  if (window[key]) return;
  const documentId = crypto.randomUUID(), pending = new Set();
  let sequence = 0, sent = 0, omitted = 0, closed = false;
  const transmit = payload => {
    const p = window[binding]({...payload, document_id:documentId, document_sequence:++sequence});
    pending.add(p); p.catch(()=>{}).finally(()=>pending.delete(p));
  };
  const emit = payload => {
    if (closed) return;
    if (sent++ >= 64) { omitted++; return; }
    transmit(payload);
  };
  const visible = el => {
    if (!(el instanceof Element) || !el.isConnected || !el.getClientRects().length) return false;
    for (let p=el; p instanceof Element; p=p.parentElement) {
      if (p.hidden || p.getAttribute('aria-hidden')==='true') return false;
      const s=getComputedStyle(p);
      if (s.display==='none' || s.visibility==='hidden' || s.visibility==='collapse' || s.opacity==='0') return false;
    }
    return true;
  };
  const label = el => (el.getAttribute('aria-label') ||
    Array.from(el.labels || []).map(x=>x.innerText).join(' ') || el.innerText || '').trim().slice(0,320);
  const describe = el => {
    const result={tag:el.tagName.toLowerCase(), label:label(el), role:el.getAttribute('role') || ''};
    if (el.type==='password') return {...result,value:'[password omitted]'};
    if (el.matches('input[type=checkbox],input[type=radio]')) result.checked=el.checked;
    else if (el.matches('input:not([type=hidden]),textarea,select')) result.value=String(el.value).slice(0,320);
    return result;
  };
  const live = '[role="alert"],[role="status"],[aria-live="polite"],[aria-live="assertive"]';
  const observer = new MutationObserver(records => {
    const seen = new Set();
    const textEvent = (el, kind) => {
      if (!visible(el) || el.matches('script,style,input,textarea,select')) return;
      const text=(el.innerText || '').trim();
      // Generic text changes are intentionally small. Large regions are handled
      // by the normal AX observation; do not stream an entire document here.
      if (!text || (kind==='text_appeared' && text.length>400)) return;
      const identity=kind+'\0'+text;
      if (seen.has(identity)) return;
      seen.add(identity); emit({kind,text:text.slice(0,800),truncated:text.length>800});
    };
    for (const r of records.slice(0,200)) {
      const el=r.target.nodeType===1 ? r.target : r.target.parentElement;
      textEvent(el?.closest(live),'page_announcement');
      if (r.type==='characterData') textEvent(el,'text_appeared');
      if (r.type==='attributes' && visible(el) && r.attributeName.startsWith('aria-') &&
          !['aria-live','aria-hidden'].includes(r.attributeName)) {
        emit({kind:'control_state', ...describe(el), attribute:r.attributeName,
          previous:r.oldValue, value:el.getAttribute(r.attributeName)});
      }
      for (const node of Array.from(r.addedNodes).slice(0,32)) {
        if (node.nodeType===3) { textEvent(node.parentElement,'text_appeared'); continue; }
        if (!(node instanceof Element)) continue;
        if (node.matches(live)) textEvent(node,'page_announcement');
        for (const a of Array.from(node.querySelectorAll(live)).slice(0,16)) textEvent(a,'page_announcement');
        textEvent(node,'text_appeared');
      }
    }
    if (records.length>200) omitted+=records.length-200;
  });
  observer.observe(document,{subtree:true,childList:true,characterData:true,attributes:true,
    attributeOldValue:true,attributeFilter:['aria-checked','aria-expanded','aria-selected',
      'aria-disabled','aria-invalid','aria-valuenow','aria-hidden','hidden','role','aria-live']});
  const handlers=[];
  for (const type of ['input','change','invalid','submit','focusin']) {
    const handler = e => {
      const el=e.target;
      if (!visible(el)) return;
      const value={kind:type==='focusin'?'focus':type, ...describe(el)};
      if (type==='invalid') value.text=String(el.validationMessage || '').slice(0,320);
      emit(value);
    };
    document.addEventListener(type,handler,true); handlers.push([type,handler]);
  }
  Object.defineProperty(window,key,{configurable:true,value:{
    async flush() {
      await Promise.resolve();
      if (omitted) { transmit({kind:'capture_gap', count:omitted}); omitted=0; }
      await Promise.allSettled(Array.from(pending)); sent=0;
    },
    close() { closed=true;observer.disconnect();for(const [t,h] of handlers) document.removeEventListener(t,h,true);delete window[key]; }
  }});
})();"""


class BrowserEvents:
    def __init__(self, max_events=64):
        self.max_events = max_events
        self.key = '__intent_capture_' + uuid4().hex
        self.binding = '__intent_emit_' + uuid4().hex
        self.source = INSTALL.replace('__KEY__', json.dumps(self.key)).replace('__BINDING__', json.dumps(self.binding))
        self.events = []
        self.omitted = self.sequence = 0
        self.phase = 'between_actions'
        self.context = None
        self.pages, self.frames, self.sessions, self.listeners = {}, {}, [], []
        self.watched_pages = set()
        self.errors = set()
        self.closed = False

    def _id(self, mapping, value, prefix):
        if value not in mapping: mapping[value] = f'{prefix}{len(mapping)+1}'
        return mapping[value]

    def _append(self, page, frame, payload, *, native=False):
        if self.closed or not isinstance(payload, dict): return
        allowed = {'page_announcement','text_appeared','control_state','input','change','invalid',
                   'submit','focus','capture_gap'}
        if not native and payload.get('kind') not in allowed: return
        self.sequence += 1
        if len(self.events) >= self.max_events:
            self.omitted += 1
            return
        fields = {'kind','text','truncated','tag','role','label','checked','value','attribute',
                  'previous','document_id','document_sequence','count','url','dialog_type'}
        clean = {k: (v[:800] if isinstance(v,str) else v) for k,v in payload.items()
                 if k in fields and (v is None or type(v) in (str,int,bool))}
        self.events.append({**clean, 'sequence':self.sequence,
            'observed_monotonic':time.monotonic(), 'window':self.phase,
            'page':self._id(self.pages,page,'p'),
            'frame':self._id(self.frames,frame,'f') if frame else None,
            'source':'browser_event' if native else 'page_dom'})

    def _listen(self, emitter, event, callback):
        emitter.on(event, callback); self.listeners.append((emitter,event,callback))

    def _page(self, page, *, opened=False):
        if page in self.watched_pages: return
        self.watched_pages.add(page)
        self._id(self.pages,page,'p')
        if opened: self._append(page,None,{'kind':'page_opened','url':page.url},native=True)
        self._listen(page,'framenavigated', lambda f:self._append(page,f,{'kind':'navigation','url':f.url},native=True))
        self._listen(page,'close',lambda:self._append(page,None,{'kind':'page_closed'},native=True))
        self._listen(page,'framedetached',lambda f:self._append(page,f,{'kind':'frame_detached'},native=True))
        try:
            session=self.context.new_cdp_session(page)
            session.send('Page.enable')
            session.on('Page.javascriptDialogOpening',lambda e:self._append(page,None,
                {'kind':'dialog_opened','dialog_type':e.get('type'),'text':e.get('message')},native=True))
            session.on('Page.javascriptDialogClosed',lambda e:self._append(page,None,{'kind':'dialog_closed'},native=True))
            self.sessions.append(session)
        except Exception:
            self.errors.add('native_dialog_observer_unavailable')

    def start(self, context):
        self.context=context
        context.expose_binding(self.binding, lambda source,payload:self._append(source['page'],source['frame'],payload))
        context.add_init_script(script=self.source)
        self._listen(context,'page',lambda page:self._page(page,opened=True))
        for page in context.pages:
            self._page(page)
            for frame in page.frames:
                try: frame.evaluate(self.source)
                except Exception: self.errors.add('initial_frame_install_unavailable')

    def drain(self):
        # Flush bindings in live documents without sleeping or mutating page UI.
        # Already delivered events in Python survive navigation/frame removal.
        for page in list(self.context.pages):
            for frame in list(page.frames):
                try:
                    available=frame.evaluate('(key) => !!window[key]',self.key)
                    if available: frame.evaluate('(key) => window[key].flush()',self.key)
                    else: self.errors.add('document_observer_unavailable')
                except Exception: self.errors.add('frame_flush_unavailable')
        result={'events':self.events, 'omitted':self.omitted, 'capture_warnings':sorted(self.errors)}
        self.events=[]; self.omitted=0; self.errors.clear()
        return result

    def close(self):
        self.closed=True
        for emitter,event,callback in self.listeners:
            try: emitter.remove_listener(event,callback)
            except Exception: pass
        for session in self.sessions:
            try: session.detach()
            except Exception: pass
        if self.context is not None:
            for page in list(self.context.pages):
                for frame in list(page.frames):
                    try: frame.evaluate('(key) => window[key]?.close()',self.key)
                    except Exception: pass
