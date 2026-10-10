"""Replay retained decisions through the real harness on a NEW isolated world.

This executes browser actions, unlike read-only trace playback. No inference,
retry, oracle repair, request-prefix rewriting or response edits occur here.
"""
from copy import deepcopy
import json
from pathlib import Path

from .backend import Completion
from .checkpoint_browser import digest


def validate_rows(rows):
    for row in rows:
        if (row.get('error') or row.get('action_error') or row.get('model_response') is None or
                row.get('model_request') is None or row.get('kind') in ('checkpoint','input_limit')):
            raise ValueError('Ambiguous/failed/unexecuted decision cannot be auto-replayed')
        for call in row.get('batch_calls',[]):
            if (call.get('error') or call.get('action_error') or call.get('tool_error') or
                    call.get('batch_guard_error') or call.get('kind')=='skipped'):
                raise ValueError('Failed/partial batch cannot be auto-replayed')
        request=row['model_request']
        if request.get('messages')!=row['messages']:
            raise ValueError('Retained request differs from selected decision')


def selected_rows(trace,start=0,stop=None):
    rows=[json.loads(line) for line in (Path(trace)/'steps.jsonl').read_text().splitlines()]
    if (type(start) is not int or start<0 or start>=len(rows) or
            (stop is not None and (type(stop) is not int or stop<=start or stop>len(rows)))):
        raise ValueError('Invalid replay range')
    selected=rows[start:stop]
    validate_rows(selected)
    return deepcopy(selected)


class RecordedDecisionReplay:
    supports_images=True
    recorded_replay=True
    requires_browser_thread=True
    def __init__(self,rows,*,source):
        if not rows:raise ValueError('Replay requires recorded decisions')
        validate_rows(rows)
        self.rows=deepcopy(rows);self.source=str(source);self.calls=0;self.last_request=None
        self.replay_evidence=[]

    def configure_tools(self,value):self.options=deepcopy(value)

    def complete(self,messages):
        if self.calls>=len(self.rows):raise ValueError('Replay exhausted; no new inference or replay permitted')
        row=self.rows[self.calls]
        if messages!=row['messages']:raise ValueError('Replay request differs; no action replayed')
        for key,value in self.options.items():
            if row['model_request'].get(key)!=value:
                raise ValueError('Replay native tool configuration differs')
        self.last_request={'messages':deepcopy(messages),**deepcopy(self.options)}
        self.replay_evidence.append({'source':self.source,'source_step':row['step'],
            'messages_sha256':digest(messages),'response_sha256':digest(row['model_response']),
            'new_http_request':False,'new_inference':False})
        self.calls+=1
        return Completion(row['model_output'],deepcopy(row['model_response']),deepcopy(self.last_request))
