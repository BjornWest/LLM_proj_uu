"""Validate final saved action batch without browser/model calls."""
import argparse,json
from pathlib import Path
from data.curation.expansion.tricky.batch02.tasks import ROOT,HERE,sha

def main():
 p=argparse.ArgumentParser();p.add_argument('--report',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 if a.output.exists():raise FileExistsError(a.output)
 report=json.loads(a.report.read_text());assert report['passed'];rows=[];files=0;targets=0
 for path,pin in report['source_sha256'].items():assert sha(ROOT/path)==pin,path
 for row in report['rows']:
  trace=Path(row['trace'])
  for name,pin in row['files'].items():assert sha(trace/name)==pin,(trace,name);files+=1
  ev=json.loads((trace/'evaluation.json').read_text());assert ev==row['evaluation'];assert not ev['technical_error']
  expected_auth=False if row['case'] in ['wrong_product','duplicate'] else None
  assert ev['authorization_satisfied'] is expected_auth,(row['task_id'],row['case'],ev)
  initial=json.loads((trace/'initial-state.json').read_text())['task_state'];assert initial['cart']==[] and initial['purchasedItems']==[]
  driver=json.loads((trace/'driver-evidence.json').read_text());assert driver['reference_targets_read'] is False
  for check in driver['checks']:
   if 'bid' in check:assert check['in_current_delivered_AX'];targets+=1
  details=json.loads((trace/'action-evaluation.json').read_text());assert all(details['completion_requirements'].values())==ev['task_completed']
  events=[json.loads(l)['event'] for l in (trace/'events.jsonl').read_text().splitlines()];assert events.index('evaluation_completed')<events.index('environment_close_started')
  steps=[json.loads(l) for l in (trace/'steps.jsonl').read_text().splitlines()];assert not any(s.get('action_error') for s in steps)
  rows.append({k:row[k] for k in ['task_id','case','trace','passed']})
 result={'schema_version':1,'status':'scripted_pass_pending_independent_review','task_contract_count':len({r['task_id'] for r in rows}),'site_count':1,'browser_case_count':len(rows),'model_calls':0,'training_eligible':False,'independent_review':False,'artifact_hash_checks':files,'current_AX_target_checks':targets,'checks':['source_hashes','artifact_hashes','raw_evaluation_equality','known_forbidden_effects_false_unknown_otherwise','fresh_cart_and_receipt_per_case','current_AX_BID_checks','evaluation_before_close','no_action_errors'],'report':str(a.report),'report_sha256':sha(a.report),'source_sha256':report['source_sha256'],'cases':rows}
 with a.output.open('x') as f:json.dump(result,f,indent=2);f.write('\n')
 print(json.dumps({k:result[k] for k in ['task_contract_count','browser_case_count','artifact_hash_checks','current_AX_target_checks']}))
if __name__=='__main__':main()
