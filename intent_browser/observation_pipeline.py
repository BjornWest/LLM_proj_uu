"""Opt-in BrowserGym 0.14.3 observation pipeline, one browser-owning thread.

A shallow public preview is NOT installed in the full AX index. Completion may
run in a separately opted-in model thread while the browser owner captures full
AX. Unsupported pages retain native BrowserGym extraction. No task state is read.
"""
from concurrent.futures import ThreadPoolExecutor
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass, field, asdict
from importlib.metadata import version
from pathlib import Path
from urllib.parse import urlsplit
import hashlib
import json
import time

from .cdp_json import send_json, capture_json
from .readiness import Readiness, ReadinessSpec

REVISION_PATH = Path(__file__).with_name('observation_revision.js')


def origin(url):
    p = urlsplit(url)
    return f'{p.scheme}://{p.netloc}'


def partial(obs):
    return obs.get('observation_capture', {}).get('coverage') == 'partial'


def ax_node_signature(node):
    """Only CDP's regenerated negative layout IDs are nonsemantic here.

    Preserve every public field, real DOM identity, child count and ordering.
    Full raw records (including the synthetic IDs) remain in trace artifacts.
    """
    value=deepcopy(node)
    def stable(identifier):
        return '<synthetic-layout-id>' if isinstance(identifier,str) and identifier.startswith('-') and identifier[1:].isdigit() else identifier
    for key in ('nodeId','parentId'):
        if key in value:value[key]=stable(value[key])
    if 'childIds' in value:value['childIds']=[stable(i) for i in value['childIds']]
    return json.dumps(value,sort_keys=True,ensure_ascii=False)


@dataclass(frozen=True)
class ObservationPipelineConfig:
    static_origins: tuple[str, ...]
    shallow_depth: int = 1
    trace_screenshots: bool = True
    readiness_by_action: dict = field(default_factory=dict)
    readiness_contract: str | None = None
    full_capture_only: bool = False
    dynamic_preview: bool = False
    preview_node_limit: int = 64
    preview_bids: bool = True
    targeted_actions: bool = False
    agent_custody: bool = False
    decision_capture: str = 'shallow_preview'

    def __post_init__(self):
        if type(self.agent_custody) is not bool:raise ValueError('agent_custody must be boolean')
        if self.decision_capture not in ('shallow_preview','budgeted_overview'):
            raise ValueError('decision_capture must be shallow_preview or budgeted_overview')
        if self.decision_capture=='budgeted_overview' and not (self.dynamic_preview and self.agent_custody):
            raise ValueError('Budgeted decision capture requires dynamic decision capture with agent custody')
        if self.agent_custody and not self.full_capture_only:
            raise ValueError('Agent custody requires native full-capture backing')
        if type(self.targeted_actions) is not bool:raise ValueError('targeted_actions must be boolean')
        if self.targeted_actions and (not self.dynamic_preview or self.trace_screenshots):
            raise ValueError('Targeted actions require dynamic_preview and trace_screenshots=False')
        if type(self.preview_bids) is not bool:raise ValueError('preview_bids must be boolean')
        if type(self.dynamic_preview) is not bool:raise ValueError('dynamic_preview must be boolean')
        if self.dynamic_preview and not self.full_capture_only:
            raise ValueError('Dynamic preview requires native full-capture backing')
        if type(self.preview_node_limit) is not int or not 1 <= self.preview_node_limit <= 128:
            raise ValueError('preview_node_limit must be 1..128')
        if type(self.full_capture_only) is not bool:raise ValueError('full_capture_only must be boolean')
        if self.full_capture_only and (self.static_origins or self.readiness_by_action):
            raise ValueError('Full-capture mode does not accept static origins or custom action readiness')
        if (not self.static_origins and not self.full_capture_only) or any(origin(u) != u or urlsplit(u).scheme not in ('http','https') for u in self.static_origins):
            raise ValueError('Pipeline requires explicit HTTP(S) origins without paths')
        if type(self.shallow_depth) is not int or not 1 <= self.shallow_depth <= 5:
            raise ValueError('shallow_depth must be 1..5')
        if type(self.trace_screenshots) is not bool:raise ValueError('trace_screenshots must be boolean')
        if self.readiness_by_action and not self.readiness_contract:
            raise ValueError('Explicit application waits require a named readiness_contract')
        from .actions import ACTION_NAMES, NAVIGATION_NAMES, VISION_ACTION_NAMES
        for name,spec in self.readiness_by_action.items():
            if name not in (*ACTION_NAMES,*NAVIGATION_NAMES,*VISION_ACTION_NAMES) or not isinstance(spec,ReadinessSpec):
                raise ValueError('Invalid action readiness contract')
            spec.validate()

    def describe(self):
        return {**asdict(self), 'version':'browsergym-progressive-v1',
            'revision_sha256':hashlib.sha256(REVISION_PATH.read_bytes()).hexdigest(),
            'fast_path':('unmarked AX decision read with budgeted overview; background full capture; targeted checks; final observation deferred'
                         if self.decision_capture=='budgeted_overview' and self.targeted_actions else
                         'targeted main-document action checks; final batch observation deferred to fresh decision preview' if self.targeted_actions else
                         'opt-in shallow main-document decision preview; native reset/step/guards' if self.dynamic_preview else
                         'disabled; explicit native full capture' if self.full_capture_only else
                         'declared origin, current response forbids scripts, stable revision, single document'),
            'fallback':'native BrowserGym full observation',
            'dom_snapshot':'omitted only on fast path; never supplied as an empty complete DOM',
            'inference_overlap':'explicit backend capability; browser stays on owner thread'}


