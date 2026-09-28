"""Bounded, context-wide browser evidence. No website or verifier knowledge.

DOM events stream to Python, so delivered events survive document destruction.
CDP dialog observation deliberately avoids installing a Playwright dialog handler:
doing that would change the browser's automatic dialog-dismissal behavior.
"""
import json
import asyncio
import time
from uuid import uuid4


INSTALL = r"""(() => {
  const key = __KEY__, binding = __BINDING__;
  if (window[key]) return;
  const documentId = crypto.randomUUID(), pending = new Set();
  let sequence = 0, sent = 0, omitted = 0, closed = false;
  let windowStart = performance.now(), gapTimer = null;
  const reportGap = () => {
    if (closed || gapTimer !== null) return;
    gapTimer = setTimeout(() => {
      gapTimer = null;
      if (closed || !omitted) return;
      if (pending.size >= 64) { reportGap(); return; }
      const count = omitted; omitted = 0;
      transmit({kind:'capture_gap', count});
    }, 250);
  };
  const transmit = payload => {
    const p = window[binding]({...payload, document_id:documentId, document_sequence:++sequence, page_time_ms:Date.now()});
    pending.add(p); p.catch(()=>{}).finally(()=>pending.delete(p));
  };
  const emit = payload => {
    if (closed) return;
    // Local rate/pending bounds reset without any Python flush RPC.
    const now = performance.now();
    if (now-windowStart >= 250) { sent=0; windowStart=now; }
    if (sent >= 64 || pending.size >= 64) { omitted++; reportGap(); return; }
    sent++;
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
    if (records.length>200) { omitted+=records.length-200; reportGap(); }
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
    close() { closed=true;clearTimeout(gapTimer);observer.disconnect();for(const [t,h] of handlers) document.removeEventListener(t,h,true);delete window[key]; }
  }});
})();"""


