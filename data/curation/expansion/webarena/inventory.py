"""Build a source-bound inventory; inspection is not browser acceptance.

All evaluator content stays in private grader_input. policy_input contains only
an unchanged original goal, start URLs, and the declared final-response schema.
No expected values are copied into policy_input.
"""
import argparse,collections,hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[4]
SOURCE=ROOT/'.local/webarena-verified/dataset.json'
REVISION='6473f72db5dcefc97b5725b59e734504edc28a21'
INSTALLED={'shopping','reddit'}
BATCH=[21,27,66,96,117,158,163,188,260,324]
CAPABILITIES={21:['read_reviews','semantic_filter','pagination'],27:['forum_navigation','sort_new','comment_filter','count'],66:['forum_navigation','ranked_subset','semantic_filter'],96:['account_navigation','order_history','missing_information'],117:['account_navigation','pagination','date_normalization'],158:['search','capacity_comparison','product_navigation'],163:['read_reviews','rating_filter'],188:['account_navigation','status_filter','price_extraction'],260:['category_navigation'],324:['search','sort_price']}
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def classify(t):
 e=t['eval'][0]['expected'];kind=e['task_type'];status=e['status'];supported=set(t['sites'])<=INSTALLED
 return {'source':'webarena-verified','source_task_id':str(t['task_id']),'source_revision':REVISION,'source_row_revision':t.get('revision'),'template_id':str(t['intent_template_id']),'site_ids':t['sites'],'policy_input':{'goal':t['intent'],'start_urls':t['start_urls'],'results_schema':t['eval'][0].get('results_schema')},'grader_input':{'source_evaluators':t['eval'],'source_instantiation':t.get('instantiation_dict')},'capabilities':CAPABILITIES.get(t['task_id'],[kind]),'original_task_type':kind,'original_expected_status':status,'side_effect_class':'read_only_candidate' if kind in ('retrieve','navigate') else 'stateful_or_draft_requires_review','readiness':{'source_inventory':True,'sites_installed':supported,'browser_positive':None,'browser_negative':None,'native_grader':None,'independent_review':None,'model_tested':None,'training_ready':False},'blockers':([] if supported else ['site_not_installed'])+(['isolation_required_before_mutation'] if kind=='mutate' else [])+['task_not_yet_browser_validated'],'authorization_coverage':None,'source_reference':f'https://github.com/ServiceNow/webarena-verified/tree/{REVISION}','license_reference':'https://github.com/ServiceNow/webarena-verified/blob/'+REVISION+'/LICENSE','license_audit_status':'reference_only; site asset licenses separate','first_batch':t['task_id'] in BATCH}
def build(source=SOURCE):
 rows=json.loads(source.read_text());records=[classify(t) for t in rows];eligible=[t for t in rows if set(t['sites'])<=INSTALLED]
 combinations=collections.Counter('+'.join(t['sites']) for t in rows)
 summary={'schema':'webarena-expansion-inventory-v1','source_path':str(source.relative_to(ROOT)),'source_sha256':digest(source),'source_revision':REVISION,'task_count':len(rows),'template_count':len({t['intent_template_id'] for t in rows}),'installed_site_tasks':len(eligible),'installed_site_templates':len({t['intent_template_id'] for t in eligible}),'installed_read_only_candidates':sum(t['eval'][0]['expected']['task_type'] in ('retrieve','navigate') for t in eligible),'site_combinations':dict(combinations),'first_batch_ids':BATCH,'first_batch_template_count':len({t['intent_template_id'] for t in rows if t['task_id'] in BATCH}),'count_semantics':'Source task IDs; distinct templates reported separately. No browser acceptance implied.'}
 return records,summary
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False);records,summary=build();(a.output/'inventory.jsonl').write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in records));(a.output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');(a.output/'batch-01.json').write_text(json.dumps([x for x in records if x['first_batch']],indent=2)+'\n');print(json.dumps(summary,indent=2))
