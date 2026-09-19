"""Saved-evidence selection for AX-STRESS-01; no browser or inference requests."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
from webarena_verified.api import WebArenaVerified
from webarena_verified.types.config import WebArenaVerifiedConfig

ROOT=Path(__file__).resolve().parents[3]
BASE=ROOT/'.local/expansion-webarena/batch03-frozen-pairs-v3'


def review():
    api=WebArenaVerified(config=WebArenaVerifiedConfig(environments={'__SHOPPING__':{'urls':['http://localhost:7770']}}))
    rows=[]
    for tid in [146,334]:
        for variant in ['positive','negative']:
            p=BASE/f'{tid}-{variant}'/'report.json'
            assert p.exists(),p
            c=json.loads(p.read_text())['tasks'][0];trace=ROOT/c['trace']
            assert c['source_unchanged'] and c['scripted_path_completed'] and c['summary']['error'] is None and c['summary']['action_error_count']==0
            verdict=api.evaluate_task(task_id=tid,agent_response=c['derived_response'],network_trace=trace/'network.har').model_dump(mode='json')
            assert (verdict['score']==1)==(variant=='positive')
            steps=[json.loads(l) for l in (trace/'steps.jsonl').read_text().splitlines()]
            for s in steps:
                assert not s.get('action_error') and s['model_response']['offline_fixture'] is True
                assert s['model_request']['messages']==s['messages']
                a=ast.parse(s['action'],mode='eval').body
                if a.func.id!='send_msg_to_user':
                    kw={k.arg:ast.literal_eval(k.value) for k in a.keywords};bid=kw.get('bid',ast.literal_eval(a.args[0]) if a.args else None)
                    assert f'[{bid}]' in (trace/s['observation']['text']).read_text()
            files={str(f.relative_to(trace)):hashlib.sha256(f.read_bytes()).hexdigest() for f in trace.rglob('*') if f.is_file()}
            rows.append({'task_id':tid,'variant':variant,'trace':c['trace'],'browser_report':str(p.relative_to(ROOT)),
                         'browser_report_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),
                         'native_recomputed_score':verdict['score'],'steps':len(steps),'action_errors':0,
                         'observation_characters':[len((trace/s['observation']['text']).read_text()) for s in steps],
                         'artifact_sha256':files,'final_response':c['derived_response']})
    return {'schema':'ax-stress-saved-candidate-review-v1','coordination_id':'AX-STRESS-01',
            'candidates':[334,146],'records':rows,'network_model_calls':0,'new_browser_runs':0,
            'training_eligible':False,'scope':'Original task positives and wrong-answer negatives; native grader replay and current-target evidence.',
            'limits':['Scripted paths provide a stress-test starting point, not teacher-model difficulty measurements.',
                      'New progressive AX profile has not been exercised by these core-tools-v3 traces.',
                      'Complete WebArena batch independent review remains separate.']}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();r=review()
    with a.output.open('x') as out:json.dump(r,out,indent=2);out.write('\n')
    print(json.dumps({'cases':len(r['records']),'tasks':r['candidates']}))
