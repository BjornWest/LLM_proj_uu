"""Read-only independent-format replay/hash checks for authored native evidence."""
import argparse,json,hashlib
from pathlib import Path
from data.curation.expansion.tricky.authored02.grader import grade
ROOT=Path(__file__).resolve().parents[5];HERE=Path(__file__).parent
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
 p=argparse.ArgumentParser();p.add_argument('--report',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 if a.output.exists():raise FileExistsError(a.output)
 report=json.loads(a.report.read_text());assert report['complete'] and report['passed'] and report['completed_cases']==40
 tasks={t['id']:t for t in json.loads((HERE/'contracts.json').read_text())['tasks']};files=0;targets=0;requests=0;cases=[]
 assert sha(HERE/'contracts.json')==report['source_sha256'][str((HERE/'contracts.json').relative_to(ROOT))]
 for row in report['rows']:
  assert row['source_unchanged'] and row['source_sha256']==report['source_sha256']
  trace=Path(row['trace'])
  for name,pin in row['files_sha256'].items():assert sha(trace/name)==pin,(trace,name);files+=1
  detail=json.loads((trace/'authored-evaluation.json').read_text());replay=grade(tasks[row['task_id']],detail['answer'],detail['state'],detail['events'])
  for key in ['task_completed','authorization_satisfied','requirements','unauthorized_effects']:assert replay[key]==detail[key],(row['task_id'],key)
  assert replay['task_completed'] is (row['case']=='positive')
  ev=json.loads((trace/'evaluation.json').read_text());assert ev==row['summary']['evaluation']
  events=[json.loads(l)['event'] for l in (trace/'events.jsonl').read_text().splitlines()];assert events.index('evaluation_completed')<events.index('environment_close_started')
  checks=json.loads((trace/'scripted-targets.json').read_text());assert all(c['in_current_delivered_AX'] for c in checks);targets+=len(checks)
  steps=[json.loads(l) for l in (trace/'steps.jsonl').read_text().splitlines()]
  assert all(not s.get('action_error') for s in steps)
  for s in steps:
   request=s.get('model_request');assert isinstance(request,dict) and request.get('tools');requests+=1
   assert 'grader_input' not in json.dumps(request['messages'])
   protocol=json.loads((HERE/'contracts.json').read_text())['policy_response_protocol'];assert protocol in request['messages'][0]['content'];assert protocol in tasks[row['task_id']]['policy_input']['goal']
  cases.append({k:row[k] for k in ['task_id','template_id','site','case','trace','passed']})
 summary={'schema_version':1,'status':'scripted_native_pass_pending_independent_review','source':'project_authored','instances':len(tasks),'templates':len({t['template_id'] for t in tasks.values()}),'sites':4,'browser_cases':len(cases),'profile':'core-tools-v3','transport':'httpx.MockTransport','model_calls':0,'training_eligible':False,'independent_review':False,'artifact_hash_checks':files,'current_AX_target_checks':targets,'mock_native_requests':requests,'outcome_replays':len(cases),'report':str(a.report),'report_sha256':sha(a.report),'source_sha256':report['source_sha256'],'current_source_matches_recorded':all((ROOT/k).exists() and sha(ROOT/k)==v for k,v in report['source_sha256'].items()),'cases':cases,'limits':['Synthetic authored goals, not additional original benchmark task coverage.','No teacher-model success measurement.','Broad authorization remains unknown when no scoped violation is found.','Source agreement is checked per process and cohort; historical evidence stays valid if current source later changes.']}
 with a.output.open('x') as f:json.dump(summary,f,indent=2);f.write('\n')
 print(json.dumps({k:summary[k] for k in ['instances','templates','browser_cases','artifact_hash_checks','current_AX_target_checks','mock_native_requests','current_source_matches_recorded']}))
if __name__=='__main__':main()
