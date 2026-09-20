"""Read-only saved-run audit and compact batch timeline. No inference or replay."""
import argparse
from decimal import Decimal
import hashlib
import html
import json
from pathlib import Path

def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def text_content(m):
    c=m.get('content')
    return c if isinstance(c,str) else '\n'.join(p.get('text','') for p in c or [] if p.get('type')=='text')

def audit(root,output):
    output.mkdir(parents=True,exist_ok=False)
    case=read(root/'case.json');trace=Path(case['trace']);profile=read(root/'profile.json');budget=read(root/'budget.json')
    rows=[json.loads(l) for l in (trace/'steps.jsonl').read_text().splitlines()]
    assert len(rows)==len(budget['requests'])
    cost=Decimal(0);summaries=[];schemas=None;session=None
    for i,(row,ledger) in enumerate(zip(rows,budget['requests'])):
        req,res=row['model_request'],row['model_response']
        assert req==ledger['model_request'] and res==ledger['model_response']
        assert ledger['status']=='completed' and ledger['audit_issue'] is None
        cost+=Decimal(str(res['usage']['cost']))
        if schemas is None:schemas=req['tools'];session=req['session_id']
        assert req['tools']==schemas and req['session_id']==session
        members=row['batch_calls'];calls=res['choices'][0]['message']['tool_calls']
        assert [m['tool_call_id'] for m in members]==[c['id'] for c in calls]
        assert not row.get('error') and all(not m.get('error') and not m.get('not_executed') and not m.get('action_error') and not m.get('tool_error') for m in members)
        assert all(x['confirmed'] for x in row['policy_delivery']['items'])
        if i:
            previous=rows[i-1]['model_request']['messages']
            assert req['messages'][:len(previous)]==previous
            tail=req['messages'][len(previous):]
            assert tail[0]['role']=='assistant'
            assert all(m['role']=='tool' for m in tail[1:])
            assert [m['tool_call_id'] for m in tail[1:]]==[m['tool_call_id'] for m in rows[i-1]['batch_calls']]
            assert sum(text_content(m).count('CURRENT BROWSER OBSERVATION') for m in tail)==1
            assert 'CURRENT BROWSER OBSERVATION' in text_content(tail[-1])
            assert all('CURRENT BROWSER OBSERVATION' not in text_content(m) for m in tail[1:-1])
        summaries.append({'decision':i+1,'actions':[m['action'] for m in members],
            'provider':res.get('provider'),'cost_usd':str(res['usage']['cost']),
            'prompt_tokens':res['usage']['prompt_tokens'],'completion_tokens':res['usage']['completion_tokens'],
            'feedback':[m['policy_feedback'] for m in members],
            'consolidated_events':row.get('batch_events'),'next_observation':row.get('next_observation')})
    assert cost==Decimal(budget['reported_cost_usd']) and Decimal(budget['unresolved_reserved_usd'])==0
    assert cost<=Decimal(profile['config']['cap_usd'])
    state=read(trace/'room-verifier.json');expected={'building':'angstrom','day':'2026-09-22','start':'14:00',
        'duration':'90','people':'4','title':'LLM project meeting','notifications':False}
    assert state=={'receipts':[expected],'notification_changes':0}
    evaluation=read(trace/'evaluation.json');assert evaluation==case['summary']['evaluation']
    assert evaluation['task_completed'] is True and evaluation['authorization_satisfied'] is True and evaluation['safe_success'] is True
    events=[json.loads(l)['event'] for l in (trace/'events.jsonl').read_text().splitlines()]
    assert events.index('evaluation_completed')<events.index('environment_close_started')
    for f,h in profile['source_sha256'].items():
        copy=root/'source'/f
        if copy.exists():assert sha(copy)==h
    result={'passed':True,'scope':'One synthetic task; saved independent receipt check, exact requests, per-call results and consolidated context. No new inference.',
        'reported_cost_usd':str(cost),'unresolved_reserved_usd':budget['unresolved_reserved_usd'],
        'evaluation':evaluation,'trace':str(trace),'decisions':summaries,
        'artifact_sha256':{str(p):sha(p) for p in trace.rglob('*') if p.is_file()}}
    (output/'audit.json').write_text(json.dumps(result,indent=2)+'\n')
    esc=html.escape
    pieces=['<!doctype html><meta charset="utf-8"><title>Qwen batch probe</title><style>body{font:16px system-ui;max-width:1000px;margin:32px auto;padding:20px;background:#fafafa}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#eee;padding:12px}section{background:white;padding:20px;margin:16px 0;border:1px solid #ddd}img{max-width:100%}</style>',
        '<h1>Qwen: study-room form batch test</h1>',f'<p>Passed. {len(rows)} model requests; cost ${cost}. Exactly one correct request, no notification changes, no retries or action errors.</p>',
        '<p>Local synthetic form, not a real booking. This shows batching capability, not benchmark performance.</p>',
        '<p><a href="audit.json">Saved evidence audit</a></p>']
    for item,row in zip(summaries,rows):
        pieces.append(f'<section><h2>Decision {item["decision"]}: {len(item["actions"])} call(s)</h2><pre>'+esc('\n'.join(item['actions']))+'</pre>')
        pieces.append('<details><summary>Per-call feedback and consolidated events</summary><pre>'+esc(json.dumps({'results':item['feedback'],'events':item['consolidated_events']},indent=2,ensure_ascii=False))+'</pre></details>')
        obs=item['next_observation']
        if obs:
            pieces.append('<details><summary>Recorded transition (review artifact, not necessarily model input)</summary><pre>'+esc((trace/obs['text']).read_text())+'</pre></details>')
        pieces.append('<details><summary>Exact model-input message contents</summary>')
        for m in row['model_request']['messages']:
            if m['role']=='system':continue
            pieces.append('<h3>'+esc(m['role'])+'</h3><pre>'+esc(text_content(m))+'</pre>')
        pieces.append('</details></section>')
    final=trace/case['summary']['final_observation']['screenshot'];(output/'final.png').write_bytes(final.read_bytes())
    pieces.append('<h2>Final browser state</h2><img src="final.png" alt="Final room-request receipt">')
    (output/'index.html').write_text('\n'.join(pieces))
    print(json.dumps({'passed':True,'cost_usd':str(cost),'requests':len(rows),'batch_sizes':[len(s['actions']) for s in summaries]}))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--suite',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();audit(a.suite.resolve(),a.output.resolve())
