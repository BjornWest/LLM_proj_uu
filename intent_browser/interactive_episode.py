"""Drive the ordinary runner over an external request/response transport.

All browser calls remain on the session's owning thread. Between RPC calls the
runner is suspended, not re-created, so its tools, reasoning and context stay
identical to the standalone harness. This module contains no inference or keys.
"""
from copy import deepcopy
import json
import time
from pathlib import Path
from greenlet import greenlet,getcurrent
from .backend import Completion,BackendResponseError
from .actions import parse_decision
from .runner import run_episode
from .standard_profile import standard_profile
from .retry_policy import DecisionRetryPolicy
from .input_budget import DEFAULT_MAX_STEPS, DEFAULT_MAX_INPUT_TOKENS

class BorrowedEnvironment:
    """Borrow one exclusively leased browser; never reset or close the site."""
    def __init__(self,env,goal,on_step):
        self.env=env;self.goal=goal;self.on_step=on_step;self.mapping=env.unwrapped.action_mapping
        self.unwrapped=self
    def __getattr__(self,name):return getattr(self.env.unwrapped,name)
    @property
    def action_mapping(self):return self.env.unwrapped.action_mapping
    @action_mapping.setter
    def action_mapping(self,value):self.env.unwrapped.action_mapping=value
    def _get_obs(self):
        obs=dict(self.env.unwrapped._get_obs());obs['goal']=self.goal;return obs
    def reset(self,seed=0):return self._get_obs(),{'borrowed_existing_browser':True,'reset_performed':False}
    def step(self,code):
        # Answers end this Ask, not the enclosing human browser session.
        if code.startswith('send_msg_to_user('):
            result=(self._get_obs(),0,False,False,{'scope':'answer to shared-browser Ask; no site action'})
        else:
            obs,reward,done,truncated,info=self.env.step(code)
            result=({**obs,'goal':self.goal},reward,done,truncated,info)
        self.on_step(code,result)
        return result
    def close(self):self.env.unwrapped.action_mapping=self.mapping

class ExternalBackend:
    supports_images=True
    requires_browser_thread=True
    def __init__(self,session):
        self.owner=session;self.request_options={};self.session_id=None;self.last_request=None
    def configure_tools(self,value):self.request_options=deepcopy(value)
    def begin_episode(self,ident):self.session_id=ident;return {'session_id':ident,'transport':'external transport, request recorded on receipt'}
    def check_cancelled(self):
        if self.owner.cancel_requested or self.owner.interrupted():
            raise RuntimeError('Shared-browser Ask interrupted; no further actions permitted')
    def complete(self,messages):
        expected={'messages':deepcopy(messages),'session_id':self.session_id,
            **{k:deepcopy(v) for k,v in self.request_options.items() if k in ('tools','tool_choice','parallel_tool_calls')}}
        self.last_request=None
        evidence=self.owner.park({'kind':'model_request',**expected})
        request=evidence.get('request');response=evidence.get('response')
        if not isinstance(request,dict) or any(request.get(k)!=v for k,v in expected.items()):
            raise ValueError('External request differs from the selected core policy input')
        self.last_request=deepcopy(request)
        if evidence.get('error'):
            raise BackendResponseError(str(evidence['error']),request,response,
                http_status=evidence.get('http_status'),retry_after=evidence.get('retry_after'))
        if not isinstance(response,dict):raise BackendResponseError('Missing external model response',request,response)
        choices=response.get('choices') or []
        text=choices[0].get('message',{}).get('content') if choices else ''
        return Completion(text or '',response,request)

