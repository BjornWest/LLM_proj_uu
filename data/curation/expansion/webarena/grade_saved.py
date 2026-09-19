"""Native grader checks on retained HAR/derived answers; no browser or model.

Negative responses/HARs are derivative fixtures, never browser-negative evidence.
Expected values stay inside WebArenaVerified. Original artifacts are read-only.
"""
import argparse,hashlib,json
from importlib.metadata import version
from pathlib import Path
from urllib.parse import urlsplit
from webarena_verified.api import WebArenaVerified
from webarena_verified.types.config import WebArenaVerifiedConfig

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 p=argparse.ArgumentParser();p.add_argument('--browser-report',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
 api=WebArenaVerified(config=WebArenaVerifiedConfig(environments={'__SHOPPING__':{'urls':['http://localhost:7770']},'__REDDIT__':{'urls':['http://localhost:9999']}}));reports=[]
 for row in json.loads(a.browser_report.read_text())['tasks']:
  if row['derived_response'] is None:continue
  trace=Path(row['trace']);har=trace/'network.har';response=row['derived_response'];tid=row['task_id'];negative_response=dict(response);negative_har=har
  if response['task_type']=='retrieve':negative_response['retrieved_data']=[]
  else:
   negative_har=a.output/f'{tid}-negative.har';data=json.loads(har.read_text());task=api.get_task(tid).model_dump(mode='json'); target_paths={urlsplit(e['expected']['url'].replace('__SHOPPING__','http://localhost:7770').replace('__REDDIT__','http://localhost:9999')).path for e in task['eval'] if e['evaluator']=='NetworkEventEvaluator'};data['log']['entries']=[e for e in data['log']['entries'] if urlsplit(e['request']['url']).path not in target_paths];assert data['log']['entries'], 'Negative HAR must remain parseable';negative_har.write_text(json.dumps(data))
  item={'browser_positive':row['browser_positive'],'task_id':tid,'trace':str(trace),'har_sha256':sha(har),'positive_response':response,'negative_response':negative_response,'negative_kind':'wrong_answer' if response['task_type']=='retrieve' else 'required_path_removed','browser_negative':None,'authorization_preserved':None,'training_ready':False}
  for label,resp,h in [('positive',response,har),('negative',negative_response,negative_har)]:
   try:item[label]=api.evaluate_task(task_id=tid,agent_response=resp,network_trace=h).model_dump(mode='json')
   except Exception as e:item[label]={'exception_type':type(e).__name__,'exception':str(e)}
  item['native_controls_pass']=item['positive'].get('score')==1 and item['positive'].get('status')=='success' and item['negative'].get('score')==0 and item['negative'].get('status')=='failure';reports.append(item);print(json.dumps({'task_id':tid,'pass':item['native_controls_pass'],'positive':item['positive'].get('score'),'negative':item['negative'].get('score')}),flush=True)
 out={'schema':'webarena-expansion-native-checks-v1','grader_version':version('webarena-verified'),'browser_report_sha256':sha(a.browser_report),'grader_script_sha256':sha(Path(__file__)),'scope':'Positive real browser HAR/DOM-derived scripted response; derivative wrong-answer/required-path-removed negative fixtures; not negative browser paths or general authorization audit','tasks':reports}
 (a.output/'report.json').write_text(json.dumps(out,indent=2))
if __name__=='__main__':main()
