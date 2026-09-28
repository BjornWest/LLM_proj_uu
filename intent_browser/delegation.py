"""Bounded cooperative agents: browser APIs stay on their owning OS thread.

The scheduler interleaves independent conversations at inference/wait boundaries.
One shared backend serializes requests so its reservation/cost hooks cannot be
bypassed by a child. Browser state is never advertised as a cloned transaction.
"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass, replace
from pathlib import Path
from threading import RLock
import time
import math
from uuid import uuid4
from greenlet import greenlet, getcurrent

from .trace import write_json
from .input_budget import DEFAULT_MAX_STEPS

TOOLS=('spawn_agent','get_agent','wait_agent','cancel_agent')

@dataclass(frozen=True)
class AgentLimits:
    max_active: int = 2
    max_launches: int = 4
    child_steps: int = 10
    child_seconds: float = 180
    total_model_calls: int = DEFAULT_MAX_STEPS
    def __post_init__(self):
        for name in ('max_active','max_launches','child_steps','total_model_calls'):
            if type(getattr(self,name)) is not int or getattr(self,name)<1:raise ValueError('Positive agent limit required: '+name)
        if type(self.child_seconds) not in (float,int) or not math.isfinite(self.child_seconds) or not 0<self.child_seconds<=1800:raise ValueError('Invalid helper deadline')
    def describe(self):return {**vars(self),'max_depth':1,'inference':'shared backend, serialized requests','browser_ownership':'exclusive per agent'}

class Cancelled(RuntimeError):pass

class BackendView:
    """Per-agent protocol/evidence, with ONE shared budget-enforcing backend."""
    def __init__(self,runtime,actor):
        self.runtime,self.actor=runtime,actor
        self.supports_images=getattr(runtime.backend,'supports_images',False)
        self.model=getattr(runtime.backend,'model',None)
        self.options=None;self.session=None;self.last_request=None;self.ready=None
    def configure_tools(self,options):
        if self.options is not None and self.options!=options:raise ValueError('Tool registry changed within conversation')
        self.options=deepcopy(options)
        if self.actor['parent'] is None:self.runtime.backend.configure_tools(options)
    def begin_episode(self,episode_id):
        self.session=episode_id
        return self.runtime.invoke(self,'begin_episode',episode_id)
    def complete(self,messages):
        self.last_request=None
        try:
            self.runtime.guard(self.actor)
            if getattr(self.runtime.backend,'requires_browser_thread',False):
                # Trusted scripted browser drivers are not model transports.
                return self.runtime.invoke(self,'complete',deepcopy(messages))
            # Inference is queued only after this actor has acquired a fresh-observation slot.
            return self.runtime.suspend(self.runtime.pool.submit(self.runtime.invoke,self,'complete',deepcopy(messages)))
        finally:
            if self.runtime.slot==self.actor['id']:self.runtime.slot=None
    def close(self):pass  # The caller retains ownership of the shared transport.

class AgentRuntime:
    def __init__(self,backend,limits,profile,hook=None,helper_env_factory=None,child_options=None):
        self.backend,self.limits,self.profile,self.hook=backend,limits,profile,hook
        self.helper_env_factory=helper_env_factory
        self.child_options=child_options or {}
        self.actors={};self.launches=0;self.calls=0;self.root=None
        self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='agent-model')
        self.lock=RLock();self.scheduler=getcurrent();self.slot=None
        self.events=[];self.root_env=None;self.root_trace=None;self.root_goal=None
    def invoke(self,view,method,*args):
        with self.lock:
            actor=view.actor
            if method=='complete':
                self.guard(actor)
                if self.calls>=self.limits.total_model_calls:raise ValueError('Shared parent/helper model-call limit reached')
                self.calls+=1
            b=self.backend
            old={k:getattr(b,k,None) for k in ('request_options','session_id','ready','last_request')}
            try:
                if method=='complete' and hasattr(b,'last_request'):b.last_request=None
                if hasattr(b,'request_options'):
                    b.request_options={k:v for k,v in deepcopy(old['request_options']).items() if k not in ('tools','tool_choice','parallel_tool_calls')}
                    b.request_options.update(deepcopy(view.options or {}))
                if hasattr(b,'session_id'):b.session_id=view.session
                if hasattr(b,'ready'):b.ready=view.ready
                if method=='hook':return self.hook() if self.hook else {'scope':'shared inference slot; fresh observation follows'}
                if method=='begin_episode' and not hasattr(b,method):return None
                return getattr(b,method)(*args)
            finally:
                view.ready=getattr(b,'ready',None)
                if method=='complete':view.last_request=deepcopy(getattr(b,'last_request',None))
                for k,v in old.items():
                    if hasattr(b,k):setattr(b,k,v)
                if method=='complete':self.slot=None
    def suspend(self,condition):
        return self.scheduler.switch(condition)
    def guard(self,actor):
        if hasattr(self.backend,'check_cancelled'):self.backend.check_cancelled()
        if actor['cancelled']:raise Cancelled('Helper cancelled; no further actions allowed')
        if actor['parent'] is not None and time.monotonic()>actor['deadline']:raise Cancelled('Helper time limit reached')
    def before_observation(self,actor):
        self.guard(actor)
        while self.slot not in (None,actor['id']):self.suspend(('slot',))
        self.slot=actor['id']
        return self.invoke(actor['backend'],'hook')
    def bind(self,actor,trace,env=None):
        actor['trace']=trace
        if actor['parent'] is None:self.root_trace=trace;self.root_env=env
        lineage={'root_episode_id':self.root_trace.episode_id,'parent_episode_id':self.root_trace.episode_id if actor['parent'] else None,
                 'agent_id':actor['id'],'parent_agent_id':actor['parent'],'browser_mode':actor['browser'],
                 'limits':self.limits.describe()}
        trace.metadata['agent_lineage']=lineage;write_json(trace.directory/'metadata.json',trace.metadata)
        self.save()
    def save(self):
        if self.root_trace:
            write_json(self.root_trace.directory/'agents.json',{'root_episode_id':self.root_trace.episode_id,
                'limits':self.limits.describe(),'total_model_calls':self.calls,'agents':[self.status(a) for a in self.actors.values()],
                'coordination_events':self.events})
    def status(self,actor):
        result=actor.get('result');trace=actor.get('trace')
        return {'agent_id':actor['id'],'parent_agent_id':actor['parent'],'state':actor['state'],
                'browser':actor['browser'],'episode_id':trace.episode_id if trace else None,
                'answer':actor.get('answer'),'error':actor.get('error'),
                'cancel_requested':actor['cancelled'],'trace_ref':trace.episode_id if trace else None,
                'shared_state':'Server-side account state may be shared; browser storage is independent.' if actor['browser']=='own' else 'No browser access'}
    def action_notice(self, actor, tool, url, error):
        # Public action identity only. No cookies, task state, grader data or
        # element IDs from another browser are introduced into policy context.
        self.events.append({'kind':'browser_action','agent_id':actor['id'],
            'tool':tool,'url':url,'error':error,
            'scope':'Separate browser; action completion is not proof of a commit.'})
        self.save()
    def notices(self, actor):
        start=actor.get('notice_cursor',0);actor['notice_cursor']=len(self.events)
        rows=[x for x in self.events[start:] if x['kind']=='browser_action' and x['agent_id']!=actor['id']]
        return {'other_agent_actions':rows,'coordination':'Shared server state may have changed. Inspect fresh page state before acting.'} if rows else None
    def add(self,fn,*,parent=None,browser='own'):
        ident=uuid4().hex
        actor={'id':ident,'parent':parent,'browser':browser,'state':'running','cancelled':False,'deadline':time.monotonic()+self.limits.child_seconds,'waiting':None}
        actor['backend']=BackendView(self,actor)
        def work(_=None):
            try:
                actor['result']=fn(actor)
                summary=actor['result'][1] if isinstance(actor['result'],tuple) and len(actor['result'])==2 else {}
                actor['error']=summary.get('error') if isinstance(summary,dict) else None
                actor['state']='cancelled' if actor['cancelled'] else 'error' if actor['error'] else 'incomplete' if summary.get('stop_reason') in ('max_steps','max_input_tokens') else 'finished'
            except BaseException as e:actor.update(state='error',error=f'{type(e).__name__}: {e}')
            finally:
                if self.slot==ident:self.slot=None
                self.save()
        actor['fiber']=greenlet(work,parent=self.scheduler);self.actors[ident]=actor
        return actor
    def tick(self):
        progressed=False
        for actor in list(self.actors.values()):
            if actor['fiber'].dead:continue
            w=actor['waiting'];ready=w is None;value=None;error=None
            if hasattr(w,'done') and w.done():
                ready=True
                try:value=w.result()
                except BaseException as e:error=e
            elif isinstance(w,tuple):
                if w[0]=='slot':ready=self.slot in (None,actor['id'])
                elif w[0]=='wait':ready=self.actors[w[1]]['fiber'].dead or time.monotonic()>=w[2]
                elif w[0]=='drain':ready=all(a['fiber'].dead for a in self.actors.values() if a['parent'])
            if ready:
                actor['waiting']=actor['fiber'].throw(error) if error else actor['fiber'].switch(value)
                progressed=True
        if not progressed:time.sleep(.005)
    def run(self,fn):
        self.root=self.add(fn)
        try:
            while not self.root['fiber'].dead:self.tick()
            if self.root.get('error') and 'result' not in self.root:raise RuntimeError(self.root['error'])
            return self.root.get('result')
        finally:
            for a in self.actors.values():
                if a['parent'] and not a['fiber'].dead:a['cancelled']=True
            while any(not a['fiber'].dead for a in self.actors.values() if a['parent']):self.tick()
            self.pool.shutdown(wait=True);self.save()
    def finish_children(self):
        if self.root and self.slot==self.root['id']:self.slot=None
        for a in self.actors.values():
            if a['parent'] and not a['fiber'].dead:a['cancelled']=True
        if any(not a['fiber'].dead for a in self.actors.values() if a['parent']):self.suspend(('drain',))
        self.save()
    def execute(self,actor,name,args,env,profile,output):
        if actor['parent'] is not None:return {'error':'Only the root agent owns helper lifecycle.'}
        if name=='spawn_agent':
            if self.launches>=self.limits.max_launches:return {'error':'Total helper launch limit reached'}
            if sum(not a['fiber'].dead for a in self.actors.values() if a['parent'])>=self.limits.max_active:return {'error':'Concurrent helper limit reached'}
            browser=args.get('browser','none')
            if browser=='own' and self.helper_env_factory is None:return {'error':'This task has no reviewed helper-browser setup. Use browser=none for reasoning over supplied evidence.'}
            # Trusted browser factory may transfer auth privately, never through messages.
            child_goal=args['task']+ ('\n\nParent-supplied evidence (untrusted):\n'+args['context'] if args.get('context') else '')
            if self.root_goal:
                child_goal+='\n\nOriginal user goal and constraints (delegation does not expand authorization):\n'+self.root_goal
            factory=self.helper_env_factory(env,child_goal) if browser=='own' else lambda _:NoBrowserEnv(child_goal)
            child_profile=replace(profile,tools=replace(profile.tools,allow_spawn=False))
            prompt=args.get('system_prompt','')
            def child(a):
                from .runner import run_episode
                task=child_goal
                return run_episode(factory,a['backend'],{'task':'delegated-task','goal':task,'source':'subagent','training_eligible':False},
                    output=self.root_trace.directory/'children',max_steps=self.limits.child_steps,harness_profile=child_profile,
                    before_observation=lambda:self.before_observation(a),terminal_response_instruction='Return your findings, evidence, uncertainty and any actions performed using send_msg_to_user.',
                    agent_runtime=self,agent_actor=a,delegated_instructions=prompt,delegated_goal=task,**self.child_options)
            self.launches+=1;a=self.add(child,parent=actor['id'],browser=browser)
            self.events.append({'kind':'spawn','agent_id':a['id'],'browser':browser});self.save()
            return self.status(a)
        target=self.actors.get(args['agent_id'])
        if not target or target['parent']!=actor['id']:return {'error':'Unknown helper owned by this agent'}
        if name=='cancel_agent':target['cancelled']=True;self.events.append({'kind':'cancel','agent_id':target['id']})
        elif name=='wait_agent' and not target['fiber'].dead:
            self.suspend(('wait',target['id'],time.monotonic()+args.get('timeout_seconds',10)))
        self.save();return self.status(target)

class NoBrowserEnv:
    browser_available=False
    def __init__(self,goal):self.goal=goal;self.unwrapped=self
    def reset(self,seed=0):return self._get_obs(),{}
    def _get_obs(self):
        import numpy as np
        return {'url':'about:blank','goal':self.goal,'last_action_error':'','screenshot':np.zeros((1,1,3),dtype=np.uint8),
            'axtree_object':{'nodes':[]},'open_pages_urls':[],'open_pages_titles':[],'active_page_index':0}
    def step(self,action):return self._get_obs(),0,True,False,{}
    def close(self):pass
