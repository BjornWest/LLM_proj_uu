"""Build an immutable, source-bound review index for the remaining40 originals."""
import argparse,collections,hashlib,json
from pathlib import Path
ROOT=Path('/home/bjorn/code/LLM_proj_uu');BASE=ROOT/'.local/expansion-webarena'
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def build(out):
 out.mkdir(parents=True,exist_ok=False)
 contracts=read(BASE/'batch06-plan-v1/contracts.json');selected={};files=set();dirs=sorted(p for p in BASE.glob('batch06-*')if p.is_dir())
 pins=read(ROOT/'.local/curation-expansion/frozen-runtime-v1/manifest.json')['source_sha256']
 for directory in dirs:
  if not(directory/'report.json').exists():continue
  report=read(directory/'report.json')
  if report.get('schema')!='webarena-native-browser-suite-v1':continue
  grade_dir=BASE/(directory.name.replace('-positive-','-native-').replace('-pairs-','-native-'))
  grades={(r['task_id'],r['variant']):r for r in read(grade_dir/'report.json')['cases']}if(grade_dir/'report.json').exists()else{}
  for c in report['tasks']:
   trace=ROOT/c['trace'];folder=trace.parent.parent;before=read(folder/'source-before.json');after=read(folder/'source-after.json');profile=read(folder/'profile.json')
   assert before==after and c['source_unchanged'];assert read(trace/'metadata.json')['runtime']['source_sha256']=={Path(k).name:v for k,v in pins.items()}
   g=grades.get((c['task_id'],c['variant']))
   item={'variant':c['variant'],'trace':c['trace'],'browser_report':str((directory/'report.json').relative_to(ROOT)),'native_report':str((grade_dir/'report.json').relative_to(ROOT))if g else None,'profile':str((folder/'profile.json').relative_to(ROOT)),'source_unchanged':True,'actual_loaded_snapshot_matches':True,'harness_profile':profile['harness']['name'],'observation_characters':profile['observation_chars'],'scripted_path_completed':c['scripted_path_completed'],'delivery_aligned':c['delivery_aligned'],'action_error_count':c['summary']['action_error_count'],'error':c['summary']['error'],'derived_response':c['derived_response'],'final_url':c['final_url'],'native_status':g['native_result']['status']if g else None,'native_score':g['native_result']['score']if g else None,'native_grader_error':g['native_grader_error']if g else None,'native_matches_intended':g['native_matches_intended']if g else None}
   key=(c['task_id'],c['variant']);prev=selected.get(key)
   if not prev or ('pairs' in directory.name)or not prev['scripted_path_completed']:selected[key]=item
 tasks=[]
 for contract in contracts:
  n=int(contract['source_task_id']);cases=[selected[(n,v)]for v in ['positive','negative']if(n,v)in selected];flags=[]
  if contract['source_hold']:status='held_source_contract';flags.append(contract['source_hold'])
  elif n in(125,126,279,284):status='blocked_query_pagination_bound';flags.append('More than30 original result pages; no complete membership/min-max claim.')
  elif n in(270,271,272,273):status='blocked_original_price_control';flags.append('Actual visible price buckets do not express requested exact ceiling; no forged URL.')
  elif n in(352,353,354,355):status='blocked_native_category_route_coverage';flags.append('Original UI sidebar reaches correct filtered category and sort, but native expects canonical category path.')
  elif n in(280,282,385):status='blocked_native_semantic_membership';flags.append('Retained actual qualifying product/reviewer absent from gold;280 additionally has ambiguous cable/charger scope.')
  elif len(cases)!=2 or not all(c['scripted_path_completed']and c['delivery_aligned']for c in cases):status='blocked_scripted_path'
  elif not all(c['native_matches_intended']is True for c in cases):status='blocked_native_verifier_disagreement'
  elif any(c['action_error_count']for c in cases):status='scripted_pair_with_action_warnings'
  else:status='scripted_pair_validated_pending_review'
  if n in(125,126,279,280,282,284,286):flags.append('Product membership/capacity and catalog coverage require independent review; scripts derive values from visible pages without loading gold.')
  if n in(22,23,24,26,384,385):flags.append('Semantic review selection is a privileged scripted rule, not a trained classifier. Actual bodies and selected authors retained.')
  if n in(22,24,376):flags.append('Wrong negative status uses null retrieved_data, preserving declared schema; native exceptions never count as rejection.')
  if n in(270,271,272,273,352,353,354,355):flags.append('Original visible category sidebar may produce filtered-parent route rather than native canonical category path; no direct URL substitution.')
  tasks.append({'source':contract['source'],'source_task_id':str(n),'source_template_id':contract['template_id'],'source_revision':contract['source_revision'],'site_ids':contract['site_ids'],'original_goal':contract['policy_input']['goal'],'status':status,'audit_flags':flags,'cases':cases,'independent_acceptance':None,'training_ready':False,'authorization_satisfied':None,'safe_success':None})
 for d in dirs:files.update(p for p in d.rglob('*')if p.is_file())
 files.add(Path(__file__))
 result={'schema':'webarena-expansion-batch06-review-v1','source_task_ids':len(tasks),'source_templates':len({t['source_template_id']for t in tasks}),'site_contexts':1,'new_source_templates':5,'new_browser_exercised_templates':3,'cumulative_selected_source_ids':140,'selected_browser_cases':len(selected),'browser_attempts':sum(len(read(d/'report.json').get('executions',[]))for d in dirs if(d/'report.json').exists()),'counts_by_status':dict(collections.Counter(t['status']for t in tasks)),'network_model_calls':0,'independently_accepted':0,'training_ready':0,'tasks':tasks,'artifact_sha256':{str(p.relative_to(ROOT)):sha(p)for p in sorted(files)},'notes':['40source candidates, not40accepted tasks. Seven source-only holds.','All evidence privileged scripted; no model capability or authorization claim. Historical artifacts preserved.']}
 (out/'report.json').write_text(json.dumps(result,indent=2)+'\n');print(result['counts_by_status']);print('artifact_count',len(files))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);build(p.parse_args().output)
