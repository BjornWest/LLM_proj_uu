"""Bind saved browser/native evidence to task IDs without readiness promotion."""
import argparse,hashlib,json
from pathlib import Path
from data.curation.expansion.webarena.inventory import build,ROOT

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 p=argparse.ArgumentParser();p.add_argument('--browser-report',type=Path,required=True);p.add_argument('--native-report',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
 browser=json.loads(a.browser_report.read_text());native=json.loads(a.native_report.read_text());assert native['browser_report_sha256']==sha(a.browser_report)
 inv,_=build();by_id={int(t['source_task_id']):t for t in inv};grades={t['task_id']:t for t in native['tasks']};items=[];artifacts={}
 for row in browser['tasks']:
  tid=row['task_id'];trace=Path(row['trace']);grade=grades.get(tid);steps=[json.loads(s) for s in (trace/'steps.jsonl').read_text().splitlines()];blocked=row['blocked_requests'];assert all(s.get('model_request') is None for s in steps),'Unexpected model request in scripted run'
  for f in trace.rglob('*'):
   if f.is_file():artifacts[str(f)]=sha(f)
  if grade:assert grade['har_sha256']==sha(trace/'network.har')
  item={'source':'webarena-verified','source_task_id':str(tid),'template_id':by_id[tid]['template_id'],'source_revision':by_id[tid]['source_revision'],'site_ids':by_id[tid]['site_ids'],'original_goal':by_id[tid]['policy_input']['goal'],'trace':str(trace),'gates':{'positive_browser_zero_action_errors':row['browser_positive'],'native_positive':None if not grade else grade['positive'].get('status')=='success' and grade['positive'].get('score')==1,'native_negative_fixture':None if not grade else grade['negative'].get('status')=='failure' and grade['negative'].get('score')==0,'negative_browser':None,'fresh_browser_context':True,'seeded_database_reset':None,'independent_review':None,'current_native_tool_profile':None,'model_tested':False},'training_ready':False,'authorization_preserved':None,'safe_success':None,'blocked_requests':blocked,'action_errors':row['summary']['action_error_count'],'evidence':{'browser_report':str(a.browser_report),'native_report':str(a.native_report)},'limitations':['Read-only rehearsals on existing shared data, not seeded database reset.','DOM-assisted scripted driver using legacy browser actions and 120000-character observation ceiling.','Native pass establishes original criterion, not general side-effect safety.','Negative controls are derivative fixtures, not negative browser executions.']}
  item['ready_for_independent_review']=all(item['gates'][k] is True for k in ['positive_browser_zero_action_errors','native_positive','native_negative_fixture']);items.append(item)
 files={str(a.browser_report):sha(a.browser_report),str(a.native_report):sha(a.native_report)}
 result={'schema':'webarena-expansion-acceptance-review-v1','tasks':items,'counts':{'tasks_attempted':len(items),'ready_for_independent_review':sum(t['ready_for_independent_review'] for t in items),'independently_accepted':0,'training_ready':0,'model_calls':0},'reports_sha256':files,'artifact_sha256':artifacts}
 (a.output/'acceptance.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result['counts']))
if __name__=='__main__':main()
