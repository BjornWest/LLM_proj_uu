"""Evidence-only completion classification. Never repair JSON or infer an answer."""
import json


def completion_diagnostic(raw, request):
    if not isinstance(raw,dict):return None
    choices=raw.get('choices')
    if not isinstance(choices,list) or len(choices)!=1 or not isinstance(choices[0],dict):return None
    choice=choices[0];usage=raw.get('usage') or {};request=request or {}
    if not isinstance(usage,dict) or not isinstance(request,dict):return None
    cap=request.get('max_tokens');used=usage.get('completion_tokens')
    reached=type(cap) is int and cap>0 and type(used) is int and used>=cap
    finish=choice.get('finish_reason');native=choice.get('native_finish_reason')
    reported=finish=='length' or native=='length'
    if not reached and not reported:return None
    message=choice.get('message') or {};calls=message.get('tool_calls') if isinstance(message,dict) else None
    invalid=[]
    if isinstance(calls,list):
        for index,call in enumerate(calls):
            function=call.get('function') if isinstance(call,dict) else None
            args=function.get('arguments') if isinstance(function,dict) else None
            if isinstance(args,str) and len(args)<=1_000_000:
                try:json.loads(args)
                except json.JSONDecodeError as exc:
                    invalid.append({'call_index':index,'line':exc.lineno,'column':exc.colno,'parse_error':exc.msg})
    probable=reached and bool(invalid)
    return {'kind':('reported_incomplete_output' if reported else
                    'probable_output_truncation' if probable else 'output_limit_reached'),
            'finish_reason':finish,'native_finish_reason':native,
            'completion_tokens':used,'max_tokens':cap,
            'reasoning_tokens':(usage.get('completion_tokens_details') or {}).get('reasoning_tokens')
                if isinstance(usage.get('completion_tokens_details'),dict) else None,
            'invalid_argument_json':invalid,'retry_unchanged':False if reported or probable else None,
            'scope':'Provider-reported token usage; probable is not proof of causation. Raw response unchanged.'}
