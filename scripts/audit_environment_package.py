"""Read-only audit of retained package acceptance; no browser or model calls."""
import argparse
import json
from pathlib import Path
import subprocess

from intent_browser.environment_package import verify, digest


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--package',type=Path,required=True)
    p.add_argument('--evidence',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--container-prefix',default='environment-final-')
    args=p.parse_args()
    if args.output.exists() or args.output.is_symlink():raise FileExistsError('Choose a new audit output')
    manifest=verify(args.package);package_hash=digest(args.package/'manifest.json')
    reports={};files=0;cases=0;checks=0;report_hashes={}
    for label,count in [('positive',20),('negative',14),('miniwob-load',125),('local-positive',20)]:
        report_path=args.evidence/label/'report.json';report=json.loads(report_path.read_text())
        assert report['package_sha256']==package_hash and len(report['cases'])==count
        assert len({c['task'] for c in report['cases']})==count
        for case in report['cases']:
            directory=args.evidence/label/'runs'/case['episode']
            actual={f.name:digest(f) for f in directory.iterdir() if f.is_file()}
            assert actual==case['artifact_sha256']
            files+=len(actual);cases+=1
            assert case['passed'] and all(v is True for v in case['checks'].values())
            checks+=len(case['checks'])
            saved=json.loads((directory/'evaluation.json').read_text())
            assert saved==case['evaluation']==json.loads((directory/'episode.json').read_text())['evaluation']
            network=json.loads((directory/'package-network.json').read_text());assert not network['blocked']
            if case['task'].startswith('chaos-'):
                assert 'https://rsms.me/inter/inter.css' in network['fulfilled_from_package']
            events=[json.loads(l)['event'] for l in (directory/'events.jsonl').read_text().splitlines()]
            assert events.index('evaluation_completed')<events.index('environment_close_started')
            steps=[json.loads(l) for l in (directory/'steps.jsonl').read_text().splitlines()]
            assert all(s.get('model_request') is None for s in steps)
        reports[label]=report;report_hashes[label]=digest(report_path)
    left={c['task']:c['evaluation'] for c in reports['positive']['cases']}
    right={c['task']:c['evaluation'] for c in reports['local-positive']['cases']}
    assert left==right
    mini=set(next(d['tasks'] for d in manifest['datasets'] if d['id']=='miniwob'))
    assert mini=={c['task'] for c in reports['miniwob-load']['cases']}
    execution=[]
    for label in ('positive','negative','miniwob-load'):
        value=json.loads(subprocess.check_output(['docker','inspect',args.container_prefix+label],text=True))[0]
        assert value['State']['Status']=='exited' and value['State']['ExitCode']==0
        assert value['HostConfig']['NetworkMode']=='none' and value['HostConfig']['ReadonlyRootfs']
        assert value['Config']['User']=='10001:10001'
        assert any(m['Destination']=='/package' and not m['RW'] for m in value['Mounts'])
        assert not any(e.split('=',1)[0] in ('OPENROUTER_API_KEY','DAYLIGHT_OPENROUTER_API_KEY','PARALLEL_API_KEY','HARNESS_WORKER_TOKEN','BLOB_READ_WRITE_TOKEN') for e in value['Config']['Env'])
        execution.append({'name':value['Name'],'image':value['Image'],'network':'none',
                          'readonly_root':True,'readonly_package':True,'user':'10001:10001','exit_code':0})
    report={'schema_version':1,'passed':True,'package_sha256':package_hash,
        'package_files':len(manifest['files']),'package_bytes':sum(f['bytes'] for f in manifest['files'].values()),
        'cases':cases,'recorded_checks':checks,'artifact_hashes_checked':files,
        'local_container_full_evaluation_parity':True,'report_sha256':report_hashes,
        'containers':execution,'datasets':manifest['datasets'],'paid_calls':0,
        'miniwob_scope':'All 125 loaded offline; two native positive completions. Not a full benchmark success claim.',
        'susbench_scope':'One diagnostic, all transaction/authorization/avoidance fields null.',
        'deployed_to_vercel':False,'training_readiness_changed':False}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x') as out:json.dump(report,out,indent=2);out.write('\n')
    print(json.dumps({k:report[k] for k in ('passed','package_sha256','package_bytes','cases','recorded_checks','artifact_hashes_checked','paid_calls')}))


if __name__=='__main__':main()
