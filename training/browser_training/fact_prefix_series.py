"""Replay native transport at actual main-agent request boundaries.

Append order in events.jsonl, rather than wall time or step inequalities, bounds
capture inventory. The retained request and receipt are rechecked separately.
Missing/ambiguous lifecycle joins yield unknown inventory, never future credit.
This records cumulative delivered evidence, not memory or attention.
"""
import json
from pathlib import Path

from .fact_delivery_features import extract
from .fact_exposure import object_digest, require


def _boundaries(trace):
    path=trace/'events.jsonl'
    if not path.is_file():return {}
    captures=set(); starts={}; boundaries={}; ambiguous=set()
    for ordinal,line in enumerate(path.read_text().splitlines()):
        event=json.loads(line); kind=event.get('event')
        if kind=='fact_capture_recorded':
            artifact=event.get('artifact')
            if isinstance(artifact,str):captures.add(artifact)
        elif kind=='model_started':
            call=event.get('call_id')
            if not isinstance(call,str):continue
            if call in starts:ambiguous.add(call)
            starts[call]=(ordinal,frozenset(captures))
        elif kind=='model_completed':
            call=event.get('call_id'); request=event.get('model_request')
            if call not in starts or call in ambiguous or not isinstance(request,dict):continue
            messages=request.get('messages')
            if not isinstance(messages,list):continue
            key=(call,object_digest(messages))
            if key in boundaries:ambiguous.add(call)
            else:boundaries[key]=starts[call]
    return {k:v for k,v in boundaries.items() if k[0] not in ambiguous}


def extract_prefixes(trace, *, recipient='main', strict_render=False):
    trace=Path(trace).resolve(); path=trace/'policy-delivery.jsonl'
    if not path.is_file():
        return {'schema':'native-fact-prefix-series-v1','recipient':recipient,
                'status':'delivery_ledger_missing','prefixes':[],
                'task_requirement_joins':'not_bound','inventory_complete':False}
    boundaries=_boundaries(trace); prefixes=[]
    for index,line in enumerate(path.read_text().splitlines()):
        record=json.loads(line)
        if record.get('recipient')!=recipient:continue
        step=record['step']
        require(type(step) is int and step>=0,'Invalid policy prefix step')
        # Current model-* lifecycle events identify only the main runner.
        # Worker inventories need their own recipient-bound start event.
        boundary=boundaries.get((f'model-{step:03d}',record.get('messages_sha256'))) if recipient=='main' else None
        artifacts=boundary[1] if boundary is not None else frozenset()
        result=extract(trace,step=step,recipient=recipient,receipt_index=index,
                       capture_artifacts=artifacts, strict_render=strict_render)
        if boundary is None:result['diagnostics']['request_capture_boundary_unknown']=1
        prefixes.append({'step':step,'receipt_index':index,
            'messages_sha256':record.get('messages_sha256'),'scope':record.get('scope'),
            'acknowledged':record.get('backend_completion_returned') is True,
            'capture_boundary_status':'joined' if boundary is not None else 'unknown',
            'model_started_event_ordinal':boundary[0] if boundary else None,
            'native_coverage':result})
    return {'schema':'native-fact-prefix-series-v1','episode_id':trace.name,
            'recipient':recipient,'status':'replayed_request_receipts_with_qualified_boundaries',
            'prefixes':prefixes,'task_requirement_joins':'not_bound',
            'scope':'cumulative_confirmed_transport_through_receipt_not_attention_or_current_context_retention',
            'inventory_complete':False}
