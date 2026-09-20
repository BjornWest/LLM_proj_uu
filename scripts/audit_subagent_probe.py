"""Read-only reconciliation of synthetic parent/helper evidence and shared spend."""
import argparse
from decimal import Decimal
import hashlib
import json
from pathlib import Path


def read(path):return json.loads(path.read_text())
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('directory',type=Path);p.add_argument('--prior',type=Path);a=p.parse_args()
    root=Path(__file__).resolve().parents[1];result=read(a.directory/'result.json');trace=Path(result['trace'])
    profile=read(a.directory/'profile.json');ledger=read(a.directory/'budget.json')
    family=read(trace/'agents.json');rows=[];checks={};tools={}
    actors=[actor for actor in family['agents'] if actor['episode_id']]
    for actor in actors:
        directory=trace if actor['parent_agent_id'] is None else trace/'children'/actor['episode_id']
        steps=[json.loads(line) for line in (directory/'steps.jsonl').read_text().splitlines()]
        selected=[row for row in steps if row.get('model_request')]
        assert selected
        tools[actor['agent_id']]=selected[0]['model_request']['tools']
        checks[directory.name+' fixed tools']=all(r['model_request']['tools']==tools[actor['agent_id']] for r in selected)
        checks[directory.name+' session']=all(r['model_request']['session_id']==directory.name for r in selected)
        checks[directory.name+' no errors']=all(not r.get('error') and not r.get('action_error') for r in steps)
        events=[json.loads(line)['event'] for line in (directory/'events.jsonl').read_text().splitlines()]
        checks[directory.name+' graded before close']=events.index('evaluation_completed')<events.index('environment_close_started')
        rows.extend(selected)
    parent=next(actor for actor in actors if actor['parent_agent_id'] is None)
    for actor in actors:
        if actor['parent_agent_id'] is not None:
            checks[actor['agent_id']+' inherited tools']=tools[actor['agent_id']]==[t for t in tools[parent['agent_id']] if t['function']['name']!='spawn_agent']
    key=lambda r:json.dumps(r,sort_keys=True)
    checks['all exact requests retained']=sorted(key(r['model_request']) for r in rows)==sorted(key(r['model_request']) for r in ledger['requests'])
    checks['all exact responses retained']=sorted(key(r['model_response']) for r in rows)==sorted(key(r['model_response']) for r in ledger['requests'])
    checks['safe success']=result['summary']['evaluation']['safe_success'] is True
    checks['frozen source copies']=all(sha(a.directory/'source'/name)==digest for name,digest in profile['source_sha256'].items() if not name.startswith('training/.cache/'))
    current=all(sha(root/name)==digest for name,digest in profile['source_sha256'].items())
    cost=sum(Decimal(str(r['reported_cost_usd'])) for r in ledger['requests'])
    prior=Decimal(read(a.prior/'budget.json')['reported_cost_usd']) if a.prior else Decimal(0)
    checks['spend reconciled']=cost==Decimal(ledger['reported_cost_usd']) and Decimal(ledger['unresolved_reserved_usd'])==0 and cost+prior<=Decimal('.25')
    report={'passed':all(checks.values()),'checks':checks,'current_source_matches':current,'reported_usd':str(cost),
            'combined_reported_usd':str(cost+prior),'requests':len(rows),'artifact_sha256':{str(p.relative_to(a.directory)):sha(p) for p in trace.rglob('*') if p.is_file()}}
    out=a.directory/'audit-v2.json'
    with out.open('x') as f:json.dump(report,f,indent=2)
    print(json.dumps({k:v for k,v in report.items() if k!='artifact_sha256'}))
    if not report['passed']:raise SystemExit(1)

if __name__=='__main__':main()
