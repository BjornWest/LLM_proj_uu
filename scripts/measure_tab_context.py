"""Read-only offline ablation: replace tab lines only, reconstruct all states."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from intent_browser.tab_context import TabContext
from intent_browser.input_budget import QwenInputCounter


def replay(old, delta):
    kind=delta['kind']
    if kind=='snapshot':result={k:deepcopy(delta[k]) for k in ('active_tab_id','tabs')}
    else:
        result=deepcopy(old)
        assert TabContext.identity(old)==(delta['id'] if kind=='unchanged' else delta['base'])
        if 'active_tab_id' in delta:result['active_tab_id']=delta['active_tab_id']
        for key,fields in delta.get('set',{}).items():result['tabs'].setdefault(key,{}).update(fields)
        for key in delta.get('removed',[]):del result['tabs'][key]
    assert TabContext.identity(result)==delta['id']
    return result


def measure(trace, output):
    rows=[json.loads(s) for s in (trace/'steps.jsonl').read_text().splitlines()]
    messages=deepcopy(rows[-1]['messages']);tools=next(r['model_request']['tools'] for r in reversed(rows) if r.get('model_request'))
    counter=QwenInputCounter(ROOT/'training/.cache/qwen38-tokenizer/tokenizer.json')
    before=counter(messages,tools);projector=TabContext();state=None;projections=[]
    pattern=r'(?m)^(BROWSER TABS [^\n]*?: )(\{[^\n]*\})$'
    def replace_line(match):
        nonlocal state
        original=json.loads(match[2]);delta=projector.project(original)
        state=replay(state,delta)
        assert state==TabContext.state(original)
        projector.commit(original);projections.append(delta)
        return match[1]+json.dumps(delta,ensure_ascii=False)
    for message in messages:
        if isinstance(message.get('content'),str):message['content']=re.sub(pattern,replace_line,message['content'])
        elif isinstance(message.get('content'),list):
            for part in message['content']:
                if part.get('type')=='text':part['text']=re.sub(pattern,replace_line,part['text'])
    assert projections
    after=counter(messages,tools)
    # All data outside the projected tab lines is byte-identical.
    def without_tabs(ms):
        ms=deepcopy(ms)
        for m in ms:
            if isinstance(m.get('content'),str):m['content']=re.sub(pattern,'',m['content'])
            elif isinstance(m.get('content'),list):
                for part in m['content']:
                    if part.get('type')=='text':part['text']=re.sub(pattern,'',part['text'])
        return ms
    assert without_tabs(messages)==without_tabs(rows[-1]['messages'])
    report={'scope':'Offline tab-line ablation only; original trace unchanged; not a model rollout or measured cache result',
        'trace':str(trace),'tokenizer':'local Qwen3.8 tokenizer via QwenInputCounter; complete request estimate',
        'before':before,'after':after,'saved_input_tokens':before['input_tokens']-after['input_tokens'],
        'reconstructed_states':len(projections),'kinds':{k:sum(d['kind']==k for d in projections) for k in ('snapshot','delta','unchanged')},
        'source_sha256':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (trace/'steps.jsonl',ROOT/'intent_browser/tab_context.py',Path(__file__).resolve())}}
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('x') as f:json.dump(report,f,indent=2)
    print(json.dumps(report,indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--trace',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();measure(a.trace,a.output)
