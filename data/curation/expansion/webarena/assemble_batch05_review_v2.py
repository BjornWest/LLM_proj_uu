"""Source-bound batch05 review; never equate selected IDs with accepted tasks."""
import argparse
from collections import Counter
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[4]
BASE=ROOT/'.local/expansion-webarena'
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def build(output):
 output.mkdir(parents=True,exist_ok=False)
 contracts=read(BASE/'batch05-plan-v1/contracts.json');selected={};files=set()
 pins=read(ROOT/'.local/curation-expansion/frozen-runtime-v1/manifest.json')['source_sha256']
 for bn,gn in [('batch05-development-positive-v1','batch05-development-native-v1'),('batch05-frozen-pairs-v2','batch05-frozen-native-v2'),('batch05-capacity-pair-v5','batch05-capacity-native-v5'),('batch05-review-author-pairs-v6','batch05-review-author-native-v6')]:
  browser_path=BASE/bn/'report.json';grade_path=BASE/gn/'report.json';b=read(browser_path);grades={(g['task_id'],g['variant']):g for g in read(grade_path)['cases']}
  for c in b['tasks']:
   n=c['task_id']
   if bn.startswith('batch05-development') and n not in (261,262,263,264):continue
   trace=ROOT/c['trace'];folder=trace.parent.parent;before=read(folder/'source-before.json');after=read(folder/'source-after.json')
   assert before==after and c['source_unchanged']
   profile=read(folder/'profile.json');loaded=read(trace/'metadata.json')['runtime']['source_sha256']
   assert loaded=={Path(k).name:v for k,v in pins.items()}
   g=grades.get((n,c['variant']))
   selected[(n,c['variant'])]={'variant':c['variant'],'trace':c['trace'],'browser_report':str(browser_path.relative_to(ROOT)),
    'native_report':str(grade_path.relative_to(ROOT)),'profile':str((folder/'profile.json').relative_to(ROOT)),
    'source_unchanged':True,'actual_loaded_snapshot_matches':True,'harness_profile':profile['harness']['name'],
    'observation_characters':profile['observation_chars'],'scripted_path_completed':c['scripted_path_completed'],
    'delivery_aligned':c['delivery_aligned'],'action_error_count':c['summary']['action_error_count'],'error':c['summary']['error'],
    'native_status':g['native_result']['status']if g else None,'native_score':g['native_result']['score']if g else None,
    'native_grader_error':g['native_grader_error']if g else None,'native_matches_intended':g['native_matches_intended']if g else None}
 tasks=[]
 for contract in contracts:
  n=int(contract['source_task_id']);cases=[selected[(n,v)]for v in ['positive','negative']if(n,v)in selected];flags=[]
  if n in (261,262,263,264):status='blocked_nested_menu_path';flags.append('Only failed original keyboard-opening development path retained; no hidden-menu click, hover-tool addition or direct-URL shortcut.')
  elif n==142:status='blocked_hair_accessory_scope';flags.append('Broad hair-style total includes$11.99 hairbands; native excludes them. Original wording retained; explicit exclusion proposed, not executed.')
  elif n in (301,302):status='blocked_native_history_query_coverage';flags.append('Full37-row inspection uses limit=50; native response accepts absence but navigation predicate rejects that display-only query. No evidence rewritten to remove it.')
  elif len(cases)!=2 or not all(c['scripted_path_completed']and c['delivery_aligned']for c in cases):status='blocked_scripted_path'
  elif not all(c['native_matches_intended']is True for c in cases):status='blocked_native_verifier_disagreement'
  elif any(c['action_error_count']for c in cases):status='scripted_pair_with_action_warnings'
  else:status='scripted_pair_validated_pending_review'
  if n in (227,228,229,230):flags.append('Brand membership inferred from visible title prefix; no catalog manufacturer field claim.')
  if n==285:flags.append('Nintendo Switch name query followed by visible capacity comparison; review capacity text and product-universe coverage separately.')
  if n in (143,144,145):flags.append('Privileged semantic line-item selection retained with actual products; native match alone is not independent category interpretation.')
  if n in (166,191,225,234,235,301,302):flags.append('Negative preserves null data and changes status toSUCCESS; schema errors never count as intentional rejection.')
  tasks.append({'source':contract['source'],'source_task_id':str(n),'source_template_id':contract['template_id'],'source_revision':contract['source_revision'],
    'site_ids':contract['site_ids'],'original_goal':contract['policy_input']['goal'],'status':status,'audit_flags':flags,'cases':cases,
    'independent_acceptance':None,'training_ready':False,'authorization_satisfied':None,'safe_success':None})
 dirs=['batch05-plan-v1','batch05-source-v1','batch05-source-v2','batch05-development-positive-v1','batch05-development-native-v1',
  'batch05-protocol-v2','batch05-frozen-pairs-v2','batch05-frozen-native-v2','batch05-source-v3','batch05-capacity-pair-v3','batch05-capacity-native-v3','batch05-query-limit-v1','batch05-source-v4','batch05-capacity-pair-v4','batch05-capacity-native-v4','batch05-short-query-recon-v1','batch05-source-v5','batch05-capacity-pair-v5','batch05-capacity-native-v5','batch05-capacity-unit-v5','batch05-source-v6','batch05-review-author-pairs-v6','batch05-review-author-native-v6','review-batch05-v1','batch05-recon-home-v1',
  'batch05-development-recovery-v1','batch05-development-recovery-native-v1','maps-native-root-gate-audit-v1','batch05-menu-recon-v1','batch05-menu-recon-v2','batch05-menu-recon-v3','batch05-menu-recon-v4','remaining-after100-inventory-v1','batch05-semantic-review-v1']
 for name in dirs:files.update(p for p in(BASE/name).rglob('*')if p.is_file())
 files.update([Path(__file__),ROOT/'data/curation/expansion/webarena/grade_browser_pairs_v2.py',ROOT/'data/curation/expansion/webarena/assemble_batch05_review.py'])
 result={'schema':'webarena-expansion-batch05-review-v2','supersedes_review':'.local/expansion-webarena/review-batch05-v1/report.json','source_task_ids':len(tasks),'source_templates':len({t['source_template_id']for t in tasks}),
  'new_source_templates':3,'site_contexts':1,'selected_browser_cases':len(selected),'selected_final_pair_browser_cases':52,'closure_browser_attempts':62,
  'development_and_closure_browser_attempts':92,'counts_by_status':dict(Counter(t['status']for t in tasks)),
  'network_model_calls':0,'independently_accepted':0,'training_ready':0,'tasks':tasks,
  'artifact_sha256':{str(p.relative_to(ROOT)):sha(p)for p in sorted(files)},
  'notes':['100 cumulative selected source IDs is not100 accepted tasks. Parent owns independent admission.',
   'Selected evidence contains52 final cases plus4 failed development-only menu paths. Task285v5 replaces its failed v2/v3/v4 pairs and387/388v6 replace their failedv2 pairs in selection, not in historical artifacts.',
   'Development serialization errors occurred after actual browser episodes; traces/source guards remain even where case report failed.',
   'Final copied runtime unchanged; driver profilev2 plus separately corrected task285 profilev5 and review-author387/388 profilev6.240-second process limit accommodates complete year-history inspection.',
   'Zero model calls. These are privileged scripted tests, not teacher or policy capability evidence.', 'Episode counts refer to BrowserGym cases; six additional GET-only Playwright reconnaissance sessions are separate, including one retrospectively documented locator timeout.']}
 (output/'report.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:result[k]for k in ['source_task_ids','source_templates','selected_browser_cases','counts_by_status']}));print('Artifact hashes',len(files))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);build(p.parse_args().output)
