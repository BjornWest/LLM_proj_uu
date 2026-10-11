"""Order-preserving frozen95 Training relay counter; no model generation."""
from copy import deepcopy
from hashlib import sha256
import json
import ast
import math
import importlib.metadata
import os
from pathlib import Path
import time
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()


def digest(value):return sha256(canonical(value)).hexdigest()


def wire_bytes(value):
    """Match frozen httpx0.28.1 JSON bytes, retaining nested schema insertion order."""
    return json.dumps(value,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf-8')


def wire_digest(value):return sha256(wire_bytes(value)).hexdigest()


def number(value):
    if type(value) not in {int,float} or not math.isfinite(value):raise ValueError('Finite deadline required')
    return value


def checked(pin):
    if not isinstance(pin,dict) or set(pin)!={'path','sha256'}:raise ValueError('Exact evidence pin required')
    data=Path(pin['path']).read_bytes()
    if sha256(data).hexdigest()!=pin['sha256']:raise ValueError('Pinned live evidence changed')
    return json.loads(data)


def hash_value(value):
    if not isinstance(value,str) or len(value)!=64 or any(c not in '0123456789abcdef' for c in value):raise ValueError('Actual SHA256 required')
    return value



def serving_limits(live):
    """Recognize historical limits or explicit native context/output headroom.

    Native ``isl`` is a compatibility alias for context minus one output token,
    not an independent policy cap. Every real request is sized by the factory.
    """
    context, isl = live.get('server_context'), live.get('isl')
    if type(context) is not int or type(isl) is not int:
        raise ValueError('Integer serving limits required')
    admission = live.get('input_admission')
    if (context, isl) == (131072, 100000) and admission is None:
        return context, isl, '100000-input-boundary'
    if (context, isl) == (262144, 262143) and admission == {
            'scope': 'native-context-output-headroom', 'minimum_output_tokens': 1} and type(admission.get('minimum_output_tokens')) is int:
        return context, isl, 'native-context-input-boundary'
    raise ValueError('Historical or explicit native context/headroom binding required')


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):raise ValueError('Relay redirects forbidden')


