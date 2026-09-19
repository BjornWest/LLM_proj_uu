"""Grade actual browser variants; preserve native verdict even if it rewards a loophole."""
import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit
from webarena_verified.api import WebArenaVerified
from webarena_verified.types.config import WebArenaVerifiedConfig

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def main():
 p=argparse.ArgumentParser();p.add_argument('--browser-report',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
 rows=[]
 for case in json.loads(a.browser_report.read_text())['tasks']:
  if case['derived_response'] is None:continue
  trace=Path(case['trace']);har=trace/'network.har';origin=urlsplit(case['final_url']);origin=f'{origin.scheme}://{origin.netloc}';reddit=origin if ':18999' in origin else 'http://localhost:18999';shopping=origin if ':7770' in origin else 'http://localhost:7770'
  api=WebArenaVerified(config=WebArenaVerifiedConfig(environments={'__SHOPPING__':{'urls':[shopping]},'__REDDIT__':{'urls':[reddit]}}))
  result=api.evaluate_task(task_id=case['task_id'],agent_response=case['derived_response'],network_trace=har).model_dump(mode='json')
  passed=result.get('score')==1 and result.get('status')=='success'
  row={'task_id':case['task_id'],'variant':case['variant'],'trace':str(trace),'native_result':result,'final_url':case['final_url'],'intended_outcome':case['intended_outcome'],'native_matches_intended':passed==case['intended_outcome'],'native_success':passed,'source_unchanged':case['source_unchanged'],'action_errors':case['summary']['action_error_count'],'scripted_path_completed':case['scripted_path_completed'],'network_model_calls':0,'training_ready':False,'har_sha256':sha(har),'browser_report_sha256':sha(a.browser_report),'final_observation_sha256':sha(trace/case['summary']['final_observation']['text'])}
  rows.append(row);print(json.dumps({k:row[k] for k in ('task_id','variant','native_success','native_matches_intended','action_errors')}),flush=True)
 (a.output/'report.json').write_text(json.dumps({'schema':'webarena-browser-negative-native-audit-v1','cases':rows,'grader_script_sha256':sha(__file__),'scope':'Actual scripted browser paths; native HAR grading retained separately from intended task outcome; no automatic relabeling'},indent=2))
if __name__=='__main__':main()
