"""Bind batch04 evidence with separate native, derived and semantic acceptance gates."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[4]
BASE=ROOT/'.local/expansion-webarena'
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def build(output):
 output.mkdir(parents=True,exist_ok=False)
 contracts=read(BASE/'batch04-plan-v1/contracts.json')
 browser_path=BASE/'batch04-frozen-pairs-v3/report.json';grade_path=BASE/'batch04-frozen-native-v3/report.json'
 browser=read(browser_path);grades=read(grade_path);grade_map={(r['task_id'],r['variant']):r for r in grades['cases']}
 pins=read(ROOT/'.local/curation-expansion/frozen-runtime-v1/manifest.json')['source_sha256']
 selected={};files=set()
 for case in browser['tasks']:
  key=case['task_id'],case['variant'];trace=ROOT/case['trace'];folder=trace.parent.parent
  before=read(folder/'source-before.json');after=read(folder/'source-after.json')
  assert before==after and case['source_unchanged']
  profile=read(folder/'profile.json');loaded=read(trace/'metadata.json')['runtime']['source_sha256']
  assert profile['frozen_runtime'].endswith('/frozen-runtime-v1') and loaded=={Path(k).name:v for k,v in pins.items()}
  grade=grade_map.get(key)
  draft=read(trace/'draft-final-state.json')if(trace/'draft-final-state.json').exists()else None
  selected[key]={'variant':case['variant'],'trace':case['trace'],'browser_report':str(browser_path.relative_to(ROOT)),
   'native_report':str(grade_path.relative_to(ROOT)),'profile':str((folder/'profile.json').relative_to(ROOT)),
   'source_unchanged':True,'actual_loaded_snapshot_matches':True,'harness_profile':profile['harness']['name'],
   'observation_characters':profile['observation_chars'],'scripted_path_completed':case['scripted_path_completed'],
   'delivery_aligned':case['delivery_aligned'],'action_error_count':case['summary']['action_error_count'],
   'native_status':grade['native_result']['status']if grade else None,'native_score':grade['native_result']['score']if grade else None,
   'native_grader_error':grade['native_grader_error']if grade else None,'native_matches_intended':grade['native_matches_intended']if grade else None,
   'derived_final_draft':{k:draft[k]for k in ['checks','task_completed','authorization_satisfied','safe_success','verifier_contract']}if draft else None,
   'derived_matches_intended':draft['task_completed']==case['intended_outcome']if draft else None}
 tasks=[]
 special={51:('blocked_date_interval_ambiguity','Calendar-six-month result is9/$1774.62; original native expects7/$1700.84. Explicit-date goal proposed separately, not executed.'),
  67:('blocked_description_scope','A Christmas Carol occurs in title, not body. Proposed visible-post-text wording retained separately.'),
  68:('blocked_description_scope','Same title/body ambiguity; expected author null despite public schema string is retained raw.'),
  141:('semantic_food_scope_review','Food-related selection includes cake decorations; correct raw native result does not settle interpretation.'),
  653:('blocked_derived_draft_semantics','Native HAR accepts wrong final draft. Derived keyword check also accepts a synthetic Do not refund counterexample; final browser pair alone is insufficient. Exact-message adaptation proposed, not executed.'),
  689:('derived_draft_pair_pending_independent_review','Native requires an aborted dummy_bin bridge; no such synthetic traffic is emitted. Final-DOM positive/negative checks are separate.')}
 for contract in contracts:
  n=int(contract['source_task_id']);cases=[selected[(n,v)]for v in ['positive','negative']if(n,v)in selected]
  flags=[]
  if n in special:status,note=special[n];flags.append(note)
  elif len(cases)!=2 or not all(c['scripted_path_completed']and c['delivery_aligned']for c in cases):status='blocked_scripted_path'
  elif not all(c['native_matches_intended']is True for c in cases):status='blocked_native_verifier_disagreement'
  elif any(c['action_error_count']for c in cases):status='scripted_pair_with_action_warnings'
  else:status='scripted_pair_validated_pending_review'
  if n in (653,689):
   if len(cases)!=2 or not all(c['derived_matches_intended']is True for c in cases):status='blocked_derived_draft_check'
  if n==281:flags.append('Corrected query Oral-B limits overbroad Oral matching floral/coral. Product-family membership still checked from visible names; original failed30-page attempt retained.')
  tasks.append({'source':contract['source'],'source_task_id':str(n),'source_template_id':contract['template_id'],
    'source_revision':contract['source_revision'],'site_ids':contract['site_ids'],'original_goal':contract['policy_input']['goal'],
    'status':status,'audit_flags':flags,'cases':cases,'independent_acceptance':None,'training_ready':False,
    'authorization_satisfied':None,'safe_success':None})
 dirs=['batch04-plan-v1','batch04-development-positive-v1','batch04-development-positive-v2','batch04-development-native-v2',
  'batch04-frozen-pairs-v3','batch04-frozen-native-v3','batch04-source-v1','batch04-source-v2','batch04-source-v3',
  'batch04-draft-unit-v1','batch04-draft-unit-v3','batch04-semantic-review-v1','batch04-product-scope-v1','batch04-draft-adversarial-v1']
 for name in dirs:files.update(p for p in(BASE/name).rglob('*')if p.is_file())
 files.update([Path(__file__),ROOT/'data/curation/expansion/webarena/grade_browser_pairs_v2.py',
  ROOT/'.local/curation-expansion/infrastructure/reddit-reset-for-batch3.json'])
 result={'schema':'webarena-expansion-batch04-review-v1','source_task_ids':len(tasks),
  'source_templates':len({t['source_template_id']for t in tasks}),'new_source_templates':5,'site_contexts':2,
  'selected_browser_cases':len(selected),'development_and_closure_browser_attempts':90,'pre_browser_wrapper_failures':30,
  'counts_by_status':dict(Counter(t['status']for t in tasks)),'network_model_calls':0,'independently_accepted':0,'training_ready':0,
  'scope':'28shopping/2forum original tasks. Bounded two-process GET-only final browser pairs; contact drafts are client-side only. Pinned snapshot, not active harness.',
  'tasks':tasks,'artifact_sha256':{str(p.relative_to(ROOT)):sha(p)for p in sorted(files)},
  'notes':['Original goal/evaluators remain in contracts. Proposed adaptations are not silently applied.',
   'Draft v2 development checker missed explicit refund request; v3 adds it prospectively. Same developmental label is distinguished by exact source hashes; no backward relabeling.',
   'Action errors remain visible even if eventual scripted path succeeds. Semantic acceptance is independent of native score.',
   'No model performance or broad authorization claim. Privileged scripts read DOM and make human semantic selections.',
   'Original startup failures predate browser creation and are not90+30 browser episodes.']}
 (output/'report.json').write_text(json.dumps(result,indent=2)+'\n')
 print(json.dumps({k:result[k]for k in ['source_task_ids','source_templates','selected_browser_cases','counts_by_status']}));print('Artifact hashes:',len(files))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);build(p.parse_args().output)
