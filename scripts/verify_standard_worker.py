"""Scripted current-profile worker acceptance, including exact publication.

Uses privileged fixture drivers through an offline model transport. It measures
dispatch, outcome preservation and packaging, not autonomous model ability.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import sys
from uuid import uuid4
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--task',required=True)
    p.add_argument('--negative',action='store_true')
    p.add_argument('--backend-failure',action='store_true')
    p.add_argument('--fixtures',type=Path,required=True)
    p.add_argument('--chaos-url')
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    if args.negative and args.task.startswith('prislyktan:') and args.task not in ('prislyktan:AG01','prislyktan:AG06'):
        raise ValueError('The source fixture has negative drivers only for AG01 and AG06')
    args.output.mkdir(parents=True,exist_ok=False)
    os.environ['LD_LIBRARY_PATH']=str(ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu')+':'+os.getenv('LD_LIBRARY_PATH','')
    from intent_browser.team_worker import execute_job
    from intent_browser.hosted_tasks import entry
    from scripts.harness_suite_tasks import scripted_backend
    from scripts.verify_hosted_worker import driver,FailingBackend,original_zip_exact
    if args.task.startswith('prislyktan:'):
        from intent_browser.prislyktan import entry as pris_entry
        row=pris_entry(args.task)
    else:row=entry(args.task)
    calls,artifacts=[],{}
    class Broker:
        def post(self,operation,value):
            if operation=='reserve':raise AssertionError('No paid request allowed')
            if operation=='artifact':
                raw=base64.b64decode(value['data'])
                assert hashlib.sha256(raw).hexdigest()==value['sha256']
                artifacts[value['name']]=raw
                calls.append({'operation':operation,'name':value['name'],'sha256':value['sha256']})
            else:calls.append({'operation':operation,'value':value})
            return {'ok':True}
    def backend_factory(task,holder):
        if args.backend_failure:
            class Failure(FailingBackend):
                supports_images=True
                request_options={}
                def configure_tools(self,options):self.request_options=dict(options)
            return Failure()
        if args.task.startswith('prislyktan:'):
            from data.curation.aggregator_trial.verify import Driver
            script=Driver(task,holder,negative=args.negative)
        else:script=driver(task,holder,row['kind'],not args.negative)
        backend=scripted_backend(script)
        backend.requires_browser_thread=True
        backend.supports_images=True
        return backend
    job={'id':str(uuid4()),'lease':'offline-lease','task':args.task,'goal':row['goal'],
         'task_revision':row['revision'],'mode':'rehearsal'}
    env={'HARNESS_FIXTURES_DIR':str(args.fixtures.resolve()),'HARNESS_VALIDATE_CURRENT_PROFILE':'1'}
    execute_job(Broker(),job,args.output,env,args.chaos_url,backend_factory=backend_factory)
    terminals=[c['value']['snapshot'] for c in calls if c['operation']=='update' and c['value']['snapshot'].get('status')]
    assert len(terminals)==1
    final=terminals[0]
    directory=args.output/'runs'/final['episode']
    evaluation=json.loads((directory/'evaluation.json').read_text())
    episode=json.loads((directory/'episode.json').read_text())
    metadata=json.loads((directory/'metadata.json').read_text())
    events=[json.loads(s)['event'] for s in (directory/'events.jsonl').read_text().splitlines()]
    checks={'expected_grade':evaluation['safe_success'] is (None if args.backend_failure else not args.negative),
            'full_evaluation_preserved':final['evaluation']==evaluation==episode['evaluation'],
            'status':final['status']==('error' if args.backend_failure else 'finished'),
            'no_action_errors':episode['action_error_count']==0,
            'exact_fixed_goal':row['goal'] is None or final['resolved_goal']==row['goal'],
            'current_profile':metadata['harness_profile']['name']=='core-tools-v10-agents',
            'scripted_label':metadata['driver']=='scripted-validation',
            'no_reservations':not (directory/'team-reservations.jsonl').exists(),
            'grade_before_close':events.index('evaluation_completed')<events.index('environment_close_started')}
    archive=args.output/'published.zip'
    with archive.open('xb') as f:
        for part in final['trace_parts']:f.write(artifacts[part])
    with zipfile.ZipFile(archive) as z:checks['exact_original_zip']=original_zip_exact(z,directory)
    source={str(f.relative_to(ROOT)):hashlib.sha256(f.read_bytes()).hexdigest()
            for folder in ('intent_browser','environments/aggregator_trial','data/curation/aggregator_trial')
            for f in (ROOT/folder).rglob('*') if f.is_file() and f.suffix in ('.py','.html','.css','.js','.json') and '__pycache__' not in f.parts}
    report={'passed':all(checks.values()),'task':args.task,'negative':args.negative,'backend_failure':args.backend_failure,
            'checks':checks,'trace':str(directory),'evaluation':evaluation,'model_calls':0,'source_sha256':source,
            'artifact_sha256':{str(f.relative_to(directory)):hashlib.sha256(f.read_bytes()).hexdigest() for f in directory.rglob('*') if f.is_file()}}
    (args.output/'publication-events.json').write_text(json.dumps(calls,indent=2)+'\n')
    (args.output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'task':args.task,'passed':report['passed'],'checks':checks}))
    if not report['passed']:raise SystemExit(1)


if __name__=='__main__':main()
