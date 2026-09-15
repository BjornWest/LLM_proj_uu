"""Read-only saved manual trace/ZIP checks, without importing a task or verifier."""
import argparse,hashlib,json,zipfile
from pathlib import Path

def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def audit(reports,source):
    checks=0;cases=[]
    def check(ok,label):
        nonlocal checks
        if not ok:raise AssertionError(label)
        checks+=1
    for file in reports:
        report=json.loads(file.read_text());root=file.parent
        check(report['passed'] and report['model_calls']==0,str(file))
        for name,sha in report['sources'].items():check(digest(source/name)==sha,'Source '+name)
        for case in report['cases']:
            directory=root/case['trace_directory'];final=case['final']
            for name,sha in case['artifacts'].items():check(digest(root/name)==sha,'Artifact '+name)
            episode=json.loads((directory/'episode.json').read_text())
            events=[json.loads(x) for x in (directory/'events.jsonl').read_text().splitlines()]
            steps=[json.loads(x) for x in (directory/'steps.jsonl').read_text().splitlines()]
            check(episode['driver']=='scripted_validation' and episode['model'] is None,'Actor')
            check(episode['evaluation'] is None and episode['success'] is None and final['evaluation'] is None,'Ungraded')
            check(episode['reference_evaluation']==final['reference_evaluation']==json.loads((directory/'reference-evaluation.json').read_text()),'Reference full object')
            check(episode['reference_evaluation']['injection_exposed'] is None and episode['reference_evaluation']['injection_avoided'] is None,'No AX exposure claim')
            check(episode['browser_step_count']==len(steps)==final['action_count'],'All action rows retained')
            check(all(s['actor']=='scripted_validation' and s['model_request'] is None and s['model_response'] is None for s in steps),'No inferred model output')
            kinds=[e['event'] for e in events]
            check(not any(k.startswith('model_') or k.startswith('policy_input_') for k in kinds),'No model or policy dispatch')
            check(kinds.index('evaluation_completed')<kinds.index('environment_close_started')<kinds.index('episode_finished'),'Evaluate before close')
            archive=root/case['archive'] if case.get('archive') else root/'sessions'/case['id']/'trace.zip'
            with zipfile.ZipFile(archive) as z:
                names=z.namelist();expected={str(p.relative_to(directory.parent)):p for p in directory.rglob('*') if p.is_file()}
                check(len(names)==len(set(names)) and set(names)==set(expected),'Exact ZIP file set, no duplicates')
                for name,p in expected.items():check(z.read(name)==p.read_bytes(),'ZIP bytes '+name)
            cases.append({'task':case['task'],'id':case['id'],'archive_sha256':digest(archive),'files':len(expected)})
    check(len({c['id'] for c in cases})==len(cases),'Unique sessions')
    return {'passed':True,'checks':checks,'cases':cases,'case_count':len(cases),'model_calls':0,'grader_recomputed':False,'scope':'Exact saved artifacts, null semantics and full ZIP equality; no task/verifier imports'}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('reports',nargs='+',type=Path);p.add_argument('--source',required=True,type=Path);p.add_argument('--output',required=True,type=Path);a=p.parse_args()
    result=audit(a.reports,a.source)
    with a.output.open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps({'passed':True,'cases':result['case_count'],'checks':result['checks'],'output':str(a.output)}))
