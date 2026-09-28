"""Version-pinned native extraction: overlapped visibility waits and RPC deadline.

No global BrowserGym/Playwright patch. Each capture owns its connection wrapper;
all browser calls remain on the original sync owner thread. Deadline aborts capture,
not a browser action. Cancellation cannot undo a command already sent to Chromium.
"""
import asyncio
from contextlib import contextmanager
import hashlib
from importlib.metadata import version
import pkgutil
import time
from types import FunctionType
from uuid import uuid4
from playwright.async_api import Frame as AsyncFrame

from browsergym.core.env import BrowserEnv
from browsergym.core import observation as core
from .cdp_json import extract_json

CAPTURE_SECONDS=5.0
TARGET_SECONDS=1.0
CHILD_RPC_SECONDS=0.5
OWNER_CONCURRENCY=8
_SKIPPED=object()


def owner_lookup_invalidation(exc, index):
    """Only known Playwright owner/parent-document races, not arbitrary errors."""
    from .batching import DocumentScanInvalidated
    if not isinstance(exc,core.playwright.sync_api.Error):return None
    text=str(exc)
    if 'Unable to adopt element handle from a different document' in text:
        reason='frame_owner_document_replaced'
    elif any(message in text for message in ('Frame has been detached','Frame was detached')):
        reason='frame_owner_detached'
    else:return None
    return DocumentScanInvalidated({'reason':reason,'phase':'frame_owner_lookup',
        'child_index':index,'native_error':text[:2000],
        'scope':'Discard this observation attempt; never replay a browser action'})
SOURCE=pkgutil.get_data('browsergym.core.observation','javascript/frame_mark_elements.js').decode()
UNMARK=pkgutil.get_data('browsergym.core.observation','javascript/frame_unmark_elements.js').decode()
SOURCE_HASH='6ecfbba89d756c37874bdf692e4bf24126459ab79f9120c1f053305b7ba2978a'


def marker_source():
    if version('browsergym-core')!='0.14.3' or hashlib.sha256(SOURCE.encode()).hexdigest()!=SOURCE_HASH:
        raise RuntimeError('Native capture requires reviewed BrowserGym marker source')
    start=SOURCE.replace('async ([parent_bid, bid_attr_name, tags_to_mark]) => {',
        'async ([parent_bid, bid_attr_name, tags_to_mark, job_key]) => {',1)
    start=start.replace('warning_msgs = new Array();','const warning_msgs = new Array();',1)
    a=start.index('    // wait for all elements to be visited for visibility')
    b=start.index('    return warning_msgs;',a)+len('    return warning_msgs;')
    return start[:a]+'''    const job = {cancel: () => intersection_observer.disconnect()};
    job.promise = (async () => {
        let visibility_marking_timeout = 1000;
        try { await until(() => elems_to_be_visited.size == 0, visibility_marking_timeout); }
        catch { warning_msgs.push(`Frame marking: not all elements have been visited by the intersection_observer after ${visibility_marking_timeout} ms`); }
        finally { intersection_observer.disconnect(); }
        return warning_msgs;
    })();
    globalThis[job_key] = job;
    return [];
''' +start[b:]


START=marker_source()
FINISH='''async key => {
 const job=globalThis[key]; if(!job)throw new Error('Capture job document replaced');
 try { return await job.promise; } finally { job.cancel(); delete globalThis[key]; }
}'''
CANCEL='key => { const job=globalThis[key]; if(job){job.cancel();delete globalThis[key];} }'


class CaptureDeadlineExceeded(RuntimeError):
    def __init__(self,detail):
        self.document_scan_detail=detail
        message={'browser_guard':'Browser guard exceeded its time budget; no action authorized',
                 'browser_cleanup':'Browser cleanup exceeded its time budget'}.get(detail.get('scope'),
                 'Observation capture exceeded its time budget; no observation delivered')
        super().__init__(message)


