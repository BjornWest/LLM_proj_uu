"""Check retained scripted artifacts and emit a small, exclusive review index."""
import argparse,json
from pathlib import Path
from data.curation.expansion.tricky.lookup_tasks import ROOT,HERE,SHA

def main():
 p=argparse.ArgumentParser();p.add_argument('--report',type=Path,required=True);p.add_argument('--site-report',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 if a.output.exists():raise FileExistsError(a.output)
 report=json.loads(a.report.read_text());site=json.loads(a.site_report.read_text());checks=[];artifacts=0;rows=[];targets=0;extractions=0
 assert report['passed'] and report['model_calls']==0
 assert site['all_diagnostic_checks_pass']
 for path,expected in report['source_sha256'].items():assert SHA(ROOT/path)==expected,path
 for path,expected in site['source_sha256'].items():assert SHA(ROOT/path)==expected,path
 for row in report['rows']:
  folder=Path(row['trace'])
  for name,expected in row['files'].items():assert SHA(folder/name)==expected,(folder,name);artifacts+=1
  evaluation=json.loads((folder/'evaluation.json').read_text());assert evaluation==row['evaluation']
  events=[json.loads(l)['event'] for l in (folder/'events.jsonl').read_text().splitlines()]
  assert events.index('evaluation_completed')<events.index('environment_close_started')
  driver=json.loads((folder/'scripted-driver-evidence.json').read_text());assert driver['grader_reference_used_by_driver'] is False
  assert driver['extractions'] and all(x['in_current_delivered_text'] for x in driver['extractions'])
  assert driver['target_checks'] and all(x['in_current_delivered_text'] for x in driver['target_checks'])
  targets+=len(driver['target_checks']);extractions+=len(driver['extractions'])
  detail=json.loads((folder/'lookup-evaluation.json').read_text());assert all(detail['requirements'].values())==(row['case']=='positive')
  assert evaluation['authorization_satisfied'] is None
  rows.append({k:row[k] for k in ['task_id','site','case','trace','passed']})
 for name,expected in site['artifact_sha256'].items():assert SHA(a.site_report.parent/name)==expected,name
 index={'schema_version':1,'status':'scripted_pass_pending_independent_review','source_revision':'4ed5d744d8e9fb53abb7057ba7c5664feb2a67e4','environment_revision':'8201821fb64a5075f50b015f99653881ab09a030','full_site_revision':'9fc287a252ddee32e579575bec50e33568070272de2e81ef5c9033bde19eb90e','task_contract_count':len({r['task_id'] for r in rows}),'site_count':len({r['site'] for r in rows}),'browser_case_count':len(rows),'model_calls':0,'training_eligible':False,'independent_review':False,'authorization_coverage':None,'artifact_hash_checks':artifacts,'native_action_target_in_current_AX_checks':targets,'browser_extractions_in_current_AX_checks':extractions,'checks':['exact_artifact_hashes','source_hashes_match_current_candidate','raw_evaluations_match','evaluation_before_browser_close','all_positive_and_negative_expectations','BIDs_present_in_current_delivered_AX','extracted_browser_answers_present_in_current_delivered_AX'],'reports':{str(a.report):SHA(a.report),str(a.site_report):SHA(a.site_report)},'source_sha256':report['source_sha256'],'cases':rows}
 with a.output.open('x') as f:json.dump(index,f,indent=2);f.write('\n')
 print(json.dumps({k:index[k] for k in ['task_contract_count','site_count','browser_case_count','artifact_hash_checks','native_action_target_in_current_AX_checks','browser_extractions_in_current_AX_checks']}))
if __name__=='__main__':main()
