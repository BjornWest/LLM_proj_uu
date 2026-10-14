"""Opt-in BrowserGym 0.14.3 tab custody. All Playwright calls stay on its owner thread."""
from copy import deepcopy
import hashlib
from importlib.metadata import version
import json
import time
from types import SimpleNamespace

from browsergym.core.env import BrowserEnv
from playwright.sync_api import Error as PlaywrightError

from .batching import document_signature, DocumentScanInvalidated
from .observation_pipeline import ax_node_signature
from .native_capture import CaptureBudget, CaptureDeadlineExceeded, capture_native, TARGET_SECONDS

CONTROL_TOOLS = ('handover_tab', 'tab_focus', 'new_tab', 'tab_close')
CAPTURE_MAX_ATTEMPTS = 3
GUARD_SECONDS = 2.0

# These operations inspect fresh evidence or explicitly choose another location.
# They retain tab/document/custody fencing and normal tool/ref validation. Other
# operations still require full-content agreement until a narrower mutation
# confirmation contract has separate acceptance.
CONTENT_INDEPENDENT_TOOLS = frozenset((
    'ax_search', 'ax_read', 'ax_changes', 'screenshot', 'extract_page',
    'run_python', 'release_image', 'noop', 'goto', 'new_tab', 'tab_focus', 'handover_tab',
))


class _ObservationView:
    """Native extraction on one real Page; never evaluate other tabs' titles."""
    def __init__(self, env, page):
        self._env=env;self.page=page;self.context=SimpleNamespace(pages=[page])
    def __getattr__(self, name): return getattr(self._env,name)


def ax_digest(obs):
    nodes=obs.get('axtree_object',{}).get('nodes',[])
    return hashlib.sha256(json.dumps([ax_node_signature(n) for n in nodes],
        sort_keys=True,default=str,ensure_ascii=False).encode()).hexdigest()