class Bridge:
    def __init__(self,live,deadline,*,exchange=None,mono=time.monotonic,utc=time.time,environ=None):
        if importlib.metadata.version('httpx')!='0.28.1':raise ValueError('Qualified httpx0.28.1 serialization required')
        self.live=deepcopy(live);self.deadline=number(deadline);self.mono,self.utc=mono,utc
        self.context,self.input_limit,self.boundary_probe=serving_limits(live)
        self.environ=os.environ if environ is None else environ
        self.base=live.get('relay_base_url',live.get('base_url'));u=urlsplit(self.base or '')
        if live.get('base_url',self.base)!=self.base:raise ValueError('Relay URL aliases differ')
        if u.scheme!='http' or u.hostname not in {'127.0.0.1','::1'} or not u.port or u.path!='/v1' or u.username or u.password or u.query or u.fragment:raise ValueError('Numeric loopback explicit-port /v1 required')
        self.origin=self.base[:-3]
        if live.get('dispatch_authorized') is not True or 'api_key' in live:raise ValueError('Explicit live grant and no embedded secret required')
        envname=live.get('api_key_env')
        if envname is not None and (not isinstance(envname,str) or not envname or not envname.replace('_','').isalnum()):raise ValueError('Named relay auth environment required')
        self.key=self.environ.get(envname) if envname is not None else None
        if envname is not None and (not self.key or '\n' in self.key or '\r' in self.key):raise ValueError('Relay auth unavailable')
        self.gates=checked(live['qualification_receipt']);self.serving=checked(live['serving_binding'])
        self.deployment=checked(live['deployment_receipt'])
        self.processor=checked(live['processor_parity_proof'])
        self.count_proof=checked(live['complete_wire_count_parity_proof'])
        self.identity=deepcopy(live['identity']);self.gpu_deadline=number(live['gpu_deadline_utc'])
        self.server=deepcopy(self.deployment['qualification'])
        if 'server_identity' in self.deployment and checked(self.deployment['server_identity'])!=self.server:raise ValueError('Deployment server identity receipt differs')
        self.session=live['serving_session_id']
        if not isinstance(self.session,str) or not self.session or not isinstance(live.get('pilot_id'),str) or not live['pilot_id']:raise ValueError('Actual serving/pilot ID required')
        if not self.gates.get('ready') is True or self.gates.get('identity')!=self.identity or self.gates.get('server_context')!=self.context or self.gates.get('isl')!=self.input_limit or any(self.gates.get(k) is not True for k in ['vision','native_tools','exact_complete_request_counter']):raise ValueError('Actual qualified gates required')
        if self.server.get('server_context')!=self.context or self.server.get('isl')!=self.input_limit:raise ValueError('Deployment limits mismatch')
        if self.serving['model']['repository']!='Qwen/Qwen3.8-27B-FP8' or self.serving['model']['revision']!='017b9c7af6b5689d5dd426a76e0bc077eb5ca20a' or self.serving['first_case']['commit']!='95e9ac988ea515f7194cbdc82ae327e248fc94fa':raise ValueError('Approved model/revision/source mismatch')
        if self.serving['tokenizer']['tokenizer.json']['sha256']!='0997f410c57a1f4e53b09e4be8f4a172d90edd9564368fb0847030937229b9f3' or self.serving['tokenizer']['chat_template.jinja']['sha256']!='c3cf9e34abf4f9e36c2d72165aa9c132d3e2a725b6c2586aaa3a8af9d7a81041':raise ValueError('Approved tokenizer/template mismatch')
        expected=dict(model=self.serving['model']['repository'],serving_revision=self.serving['model']['revision'],tokenizer_sha256=self.serving['tokenizer']['tokenizer.json']['sha256'],template_sha256=self.serving['tokenizer']['chat_template.jinja']['sha256'],image_processor_sha256=self.identity['image_processor_sha256'],tool_parser='qwen3_coder',source_commit='95e9ac988ea515f7194cbdc82ae327e248fc94fa')
        for name in ['tokenizer_sha256','template_sha256','image_processor_sha256']:hash_value(expected[name])
        if self.identity!=expected or self.server.get('identity')!=expected:raise ValueError('Serving/qualified identity differs')
        if self.processor.get('passed') is not True or self.processor.get('official_processor')!=self.server.get('processor') or self.processor.get('image_processor_sha256')!=self.identity['image_processor_sha256'] or digest(self.server['processor'])!=self.identity['image_processor_sha256']:raise ValueError('Actual official processor parity/digest differs')
        # Root-reviewed count proof also binds Training tokenize_payload projection
        # and prompt independence of output controls/parallel flag. No count is
        # invented from these flags; every distinct prompt uses actual /tokenize.
        if self.count_proof.get('passed') is not True or self.count_proof.get('output_controls_prompt_independent') is not True or self.count_proof.get('parallel_tool_calls_prompt_independent') is not True or self.count_proof.get('ready') is not True or self.count_proof.get('identity')!=self.identity or self.count_proof.get('exact_complete_request_counter') is not True:raise ValueError('Actual passed wire count proof missing')
        if self.count_proof.get('wire_serialization')!='json-insertion-order-v1' or self.count_proof.get('counter_wire_function_sha256')!='f21b9f8becf3a8713ad3bcf59d610cc59f97406a5d17b6396013191dd5ad2de3':raise ValueError('Order-preserving wire qualification proof required')
        probes=self.count_proof.get('parity_probes')
        if not isinstance(probes,list) or not probes:raise ValueError('Actual parity probes required')
        labels={row.get('probe') for row in probes}
        if not {'image-64x64','image-1280x720','image-2048x1024','retained-history',self.boundary_probe}<=labels:raise ValueError('Missing qualified modality/history/ISL probes')
        for row in probes:
            if type(row.get('input_tokens')) is not int or row['input_tokens']<0 or row.get('server',{}).get('count')!=row['input_tokens'] or row['server'].get('max_model_len')!=self.context:raise ValueError('Parity server count differs')
            hash_value(row['server'].get('token_ids_sha256'))
            if row.get('probe') in {'retained-history',self.boundary_probe}:
                if not isinstance(row.get('generation'),dict) or row['generation'].get('prompt_tokens')!=row['input_tokens']:raise ValueError('Actual GPU parity usage missing')
        if next(row for row in probes if row['probe']==self.boundary_probe)['input_tokens']!=self.input_limit:raise ValueError('Actual ISL boundary probe differs')
        if self.deployment.get('serving_session_id')!=self.session or self.deployment.get('deadline')!=self.gpu_deadline or self.server.get('serving_session_id')!=self.session or self.server.get('deadline')!=self.gpu_deadline:raise ValueError('Pinned deployment lifetime differs')
        relay=live.get('relay_source')
        if not isinstance(relay,dict) or set(relay)!={'path','sha256'}:raise ValueError('Explicit frozen Training relay source pin required')
        if not isinstance(relay['path'],str) or not Path(relay['path']).is_absolute():raise ValueError('Absolute frozen relay source path required')
        if relay['sha256']!=self.count_proof['tokenize_projection_source_sha256']:raise ValueError('Parity proof relay source differs')
        raw=Path(relay['path']).read_bytes()
        if sha256(raw).hexdigest()!=relay['sha256']:raise ValueError('Reviewed Training relay source changed')
        functions=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='tokenize_payload']
        if len(functions)!=1 or sha256(ast.get_source_segment(raw.decode('utf-8'),functions[0]).encode()).hexdigest()!='6b4dc9a1ab5b10217a6b475f2aa3989941e41f5f5a080a9873f970fb51380955':raise ValueError('Unreviewed tokenize_payload projection semantics')
        self.relay_pin=deepcopy(relay)
        history=next(row for row in probes if row['probe']=='retained-history')
        if history.get('alternate_controls_generation',{}).get('prompt_tokens')!=history['input_tokens']:raise ValueError('Actual output/parallel control parity usage missing')
        self.proof=digest({k:live[k] for k in ['qualification_receipt','deployment_receipt','processor_parity_proof','complete_wire_count_parity_proof']})
        self.opener=build_opener(ProxyHandler({}),NoRedirect())
        self.exchange=exchange or self.http
        self.cache=None;self.last_mono=None;self.last_utc=None
        self.remaining()

    def remaining(self):
        m,u=self.mono(),self.utc();number(m);number(u)
        if self.last_mono is not None and (m<self.last_mono or u<self.last_utc):raise ValueError('Clock moved backwards')
        self.last_mono,self.last_utc=m,u
        n=min(self.deadline-m,self.gpu_deadline-u)
        if n<=0:raise TimeoutError('Episode/GPU deadline reached')
        return n

    def http(self,method,path,body=None):
        timeout=min(30,self.remaining())
        headers={'Content-Type':'application/json'}
        if self.key is not None:headers['Authorization']='Bearer '+self.key
        request=Request(self.origin+path,data=wire_bytes(body) if body is not None else None,headers=headers,method=method)
        try:
            with self.opener.open(request,timeout=timeout) as response:
                if response.status!=200:raise RuntimeError('Relay returned non200')
                data=response.read(8*1024*1024+1)
                if len(data)>8*1024*1024:raise ValueError('Relay response bound exceeded')
                result=json.loads(data) if data else None
        except Exception:
            # Credential/prompt/server-body details must not enter receipts/logs.
            raise RuntimeError('Private relay request failed; no retry') from None
        self.remaining()
        return result

    def readiness(self):
        self.remaining()
        for name in ['qualification_receipt','serving_binding','deployment_receipt','processor_parity_proof','complete_wire_count_parity_proof']:checked(self.live[name])
        if 'server_identity' in self.deployment:checked(self.deployment['server_identity'])
        relay=Path(self.relay_pin['path']).read_bytes()
        if sha256(relay).hexdigest()!=self.relay_pin['sha256']:raise ValueError('Reviewed relay source changed')
        self.exchange('GET','/health')
        current=self.exchange('GET','/qualification')
        if current!=self.server:raise ValueError('Live qualification/server lifetime changed')
        self.remaining()
        observed=self.utc();expiry=min(self.gpu_deadline,observed+self.remaining(),observed+30)
        return dict(ready=True,identity=deepcopy(self.identity),server_context=self.context,isl=self.input_limit,vision=True,native_tools=True,exact_complete_request_counter=True,issued_at_utc=observed,expires_at_utc=expiry,serving_session_id=self.session,qualification_proof_sha256=self.proof)

    def count(self,request):
        ready=self.readiness()
        allowed={'model','messages','temperature','max_tokens','stream','tools','tool_choice','parallel_tool_calls'}
        if not isinstance(request,dict) or set(request)-allowed or not {'model','messages','temperature','max_tokens','stream'}<=set(request):raise ValueError('Unqualified wire fields')
        if request['model']!=self.identity['model'] or request['temperature']!=0 or request['stream'] is not False or not isinstance(request['messages'],list) or type(request['max_tokens']) is not int or request['max_tokens']<=0:raise ValueError('Unexpected generation wire contract')
        if request.get('tool_choice','auto') not in {'auto','none'} or ('parallel_tool_calls' in request and type(request['parallel_tool_calls']) is not bool):raise ValueError('Unqualified native options')
        if request.get('tools') and request.get('tool_choice')=='none':raise ValueError('Training rejects tools with tool_choice none')
        # Conservatively include top-level/message ordering too. Reordering these
        # may cause an extra count; source95 runner/factory have identical order.
        prompt=deepcopy(request);prompt.pop('max_tokens');key=(wire_digest(prompt),digest(self.identity),ready['serving_session_id'],self.proof)
        reused=self.cache is not None and self.cache['key']==key and self.mono()-self.cache['counted_at_monotonic']<=30
        if not reused:
            payload={k:deepcopy(request[k]) for k in ['model','messages']}
            # Count-only mirror of vLLM ChatCompletionRequest alias precedence.
            # Actual generation/request/history and full request hashes stay raw.
            for message in payload['messages']:
                reasoning_content=message.pop('reasoning_content',None)
                if reasoning_content is not None and message.get('reasoning') is None:
                    message['reasoning']=reasoning_content
            if request.get('tools') and request.get('tool_choice','auto')!='none':payload['tools']=deepcopy(request['tools'])
            raw=self.exchange('POST','/tokenize',payload)
            if not isinstance(raw,dict) or type(raw.get('count')) is not int or raw['count']<0 or raw.get('max_model_len')!=self.context:raise ValueError('Actual /tokenize count/context invalid')
            hash_value(raw.get('token_ids_sha256'))
            self.cache={'key':key,'counted_at_monotonic':self.mono(),'counted_at_utc':self.utc(),'request_sha256':wire_digest(request),'tokenize_payload_sha256':wire_digest(payload),'raw':deepcopy(raw)}
        self.readiness() # afterRPC/reuse, fresh health/identity and hard deadline
        measured=self.cache
        return dict(input_tokens=measured['raw']['count'],identity=deepcopy(self.identity),exact_complete_request=True,method='actual-training-relay-vllm-tokenize',token_ids_sha256=measured['raw']['token_ids_sha256'],request_sha256=wire_digest(request),semantic_request_sha256=digest(request),wire_serialization='json-insertion-order-v1',counted_request_sha256=measured['request_sha256'],prompt_sha256=key[0],tokenize_payload_sha256=measured['tokenize_payload_sha256'],count_receipt=deepcopy(measured['raw']),qualification_proof_sha256=self.proof,qualification_receipt=deepcopy(self.live['qualification_receipt']),deployment_receipt=deepcopy(self.live['deployment_receipt']),processor_parity_proof=deepcopy(self.live['processor_parity_proof']),complete_wire_count_parity_proof=deepcopy(self.live['complete_wire_count_parity_proof']),relay_source=deepcopy(self.relay_pin),reused_output_cap_only=reused,counted_at_utc=measured['counted_at_utc'],observed_at_utc=self.utc())

    def runner_count(self,messages,tools):
        # Exact accepted95 NativeToolConfig.request_options defaults: tools,
        # tool_choice auto, parallel_tool_calls False. No omitted native fields.
        return self.count(dict(model=self.identity['model'],messages=messages,temperature=0,max_tokens=self.context,stream=False,tools=tools,tool_choice='auto',parallel_tool_calls=False))


def build(*,live,deadline_monotonic):
    bridge=Bridge(live,deadline_monotonic)
    return dict(complete_request_counter=bridge.count,runner_input_counter=bridge.runner_count,readiness=bridge.readiness,expected_identity=deepcopy(bridge.identity),base_url=bridge.base,api_key=bridge.key)
