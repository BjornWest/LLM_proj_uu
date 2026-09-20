"""Saved-batch adapter/triage audit and read-only viewer check; no inference."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT.parent/'common_agent_util'));sys.path.insert(0,str(ROOT))
os.environ['LD_LIBRARY_PATH']=str(ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu')+':'+os.getenv('LD_LIBRARY_PATH','')
from agent_trace.adapters.browsergym import project,asset
from data.curation.trace_triage.core import analyze

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def audit(output):
    output.mkdir(parents=True,exist_ok=False)
    suite=json.loads((ROOT/'.local/preflight/native-batch-v4/report.json').read_text())
    paths=[Path(c['trace']) for c in suite['cases']]
    paths.append(Path(json.loads((ROOT/'.local/preflight/room-batch-model-v1/case.json').read_text())['trace']))
    results=[];sessions={}
    for trace in paths:
        trace=trace.resolve();before={p.name:sha(p) for p in trace.iterdir() if p.is_file()}
        steps=[json.loads(l) for l in (trace/'steps.jsonl').read_text().splitlines()]
        members=[m for s in steps for m in s.get('batch_calls',[])]
        session=project(trace);messages=session['messages'];tools=[m for m in messages if m['kind']=='tool']
        assert [m['text'] for m in tools]==[m['action'] for m in members]
        for tool,record in zip(tools,members):
            assert tool['tool_call_id']==record['tool_call_id']
            expected=('skipped' if record.get('not_executed') else 'failed' if record.get('error') or record.get('action_error') or record.get('tool_error') else 'completed')
            assert tool['execution_status']==expected
            assert tool['turn']==record['step']
        summary=json.loads(next(m['text'] for m in messages if m['title']=='Recorded execution summary'))
        assert summary['recorded_model_request_attempts']==sum(s.get('model_request') is not None for s in steps)
        assert summary['recorded_tool_call_count']==len(members)
        assert summary['returned_browser_actions']['total']==sum(m.get('browser_stepped') is True for m in members)
        assert len([m for m in messages if m['title']=='Raw model response'])==sum(s.get('model_response') is not None for s in steps)
        assert len([m for m in messages if m['title'].startswith('Tool result —')])==len(members)
        for m in messages:
            for a in m.get('attachments',[]):
                p,_=asset(trace.parent,a['url'].split('/artifacts/',1)[1]);assert p.is_file()
        evaluation=json.loads((trace/'evaluation.json').read_text())
        assert json.loads(next(m['text'] for m in messages if m['title']=='Privileged verifier — not model input'))==evaluation
        triage,evidence=analyze(trace)
        assert triage['recorded_evaluation']==evaluation and evidence.unchanged()
        assert triage['action_counts']['recorded']==len(members)
        assert triage['action_counts']['skipped']==sum(bool(m.get('not_executed')) for m in members)
        assert before=={p.name:sha(p) for p in trace.iterdir() if p.is_file()}
        name=trace.parent.parent.name if trace.parent.name=='traces' else trace.parent.name;sessions[name]=session
        results.append({'trace':str(trace),'tools':len(members),'summary':summary,'original_hashes':before})
    # Exercise the actual renderer with real projected evidence and intercepted
    # GET-only local fixture routes; uploaded HTML is never used as code.
    from playwright.sync_api import sync_playwright
    viewer=ROOT.parent/'common_agent_util/agent_trace/session_viewer.html'
    checks=[];requests=[];errors=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True);page=browser.new_page(viewport={'width':1400,'height':900})
        page.on('pageerror',lambda e:errors.append(str(e)))
        selected=sessions['room-batch-model-v1']
        def route(r):
            requests.append((r.request.method,r.request.url));path=r.request.url.split('viewer.test',1)[-1].split('?',1)[0]
            if path=='/':r.fulfill(body=viewer.read_text(),content_type='text/html')
            elif path=='/api/sessions':r.fulfill(json=[selected])
            elif path.startswith('/api/sessions/'):r.fulfill(json=selected)
            elif path.startswith('/artifacts/'):r.fulfill(body=b'',content_type='image/png')
            else:r.abort()
        page.route('**/*',route)
        for name in ('room-batch-model-v1','navigation','failure','vision'):
            selected=sessions[name];page.goto('http://viewer.test/#'+selected['id'])
            page.locator('#chat article').first.wait_for();page.locator('#live').uncheck()
            expected=[m for m in selected['messages'] if m['kind']=='tool']
            page.locator('#filter').select_option('tools')
            assert page.locator('article.tool').count()==len(expected),(name,len(expected))
            checks.append(name+': individual tools shown')
            labels=page.locator('article.tool .badge').all_text_contents()
            assert sum('skipped' in s for s in labels)==sum(m.get('execution_status')=='skipped' for m in expected)
            if name=='failure':
                page.locator('#filter').select_option('problems');assert page.locator('article.tool').count()==1
                checks.append('failed batch member visible in Errors filter')
        assert not errors;assert all(method=='GET' for method,_ in requests)
        checks+=['no JavaScript errors','zero writes or inference']
        browser.close()
    report={'passed':True,'cases':results,'browser_checks':checks,'model_calls':0,
        'sources':{str(f):sha(f) for f in (viewer,viewer.parent/'adapters/browsergym.py',ROOT/'data/curation/trace_triage/core.py')}}
    (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'passed':True,'saved_cases':len(results),'browser_checks':len(checks)}))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();audit(a.output)
