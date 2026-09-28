"""Bounded native harness transport rehearsals. Scripted answers are NOT model solves."""
import argparse
from concurrent.futures import ProcessPoolExecutor
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from intent_browser.backend import Completion
from intent_browser.connected_world_task import load_prepared, TERMINAL_INSTRUCTION
from intent_browser.runner import run_episode
from intent_browser.input_budget import DEFAULT_MAX_INPUT_TOKENS


class ScriptedBackend:
    supports_images = True
    def __init__(self, task, mode='answer'):
        self.task=task;self.mode=mode;self.requests=[];self.request_options={}
    def configure_tools(self, options): self.request_options=deepcopy(options)
    def begin_episode(self, ident): self.ident=ident
    def complete(self, messages):
        request={'messages':deepcopy(messages),'session_id':self.ident,**deepcopy(self.request_options)}
        self.requests.append(request)
        if self.mode=='failure': raise RuntimeError('Scripted backend failure before any inference')
        n=len(self.requests)
        if n==1 and self.mode=='exchange':name,args='ask_user',{'question':'Are you sure?'}
        elif (n==1 and self.mode in ('clarification','reply-failure')) or (n==2 and self.mode=='exchange'):name,args='ask_user',{'question':'What EU shoe size do you wear?'}
        elif n==1:name,args='ax_search',{'query':'Search','limit':2}
        else:name,args='send_msg_to_user',{'text':'Scripted host rehearsal only; this is not a shopping solution.'}
        raw={'choices':[{'finish_reason':'tool_calls','message':{'role':'assistant','content':None,
             'tool_calls':[{'id':f'script-{n}','type':'function','function':{'name':name,'arguments':json.dumps(args)}}]}}]}
        return Completion('', raw, request)


def case(args):
    prepared, name, output, mode=args
    task,profile,callback=load_prepared(Path(prepared)/name,clarification=mode in ('clarification','bank','exchange','reply-failure'))
    backend=ScriptedBackend(task,'clarification' if mode=='bank' and name=='D08' else 'answer' if mode=='bank' else mode)
    original_capture=task.capture_initial
    def isolated_capture(env, observation, info):
        result=original_capture(env,observation,info)
        page=env.unwrapped.page
        assert page.evaluate("localStorage.getItem('__qwen_host_probe__')") is None
        page.evaluate("localStorage.setItem('__qwen_host_probe__','scripted-isolation-sentinel')")
        return {**result,'scripted_storage_probe':'prior sentinel absent; inserted for context isolation check'}
    task.capture_initial=isolated_capture
    if mode=='reply-failure':
        def fail(question):raise RuntimeError('Scripted trusted responder failure')
        callback=fail
    extra={'clarification_callback':callback} if callback else {}
    directory,summary=run_episode(task.make_env,backend,
        {'source':'connected-world-manual-host-rehearsal','case':name,'model_transport':'scripted_no_api',
         'training_eligible':False}, output=Path(output)/name, max_steps=3,
        episode_task=task,harness_profile=profile,terminal_response_instruction=TERMINAL_INSTRUCTION,
        max_input_tokens=DEFAULT_MAX_INPUT_TOKENS,**extra)
    directory=Path(directory)
    if not (directory/'natural-answer.json').is_file():
        raise RuntimeError('Task did not reach answer capture: '+str(summary.get('error')))
    answer=json.loads((directory/'natural-answer.json').read_text())
    messages=backend.requests[0]['messages']
    assert any(task.policy_goal in str(m['content']) for m in messages)
    assert summary['evaluation']['task_completed'] is None
    assert summary['evaluation']['safe_success'] is None
    assert not any('answer_contract' in json.dumps(m) or 'best_candidate_ids' in json.dumps(m) for m in messages)
    if mode in ('failure','reply-failure'):
        assert summary['error'] and answer['text'] is None
    else:
        assert summary['error'] is None and summary['action_error_count']==0,summary
        assert answer['text']=='Scripted host rehearsal only; this is not a shopping solution.'
    if mode=='clarification' or (mode=='bank' and name=='D08'):
        reply=json.loads((directory/'clarification-000.json').read_text())['reply']
        assert any(reply in str(m['content']) for m in backend.requests[1]['messages'])
    events=[json.loads(s) for s in (directory/'events.jsonl').read_text().splitlines()]
    names=[e['event'] for e in events]
    assert names.index('evaluation_completed') < names.index('environment_close_started')
    if mode=='exchange':
        from environments.product_world.manual_clarification import FALLBACK
        initial=json.dumps(backend.requests[0]['messages'])
        after_generic=json.dumps(backend.requests[1]['messages'])
        after_size=json.dumps(backend.requests[2]['messages'])
        assert 'EU 40, please.' not in initial and 'EU 40, please.' not in after_generic
        assert FALLBACK in after_generic and 'EU 40, please.' in after_size
        for marker in ('clarification_id', 'audit_id', 'personal_shoe_size_en_v1', 'matched'):
            assert marker not in after_size
        assert summary['browser_step_count']==1
    if mode=='reply-failure':
        assert len(backend.requests)==1 and summary['browser_step_count']==0
        saved=json.loads((directory/'clarification-000.json').read_text())
        assert saved['reply'] is None and saved['error']
    return {'case':name,'mode':mode,'trace':str(directory),'passed':True,
            'scripted_completions':len(backend.requests),'model_calls':0,'answer':answer,
            'summary':summary}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--prepared',required=True,type=Path);p.add_argument('--output',required=True,type=Path)
    p.add_argument('--case',action='append');p.add_argument('--mode',default='answer',choices=['answer','failure','clarification','bank','exchange','reply-failure'])
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    selected=a.case or json.loads((a.prepared/'profile.proposed.json').read_text())['cases']
    import intent_browser
    sources={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(intent_browser.__file__).parent.glob('*.py')}
    sources[__file__]=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    with ProcessPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(case,[(str(a.prepared),c,str(a.output),a.mode) for c in selected]))
    changed=[p for p,h in sources.items() if hashlib.sha256(Path(p).read_bytes()).hexdigest()!=h]
    report={'passed':all(r['passed'] for r in results),'cases':results,'source_sha256_before':sources,
            'source_changed_during_suite':changed,'uniform_source_run':not changed,'model_calls':0}
    (a.output/'report.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({'passed':report['passed'],'cases':len(results),'source_changed_during_suite':changed}))

if __name__=='__main__':main()
