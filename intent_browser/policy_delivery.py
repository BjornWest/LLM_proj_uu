"""Shared, private provenance for page evidence selected into policy requests.

No substring searches over goals or model-written prose. Conversation components
bind registered evidence to exact message spans. Delivery checks compare those
spans against the retained backend request and distinguish acknowledgement from
transport uncertainty. Adapters can interpret the resulting records separately.
"""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json

from .trace import write_json


def text_hash(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


class PolicyDelivery:
    def __init__(self, trace):
        self.trace = trace
        self.sources = {}
        self.confirmed = set()

    def register(self, kind, text, *, step, provenance=None, fact_output=None):
        if kind not in {'page_observation','browser_feedback','browser_update','search_result','ax_result','vision_result','data_result','batch_result','delegation_result','helper_result','clarification_result', 'memory_result', 'human_tab_result', 'human_message', 'site_discovery_result'}:
            raise ValueError('Unsupported policy evidence kind')
        key = f'content-{len(self.sources):04d}'
        filename=f'policy-{key}.json'
        record={'id':key, 'kind':kind, 'text':text, 'sha256':text_hash(text),
                'created_step':step, 'created_at':datetime.now(timezone.utc).isoformat(),
                'provenance':deepcopy(provenance or {}), 'artifact':filename}
        recorder=getattr(self,'fact_recorder',None)
        if recorder is not None:
            record['provenance']['fact_projection_artifact']=recorder.observe(recorder.register,record,fact_output)
        self.sources[key]=record
        write_json(self.trace.directory/filename, record)
        return key

    def record(self, event, bindings, *, acknowledged, recipient='main'):
        request=event.get('model_request')
        retained=isinstance(request,dict) and isinstance(request.get('messages'),list)
        messages=request['messages'] if retained else event.get('messages')
        scope=('retained_request_completion' if retained else 'local_backend_completion') if acknowledged else (
            'attempted_request_unconfirmed' if retained else 'no_retained_request_unconfirmed')
        items=[]
        for binding in bindings:
            source=self.sources[binding['content_id']]
            aligned=False
            try:
                content=messages[binding['message_index']]['content']
                if isinstance(content,list) and content and content[0].get('type') == 'text':
                    content=content[0].get('text')
                aligned=(isinstance(content,str) and
                         content[binding['start']:binding['end']] == source['text'])
            except (KeyError,IndexError,TypeError): pass
            confirmed=bool(acknowledged and aligned)
            identity=(recipient,source['id'])
            items.append({'content_id':source['id'], 'kind':source['kind'],
                          'artifact':source['artifact'], 'sha256':source['sha256'],
                          'message_span':deepcopy(binding), 'aligned':aligned,
                          'confirmed':confirmed, 'first_confirmed_delivery':confirmed and identity not in self.confirmed})
            if confirmed: self.confirmed.add(identity)
        record={'schema_version':1, 'step':event['step'], 'recipient':recipient,
                'recorded_at':datetime.now(timezone.utc).isoformat(),
                'scope':scope, 'backend_completion_returned':acknowledged,
                'http_dispatch_observed_by_ledger':False,
                'messages_sha256':text_hash(json.dumps(messages,ensure_ascii=False,sort_keys=True,separators=(',',':'))),
                'items':items}
        filename='policy-delivery.jsonl'
        with (self.trace.directory/filename).open('a',encoding='utf-8') as file:
            file.write(json.dumps(record,ensure_ascii=False)+'\n')
        self.trace.event('core_policy_delivery_recorded',step=event['step'],artifact=filename,scope=scope)
        recorder=getattr(self,'fact_recorder',None)
        if recorder is not None:recorder.observe(recorder.delivery,record)
        return record
