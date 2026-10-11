"""Pair an opt-in render export with the actual existing AX capture operation.

`observe(operation)` brackets exactly one caller-owned observation. The Harness
callback consumes that exact object; it never relocates equally worded trees or
looks up the latest state after the observation. Integration callers must wrap
their capture boundary explicitly. Unwrapped/stale observations remain unknown.
"""
from collections import OrderedDict
from copy import deepcopy

from .fact_exposure import object_digest
from .fact_render_capture import read_attestation, validate_attestation, capture, harness_source_packet


class FactSourceProvider:
    def __init__(self, page=None, *, enabled=False):
        if type(enabled) is not bool:
            raise TypeError('Explicit recording boolean required')
        self.enabled=enabled; self.page=page; self.latest=None; self.pairs=OrderedDict()
        self.cdp=None; self.diagnostics=[]

    def install(self):
        if not self.enabled:return
        if self.page is None:raise ValueError('Recording requires a page')
        self.page.expose_binding('__recordFactCommit',lambda sender,record:setattr(self,'latest',record))
        self.cdp=self.page.context.new_cdp_session(self.page)

    def _attest(self):
        # Reading the page also pumps the Playwright binding callback queue.
        # Navigation can replace #app/local state with a static review document.
        # Pump pending private commits before choosing the attestation reader.
        # Page.url is already available locally; same-document captures add no read.
        if self.latest is None or getattr(self.page,'url',self.latest['meta']['url'])!=self.latest['meta']['url']:
            self.page.evaluate('()=>location.href')
        if self.latest is None:raise ValueError('No committed render export')
        expected=self.latest
        attestation = getattr(self, 'attestation_function', None)
        actual=read_attestation(self.page,expected, **(
            {'attestation_function':attestation} if attestation is not None else {}))
        # evaluate() also dispatches pending private binding callbacks. Validate
        # the captured live state against the export available AFTER that pump,
        # rather than a previously read export from the preceding page/action.
        current=self.latest
        if current is None or current['meta']['state_key']!=expected['meta']['state_key']:
            raise ValueError('Render state scope changed during attestation')
        if any(current['meta'].get(k,default)!=expected['meta'].get(k,default)
               for k,default in (('root_selector','#app'),('state_kind','local_storage'))):
            raise ValueError('Render root or state kind changed during attestation')
        if ('render_state' in current['meta'])!=('render_state' in expected['meta']):
            raise ValueError('Render attestation mode changed during capture')
        if 'render_state' in current['meta'] and current['meta']['render_state'].get('schema')!='fact-render-state-browsergym-v1':
            raise ValueError('Unqualified render attestation schema')
        validate_attestation(actual,current)
        return deepcopy(current)

    def observe(self, operation):
        """Call operation exactly once; recording errors do not affect its result."""
        if not self.enabled:return operation()
        before=None
        try:before=self._attest()
        except Exception as exc:self._unknown(exc)
        observation=operation() # Browser/caller exceptions retain their ordinary behavior.
        self.pairs.pop(id(observation),None)
        if before is None:return observation
        try:
            after=self._attest()
            if object_digest(before)!=object_digest(after):raise ValueError('Render changed during observation')
            result=capture(self.page,self.cdp,before,snapshot_id=f'render-{before["revision"]}',
                           raw_ax=observation['axtree_object']['nodes'], **(
                               {'attestation_function':getattr(self,'attestation_function')}
                               if getattr(self,'attestation_function',None) is not None else {}))
            if object_digest(before)!=object_digest(self._attest()):raise ValueError('Render changed during DOM binding')
            raw_hash=object_digest(observation['axtree_object'])
            self.pairs[id(observation)]=(observation,raw_hash,result)
            self.pairs.move_to_end(id(observation))
            while len(self.pairs)>4:self.pairs.popitem(last=False)
        except Exception as exc:self._unknown(exc)
        return observation

    def _unknown(self, exc):
        self.diagnostics.append({'reason':'render_observation_pair_unavailable','error_type':type(exc).__name__})
        del self.diagnostics[:-16]

    def __call__(self, env, observation, context):
        if not self.enabled:raise ValueError('Recording disabled')
        pair=self.pairs.get(id(observation))
        if pair is None or pair[0] is not observation or pair[1]!=object_digest(observation['axtree_object']):
            raise ValueError('Observation was not paired with this render capture')
        packet=harness_source_packet(pair[2]['normalized'])
        for source in packet['sources']:source['binding']['snapshot_id']=context['snapshot_id']
        packet['private_context']['pairing']={'raw_ax_sha256':pair[1],
            'render_revision':pair[2]['commit']['revision'],'source':'bracketed_existing_observation',
            'extra_ax_captures':0,'scripted_delivery':False}
        return packet

    def result(self, observation):
        pair=self.pairs.get(id(observation))
        return pair[2] if pair is not None and pair[0] is observation else None

    def close(self):
        self.pairs.clear();self.latest=None
        if self.cdp is not None:self.cdp.detach();self.cdp=None
