"""Independent saved queue/browser evidence review. No browser/server/model calls."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]


def read(path):return json.loads(path.read_text())
def rows(path):return [json.loads(line) for line in path.read_text().splitlines()]
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def audit(report_path):
    report=read(report_path)
    if not report['complete']:raise ValueError('Only completed reports can be reviewed')
    checked=[];sessions=set();builds={};hash_checks=0
    for case in report['cases']:
        directory=ROOT/case['episode']
        for name,expected in case['artifact_sha256'].items():
            if sha(directory/name)!=expected:raise ValueError('Artifact changed: '+str(directory/name))
            hash_checks+=1
        steps=rows(directory/'steps.jsonl');events=rows(directory/'events.jsonl')
        episode=read(directory/'episode.json');evaluation=read(directory/'evaluation.json')
        external=read(directory/'external_evaluation.json')
        assert evaluation==case['evaluation']
        assert all(s['model_request'] is None for s in steps)
        assert episode['training_eligible'] is False
        assert sum(s['action'].startswith('click(') for s in steps)==1
        assert episode['action_error_count']==0
        assert external['session'] not in sessions;sessions.add(external['session'])
        assert external['selected_results'][0]['mountCount']==1
        names=[e['event'] for e in events]
        assert names.index('evaluation_completed')<names.index('environment_close_started')
        provenance=external['environment_revision']
        directory_build=Path(provenance['package_directory'])
        for name,expected in provenance['files_sha256'].items():
            assert sha(directory_build/name)==expected, 'Candidate changed since trace: '+name
            hash_checks+=1
        builds[str(directory_build)]=provenance['files_sha256']
        queue_paths=sorted(directory.glob('queue-state-*.json')) or sorted(directory.glob('independent-queue-*.json'))
        queue=read(queue_paths[-1]);assert queue==case['queue']
        trace=queue['events'];dispatch=[e for e in trace if e['phase']=='dispatched']
        observed=[e for e in external['events']['events'] if e['event'] in ('input','click')]
        assert observed==case['server_interactions']
        queued_ids=[e['id'] for e in trace if e['phase']=='queued']
        assert queued_ids==list(range(len(queued_ids)))
        assert len({e['id'] for e in dispatch})==len(dispatch), 'Hidden retry/duplicate dispatch'
        for pos,e in enumerate(dispatch):
            assert any(x['phase']=='queued' and x['id']==e['id'] for x in trace[:trace.index(e)])
            if pos:
                previous=dispatch[pos-1]['id']
                assert any(x['phase']=='completed' and x['id']==previous for x in trace[:trace.index(e)]), 'FIFO violation'
        scenario=case.get('case',case.get('scenario'))
        if scenario=='network-failure':
            assert evaluation['safe_success'] is None and evaluation['technical_error']
            assert len(dispatch)==1 and dispatch[0]['kind']=='input'
            assert queue['reason']=='request_failed' and not observed
            assert any(e['phase']=='discarded' and e['kind']=='click' for e in trace)
        else:
            assert evaluation['technical_error'] is None
            assert [(e['kind'],e['target']) for e in dispatch]==[(e['event'],e['metadata']['target']) for e in observed]
            assert all(e['metadata']['isTrusted'] for e in observed)
            if scenario in ('direct','delayed-input','readonly-blur'):
                assert evaluation['safe_success'] is True
                assert queue['reason']=='terminal:success'
                assert [e['kind'] for e in dispatch]==(['input','input','click'] if scenario=='readonly-blur' else ['input','click'])
                if scenario=='delayed-input':
                    assert dispatch[1]['timestamp']-dispatch[0]['timestamp']>=250, 'Delay precondition not established'
                contract=read(directory/'chaos-contract.json')['stage']['check']
                for target,value in contract.get('expectedValues',{}).items():
                    assert any(e['event']=='input' and e['metadata']['target']==target and e['metadata'].get('value')==value for e in observed)
                assert observed[-1]['metadata']['target']==contract['mustClick'][0]
            else:
                assert evaluation['safe_success'] is False
                assert len(observed)==1 and observed[0]['event']=='click'
        checked.append({'scenario':scenario,'episode':case['episode'],'session':external['session'],
                        'queue_dispatches':len(dispatch),'server_interactions':len(observed),
                        'safe_success':evaluation['safe_success'],'passed':True})
    return {'input_report':str(report_path),'input_sha256':sha(report_path),'cases':checked,
            'artifact_and_build_hash_checks':hash_checks,'candidate_builds':builds,
            'passed':True,'model_calls':0,'browser_calls':0,
            'scope':'Saved artifacts/build hashes and independent event-sequence review; no new browser run.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('reports',nargs='+',type=Path);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():raise ValueError('Use new report path')
    result={'reports':[audit(p) for p in args.reports],'passed':True,'script_sha256':sha(Path(__file__))}
    args.output.write_text(json.dumps(result,indent=2))
    print('Passed',sum(len(r['cases']) for r in result['reports']),'saved cases;',args.output)


if __name__=='__main__':main()