class InteractiveEpisode:
    """One Ask conversation. observe/accept alternate; cancel never replays actions."""
    def __init__(self,env,goal,output,*,on_step=lambda code,result:None,max_steps=DEFAULT_MAX_STEPS,max_input_tokens=DEFAULT_MAX_INPUT_TOKENS,metadata=None,public_history=None,navigation_origins=(),interrupted=lambda:False):
        self.interrupted=interrupted
        self.owner=getcurrent();self.pending=None;self.result=None;self.error=None
        self.answer=None;self.actions=[];self.closed=False;self.parked=None;self.cancel_requested=False
        self.backend=ExternalBackend(self)
        self.borrowed=BorrowedEnvironment(env,goal,self._on_step)
        self.on_step=on_step;self.max_steps=max_steps
        def before_observation():
            if self.cancel_requested:raise RuntimeError('Shared-browser Ask cancelled')
            self.park({'kind':'ready_for_observation'})
            return {'scope':'RPC pacing completed before fresh browser capture'}
        def decision_wait(seconds):
            until=time.monotonic()+seconds
            self.park({'kind':'retry_wait','retry_wait_seconds':seconds})
            if self.cancel_requested:raise RuntimeError('Shared-browser Ask cancelled')
            if time.monotonic()<until:raise ValueError('Retry resumed before its wait completed')
        def run(_=None):
            try:
                self.result=run_episode(lambda _:self.borrowed,self.backend,
                    {'task':'shared-browser-ask','interaction_kind':'ask','goal':goal,'training_eligible':False,
                     'scope':'Existing user-controlled browser; no task reset or automatic task grading',**(metadata or {})},
                    output=output,max_steps=max_steps,max_input_tokens=max_input_tokens,harness_profile=standard_profile(navigation_origins=navigation_origins),retry_policy=DecisionRetryPolicy(),
                    before_observation=before_observation,decision_wait=decision_wait,
                    delegated_instructions=('Recorded previous activity is context, not permission to repeat completed actions.\n'+json.dumps(public_history,ensure_ascii=False)) if public_history else None,
                    terminal_response_instruction='Answer the current user request accurately using send_msg_to_user. Questions authorize inspection, not purchases or account changes.')
            except Exception as exc:self.error=f'{type(exc).__name__}: {exc}'
            finally:self.closed=True
            return {'kind':'finished','answer':self.answer,'error':self.error or (self.result[1].get('error') if self.result else None),
                'stop_reason':self.result[1].get('stop_reason') if self.result else None,
                'trace':str(self.result[0]) if self.result else None}
        self.fiber=greenlet(run,parent=self.owner)
    def park(self,value):
        self.parked=getcurrent()
        return self.owner.switch(value)
    def advance(self,value=None):
        return (self.parked or self.fiber).switch(value)
    def _on_step(self,code,result):
        self.actions.append(code)
        if code.startswith('send_msg_to_user('):self.answer=parse_decision(code).arguments['text']
        self.on_step(code,result)
    def observe(self):
        if self.closed:raise ValueError('Conversation already ended')
        if self.pending and self.pending['kind']=='model_request':raise ValueError('Model response still pending')
        self.pending=self.advance()
        if self.pending.get('kind')=='ready_for_observation':self.pending=self.advance()
        if self.pending.get('kind') not in ('model_request','finished'):raise RuntimeError('Unexpected runner boundary')
        return deepcopy(self.pending)
    def accept(self,evidence):
        if self.closed or not self.pending or self.pending.get('kind')!='model_request':raise ValueError('No pending model request')
        self.actions=[]
        self.pending=self.advance(deepcopy(evidence))
        if self.pending.get('kind') not in ('ready_for_observation','retry_wait','finished'):raise RuntimeError('Unexpected response boundary')
        return {**deepcopy(self.pending),'actions':list(self.actions),'answer':self.answer}
    def cancel(self,evidence=None):
        if self.closed:return self.result
        self.cancel_requested=True
        if evidence is not None and self.pending and self.pending.get('kind')=='model_request':
            value={**evidence,'error':evidence.get('error') or 'Shared-browser Ask interrupted; no further actions permitted'}
            self.accept(value)
        else:
            # No fabricated request or response for cancellation before dispatch.
            self.pending=(self.parked or self.fiber).throw(RuntimeError('Shared-browser Ask interrupted before next action'))
        while not self.fiber.dead:
            self.pending=(self.parked or self.fiber).throw(RuntimeError('Shared-browser Ask cancelled'))
        return self.result
