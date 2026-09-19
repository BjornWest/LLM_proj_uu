"""Template-first planning only. Does not promote inventory to accepted tasks."""
import argparse,json,hashlib,collections
from pathlib import Path
from data.curation.expansion.webarena.inventory import ROOT,SOURCE,REVISION,BATCH
MAP_FIRST=[70,248,253,369,377,16,36,52,98,363]
ADMIN_DIAGNOSTICS=[157,94,77,112,119,183,208,344,704,709]
def diversify(rows,count,preferred=()):
 chosen=[];seen=set();ids=set()
 for i in preferred:
  t=next(t for t in rows if t['task_id']==i);chosen.append(t);ids.add(i);seen.add(t['intent_template_id'])
 for t in rows:
  if len(chosen)>=count:break
  if t['intent_template_id'] not in seen:chosen.append(t);ids.add(t['task_id']);seen.add(t['intent_template_id'])
 for t in rows:
  if len(chosen)>=count:break
  if t['task_id'] not in ids:chosen.append(t);ids.add(t['task_id'])
 return chosen
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False);rows=json.loads(SOURCE.read_text());out=[]
 for site,n,pref in [('shopping',40,[i for i in BATCH if i not in (27,66)]),('reddit',30,[27,66]),('map',30,MAP_FIRST)]:
  for t in diversify([t for t in rows if t['sites']==[site]],n,pref):out.append({'source_task_id':t['task_id'],'template_id':t['intent_template_id'],'sites':t['sites'],'goal':t['intent'],'task_type':t['eval'][0]['expected']['task_type'],'source_status':t['eval'][0]['expected']['status'],'status':'candidate_unvalidated','training_ready':False})
 result={'schema':'webarena-expansion-candidate-plan-v1','source_revision':REVISION,'source_sha256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),'scope':'Provisional 100 source IDs, not accepted tasks; site availability and relevance remain gates','task_count':len(out),'template_count':len({t['template_id'] for t in out}),'sites':dict(collections.Counter(t['sites'][0] for t in out)),'tasks':out,'shopping_admin_diagnostic_candidates':[{'source_task_id':i,'goal':rows[i]['intent'],'status':'retailer_workflow_relevance_review_required'} for i in ADMIN_DIAGNOSTICS],'blocked_additional_sites':{'gitlab':'not currently installed; relevance and download budget pending','wikipedia':'not currently installed; endpoint/source packaging availability unresolved','shopping_admin':'parent provisioning; back-office rather than consumer context'}}
 (a.output/'candidates-100.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k not in ('tasks','shopping_admin_diagnostic_candidates')},indent=2))
