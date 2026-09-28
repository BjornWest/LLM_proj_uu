"""Integrated opt-in browser experiment. No normal runner or deployment imports.

One owner thread: action -> public readiness -> shallow view -> background full AX.
Only explicitly listed no-script HTTP origins may skip strict foreground rereads.
"""
from concurrent.futures import Future
from dataclasses import asdict
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'experiments/lazy_observation'))
sys.path.insert(0,str(ROOT/'experiments/readiness'))
from background import BackgroundBrowser, Observation, ObsoleteObservation
from intent_browser.readiness import Readiness, ReadinessSpec
from visual import capture_visual

REVISION=Path(__file__).with_name('revision.js').read_text()


def origin(url):
    parsed=urlsplit(url)
    return f'{parsed.scheme}://{parsed.netloc}'


class IntegratedBrowser(BackgroundBrowser):
    def __init__(self,setup,*,static_origins=(),capture_hook=None,document_spec=None):
        self.static_origins=frozenset(static_origins)
        self.document_spec=document_spec or ReadinessSpec(
            scope='body',condition={'kind':'count','selector':'body','expected':1})
        self.document_spec.validate()
        self.navigation_responses={}
        self.navigation_policy=''
        self.receipts=[]
        self.last_readiness=None
        def initialize(page):
            page.add_init_script(REVISION);page.evaluate(REVISION)
            self.readiness=Readiness(page)
            page.on('response',self._response)
            page.on('framenavigated',self._navigation)
            setup(page)
        super().__init__(initialize,capture_hook=capture_hook,strict=True)

    def _response(self,response):
        if response.request.is_navigation_request() and response.frame==self.page.main_frame:
            self.navigation_responses[response.url]=response.headers.get('content-security-policy','')

    def _navigation(self,frame):
        if frame==self.page.main_frame:
            # Bind policy at document navigation, not merely by a historically
            # visited URL. Same-document/history transitions without a matching
            # response conservatively lose the fast-path qualification.
            self.navigation_policy=self.navigation_responses.pop(frame.url,'')
            self.navigation_responses.clear()

    def _stamp(self):
        state=self.page.evaluate('()=>__intentObservationRevision.read()')
        policy=self.navigation_policy
        directives={}
        for directive in policy.split(';'):
            parts=directive.strip().split()
            if parts:directives.setdefault(parts[0],parts[1:])
        scripts=directives.get('script-src',directives.get('default-src'))
        # Element/attribute overrides can permit code despite script-src 'none'.
        no_scripts=(scripts==["'none'"] and
                    directives.get('script-src-elem',scripts)==["'none'"] and
                    directives.get('script-src-attr',scripts)==["'none'"])
        state['fast_eligible']=(origin(self.page.url) in self.static_origins and no_scripts and
                                not any(state[k] for k in ['unsupported','resourcesPending','animations']))
        return state

    def _requires_full_validation(self,snapshot):
        return not snapshot['stamp']['fast_eligible']

    def _freshness_label(self,snapshot):
        return ('declared_no_script_origin_revision_checked' if snapshot['stamp']['fast_eligible']
                else 'full_foreground_AX_equal_at_validation')

    def _settle_document(self):
        self.page.wait_for_load_state('domcontentloaded',timeout=self.document_spec.timeout_ms)
        ticket=self.readiness.arm(self.document_spec)
        result=self.readiness.wait(ticket)
        self.last_readiness=result
        self._record('document_readiness',**result)
        if result['status']!='ready':
            raise ObsoleteObservation('New document public readiness not established: '+result['status'])
        return result

    def _observe(self,epoch,initial,ready,url,reload):
        try:
            self.setup_future.result();self._current(epoch)
            if url is not None:self.page.goto(url,wait_until='domcontentloaded',timeout=self.document_spec.timeout_ms)
            elif reload:self.page.reload(wait_until='domcontentloaded',timeout=self.document_spec.timeout_ms)
            self._settle_document()
        except BaseException as error:
            if not initial.done():initial.set_exception(error)
            if not ready.done():ready.set_exception(error)
            return
        super()._observe(epoch,initial,ready,None,False)

    def step(self,observation,ref,*,operation='click',text=None,spec=None):
        """Returns a Future of {receipt, observation}; consume observation.initial
        while full AX is prefetched. A pending/failed wait produces receipt only.
        """
        spec=spec or self.document_spec
        spec.validate()
        result=Future()
        self.pool.submit(self._step,observation,ref,operation,text,spec,result)
        return result

    def _step(self,observation,ref,operation,text,spec,result):
        started=time.perf_counter();ticket=None
        receipt=dict(operation=operation,ref=ref,readiness=None,task_success=None)
        try:
            self.setup_future.result()
            ticket=self.readiness.arm(spec)
            action=super()._act(observation,ref,operation,text,started)
            receipt['action']=action
            outcome=self.readiness.wait(ticket)
            # Destroyed old watchers are not a reason to replay a navigation.
            current=self.page.evaluate('globalThis.__intentReadinessV1?.documentId')
            if current!=ticket['document_id']:
                receipt['prior_document_readiness']=outcome
                outcome=self._settle_document()
                receipt['document_replaced']=True
            else:receipt['document_replaced']=False
            receipt['readiness']=outcome
            receipt['action_and_wait_seconds']=time.perf_counter()-started
            self.receipts.append(receipt);self._record('step_receipt',**receipt)
            if outcome['status']!='ready':
                result.set_result(dict(receipt=receipt,observation=None));return
            epoch=self._reserve_epoch();initial,ready=Future(),Future()
            observation=Observation(initial,ready,epoch)
            result.set_result(dict(receipt=receipt,observation=observation))
            self._observe(epoch,initial,ready,None,False)
        except BaseException as error:
            if ticket:self.readiness.cancel(ticket,'step_error')
            receipt['error']=dict(type=type(error).__name__,message=str(error))
            self.receipts.append(receipt);self._record('step_error',**receipt)
            if not result.done():result.set_exception(error)

    def screenshot(self,observation,path,*,scope='body',timeout_ms=2000):
        return self.pool.submit(self._screenshot,observation,path,scope,timeout_ms)

    def _screenshot(self,observation,path,scope,timeout_ms):
        self._snapshot(observation)
        stamp=self._stamp()
        result=capture_visual(self.page,path,scope=scope,timeout_ms=timeout_ms,allow_uncertain=True)
        if result['status']=='ready' and self._stamp()!=stamp:
            result['status']='unknown';result['reason']='page_revision_changed_during_capture'
        self._record('screenshot_finished',status=result['status'],saved=result['screenshot_saved'])
        return result

    def _cleanup(self):
        if getattr(self,'readiness',None):self.readiness.close()
        super()._cleanup()