class BrowserEvents:
    def __init__(self, max_events=64, *, debug_timings=None):
        self.max_events = max_events
        from .debug_timings import DebugTimings
        self.debug = debug_timings if debug_timings is not None else DebugTimings()
        self.tasks=set();self.max_tasks=128;self.loop=None;self.semaphore=None
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
        self.page_filter = None  # Optional trusted custody predicate; defaults unchanged.

    def _id(self, mapping, value, prefix):
        if value not in mapping: mapping[value] = f'{prefix}{len(mapping)+1}'
        return mapping[value]

    def _append(self, page, frame, payload, *, native=False):
        if self.closed or not isinstance(payload, dict): return
        if self.page_filter is not None and not self.page_filter(page): return
        allowed = {'page_announcement','text_appeared','control_state','input','change','invalid',
                   'submit','focus','capture_gap'}
        if not native and payload.get('kind') not in allowed: return
        self.sequence += 1
        if len(self.events) >= self.max_events:
            self.omitted += 1
            return
        fields = {'kind','text','truncated','tag','role','label','checked','value','attribute',
                  'previous','document_id','document_sequence','page_time_ms','count','url','dialog_type'}
        clean = {k: (v[:800] if isinstance(v,str) else v) for k,v in payload.items()
                 if k in fields and (v is None or type(v) in (str,int,bool))}
        self.events.append({**clean, 'sequence':self.sequence,
            'observed_monotonic':time.monotonic(), 'window':self.phase,
            'page':self._id(self.pages,page,'p'),
            'frame':self._id(self.frames,frame,'f') if frame else None,
            'source':'browser_event' if native else 'page_dom'})
        self.debug.record('feedback.event_received',time.monotonic(),kind=clean.get('kind'),page=self.pages[page],frame=self.frames.get(frame),delivery_window=self.phase)

    def _listen(self, emitter, event, callback):
        emitter.on(event, callback); self.listeners.append((emitter,event,callback))

    def _page(self, page, *, opened=False):
        # Attach listeners even to inactive tabs; delivery is custody-filtered.
        # A later tab switch must not require a synchronous observer sweep.
        if page in self.watched_pages: return
        self.watched_pages.add(page)
        self._id(self.pages,page,'p')
        if opened: self._append(page,None,{'kind':'page_opened','url':page.url},native=True)
        self._listen(page,'framenavigated', lambda f:self._append(page,f,{'kind':'navigation','url':f.url},native=True))
        self._listen(page,'close',lambda:self._append(page,None,{'kind':'page_closed'},native=True))
        self._listen(page,'framedetached',lambda f:self._append(page,f,{'kind':'frame_detached'},native=True))
        async def observe_dialogs():
            session=await self.context._impl_obj.new_cdp_session(page._impl_obj)
            self.sessions.append(session)
            # Do not install Playwright dialog handlers: preserve auto-dismiss.
            session.on('Page.javascriptDialogOpening',lambda e:self._append(page,None,
                {'kind':'dialog_opened','dialog_type':e.get('type'),'text':e.get('message')},native=True))
            session.on('Page.javascriptDialogClosed',lambda e:self._append(page,None,{'kind':'dialog_closed'},native=True))
            await session.send('Page.enable')
        self._schedule('dialog_observer_install',observe_dialogs,page=page)

    def _schedule(self,name,operation,*,page,frame=None):
        # Same Playwright owner loop; never a browser worker thread. Timeout only
        # abandons diagnostics, never dispatches/retries an agent action.
        if self.closed:return
        if len(self.tasks)>=self.max_tasks:
            self.errors.add('observer_install_queue_full');return
        queued=time.monotonic();page_id=self._id(self.pages,page,'p')
        frame_id=self._id(self.frames,frame,'f') if frame is not None else None
        async def run():
            start=None;error=None
            try:
                async with self.semaphore:
                    start=time.monotonic()
                    await asyncio.wait_for(operation(),timeout=.5)
            except asyncio.CancelledError:
                error='CancelledError';raise
            except Exception as exc:
                error=type(exc).__name__
                if not self.closed:self.errors.add(name+'_unavailable')
            finally:
                self.debug.record('feedback.'+name,queued,page=page_id,frame=frame_id,
                    queue_seconds=None if start is None else start-queued,error_type=error)
        task=self.loop.create_task(run());self.tasks.add(task)
        def done(task):
            self.tasks.discard(task)
            if not task.cancelled():task.exception()
        task.add_done_callback(done)

    def start(self, context):
        self.context=context
        self.loop=context._impl_obj._loop;self.semaphore=asyncio.Semaphore(4)
        context.expose_binding(self.binding, lambda source,payload:self._append(source['page'],source['frame'],payload))
        context.add_init_script(script=self.source)
        self._listen(context,'page',lambda page:self._page(page,opened=True))
        for page in context.pages:
            self._page(page)
            for frame in page.frames:
                self._schedule('initial_frame_install',lambda f=frame:f._impl_obj.evaluate(self.source),page=page,frame=frame)

    def drain(self):
        # Read only events already pushed to Python. Never evaluate/wait for a
        # frame here: late bindings are retained for a later decision, not forced
        # onto the inference critical path. A browser RPC elsewhere services the
        # owner event loop; no inference-only worker touches Playwright.
        started=time.monotonic()
        events=self.events
        if self.page_filter is not None:
            allowed={label for page,label in self.pages.items() if self.page_filter(page)}
            events=[e for e in events if e['page'] in allowed]
        result={'events':events, 'omitted':self.omitted, 'capture_warnings':sorted(self.errors),
                'delivery_scope':'Already delivered events only; late events may follow. Window labels denote Python delivery, not occurrence or action causality.'}
        self.events=[]; self.omitted=0; self.errors.clear()
        self.debug.record('feedback.drain',started,delivered=len(events),omitted=result['omitted'],pending_installs=len(self.tasks))
        return result

    def close(self, *, context_closing=False):
        self.closed=True
        for task in list(self.tasks):task.cancel()
        for emitter,event,callback in self.listeners:
            try: emitter.remove_listener(event,callback)
            except Exception: pass
        if context_closing:
            # Context destruction removes observers and CDP sessions. Do not
            # await JavaScript in a hung frame just to destroy it next.
            self.listeners.clear();self.sessions.clear()
            return
        for session in self.sessions:
            task=self.loop.create_task(session.detach())
            task.add_done_callback(lambda t:None if t.cancelled() else t.exception())
        if self.context is not None:
            for page in list(self.context.pages):
                for frame in list(page.frames):
                    try: frame.evaluate('(key) => window[key]?.close()',self.key)
                    except Exception: pass