class ObservationChanged(RuntimeError):pass


class ObservationPipeline:
    def __init__(self,env,config,trace):
        from browsergym.core.env import BrowserEnv
        if version('browsergym-core') != '0.14.3':raise ValueError('Pipeline requires BrowserGym 0.14.3')
        if not isinstance(env,BrowserEnv):raise ValueError('Pipeline requires a BrowserGym environment')
        for name in ('_get_obs','_wait_dom_loaded','step'):
            if name in vars(env) or getattr(type(env),name) is not getattr(BrowserEnv,name):
                raise ValueError('Review custom BrowserGym overrides before pipeline adoption: '+name)
        self.env,self.config,self.trace=env,config,trace
        self.saved={name:getattr(env,name) for name in ('_get_obs','_wait_dom_loaded','step','task_entrypoint')}
        self.page=None;self.readiness=None;self.pending=None;self.cache=None
        self.navigation_policy='';self.responses={};self.ticket=None;self.last_readiness=None
        self.pool=None;self.serial=0;self.latest_full=None;self.timings=[]
        self.dynamic=None
        self.overview_budget=lambda:None
        self.after_background=None
        self.after_validation=None
        self.defer_next_step=False;self.in_step=False
        self.shell=ReadinessSpec(scope='body',condition={'kind':'count','selector':'body','expected':1})
        def entrypoint(*args,**kwargs):
            task=self.saved['task_entrypoint'](*args,**kwargs)
            setup=task.setup
            def wrapped(page):
                self.page=page
                if not self.config.full_capture_only:
                    page.add_init_script(REVISION_PATH.read_text());page.evaluate(REVISION_PATH.read_text())
                    self.readiness=Readiness(page)
                    page.on('response',self._response);page.on('framenavigated',self._navigation)
                return setup(page)
            task.setup=wrapped
            return task
        env.task_entrypoint=entrypoint
        env._get_obs=self.capture
        env._wait_dom_loaded=self.wait
        env.step=self.step
        env._intent_observation_pipeline=self

    def _response(self,response):
        if response.request.is_navigation_request() and response.frame==self.page.main_frame:
            self.responses[response.url]=response.headers.get('content-security-policy','')

    def _navigation(self,frame):
        if frame==self.page.main_frame:
            self.navigation_policy=self.responses.pop(frame.url,'');self.responses.clear()
            self.cache=None;self.pending=None

    def stamp(self):
        if self.config.full_capture_only:return None
        if self.page is None or self.env.page is not self.page or self.page.is_closed():return None
        state=self.page.evaluate('()=>globalThis.__intentObservationRevision?.read()')
        if state is None:return None
        directives={}
        for directive in self.navigation_policy.split(';'):
            parts=directive.strip().split()
            if parts:directives.setdefault(parts[0],parts[1:])
        scripts=directives.get('script-src',directives.get('default-src'))
        state['fast_eligible']=(origin(self.page.url) in self.config.static_origins and
            scripts==["'none'"] and directives.get('script-src-elem',scripts)==["'none'"] and
            directives.get('script-src-attr',scripts)==["'none'"] and
            len(self.page.context.pages)==1 and len(self.page.frames)==1 and
            not any(state[k] for k in ('unsupported','resourcesPending','animations')))
        return state

    def wait(self):
        self.saved['_wait_dom_loaded']()
        if self.ticket is None:return
        ticket,self.ticket=self.ticket,None
        if self.env.last_action_error:
            self.readiness.cancel(ticket,'action_error')
            result={'status':'cancelled','reason':'action_error','task_success':None}
        else:
            result=self.readiness.wait(ticket)
            current=self.page.evaluate('globalThis.__intentReadinessV1?.documentId')
            if current != ticket['document_id']:
                previous=result
                result=self.readiness.wait(self.readiness.arm(self.shell))
                result={**result,'document_replaced':True,'prior_document':previous}
                destination=self.stamp()
                if not destination or not destination['fast_eligible']:
                    # The source contract does not make a new scripted site ready.
                    # Preserve BrowserGym's normal delay on this fallback transition.
                    delay=getattr(self,'prior_step_delay',0.5)
                    time.sleep(delay)
                    result['native_fallback_delay_seconds']=delay
            if result['status']!='ready':
                self.env.last_action_error=('Readiness '+result['status']+': '+result['reason']+
                    '. Action effects are uncertain; inspect before acting. No action was replayed.')
        self.last_readiness=result
        self.trace.event('observation_readiness',**result)

    def step(self,action):
        import ast
        name=ast.parse(action).body[0].value.func.id
        state=self.stamp()
        spec=self.config.readiness_by_action.get(name)
        if spec is not None and origin(self.page.url) not in self.config.static_origins:spec=None
        if spec is None and state and state['fast_eligible']:spec=self.shell
        delay=self.env.pre_observation_delay
        self.prior_step_delay=delay
        self.last_readiness=None
        if spec is not None:
            self.ticket=self.readiness.arm(spec)
            self.env.pre_observation_delay=0
        self.cache=None;self.pending=None
        self.in_step=True
        try:return self.saved['step'](action)
        finally:
            self.in_step=False;self.defer_next_step=False
            self.env.pre_observation_delay=delay
            if self.ticket is not None:
                self.readiness.cancel(self.ticket,'step_finished_without_wait');self.ticket=None

    def _metadata(self):
        raw=self.env.use_raw_page_output
        try:
            self.env.use_raw_page_output=True
            obs=self.saved['_get_obs']();obs.pop('page',None);return obs
        finally:self.env.use_raw_page_output=raw

    def _tree(self,depth=None):
        from browsergym.core.observation import _pre_extract,_post_extract,extract_data_items_from_aria
        start=time.monotonic();cdp=None;phases={}
        try:
            _pre_extract(self.page,tags_to_mark=self.env.tags_to_mark)
            phases['mark_seconds']=time.monotonic()-start
            before=self.stamp()
            cdp=self.page.context.new_cdp_session(self.page)
            capture_start=time.monotonic()
            tree=send_json(cdp,'Accessibility.getFullAXTree',{} if depth is None else {'depth':depth})
            phases['cdp_seconds']=time.monotonic()-capture_start
            if self.stamp()!=before:raise ObservationChanged('Page changed during AX capture')
            # BrowserGym's exact BID carrier convention, without full DOMSnapshot.
            for node in tree['nodes']:
                items=[]
                for i,prop in enumerate(node.get('properties',[])):
                    if prop['name']=='roledescription':
                        items,value=extract_data_items_from_aria(prop['value']['value'])
                        prop['value']['value']=value
                        if value=='':del node['properties'][i]
                        break
                if 'description' in node:
                    fallback,value=extract_data_items_from_aria(node['description']['value'])
                    node['description']['value']=value
                    if value=='':del node['description']
                    if not items:items=fallback
                if items:(node['browsergym_id'],)=items
            return tree
        finally:
            cleanup_start=time.monotonic()
            if cdp is not None:cdp.detach()
            _post_extract(self.page)
            phases['cleanup_seconds']=time.monotonic()-cleanup_start
            row={'phase':'full_ax' if depth is None else 'shallow_ax',
                 'seconds':time.monotonic()-start,**phases}
            self.timings.append(row);self.trace.event('observation_capture_phase',**row)

    def _observation(self,tree,coverage,*,screenshots=True):
        from browsergym.core.observation import extract_focused_element_bid,extract_screenshot
        obs=self._metadata()
        obs.update(axtree_object=tree,dom_object=None,extra_element_properties={},
            focused_element_bid=extract_focused_element_bid(self.page),
            screenshot=extract_screenshot(self.page) if screenshots and self.config.trace_screenshots else None,
            observation_capture={'version':'browsergym-progressive-v1','coverage':coverage,
                'dom_snapshot':'not_captured','geometry':'not_captured','shallow_depth':self.config.shallow_depth,
                'readiness':deepcopy(self.last_readiness)})
        return obs

    def capture(self,*,complete=False):
        if (self.config.targeted_actions and self.in_step and self.defer_next_step
                and not complete and self.dynamic is not None):
            return self.dynamic.deferred_observation()
        state=self.stamp()
        if not state or not state['fast_eligible'] or (self.last_readiness and self.last_readiness['status']!='ready'):
            self.cache=None;self.pending=None
            obs=capture_json(self.saved['_get_obs'],screenshots=self.config.trace_screenshots)
            obs['observation_capture']={'version':'browsergym-progressive-v1','coverage':'full',
                                        'mode':'native_fallback','readiness':deepcopy(self.last_readiness)}
            return obs
        if self.cache is not None and self.cache['stamp']==state:
            return self._observation(deepcopy(self.cache['tree']),'full')
        self.cache=None
        if not complete and self.pending is not None and self.pending['stamp']==state:
            obs=deepcopy(self.pending['observation']);obs.update(self._metadata())
            obs['observation_capture']['reused_partial']=True
            return obs
        tree=self._tree(None if complete else self.config.shallow_depth)
        obs=self._observation(tree,'full' if complete else 'partial')
        state=self.stamp()
        if not state or not state['fast_eligible']:raise ObservationChanged('Fast capture lost eligibility')
        if complete:
            self.cache={'stamp':state,'tree':deepcopy(tree)};self.pending=None
        else:
            self.pending={'stamp':state,'observation':deepcopy(obs)}
        return obs

    def prefetch(self):
        if self.dynamic is not None and self.dynamic.pending is not None:
            artifact=self.dynamic.capture()
            if getattr(self,'after_background',None) is not None:self.after_background(self.dynamic.full)
            return artifact
        if self.pending is None:return None
        pending=self.pending
        if self.stamp()!=pending['stamp']:raise ObservationChanged('Page changed after shallow preview; stale decision must not execute')
        tree=self._tree()
        # The shallow capture is a subset, not a complete tree with deletions.
        full=Counter(ax_node_signature(n) for n in tree['nodes'])
        for node in pending['observation']['axtree_object']['nodes']:
            signature=ax_node_signature(node)
            if not full[signature]:
                artifact=self.trace.observation(self.serial,self._observation(tree,'full',screenshots=False),
                    'Rejected background AX; not delivered to policy.',phase='background')
                self.serial+=1
                self.trace.event('background_capture_rejected',artifact=artifact,
                    shallow_node=node,
                    full_node=next((n for n in tree['nodes'] if n['nodeId']==node['nodeId']),None))
                raise ObservationChanged('Shallow/full AX disagreement; stale decision must not execute')
            full[signature]-=1
        obs=self._observation(tree,'full',screenshots=False)
        state=self.stamp()
        if not state or not state['fast_eligible']:raise ObservationChanged('Full prefetch lost eligibility')
        self.cache={'stamp':state,'tree':deepcopy(tree)};self.pending=None;self.latest_full=obs
        artifact=self.trace.observation(self.serial,obs,'Full background AX; not itself delivered to policy.',phase='background')
        self.serial+=1
        return artifact

    def complete(self,backend,messages,event):
        """Never move Playwright to another thread or discard a paid response."""
        capable=(type(backend).__dict__.get('supports_background_completion') is True and
                 not getattr(backend,'requires_browser_thread',False))
        dynamic=getattr(self,'dynamic',None)
        dynamic_pending=dynamic is not None and dynamic.pending is not None
        overlapping=capable and (self.pending is not None or dynamic_pending)
        event['observation_pipeline']={'overlapped':overlapping,'background_error':None}
        barrier_started=time.monotonic()
        if dynamic_pending:
            event['observation_pipeline']['mode']=getattr(dynamic,'mode',None) or (
                'dynamic-main-preview-v2' if dynamic.preview_bids else 'dynamic-main-preview-v1')
        def failed(exc):
            from .batching import DocumentScanInvalidated
            event['observation_pipeline']['background_error']=f'{type(exc).__name__}: {exc}'
            if dynamic_pending and isinstance(exc,(ObservationChanged,DocumentScanInvalidated)):
                event['observation_pipeline']['invalidated']=True
                self.invalidation_streak=getattr(self,'invalidation_streak',0)+1
        def dispatch():
            start=time.monotonic()
            event['observation_pipeline']['backend_start_seconds']=start-barrier_started
            try:return backend.complete(messages)
            finally:
                event['observation_pipeline']['backend_completion_seconds']=time.monotonic()-start
                event['observation_pipeline']['backend_end_seconds']=time.monotonic()-barrier_started
        def fill():
            start=time.monotonic()
            event['observation_pipeline']['prefetch_start_seconds']=start-barrier_started
            try:event['observation_pipeline']['artifact']=self.prefetch()
            except Exception as exc:
                failed(exc)
            finally:
                event['observation_pipeline']['prefetch_seconds']=time.monotonic()-start
                event['observation_pipeline']['prefetch_end_seconds']=time.monotonic()-barrier_started
        if overlapping:
            if self.pool is None:self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='observation-model')
            future=self.pool.submit(dispatch)
            fill()
            try:
                try:result=future.result()  # Retain success/error/request even if prefetch failed.
                except BaseException as exc:
                    if dynamic_pending and getattr(self,'after_validation',None) is not None:
                        # The decision is never validated: its deferred outputs are
                        # finalized as unknown before the original error propagates.
                        self.after_validation({'valid':False,'revision_proven':False,
                            'error':f'completion_failed: {type(exc).__name__}'})
                    raise
                if dynamic_pending and not event['observation_pipeline']['background_error']:
                    try:dynamic.validate()
                    except Exception as exc:failed(exc)
                if dynamic_pending and getattr(self,'after_validation',None) is not None:
                    # Owner thread, before policy delivery is acknowledged.
                    self.after_validation({'valid':not event['observation_pipeline']['background_error'],
                        'revision_proven':bool(getattr(dynamic,'revision_proven',False)),
                        'error':event['observation_pipeline']['background_error']})
                return result
            finally:event['observation_pipeline']['barrier_seconds']=time.monotonic()-barrier_started
        fill()
        if event['observation_pipeline']['background_error']:
            raise ObservationChanged(event['observation_pipeline']['background_error'])
        return dispatch()

    def decision_capture(self,human,backend,previous):
        """Preview only at a decision boundary; reset/step/guards stay native."""
        if self.dynamic is not None:self.dynamic.pending=None
        capable=(type(backend).__dict__.get('supports_background_completion') is True and
                 not getattr(backend,'requires_browser_thread',False))
        if not self.config.dynamic_preview or not capable:
            return self.capture()
        if getattr(self,'invalidation_streak',0)>=2:
            # Live-content pages (carousels, tickers) change between preview and full capture,
            # so every preview-based decision would be discarded as stale. After two such
            # invalidations, use native full captures for the rest of the episode.
            if not getattr(self,'preview_disabled_logged',False):
                self.preview_disabled_logged=True
                self.trace.event('dynamic_preview_disabled',reason='repeated_background_preview_invalidation')
            return self.capture()
        if self.dynamic is None and self.config.decision_capture=='budgeted_overview':
            from .budgeted_decision import BudgetedDecision
            self.dynamic=BudgetedDecision(human,self.trace,budget_tokens=lambda:self.overview_budget())
        elif self.dynamic is None:
            from .dynamic_preview import DynamicPreview
            self.dynamic=DynamicPreview(human,self.trace,depth=self.config.shallow_depth,
                                        max_nodes=self.config.preview_node_limit,preview_bids=self.config.preview_bids)
        preview=self.dynamic.preview(previous)
        return preview if preview is not None else self.capture()

    def full_after_completion(self):
        if self.dynamic is not None and self.dynamic.pending is not None:
            return self.dynamic.full
        if self.cache is not None:
            if self.stamp()!=self.cache['stamp']:
                raise ObservationChanged('Page changed during inference; stale decision must not execute')
            return self._observation(deepcopy(self.cache['tree']),'full',screenshots=False)
        # Native fallback retains the normal runner's fresh batch guards.
        return None

    def screenshot(self,index):
        from PIL import Image
        import numpy as np
        from .visual_readiness import capture_visual
        from .trace import write_json
        path=self.trace.directory/f'visual-capture-{index:03d}.png'
        result=capture_visual(self.env.page,path,allow_uncertain=True)
        artifact=f'visual-readiness-{index:03d}.json'
        write_json(self.trace.directory/artifact,{**result,'image_artifact':path.name})
        with Image.open(path) as image:pixels=np.asarray(image.convert('RGB')).copy()
        return pixels,result,artifact

    def positioning(self,bid):
        # Public viewport geometry for this requested target only; no DOMSnapshot.
        locator=self.env.page.get_by_test_id(bid)
        if locator.count()!=1:return {'bid':bid,'status':'unknown','scope':'Target missing or ambiguous'}
        ratio=locator.evaluate('''el=>{const r=el.getBoundingClientRect();
            if(!r.width||!r.height)return 0;
            return Math.max(0,Math.min(r.right,innerWidth)-Math.max(r.left,0))*
                Math.max(0,Math.min(r.bottom,innerHeight)-Math.max(r.top,0))/(r.width*r.height);}''')
        return {'bid':bid,'status':'in_viewport' if ratio>=.99 else 'partially_in_viewport' if ratio>0 else 'outside_viewport',
                'scope':'Current target viewport intersection; not proof of unobscured pixels'}

    def close(self):
        if self.pool is not None:self.pool.shutdown(wait=True)
        if self.readiness is not None and self.page is not None and not self.page.is_closed():self.readiness.close()
        if self.page is not None and not self.config.full_capture_only:
            self.page.remove_listener('response',self._response);self.page.remove_listener('framenavigated',self._navigation)
        for name,value in self.saved.items():setattr(self.env,name,value)
        if hasattr(self.env,'_intent_observation_pipeline'):del self.env._intent_observation_pipeline


class PartialFeedback:
    """Keep transient events; never claim omitted descendants were removed."""
    def __init__(self,wrapped):self.wrapped=wrapped
    def __getattr__(self,name):return getattr(self.wrapped,name)
    def after_action(self,env,before,obs):
        if not partial(obs):return self.wrapped.after_action(env,before,obs)
        from .harness import _page_lines
        sanitized={**before,'lines':_page_lines(obs)}
        result=self.wrapped.after_action(env,sanitized,obs)
        for key in ('added_or_changed','removed_or_changed','omitted_lines'):result.pop(key,None)
        result['scope']='Partial AX preview; full AX diff deferred. Browser events retained; no task-success claim.'
        result.setdefault('event_capture',{}).setdefault('warnings',[]).append('Partial AX: omission is not removal; search/read waits for full capture.')
        if result.get('timeout_context'):result['timeout_context']['accessible_content_change_observed']=None
        return result
