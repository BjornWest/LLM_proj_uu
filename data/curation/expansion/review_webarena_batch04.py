"""Independent saved native replay and conservative task acceptance of20cases.

Run using .local/webarena-verified/venv/bin/python; no new browser/model calls.
Native agreement is scoped evidence, not an independent final-state oracle.
"""
import argparse
import ast
from collections import Counter
import hashlib
import json
from pathlib import Path
from webarena_verified.api import WebArenaVerified
from webarena_verified.types.config import WebArenaVerifiedConfig

ROOT=Path(__file__).resolve().parents[3]
INDEX=ROOT/'.local/expansion-webarena/review-batch04-v1/report.json'


def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()


def review():
    index=json.loads(INDEX.read_text());counts=Counter();rows=[]
    for name,pin in index['artifact_sha256'].items():
        assert sha(ROOT/name)==pin,name
        counts['artifact_hashes']+=1
    source={str(t['task_id']):t for t in json.loads((ROOT/'.local/webarena-verified/dataset.json').read_text())}
    api=WebArenaVerified(config=WebArenaVerifiedConfig(environments={
        '__SHOPPING__':{'urls':['http://localhost:7770']},'__REDDIT__':{'urls':['http://localhost:18999']}}))
    for task in index['tasks']:
        tid=task['source_task_id'];original=source[tid]
        assert task['original_goal']==original['intent']
        case_rows=[]
        for case in task['cases']:
            trace=ROOT/case['trace']
            browser=json.loads((ROOT/case['browser_report']).read_text())
            actual=next(t for t in browser['tasks'] if t['task_id']==int(tid) and t['variant']==case['variant'])
            assert actual['source_unchanged'] and actual['scripted_path_completed'] and actual['delivery_aligned']
            profile=json.loads((ROOT/case['profile']).read_text())
            assert case['actual_loaded_snapshot_matches'] and profile['frozen_runtime']
            snapshot=Path(profile['frozen_runtime'])
            for module in (snapshot/'intent_browser').glob('*.py'):
                assert profile['source_sha256'][str(module.relative_to(ROOT))]==sha(module)
            result=api.evaluate_task(task_id=int(tid),agent_response=actual['derived_response'],network_trace=trace/'network.har').model_dump(mode='json')
            assert result['score']==case['native_score']
            if case['native_grader_error']: assert result['status']=='error'
            else: assert ((result['score']==1)==(case['variant']=='positive')) is case['native_matches_intended']
            counts['native_verdict_replays']+=1
            for line in (trace/'steps.jsonl').read_text().splitlines():
                s=json.loads(line)
                assert s['model_response']['offline_fixture'] is True
                assert s['model_request']['messages']==s['messages'] and s['model_request']['tools']
                counts['mock_requests']+=1
                a=ast.parse(s['action'],mode='eval').body
                if a.func.id!='send_msg_to_user':
                    kw={k.arg:ast.literal_eval(k.value) for k in a.keywords}
                    bid=kw.get('bid',ast.literal_eval(a.args[0]) if a.args else None)
                    selected=trace/s['observation']['text']
                    assert selected.name.startswith('decision-observation-') and f'[{bid}]' in selected.read_text()
                    counts['current_AX_targets']+=1
                if s.get('action_error'): counts['retained_action_errors']+=1
            case_rows.append({'variant':case['variant'],'trace':case['trace'],'native_recomputed':result['score'],
                              'action_errors':case['action_error_count'],'observation_chars':case['observation_characters'],'native_grader_error':case['native_grader_error']})
        reasons=[]
        if task['status']!='scripted_pair_validated_pending_review': reasons.append(task['status']);reasons.extend(task['audit_flags'])
        if not case_rows: reasons.append('No selected browser pair')
        if any(c['action_errors'] for c in case_rows): reasons.append('Action-warning cohort')
        if any(c['native_grader_error'] for c in case_rows): reasons.append('Native exception is not negative rejection')
        if any(c['observation_chars']!=48000 for c in case_rows): reasons.append('Unexpected observation profile')
        accepted=not reasons
        rows.append({'source_task_id':tid,'template_id':task['source_template_id'],'sites':task['site_ids'],
                     'accepted_development_task':accepted,'acceptance_blockers':reasons,'cases':case_rows,
                     'authorization_satisfied':None,'safe_success':None,'training_eligible':False})
    return {'schema':'webarena-batch04-independent-review-v1','index_sha256':sha(INDEX),
            'review_source_sha256':sha(Path(__file__)),'checked_tasks':len(rows),
            'accepted_development_tasks':sum(r['accepted_development_task'] for r in rows),
            'accepted_ids':[r['source_task_id'] for r in rows if r['accepted_development_task']],
            'checks':dict(counts),'records':rows,'model_calls':0,'new_browser_runs':0,'training_eligible':False,
            'limitations':['Native-grader replay is not an independent grading implementation.',
                           'Seeded dataset content and initial state remain part of each task contract.',
                           'Unaccepted cases retain useful harness diagnostics; they are not model failures.']}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    r=review()
    with a.output.open('x') as out:json.dump(r,out,indent=2);out.write('\n')
    print(json.dumps({k:v for k,v in r.items() if k!='records'},indent=2))
