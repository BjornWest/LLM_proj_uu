"""Read-only audit of saved WorkArena exercise evidence; no network/browser/model calls."""
import argparse
from decimal import Decimal
import hashlib
import json
from pathlib import Path

from data.curation.workarena_exercise.catalog_contract import configuration_correct

ROOT=Path(__file__).resolve().parents[3]


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    if args.output.exists() or args.output.is_symlink():raise SystemExit('Refusing existing output')
    files={}
    def load(path):
        p=ROOT/path;raw=p.read_bytes();files[str(path)]=hashlib.sha256(raw).hexdigest();return json.loads(raw)
    ledger=load(Path('data/curation/sweeps/budget.json'))
    requests=[r for r in ledger['requests'] if r['case_id'].startswith('WA-W01')]
    assert all(r['status']=='completed' and not r.get('audit_issue') for r in requests)
    cases=[]
    for directory,name in [('warranty-model-v1','WA-W01-model-v1'),('warranty-model-v1','WA-W01-model-v1-b'),
                           ('warranty-format-v2','WA-W01-format-v2'),('warranty-context-v3','WA-W01-context-v3'),
                           ('warranty-full-v4','WA-W01-full-v4')]:
        result=load(Path('data/curation/workarena_exercise')/directory/(name+'.json'))
        trace=Path(result['trace']);summary=result['summary'];evaluation=load(trace/'evaluation.json')
        assert evaluation==summary['evaluation']
        raw=(ROOT/trace/'steps.jsonl').read_bytes();files[str(trace/'steps.jsonl')]=hashlib.sha256(raw).hexdigest()
        steps=[json.loads(line) for line in raw.splitlines()]
        sent=[s for s in steps if s.get('model_request') is not None]
        owned=[r for r in requests if r['case_id']==name]
        assert len(sent)==len(owned)
        for step,row in zip(sent,owned):
            assert step['model_request']==row['model_request'] and step['model_response']==row['model_response']
            assert row['model_request']['session_id']==trace.name
        cleanup=load(trace/'workarena-cleanup.json');assert len(cleanup)==3 and all(r['absent_after_teardown'] for r in cleanup)
        # Verify every retained episode artifact, without exposing raw page contents.
        for path in (ROOT/trace).rglob('*'):
            if path.is_file():files[str(path.relative_to(ROOT))]=hashlib.sha256(path.read_bytes()).hexdigest()
        cases.append({'case_id':name,'trace':str(trace),'requests':len(owned),'browser_actions':summary['browser_step_count'],
                      'action_errors':summary['action_error_count'],'stop_reason':summary['stop_reason'],
                      'technical_error':evaluation['technical_error'],'task_completed':evaluation['task_completed'],
                      'authorization_satisfied':evaluation['authorization_satisfied'],'safe_success':evaluation['safe_success'],
                      'reported_cost_usd':str(sum((Decimal(str(r['reported_cost_usd'])) for r in owned),Decimal(0))),
                      'providers':sorted({r['model_response']['provider'] for r in owned}),
                      'all_three_temporary_records_removed':True})
    assert sum(c['requests'] for c in cases)==len(requests)==47
    native=load(Path('.local/workarena-exercise/warranty-native-v1/report.json'))
    assert native['final_native_result'][0]==1 and all(r['absent_after_close'] for r in native['cleanup'])
    catalog=[]
    for name,expected in [('catalog-clean-v1',True),('catalog-injected-remove-v4',True),('catalog-factory-keep-v4',False)]:
        directory=Path('.local/workarena-exercise')/name;r=load(directory/'report.json')
        assert bool(r['native_result'][0]) is expected and configuration_correct(r['request']) is expected
        assert r['only_one_order_for_user'] and r['temporary_user_absent'] and r['order_absent_after_cleanup'] and r['order_items_absent_after_cleanup']
        if r['condition']=='injected':
            assert r['insertion']['inserted'] and r['removal_persisted'] and r['reload_reinserted']
            assert r['environment_factory_sha256']==hashlib.sha256((ROOT/'environments/workarena_exercise/environment.py').read_bytes()).hexdigest()
            assert r['injection_source_sha256']==hashlib.sha256((ROOT/'environments/workarena_exercise/preselect_acrobat.js').read_bytes()).hexdigest()
        for path in (ROOT/directory).iterdir():
            if path.is_file():files[str(path.relative_to(ROOT))]=hashlib.sha256(path.read_bytes()).hexdigest()
        catalog.append({'case':name,'report':str(directory/'report.json'),'native_pass':bool(r['native_result'][0]),
                        'recorded_independent_verdict':r['independent_configuration_correct'],
                        'recomputed_configuration_verdict':configuration_correct(r['request']),
                        'structural_label_recheck':name=='catalog-clean-v1','order_count':len(r['same_user_order_ids']),
                        'acrobat':r['request']['items'][0]['options']['Adobe Acrobat'],
                        'recorded_price':r['request']['price'],'cleanup_verified':True,'model_calls':0,'model_exposure':None})
    for p in ['data/curation/workarena_exercise/catalog_contract.py','environments/workarena_exercise/environment.py',
              'environments/workarena_exercise/preselect_acrobat.js','data/curation/workarena_exercise/inspect_catalog.py']:
        files[p]=hashlib.sha256((ROOT/p).read_bytes()).hexdigest()
    result={'schema':'workarena-learning-results-v1','training_eligible':False,'production_ready':False,
            'source_revision':'a772230a94cf1caf4166b8ead3983f3b3786455b','workarena_version':'0.5.3',
            'native_warranty_scripted_pass':True,'warranty_model_cases':cases,'catalog_scripted_cases':catalog,
            'model_request_count':len(requests),
            'reported_cost_usd':str(sum((Decimal(str(r['reported_cost_usd'])) for r in requests),Decimal(0))),
            'new_reserved_usd':str(sum((Decimal(r['reservation_usd']) for r in requests),Decimal(0))),
            'cumulative_reserved_usd':ledger['reserved_cost_usd'],
            'remaining_reservation_capacity_usd':str(Decimal('3')-Decimal(ledger['reserved_cost_usd'])),
            'limitations':['Development cases use different profiles, generated data and providers; not a benchmark pass-rate estimate.',
                           'No warranty model case completed the task. Scoped records stayed unchanged; broad authorization is unknown.',
                           'Catalog checks are privileged scripted tests, not model capability or exposure evidence.',
                           'Clean catalog strict verdict is explicitly recomputed after identifying the empty Label field.',
                           'Cleanup verification covers observed sessions, not arbitrary process kills or partial setup failures.',
                           'The hosted ServiceNow service is required; this is not an offline/Vercel-hosted clone.'],
            'files_sha256':files,'audit_script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x') as f:json.dump(result,f,indent=2);f.write('\n')
    print(f'47 exact request/response matches; 5 model cases; 3 catalog outcomes; {len(files)} file hashes. No new calls.')


if __name__=='__main__':main()
