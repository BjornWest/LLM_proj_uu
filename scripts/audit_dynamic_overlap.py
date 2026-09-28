"""Read-only saved acceptance audit; no browser, provider, or credential use."""
import argparse
from datetime import datetime
import gzip
import hashlib
import json
from pathlib import Path

from tokenizers import Tokenizer

def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def lines(path):return [json.loads(s) for s in path.read_text().splitlines()]

def audit(root):
    suites=['matrix-4','windows-click-1','windows-late-change','windows-document-change','large-disabled','large-enabled']
    artifacts={};records=[];sources=None
    tokenizer=Tokenizer.from_file('training/.cache/qwen38-tokenizer/tokenizer.json')
    for suite in suites:
        path=root/suite/'report.json';report=json.loads(path.read_text());assert report['passed']
        artifacts[str(path)]=digest(path)
        current={name:digest(Path(name)) for name in report['source_sha256']}
        assert current==report['source_sha256'],suite
        if sources is None:sources=current
        else:assert sources==current
        for case in report['cases']:
            trace=Path(case['trace']);steps=lines(trace/'steps.jsonl');events=lines(trace/'events.jsonl')
            for p in trace.rglob('*'):
                if p.is_file():artifacts[str(p)]=digest(p)
            for step in steps:
                pipeline=step['observation_pipeline'];request=step['model_request']
                assert request['messages']==step['messages']
                assert hashlib.sha256(json.dumps(step['messages'],ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()==step['messages_sha256']
                if step.get('model_response') and not step.get('model_error_http_status'):
                    assert step['model_response']['usage']['cost']==0
                    assert all(x['confirmed'] for x in step['policy_delivery']['items'])
                if pipeline['overlapped']:
                    assert pipeline['barrier_seconds']>=pipeline['backend_end_seconds']
                    assert pipeline['barrier_seconds']>=pipeline['prefetch_end_seconds']
                    if case['case']=='fast_model':assert pipeline['backend_end_seconds']<pipeline['prefetch_end_seconds']
                    delivered=(trace/step['observation']['text']).read_text()
                    assert 'Shallow main-document orientation' in delivered
                    preview=json.loads(gzip.decompress((trace/step['observation']['raw']).read_bytes()))
                    assert preview['dom_object'] is None and preview['observation_capture']['coverage']=='partial'
                    assert len(preview['axtree_object']['nodes'])<=64
                    bg=pipeline.get('artifact')
                    if bg:
                        raw=json.loads(gzip.decompress((trace/bg['raw']).read_bytes()))
                        assert len(raw['axtree_object']['nodes'])>len(preview['axtree_object']['nodes'])
                        assert 'not itself delivered to policy' in (trace/bg['text']).read_text()
                        assert bg not in [step['observation']]
                if pipeline.get('invalidated'):
                    assert all(not c['action_dispatch_started'] for c in step['batch_calls'])
                if step.get('batch_stop_reason')=='human_message_pending':
                    assert all(not c['action_dispatch_started'] for c in step['batch_calls'])
            assert next(i for i,e in enumerate(events) if e['event']=='evaluation_completed')<next(i for i,e in enumerate(events) if e['event']=='environment_close_started')
            first=steps[0];pipe=first['observation_pipeline']
            start=next(e for e in events if e['event']=='decision_observation_started')
            model=next(e for e in events if e['event']=='model_started')
            elapsed=(datetime.fromisoformat(model['timestamp'])-datetime.fromisoformat(start['timestamp'])).total_seconds()
            records.append({'suite':suite,'case':case['case'],'windows':case['windows'],
                'steps':len(steps),'trace':str(trace),
                'first_request_start_after_decision_started_seconds':elapsed+pipe['backend_start_seconds'],
                'first_decision_observation_tokens':len(tokenizer.encode((trace/first['observation']['text']).read_text(),add_special_tokens=False).ids),
                'scope':'Local Qwen3.8 tokenizer, delivered observation text only; complete request differs',
                'overlapped':pipe['overlapped']})
    return {'passed':True,'paid_model_calls':0,'cases':records,'source_sha256':sources,
            'artifacts_sha256':artifacts,'tokenizer_sha256':digest(Path('training/.cache/qwen38-tokenizer/tokenizer.json')),
            'limitations':['Mock inference only','Partial main-document previews change policy context',
                'Reset, post-action and mutation guards still perform native capture','Windows child-frame limitations unchanged']}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=Path('.local/dynamic-overlap-integration'))
    p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    report=audit(args.root)
    with args.output.open('x') as f:json.dump(report,f,indent=2)
    print(json.dumps({'passed':True,'cases':len(report['cases']),'artifacts':len(report['artifacts_sha256'])}))
