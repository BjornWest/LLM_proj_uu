"""Opt-in, single-page event-driven readiness; not installed by the normal runner.

Arm before the action. Observe public conditions or an explicit application
operation lifecycle. Readiness never means task success and never replays actions.
All methods use the calling thread's synchronous Playwright page.
"""
from dataclasses import asdict, dataclass
import time


INSTALL = r"""(() => {
  const key = '__intentReadinessV1';
  if (globalThis[key]) {
    if (globalThis[key].version !== 1) throw Error('Readiness API collision');
    return;
  }
  // getRandomValues also works on plain-HTTP benchmark origins, unlike randomUUID.
  const uid = () => Array.from(crypto.getRandomValues(new Uint32Array(4)),
    n=>n.toString(16).padStart(8,'0')).join('');
  const documentId = uid();
  const operations = new Map(), subscribers = new Set(), waiters = new Map();
  const notify = event => { for (const fn of [...subscribers]) fn(event); };
  const app = Object.freeze({
    begin(scope) {
      if (typeof scope !== 'string' || !scope || scope.length > 128) throw Error('Invalid operation scope');
      if (operations.size >= 1024) throw Error('Too many pending application operations');
      const id = uid();
      operations.set(id, scope); notify({kind:'begin', id, scope}); return id;
    },
    end(id, ok=true) {
      if (typeof ok !== 'boolean') throw Error('ok must be boolean');
      if (!operations.has(id)) return false;
      const scope = operations.get(id); operations.delete(id);
      notify({kind:ok?'end':'failed', id, scope}); return true;
    }
  });
  const api = {
    version:1, documentId, app,
    arm(config) {
      if (waiters.size >= 16) throw Error('Too many active readiness waits');
      const id = uid(), started = performance.now();
      let dispatched=false, finished=false, result, resolve;
      let deadline, quiet, frame1, frame2, observer;
      let changes=0, conditionChecks=0, seen=false, failed=false;
      const pending = new Set();
      if (config.signal_scope) for (const [key,scope] of operations)
        if (scope === config.signal_scope) { pending.add(key); seen=true; }
      const root = () => {
        const roots = document.querySelectorAll(config.scope);
        return roots.length===1 ? roots[0] : null;
      };
      if (!root()) throw Error('Readiness scope must identify exactly one element');
      const busy = () => {
        const r=root();
        return !r || !!r.closest('[aria-busy="true"]') || !!r.querySelector('[aria-busy="true"]');
      };
      const condition = () => {
        conditionChecks++;
        const c=config.condition, r=root();
        if (!c || !r) return false;
        const matches=Array.from(r.querySelectorAll(c.selector));
        if (r.matches(c.selector)) matches.unshift(r);
        if (c.kind==='count') return matches.length===c.expected;
        if (matches.length!==1) return false;
        const el=matches[0];
        if (c.kind==='checked') return typeof el.checked==='boolean' && el.checked===c.expected;
        if (c.kind==='text') return el.textContent.trim()===c.expected;
        if (c.kind==='attribute') return el.getAttribute(c.name)===c.expected;
        return false;
      };
      // Syntax is checked before dispatch. An initially satisfied condition is
      // not proof that the pending action has already completed.
      let initialCondition;
      try { initialCondition=config.condition ? condition() : false; }
      catch(error) { throw Error('Invalid public condition selector: '+error.message); }
      const promise = new Promise(r=>resolve=r);
      const clear = () => {
        clearTimeout(deadline);clearTimeout(quiet);
        cancelAnimationFrame(frame1);cancelAnimationFrame(frame2);
        observer?.disconnect();subscribers.delete(onSignal);
        document.removeEventListener('input',onInput,true);
        document.removeEventListener('change',onInput,true);
      };
      const finish = (status,reason) => {
        if (finished) return;
        finished=true;clear();
        result={status,reason,document_id:documentId,elapsed_ms:performance.now()-started,
          observed_changes:changes,condition_checks:conditionChecks,
          pending_operations:pending.size,observed_operation:seen,
          initial_condition:initialCondition,task_success:null};
        resolve(result);
      };
      const satisfied = () => {
        if (window.frames.length || busy()) return false;
        if (config.condition && !condition()) return false;
        if (config.signal_scope && (!seen || pending.size)) return false;
        return !!(config.condition || config.signal_scope);
      };
      const check = () => {
        if (!dispatched || finished) return;
        if (window.frames.length) { finish('unknown','unsupported_frames'); return; }
        if (failed) { finish('failed','application_operation_failed'); return; }
        if (satisfied()) {
          if (frame1 || frame2) return;
          frame1=requestAnimationFrame(()=>{
            frame1=null;
            frame2=requestAnimationFrame(()=>{
              frame2=null;
              if (satisfied()) finish('ready',config.condition?'public_condition_met':'application_operation_completed');
            });
          });
        }
        if (!config.condition && !config.signal_scope && !busy()) {
          clearTimeout(quiet);
          quiet=setTimeout(()=>{if(!busy())finish('unknown','region_quiet_without_completion_contract');},config.quiet_ms);
        }
      };
      function onSignal(e) {
        if (e.scope!==config.signal_scope || finished) return;
        if (e.kind==='begin') { pending.add(e.id);seen=true; }
        else if (pending.has(e.id)) { pending.delete(e.id);if(e.kind==='failed')failed=true; }
        check();
      }
      function onInput(e) { if (root()?.contains(e.target)) { changes++;check(); } }
      observer=new MutationObserver(records=>{
        if (window.frames.length) { check();return; }
        const r=root();
        if (!r || records.some(x=>r.contains(x.target) ||
            [...x.addedNodes,...x.removedNodes].some(n=>n===r || n.contains?.(r)))) {
          changes++;check();
        }
      });
      observer.observe(document,{subtree:true,childList:true,characterData:true,attributes:true});
      document.addEventListener('input',onInput,true);
      document.addEventListener('change',onInput,true);
      subscribers.add(onSignal);
      waiters.set(id,{
        promise,
        dispatch() {
          if (dispatched || finished) return;
          dispatched=true;
          deadline=setTimeout(()=>{
            if (window.frames.length) { finish('unknown','unsupported_frames');return; }
            const missing=!root(), isPending=pending.size>0 || busy();
            finish(missing?'unknown':isPending?'pending':'unknown',missing?'scope_unavailable':isPending?'deadline_with_pending_work':'deadline_without_completion_evidence');
          },config.timeout_ms);
          check();
        },
        cancel:reason=>finish('cancelled',reason)
      });
      return {id,document_id:documentId};
    },
    async wait(ticket) {
      if (ticket.document_id!==documentId || !waiters.has(ticket.id)) throw Error('Unknown readiness ticket');
      const waiter=waiters.get(ticket.id);waiter.dispatch();
      try { return await waiter.promise; }
      finally {waiters.delete(ticket.id);}
    },
    cancel(ticket,reason='cancelled') {
      if (ticket.document_id!==documentId) return false;
      const waiter=waiters.get(ticket.id);if(!waiter)return false;
      waiter.cancel(reason);waiters.delete(ticket.id);return true;
    },
    close() {
      for(const waiter of waiters.values())waiter.cancel('readiness_closed');
      waiters.clear();
    },
    diagnostics() { return {waiters:waiters.size,subscribers:subscribers.size,pending_operations:operations.size}; }
  };
  Object.defineProperty(globalThis,key,{value:Object.freeze(api),configurable:false});
})();"""