class HumanBrowser:
    def __init__(self, env, controller, trace, pipeline, *, wait_for_human=False, compact_tabs=False, stable_frames=False,
                 capture_timeout_mode='bounded'):
        if capture_timeout_mode not in ('bounded','diagnostic'):
            raise ValueError('capture_timeout_mode must be bounded or diagnostic')
        if version('browsergym-core')!='0.14.3' or not isinstance(env,BrowserEnv):
            raise ValueError('Human tabs require reviewed BrowserGym 0.14.3')
        if not pipeline.config.full_capture_only:
            raise ValueError('Human tabs currently require native full capture')
        self.env,self.controller,self.trace,self.pipeline=env,controller,trace,pipeline
        self.quarantined_frames={}
        self.frame_projection_sequence=0
        self.stable_frames=stable_frames
        self.capture_timeout_mode=capture_timeout_mode
        self.compact_tabs=compact_tabs
        self.wait_for_human=wait_for_human
        self.returns={}
        self.pages={};self.active=None;self.ready=False;self.known_agent_pages=set()
        self.saved={k:getattr(env,k) for k in ('_activate_page_from_js','_active_page_check','post_step')}
        self.saved_capture=pipeline.saved['_get_obs'];self.saved_wait=pipeline.saved['_wait_dom_loaded']
        self.ignored_focus=set()
        self.notices=[]
        self.association={}
        self.observations={};self.capture_sequence=0
        self.confirmations={};self.confirmation_sequence=0
        self.last_action_execution=None
        self.capture_function=capture_native
        env._activate_page_from_js=self.activation
        env._active_page_check=self.active_check
        env.post_step=self.post_step
        pipeline.saved['_get_obs']=self.capture
        pipeline.saved['_wait_dom_loaded']=self.wait

    def activation(self,page):
        if not self.ready:return self.saved['_activate_page_from_js'](page)
        if page is not self.pages.get(self.active) and page not in self.ignored_focus:
            self.ignored_focus.add(page)
            self.trace.event('human_tab_focus_ignored',tab_id=self.id_for(page),
                scope='Focus/browser callback cannot retarget the agent; actor unknown')

    def id_for(self,page):
        return next((key for key,value in self.pages.items() if value is page),None)

    def states(self):
        snapshot=self.controller.snapshot()
        if not snapshot['available']:raise RuntimeError('Human-control controller unavailable')
        return {t['tab_id']:t for t in snapshot['tabs']}

    def sync(self):
        if self.stable_frames:return self._guard_operation('sync',self._sync)
        return self._sync()

    def _guard_operation(self,name,callback):
        budget=CaptureBudget(self.env.page,self.trace,seconds=GUARD_SECONDS,
            scope='browser_guard',event_prefix='browser_guard',enforce=self.capture_timeout_mode=='bounded')
        budget.phase=name;error=None
        self.trace.event('browser_guard_started',operation=name,observed_at=deepcopy(self.association))
        try:
            with budget.rpc_deadline():
                result=callback(budget);budget.check();return result
        except Exception as exc:
            error=f'{type(exc).__name__}: {exc}'
            raise
        finally:
            self.trace.event('browser_guard_completed',operation=name,seconds=time.monotonic()-budget.started,
                error=error,budget_seconds=GUARD_SECONDS,deadline_enforced=budget.enforce,observed_at=deepcopy(self.association))

    def _sync(self,budget=None):
        # Sync Playwright queues browser events while model I/O blocks this
        # thread. Flush before trusting cached Page.is_closed/context.pages.
        # Same event-pump idiom as BrowserGym.post_step; values are discarded.
        call=budget.timed if budget else (lambda name,fn:fn())
        call('context_event_pump',self.env.context.cookies)
        for tab_id,page in list(self.pages.items()):
            if page.is_closed():self.controller.close(tab_id)
        for page in list(self.env.context.pages):
            if self.id_for(page) is not None:continue
            tab_id=f'tab-{len(self.pages)+1}'
            self.pages[tab_id]=page
            self.controller.register(tab_id,title='',url=self.display_url(page.url))
            if page not in self.known_agent_pages:
                try:opener_id=self.id_for(call('page_opener',page.opener))
                except PlaywrightError:
                    if page.is_closed():
                        self.controller.close(tab_id);continue
                    raise
                opener=self.states().get(opener_id,{})
                if opener.get('state')!='agent_controlled':
                    self.controller.handover(tab_id,'New tab with human or unknown opener; human control retained.')
        self.emit()

    @staticmethod
    def display_url(url):
        # Error/internal pages have no public navigation URL; never coerce into
        # an allowed origin or use this display value for identity checks.
        return url if url.startswith(('http://','https://')) or url=='about:srcdoc' else 'about:blank'

    def emit(self, **association):
        for transition in self.controller.drain():
            self.trace.event('human_tab_transition',transition=transition,
                observed_at={**self.association,**association})
            if transition['event'] in ('complete','cancel'):
                self.returns[(transition['tab_id'],transition['handover_id'])]=transition['event']
            if transition['event']!='metadata_updated':
                self.notices.append({k:transition[k] for k in ('sequence','event','tab_id','new_state','actor')})
                if self.compact_tabs:
                    self.notices[-1]['handover_id']=transition['handover_id']
                else:self.notices=self.notices[-12:]

    def start(self):
        self.known_agent_pages.update(self.env.context.pages)
        self.ready=True;self.sync();self.active=self.id_for(self.env.page)
        self.prepare()

    def select(self,tab_id):
        page=self.pages[tab_id]
        if page.is_closed():raise ValueError('Selected tab is closed')
        self.active=tab_id;self.env.page=page
        # Do not bring_to_front: the human can keep working in their visible tab.
        self.env.page_history[page]=None

    def wait_for_return(self, tab_id):
        state=self.states().get(tab_id)
        if not state or state['state']=='closed':raise RuntimeError('Supervised tab closed; no replacement workspace created')
        cycle=state['handover_id'];started=time.monotonic()
        self.trace.event('human_tab_wait_started',tab_id=tab_id,handover_id=cycle)
        while state['state'] in ('awaiting_human','human_active'):
            # Browser callbacks and independent HTTP human controls remain live.
            # No inference, page actions, capture, or new workspace while waiting.
            self.sync();state=self.states().get(tab_id)
            if not state or state['state']=='closed':
                raise RuntimeError('Supervised tab closed while waiting; no replacement workspace created')
            if state['handover_id']!=cycle:raise RuntimeError('Handover cycle changed while waiting')
            if state['state'] in ('awaiting_human','human_active'):time.sleep(.1)
        if state['state']!='returned':raise RuntimeError('Expected explicit human return')
        outcome=self.returns.get((tab_id,cycle))
        if outcome not in ('complete','cancel'):raise RuntimeError('Human return evidence unavailable')
        self.trace.event('human_tab_wait_finished',tab_id=tab_id,handover_id=cycle,
            outcome=outcome,seconds=time.monotonic()-started)
        return outcome

    def prepare(self, *, allow_wait=True):
        self.sync();states=self.states()
        if self.wait_for_human:
            state=states.get(self.active)
            if not state or state['state']=='closed':raise RuntimeError('Supervised tab closed; no replacement workspace created')
            if state['state'] in ('awaiting_human','human_active'):
                if not allow_wait:raise RuntimeError('Tab became human-owned during capture; observation not delivered')
                self.wait_for_return(self.active)
            self.select(self.active)
            return
        if self.active not in states or states[self.active]['state'] not in ('agent_controlled','returned'):
            selected=next((k for k,v in states.items() if v['state']=='agent_controlled'),None)
            if selected is None:
                page=self.env.context.new_page();self.known_agent_pages.add(page);self.sync();selected=self.id_for(page)
                self.trace.event('human_tab_workspace_created',tab_id=selected,
                    reason='No available agent-owned tab; blank workspace only')
            self.select(selected)
        else:self.select(self.active)

    def active_check(self):
        if not self.ready:return self.saved['_active_page_check']()
        self.prepare()

    def wait(self):
        if not self.ready:return self.saved_wait()
        page=self.pages[self.active]
        # Upstream already treats load-state timeout as best effort. Bound the
        # aggregate wait rather than spending 3 seconds per advertising frame;
        # the subsequent full capture still inspects every native-visible frame.
        budget=CaptureBudget(page,self.trace,seconds=1.0);budget.phase='dom_load_wait'
        exhausted=False
        try:
            with budget.rpc_deadline():
                for frame in list(page.frames):
                    budget.check()
                    try:frame.wait_for_load_state('domcontentloaded',timeout=1000)
                    except PlaywrightError:pass
        except CaptureDeadlineExceeded:exhausted=True
        self.trace.event('native_dom_wait_completed',seconds=time.monotonic()-budget.started,
            budget_seconds=1.0,exhausted=exhausted,
            scope='Best-effort load wait; complete guarded capture still required')

    def post_step(self,info,*args,**kwargs):
        # BrowserGym enters post_step after execute_python_code has returned
        # (including its caught action error), BEFORE waiting/validation/capture.
        # A later extraction exception must not erase this execution evidence.
        self.last_action_execution={'action':self.env.last_action,
            'action_error':self.env.last_action_error,'returned_at':time.time(),
            'scope':'Native action code returned; not a task or side-effect verdict'}
        self.trace.event('human_tab_action_execution_completed',
            observed_at=deepcopy(self.association),**self.last_action_execution)
        return self.saved['post_step'](info,*args,**kwargs)

    def capture(self):
        if self.ready and self.wait_for_human:self.prepare()  # Human wait is outside capture deadline.
        budget=CaptureBudget(self.env.page,self.trace,enforce=self.capture_timeout_mode=='bounded')
        if self.stable_frames:budget.quarantined=self.quarantined_frames
        error=None
        try:
            with budget.rpc_deadline():
                if not self.ready:return self.capture_function(_ObservationView(self.env,self.env.page),budget,
                    screenshots=self.pipeline.config.trace_screenshots)
                return self._capture(budget)
        except Exception as exc:
            error=f'{type(exc).__name__}: {exc}'
            budget.cleanup_failed()
            raise
        finally:
            if error is None and budget.pending:budget.cleanup_failed()
            seconds=time.monotonic()-budget.started
            self.trace.event('native_capture_completed',seconds=seconds,error=error,
                target_seconds=TARGET_SECONDS,target_overrun=seconds>TARGET_SECONDS,
                budget_seconds=budget.seconds,deadline_enforced=budget.enforce,observed_at=deepcopy(self.association))

    def document_identity(self):
        if self.stable_frames:
            from .frame_capture import frame_documents,main_signature
            return self._guard_operation('document_identity',lambda budget:
                main_signature(frame_documents(self.env.page,timed=budget.timed)))
        return document_signature(self.env,active_only=True)

    def capture_viewport(self,ticket,capture):
        """Fresh pixels without native DOM/AX work; pin custody and document.

        Same-document visual changes are allowed and reported by the visual gate.
        Replaced documents/custody invalidate delivery, not silently retarget it.
        """
        budget=CaptureBudget(self.env.page,self.trace,enforce=self.capture_timeout_mode=='bounded');budget.phase='viewport_capture'
        error=None
        self.trace.event('viewport_capture_started',observed_at=deepcopy(self.association))
        try:
            with budget.rpc_deadline():
                failure=self.guard(ticket)
                if failure:raise DocumentScanInvalidated({'reason':failure,'scope':'before_viewport_capture'})
                result=capture()
                failure=self.guard(ticket)
                if failure:raise DocumentScanInvalidated({'reason':failure,'scope':'after_viewport_capture'})
                budget.check()
                return result
        except Exception as exc:
            error=f'{type(exc).__name__}: {exc}'
            raise
        finally:
            self.trace.event('viewport_capture_completed',seconds=time.monotonic()-budget.started,error=error,
                budget_seconds=budget.seconds,deadline_enforced=budget.enforce,observed_at=deepcopy(self.association),
                scope='Fresh viewport only; no DOM/AX refresh. Rejected pixels may remain in raw artifacts, never policy images.')

    def _capture(self,budget):
        self.prepare(allow_wait=False);page=self.pages[self.active];tab_id=self.active
        budget.page=page  # prepare may choose another agent-owned workspace.
        before=self.states()[tab_id]
        def require_capture_owner():
            # Pin the selected Page AND custody cycle across all attempts.
            # prepare() is deliberately not repeated: it may select/create a
            # different workspace after a handover or closed tab.
            self.sync()
            current=self.states().get(tab_id)
            if (page.is_closed() or self.active!=tab_id or self.env.page is not page
                    or not current or current['state']!=before['state']
                    or current['handover_id']!=before['handover_id']):
                raise RuntimeError('Tab custody changed during observation; observation not delivered')
            return current

        failures=[];started=time.monotonic()
        for attempt in range(1,CAPTURE_MAX_ATTEMPTS+1):
            require_capture_owner()
            stage='before_native_capture'
            try:
                if self.stable_frames:
                    from .frame_capture import frame_documents,main_signature,project_capture
                    frame_before=frame_documents(page);document=main_signature(frame_before)
                else:document=self.document_identity()
                stage='native_capture'
                obs=self.capture_function(_ObservationView(self.env,page),budget,
                    screenshots=self.pipeline.config.trace_screenshots)
                require_capture_owner()
                stage='after_native_capture'
                if self.stable_frames:
                    frame_after=frame_documents(page)
                    native_obs=obs
                    from .frame_capture import quarantined_documents
                    active_quarantine=[f for f in self.quarantined_frames if not f.is_detached() and f in page.frames]
                    prefixes=[budget.prefixes[f] for f in active_quarantine if budget.prefixes.get(f)]
                    excluded,unknown=quarantined_documents(obs,prefixes)
                    unknown=unknown or len(prefixes)!=len(active_quarantine)
                    obs=project_capture(obs,frame_before,frame_after,scale_factor=getattr(page,'_bgym_scale_factor',1.0),
                        excluded_frames=excluded,exclude_children=unknown)
                    coverage=obs['frame_capture']
                    if coverage['partial']:
                        import gzip
                        from .trace import json_default
                        self.frame_projection_sequence+=1
                        artifact=f'frame-capture-native-{self.frame_projection_sequence:04d}.json.gz'
                        with gzip.open(self.trace.directory/artifact,'xt',encoding='utf-8') as f:
                            json.dump({'before':frame_before,'after':frame_after,'excluded_frames':sorted(excluded),'exclude_children':unknown,
                                'native':{k:v for k,v in native_obs.items() if k!='screenshot'}},f,default=json_default)
                        coverage['native_artifact']=artifact
                    self.trace.event('human_tab_frame_coverage',tab_id=tab_id,
                        partial=coverage['partial'],included_frames=coverage['included_frames'],
                        omitted_frames=coverage['omitted_frames'],omitted_ax_nodes=coverage['omitted_ax_nodes'],
                        native_artifact=coverage.get('native_artifact'),observed_at=deepcopy(self.association))
                if self.document_identity()!=document:
                    raise DocumentScanInvalidated({'reason':'document_changed_during_human_tab_capture','tab_id':tab_id})
                current=require_capture_owner()
                break
            except DocumentScanInvalidated as exc:
                failure={'attempt':attempt,'stage':stage,'detail':deepcopy(exc.detail)}
                failures.append(failure)
                self.trace.event('human_tab_capture_invalidated',tab_id=tab_id,
                    observed_at=deepcopy(self.association),**failure)
                # Even a recognized frame race cannot mask a concurrent loss
                # of custody. No actions, noops, model calls or old targets are
                # replayed. Only a wholly fresh native capture can be accepted.
                require_capture_owner()
                if exc.detail.get('phase')=='frame_owner_lookup':
                    # Marking may have installed promises before owner lookup
                    # raced navigation. Cancel/unmark before another capture;
                    # the same action and old element handles are never reused.
                    self.trace.event('human_tab_capture_retry_cleanup_started',tab_id=tab_id,attempt=attempt)
                    cleaned=budget.cleanup_failed()
                    self.trace.event('human_tab_capture_retry_cleanup_completed',tab_id=tab_id,attempt=attempt,completed=cleaned)
                    if not cleaned:
                        raise RuntimeError('Observation retry cleanup failed; no fresh observation accepted') from exc
                    require_capture_owner()
                if attempt==CAPTURE_MAX_ATTEMPTS:
                    raise DocumentScanInvalidated({'reason':'human_tab_capture_attempts_exhausted',
                        'tab_id':tab_id,'attempts':attempt,'failures':failures}) from exc
        if failures:
            self.trace.event('human_tab_capture_recovered',tab_id=tab_id,attempts=attempt,
                seconds=time.monotonic()-started,observed_at=deepcopy(self.association),
                scope='Observation only; no browser action replayed')
        if current['state']=='returned':
            self.trace.event('human_tab_return_observed',tab_id=tab_id,ax_sha256=ax_digest(obs),
                scope='Fresh native capture; no verification success inferred')
            self.controller.resume(tab_id)
        self.controller.register(tab_id,title=obs['open_pages_titles'][0][:1000],url=self.display_url(page.url))
        self.emit()
        snapshot=self.controller.snapshot()
        live=[t for t in snapshot['tabs'] if t['state']!='closed']
        obs.update(open_pages_urls=tuple(t['url'] for t in live),
            open_pages_titles=tuple(t['title'] for t in live),active_page_index=[next(i for i,t in enumerate(live) if t['tab_id']==tab_id)],
            human_tabs={'active_tab_id':tab_id,'revision':snapshot['revision'],'tabs':deepcopy(live),
                'recent_transitions':deepcopy(self.notices),
                'scope':'Stable custody; titles/URLs are last captured display metadata. Returned means human-finished, never verified.'},
            human_tab_capture={'tab_id':tab_id,'document':document,'attempts':attempt})
        self.ignored_focus.clear()
        return obs

    def ticket(self,obs):
        self.sync();state=self.states()[self.active]
        self.capture_sequence+=1
        self.observations[self.capture_sequence]=deepcopy(obs.get('axtree_object',{}))
        # Confirmation retains action/identity, not entire historical AX trees.
        if len(self.observations)>2:del self.observations[min(self.observations)]
        return {'tab_id':self.active,'handover_id':state['handover_id'],
                'document':deepcopy(obs['human_tab_capture']['document']),'ax_sha256':ax_digest(obs),
                'capture_id':self.capture_sequence,
                **({'frame_capture':deepcopy(obs['frame_capture'])} if self.stable_frames else {})}

    def content_review(self,ticket,obs,decision,*,step,call_id):
        from .tab_changes import change_report,preview,target_identity
        from .trace import write_json
        before={'axtree_object':self.observations.get(ticket.get('capture_id'),{})}
        if not before['axtree_object']:
            return {'execution':'not_executed','reason':'decision_evidence_expired'}
        report=change_report(before,obs,decision)
        if not report['change_count']:return None
        bid=decision.arguments.get('bid')
        target=target_identity(before,bid) if bid is not None else None
        valid=bid is None or (target is not None and target_identity(obs,bid)==target)
        self.confirmation_sequence+=1
        cid=f'proceed-{self.confirmation_sequence}'
        filename=f'human-change-{self.confirmation_sequence:04d}.json'
        write_json(self.trace.directory/filename,{'step':step,'tool_call_id':call_id,
            'action':decision.code,'ticket':ticket,'report':report,'target_valid':valid})
        feedback={'execution':'not_executed',
            'reason':'tab_content_changed_since_decision' if valid else 'target_removed_replaced_or_disabled',
            'change_review':preview(report)}
        if valid:
            # Only the latest pending proposal remains eligible; read-only
            # inspection may follow, but no ambient or permanent bypass exists.
            self.confirmations.clear()
            self.confirmations[cid]={'decision':deepcopy(decision),'ticket':deepcopy(ticket),
                'target_identity':target,'step':step,'tool_call_id':call_id,'artifact':filename}
            feedback['confirmation']={'confirmation_id':cid,'action':decision.code,
                'instruction':'Review the changes. To execute this exact action once despite further CONTENT changes, '
                    'call proceed_action with this ID. This does not authorize new effects; target/document/custody guards still apply.'}
        self.trace.event('human_tab_change_review',step=step,tool_call_id=call_id,
            artifact=filename,confirmation_id=cid if valid else None)
        return feedback

    def take_confirmation(self,confirmation_id):
        item=self.confirmations.pop(confirmation_id,None)
        self.trace.event('human_tab_confirmation_consumed',confirmation_id=confirmation_id,
            known=item is not None,scope='One attempt only, including rejected or failed attempts')
        return item

    def confirmation_guard(self,item,obs):
        from .tab_changes import target_identity
        failure=self.guard(item['ticket'],decision=item['decision'])
        if failure:return failure
        bid=item['decision'].arguments.get('bid')
        if self.stable_frames and bid is not None and bid not in obs.get('frame_capture',{}).get('bid_frames',{}):
            return 'target_not_in_captured_stable_document'
        if bid is not None and target_identity(obs,bid)!=item['target_identity']:
            return 'target_removed_replaced_or_disabled'
        return None

    def guard(self,ticket,obs=None,*,decision=None):
        if self.stable_frames:
            return self._guard_operation('action_guard',lambda budget:self._guard(ticket,obs,decision=decision,budget=budget))
        return self._guard(ticket,obs,decision=decision)

    def _guard(self,ticket,obs=None,*,decision=None,budget=None):
        if budget is None:self.sync()
        else:self._sync(budget)
        state=self.states().get(ticket['tab_id'])
        if self.active!=ticket['tab_id'] or not state or state['state']!='agent_controlled':
            return 'tab_ownership_or_target_changed'
        if state['handover_id']!=ticket['handover_id']:return 'tab_handover_cycle_changed'
        if self.stable_frames:
            from .frame_capture import frame_documents,main_signature,target_document_error
            documents=frame_documents(self.env.page,timed=budget.timed)
            document=main_signature(documents)
        else:document=self.document_identity()
        if document!=ticket['document']:return 'tab_document_changed'
        if self.stable_frames and decision is not None and decision.arguments.get('bid') is not None:
            failure=target_document_error(ticket,documents,decision.arguments['bid'])
            if failure:return failure
            if obs is not None and decision.arguments['bid'] not in obs.get('frame_capture',{}).get('bid_frames',{}):
                return 'target_not_in_captured_stable_document'
        if obs is not None:
            if obs.get('human_tabs',{}).get('active_tab_id')!=ticket['tab_id']:
                return 'tab_ownership_or_target_changed'
            if (getattr(decision,'name',None) not in CONTENT_INDEPENDENT_TOOLS
                    and ax_digest(obs)!=ticket['ax_sha256']):
                return 'tab_content_changed_since_decision'
        return None

    def is_agent_active(self,page):
        if page is not self.pages.get(self.active):return False
        return self.states().get(self.active,{}).get('state')=='agent_controlled'

    def execute(self,decision):
        self.sync();name=decision.name
        if self.wait_for_human and (name in ('new_tab','tab_close') or
                name in ('tab_focus','handover_tab') and decision.arguments['tab_id']!=self.active):
            return {'tool':name,'execution':'not_executed','error':'Supervised wait profile keeps the current tab; no new, closed, or alternate workspace'}
        outcome=None
        if name in ('tab_focus','handover_tab'):
            target=decision.arguments['tab_id'];state=self.states().get(target)
            if state is None or state['state']=='closed':return {'tool':name,'error':'Unknown or closed tab','execution':'not_executed'}
            if name=='handover_tab':
                if state['state']!='agent_controlled':return {'tool':name,'error':'Tab is already outside agent control','execution':'not_executed'}
                self.controller.handover(target,decision.arguments['reason']);self.emit()
                if self.wait_for_human:
                    notice='Human help requested on '+target+': '+decision.arguments['reason']+' Use Start, then Finished or Cancelled in the handover controls. Agent inference is paused.'
                    self.env.chat.add_message(role='assistant',msg=notice)
                    self.trace.event('human_tab_wait_ui_notice',tab_id=target,text=notice,
                        scope='Runtime-authored UI notice, not model output')
                    outcome=self.wait_for_return(target)
                self.prepare()
            else:
                if state['state'] not in ('agent_controlled','returned'):
                    return {'tool':name,'error':'Tab is human-owned. Wait for explicit return; work in another tab.','execution':'not_executed'}
                self.select(target)
        elif name=='new_tab':
            page=self.env.context.new_page();self.known_agent_pages.add(page);self.sync();self.select(self.id_for(page))
        elif name=='tab_close':
            self.pages[self.active].close();self.prepare()
        self.emit()
        return {'tool':name,'execution':'call_completed','active_tab_id':self.active,
                **({'human_return':outcome,'fresh_inspection_required':True} if outcome else {}),
                'scope':'Tab control only; not a verification or task-success verdict'}

    def close(self):
        for tab_id in self.pages:self.controller.close(tab_id)
        self.emit()
        for k,v in self.saved.items():setattr(self.env,k,v)
        self.pipeline.saved['_get_obs']=self.saved_capture;self.pipeline.saved['_wait_dom_loaded']=self.saved_wait