class CaptureBudget:
    def __init__(self,page,trace,seconds=CAPTURE_SECONDS,*,scope='observation_capture',event_prefix='native_capture',enforce=True):
        self.page,self.trace,self.seconds=page,trace,seconds
        self.scope,self.event_prefix=scope,event_prefix
        self.enforce=enforce;self.overrun_reported=False
        self.started=time.monotonic();self.deadline=self.started+seconds
        self.phase='document_scan';self.rows=[];self.pending=[];self.needs_unmark=False;self.prefixes={};self.marked_frames=[]

    def check(self):
        if time.monotonic()>=self.deadline:
            if not self.enforce:
                if not self.overrun_reported:
                    self.overrun_reported=True
                    self.trace.event(self.event_prefix+'_budget_overrun',scope=self.scope,phase=self.phase,
                        threshold_seconds=self.seconds,elapsed_seconds=time.monotonic()-self.started,
                        enforced=False,action='Continue waiting for diagnosis; no cancellation or retry')
                return
            raise CaptureDeadlineExceeded({'reason':'capture_deadline_exceeded','phase':self.phase,
                'scope':self.scope,
                'limit_seconds':self.seconds,'elapsed_seconds':time.monotonic()-self.started})

    @contextmanager
    def rpc_deadline(self):
        # Private API intentionally version-pinned and regression-tested. Avoid
        # signal alarms (unsafe across the sync greenlet) and cross-thread Page use.
        if version('playwright')!='1.44.0':
            raise RuntimeError('Review Playwright connection cancellation before capture adoption')
        connection=self.page._impl_obj._connection
        if not self.enforce:
            # On the existing Playwright loop: emit even while an awaited RPC is
            # still pending. This never calls Playwright from a second thread.
            timer=connection._loop.call_later(max(0,self.deadline-time.monotonic()),self.check)
            try:yield self
            finally:timer.cancel();self.check()
            return
        original=connection.wrap_api_call
        async def bounded(cb,*args,**kwargs):
            self.check()
            prior=set(connection._callbacks)
            try:return await asyncio.wait_for(original(cb,*args,**kwargs),self.deadline-time.monotonic())
            except asyncio.TimeoutError:
                # The browser operation can outlive our cancelled await. Leave
                # protocol IDs registered for its reply, but consume eventual
                # exceptions (including browser teardown) on abandoned futures.
                for key in set(connection._callbacks)-prior:
                    future=connection._callbacks[key].future
                    future.add_done_callback(lambda f: None if f.cancelled() else f.exception())
                self.check()
                raise
        connection.wrap_api_call=bounded
        try:yield self
        finally:connection.wrap_api_call=original

    def timed(self,name,fn,**extra):
        previous=self.phase;self.phase=name;started=time.monotonic();error=None
        self.trace.event(self.event_prefix+'_phase_started',phase=name,**extra)
        try:
            self.check();value=fn();self.check();return value
        except Exception as exc:error=f'{type(exc).__name__}: {exc}';raise
        finally:
            row={'phase':name,'seconds':time.monotonic()-started,'error':error,**extra}
            self.rows.append(row);self.trace.event(self.event_prefix+'_phase_completed',**row);self.phase=previous

    def child_call(self,frame,name,fn,**extra):
        if frame in self.quarantined:return _SKIPPED
        local=CaptureBudget(self.page,self.trace,seconds=CHILD_RPC_SECONDS,enforce=self.enforce)
        try:
            with local.rpc_deadline():return self.timed(name,fn,**extra)
        except CaptureDeadlineExceeded:
            self.check()  # Aggregate exhaustion is still fatal.
            self.quarantined[frame]={'reason':'child_rpc_deadline','phase':name}
            self.trace.event('native_frame_quarantined',phase=name,seconds=CHILD_RPC_SECONDS,
                scope='Excluded for this Frame lifetime; cancelled RPC may complete later',**extra)
            return _SKIPPED

    def owner_attributes(self,children):
        """Overlap read-only sibling owner checks on the Playwright owner loop.

        Marking remains ordered. Preserve frame_element/content_frame/sandbox/BID
        checks; neither skip an inspected child nor evaluate a scripts-disabled
        child. Per-child deadlines start after acquiring the bounded slot.
        """
        if not children:return []
        connection=self.page._impl_obj._connection
        prior=set(connection._callbacks)
        async def inspect_all():
            slots=asyncio.Semaphore(OWNER_CONCURRENCY)
            async def inspect(child,index):
                if child in self.quarantined:return _SKIPPED
                async with slots:
                    self.check();started=time.monotonic();error=None
                    self.trace.event('native_capture_phase_started',phase='frame_owner_lookup',child_index=index)
                    async def read():
                        frame=AsyncFrame(child._impl_obj)
                        element=await frame.frame_element()
                        content=await element.content_frame()
                        if content is None or content._impl_obj is not child._impl_obj:return None
                        return await element.evaluate("el=>({sandbox:el.getAttribute('sandbox'),bid:el.getAttribute('bid')})")
                    try:
                        return (await asyncio.wait_for(read(),CHILD_RPC_SECONDS)) if self.enforce else await read()
                    except asyncio.TimeoutError:
                        self.check()
                        self.quarantined[child]={'reason':'owner_lookup_deadline'}
                        error='owner_lookup_deadline'
                        return _SKIPPED
                    except BaseException as exc:
                        error=type(exc).__name__
                        invalidation=owner_lookup_invalidation(exc,index)
                        if invalidation is not None:raise invalidation from exc
                        raise
                    finally:
                        self.trace.event('native_capture_phase_completed',phase='frame_owner_lookup',
                            child_index=index,seconds=time.monotonic()-started,error=error)
            results=await asyncio.gather(*(inspect(child,i) for i,child in enumerate(children)),return_exceptions=True)
            from .batching import DocumentScanInvalidated
            # A coincident transport/programming failure must not be hidden by
            # an earlier sibling's recoverable document race.
            for result in results:
                if isinstance(result,BaseException) and not isinstance(result,DocumentScanInvalidated):raise result
            for result in results:
                if isinstance(result,BaseException):raise result
            return results
        async def bounded():
            if not self.enforce:return await inspect_all()
            try:return await asyncio.wait_for(inspect_all(),max(0,self.deadline-time.monotonic()))
            except asyncio.TimeoutError:
                self.check();raise
        try:
            return self.timed('frame_owner_batch',lambda:self.page._sync(bounded()),
                children=len(children),concurrency=OWNER_CONCURRENCY)
        finally:
            # A cancelled await cannot retract a read already sent to Chromium.
            for key in set(connection._callbacks)-prior:
                future=connection._callbacks[key].future
                future.add_done_callback(lambda f:None if f.cancelled() else f.exception())

    def mark(self,page,tags_to_mark='standard_html',lenient=False):
        self.needs_unmark=True
        key='__intent_capture_'+uuid4().hex;frames=[]
        scoped=hasattr(self,'quarantined')
        def visit(frame,prefix):
            self.prefixes[frame]=prefix
            if scoped and frame in self.quarantined:return
            self.marked_frames.append(frame)
            self.pending.append((frame,key));index=len(frames);frames.append(frame)
            fn=lambda:frame.evaluate(START,[prefix,'bid',tags_to_mark,key])
            if scoped and frame is not page.main_frame:
                if self.child_call(frame,'frame_mark_start',fn,frame_index=index) is _SKIPPED:return
            else:self.timed('frame_mark_start',fn,frame_index=index)
            children=[child for child in frame.child_frames if not child.is_detached()]
            owners=self.owner_attributes(children) if scoped else None
            for child_index,child in enumerate(children):
                self.check()
                if child.is_detached():continue
                def inspect():
                    element=child.frame_element()
                    if element.content_frame()!=child:return None
                    return element.evaluate("el=>({sandbox:el.getAttribute('sandbox'),bid:el.getAttribute('bid')})")
                # Parent-frame inspection can identify an already quarantined child
                # without evaluating JS inside that child again.
                if scoped:
                    attrs=owners[child_index]
                    if attrs is _SKIPPED:continue
                else:attrs=inspect()
                if attrs is None:
                    self.trace.event('native_capture_frame_skipped',reason='upstream_problematic_frame');continue
                if attrs['sandbox'] is not None and 'allow-scripts' not in attrs['sandbox'].split():
                    self.trace.event('native_capture_frame_skipped',reason='upstream_scripts_sandbox');continue
                if attrs['bid'] is None:
                    if lenient:
                        self.trace.event('native_capture_frame_skipped',reason='upstream_lenient_missing_bid');continue
                    raise core.MarkingError('Cannot mark a child frame without a bid')
                visit(child,attrs['bid'])
        visit(page.main_frame,'')
        for i,frame in enumerate(frames):
            fn=lambda:frame.evaluate(FINISH,key)
            # Visibility promises normally settle within1s concurrently. Give
            # finish its native allowance; bound unexpected RPC stalls separately.
            if scoped and frame is not page.main_frame:
                if frame in self.quarantined:continue
                local=CaptureBudget(self.page,self.trace,seconds=1.1,enforce=self.enforce)
                try:
                    with local.rpc_deadline():warnings=self.timed('frame_visibility_finish',fn,frame_index=i)
                except CaptureDeadlineExceeded:
                    self.check();self.quarantined[frame]={'reason':'visibility_rpc_deadline'};continue
            else:warnings=self.timed('frame_visibility_finish',fn,frame_index=i)
            for message in warnings:self.trace.event('native_capture_warning',frame_index=i,message=message)
        self.pending=[p for p in self.pending if p[1]!=key]

    def scoped_unmark(self,page):
        # Marking already established owner/BID/sandbox eligibility. Only clean
        # frames we actually marked; no repeated owner lookups per child and no
        # JavaScript in newly attached or scripts-disabled frames. Same upstream
        # cleanup body, including shadow DOM. Quarantined late RPCs stay excluded.
        for frame in dict.fromkeys(self.marked_frames):
            if frame.is_detached() or frame in self.quarantined:continue
            try:
                fn=lambda:frame.evaluate(UNMARK)
                if frame is page.main_frame:fn()
                else:self.child_call(frame,'frame_cleanup',fn)
            except core.playwright.sync_api.Error as exc:
                if not any(msg in str(exc) for msg in ('Frame was detached','Frame has been detached')):raise
        self.marked_frames.clear()

    def cleanup_failed(self):
        # Separate short cleanup budget. Never continue the episode after timeout;
        # a cancelled RPC can still complete in Chromium. Normal teardown follows.
        if not self.pending and not self.needs_unmark:return True
        cleanup=CaptureBudget(self.page,self.trace,seconds=1.0)
        completed=True
        try:
            with cleanup.rpc_deadline():
                for frame,key in self.pending:
                    cleanup.check()
                    if not frame.is_detached() and frame not in getattr(self,'quarantined',{}):frame.evaluate(CANCEL,key)
                if self.needs_unmark:
                    if hasattr(self,'quarantined'):self.scoped_unmark(self.page)
                    else:core._post_extract(self.page)
        except Exception as exc:
            completed=False
            self.trace.event('native_capture_cleanup_failed',error=f'{type(exc).__name__}: {exc}')
        finally:self.pending.clear();self.needs_unmark=False
        return completed


def capture_native(view,budget,*,screenshots=True):
    """Clone only function globals; preserve native observation/retry logic."""
    original=BrowserEnv._get_obs
    scope=dict(original.__globals__)
    for name in ('_pre_extract','_post_extract','extract_dom_snapshot','extract_merged_axtree',
                 'extract_focused_element_bid','extract_dom_extra_properties','extract_screenshot'):
        fn=(budget.mark if name=='_pre_extract' else budget.scoped_unmark
            if name=='_post_extract' and hasattr(budget,'quarantined') else scope[name])
        def measured(*a,_name=name,_fn=fn,**kw):
            call=(lambda:extract_json(_fn,*a,**kw)) if _name in (
                'extract_dom_snapshot','extract_merged_axtree') else (lambda:_fn(*a,**kw))
            result=budget.timed(_name,call)
            if _name=='_post_extract':budget.needs_unmark=False
            return result
        scope[name]=measured
    if not screenshots:
        scope['extract_screenshot']=lambda page:None
    capture=FunctionType(original.__code__,scope,original.__name__,original.__defaults__,original.__closure__)
    return capture(view)