@dataclass(frozen=True)
class ReadinessSpec:
    scope: str = 'body'
    condition: dict | None = None
    signal_scope: str | None = None
    timeout_ms: int = 2000
    quiet_ms: int = 50

    def validate(self):
        if not isinstance(self.scope, str) or not self.scope or len(self.scope)>1000:
            raise ValueError('scope must be a nonempty CSS selector of at most 1000 characters')
        for name, minimum, maximum in [('timeout_ms',1,60000),('quiet_ms',1,1000)]:
            value=getattr(self,name)
            if type(value) is not int or not minimum<=value<=maximum:
                raise ValueError(f'{name} must be an integer in [{minimum}, {maximum}]')
        if self.signal_scope is not None and (not isinstance(self.signal_scope,str) or not 1<=len(self.signal_scope)<=128):
            raise ValueError('signal_scope must be a nonempty string of at most 128 characters')
        if self.condition is not None:
            c=self.condition
            if type(c) is not dict or c.get('kind') not in ('checked','text','attribute','count'):
                raise ValueError('unsupported public condition')
            allowed={'kind','selector','expected'} | ({'name'} if c['kind']=='attribute' else set())
            if set(c)!=allowed or not isinstance(c['selector'],str) or not 1<=len(c['selector'])<=1000:
                raise ValueError('invalid public condition fields/selector')
            value=c['expected']
            if c['kind']=='checked' and type(value) is not bool:raise ValueError('checked requires bool')
            if c['kind']=='count' and (type(value) is not int or value<0):raise ValueError('count requires nonnegative int')
            if c['kind']=='text' and not isinstance(value,str):raise ValueError('text requires string')
            if c['kind']=='attribute' and (not isinstance(c['name'],str) or not c['name'] or not (value is None or isinstance(value,str))):
                raise ValueError('attribute requires name and string/null expected value')
        return asdict(self)


class Readiness:
    def __init__(self,page):
        self.page=page
        page.add_init_script(INSTALL)
        page.evaluate(INSTALL)

    def arm(self,spec:ReadinessSpec):
        config=spec.validate()
        if len(self.page.frames)!=1:
            raise ValueError('Readiness prototype supports one main frame only')
        return self.page.evaluate('(config)=>__intentReadinessV1.arm(config)',config)

    def cancel(self,ticket,reason='cancelled'):
        try:return self.page.evaluate('([t,r])=>__intentReadinessV1.cancel(t,r)',[ticket,reason])
        except Exception:return False # A destroyed document cannot retain this waiter.

    def wait(self,ticket):
        from playwright.sync_api import Error
        start=time.perf_counter()
        try:
            if len(self.page.frames)!=1:
                self.cancel(ticket,'unsupported_frames')
                return dict(status='unknown',reason='unsupported_frames',task_success=None,
                            wait_seconds=time.perf_counter()-start)
            document=self.page.evaluate('globalThis.__intentReadinessV1?.documentId')
            if document!=ticket['document_id']:
                return dict(status='unknown',reason='document_changed',task_success=None,
                            wait_seconds=time.perf_counter()-start)
            result=self.page.evaluate('(ticket)=>__intentReadinessV1.wait(ticket)',ticket)
        except Error as error:
            self.cancel(ticket,'observation_interrupted')
            result=dict(status='unknown',reason='browser_wait_interrupted',task_success=None,
                        error_type=type(error).__name__,error=str(error)[:1000])
        return {**result,'wait_seconds':time.perf_counter()-start}

    def perform(self,action,spec:ReadinessSpec):
        """Run the caller's native action once; preserve its errors, never retry."""
        ticket=self.arm(spec);start=time.perf_counter()
        try:action_result=action()
        except BaseException:
            self.cancel(ticket,'action_error')
            raise
        action_seconds=time.perf_counter()-start
        readiness=self.wait(ticket)
        return dict(action_result=action_result,action_seconds=action_seconds,readiness=readiness)

    def close(self):
        try:self.page.evaluate('()=>globalThis.__intentReadinessV1?.close()')
        except Exception:pass
