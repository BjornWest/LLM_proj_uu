"""List independently reviewed development tasks without launching environments.

This is a discovery index, not a production registry or permission to run models.
Original contracts, private answers and case-specific source closures stay in their
referenced files. Run `python3 -m data.curation.expansion.accepted_index --help`.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
BASE=Path('data/curation/expansion')


def load(relative): return json.loads((ROOT/relative).read_text())
def pin(relative): return {'path':str(relative),'sha256':hashlib.sha256((ROOT/relative).read_bytes()).hexdigest()}


def tricky_provenance(task,origin):
    environment={'repository':'devinat1/agenttrickydps','revision':'8201821fb64a5075f50b015f99653881ab09a030'}
    if origin=='project_authored':
        src=task['source_reference'];assert src['environment_repo']==environment['repository'] and src['revision']==environment['revision']
        return {'task_source':None,'environment_source':environment,'authored_in_this_project':True,'raw_source_revision_scope':'source_reference object retained from contract'}
    inventory={r['record_id']:r for r in (json.loads(l) for l in (ROOT/'data/curation/inventory.jsonl').read_text().splitlines())}
    ids=task.get('origin_records',task.get('source_record_ids',[]));assert ids,'Original task needs source inventory references'
    records=[inventory[i] for i in ids];revisions={r['source_revision'] for r in records};assert len(revisions)==1
    assert all(r['task_family']==task['source_task_id'] for r in records)
    task_source={'repository':'LiteAgent/liteagent','revision':next(iter(revisions)),'inventory':pin(Path('data/curation/inventory.jsonl')),'record_ids':ids}
    raw=task.get('source_revision')
    scope='task_repository' if raw==task_source['revision'] else 'environment_repository' if raw==environment['revision'] else 'unknown'
    return {'task_source':task_source,'environment_source':environment,'authored_in_this_project':False,'raw_source_revision_scope':scope}


def tricky_rows(contract, reviews, selected=None, label='original'):
    raw=load(contract);tasks=raw['tasks'];rows=[]
    for t in tasks:
        if selected is not None and t['id'] not in selected:continue
        evidence=[pin(p) for p in reviews]
        rows.append({'id':'tricky:'+t['id'],'dataset':'trickyarena','instance_id':t['id'],
          'origin':label,'template_id':t.get('template_id',t.get('source_task_id')),
          'sites':[t.get('site','shop')], 'goal':t['policy_input']['goal'],
          'original_prompt':t.get('original_prompt',t.get('original_upstream_prompt')),
          'source_task_id':t.get('source_task_id',t.get('upstream_task_id')),
          'source_revision':t.get('source_revision',t.get('source_reference')),
          'qualified_provenance':tricky_provenance(t,label),
          'kind':t.get('kind',t.get('task_kind')),'condition':t.get('condition'),
          'contract_reference':pin(contract),'contract_row_id':t['id'],
          'review_references':evidence,'terminal_instruction_integration_required':True,
          'authorization_coverage':t.get('authorization_coverage','partial; unknown beyond recorded checks'),
          'license':t.get('license','upstream_reuse_terms_unspecified'),
          'status':'independently_reviewed_scripted_development','model_tested':False,
          'training_eligible':False,'production_ready':False})
    return rows


def collect():
    rows=[]
    rows+=tricky_rows(BASE/'tricky/contracts.json',[BASE/'tricky-batch01-independent-review.json',BASE/'tricky-native-originals-validation.json'])
    rows+=tricky_rows(BASE/'tricky/batch02/contracts.json',[BASE/'tricky-batch02-independent-review.json',BASE/'tricky-native-originals-validation.json'])
    rows+=tricky_rows(BASE/'tricky_original_remaining/contracts.json',[BASE/'tricky/reviews/remaining-originals-independent-v1.json'])
    batches=[('authored','tricky-authored20-independent-review.json'),('authored02','tricky-authored40-independent-review.json'),('authored03','tricky-authored60-independent-review-v1.json'),('authored04','tricky-authored79-independent-review.json')]
    for batch,review in batches:
        r=load(BASE/review)
        selected={x['task_id'] for x in r['records']}-set(r.get('held_ids',[]))
        if batch=='authored03':selected-={'AU51','AU52'} # prefer separately reviewed strict-draft closure
        rows+=tricky_rows(BASE/'tricky'/batch/'contracts.json',[BASE/review],selected,'project_authored')
    fix=BASE/'tricky-authored-drafts-v2-independent-review.json'
    rows+=tricky_rows(BASE/'tricky/authored03/contracts.json',[fix],set(load(fix)['reviewed_ids']),'project_authored')
    source={str(t['task_id']):t for t in load(Path('.local/webarena-verified/dataset.json'))}
    for review in ['webarena-native20-independent-review.json','webarena-batch03-independent-review.json','webarena-batch04-independent-review.json','webarena-batch05-independent-review-v2.json','webarena-batch06-independent-review-v2.json']:
        report=load(BASE/review)
        for t in report['records']:
            if not t['accepted_development_task']:continue
            raw=source[t['source_task_id']]
            rows.append({'id':'webarena:'+t['source_task_id'],'dataset':'webarena-verified',
                'instance_id':t['source_task_id'],'source_task_id':t['source_task_id'],
                'origin':'original','template_id':t['template_id'],'sites':t['sites'],
                'goal':raw['intent'],'original_prompt':raw['intent'],
                'source_revision':'6473f72db5dcefc97b5725b59e734504edc28a21',
                'kind':raw['eval'][0]['expected']['task_type'],'condition':'upstream_original',
                'contract_reference':pin(Path('.local/webarena-verified/dataset.json')),
                'contract_row_id':raw['task_id'],'review_references':[pin(BASE/review)],
                'terminal_instruction_integration_required':True,
                'authorization_coverage':'GET/HEAD-only browser context; broad authorization remains unknown',
                'license':'See pinned upstream dataset/environment terms; do not infer asset sublicensing',
                'status':'independently_reviewed_scripted_development','model_tested':False,
                'training_eligible':False,'production_ready':False})
    biography_review=BASE/'webarena-biography-independent-review.json'
    biography=load(biography_review)
    assert biography['accepted_development_task'] and biography['goal_unchanged']
    contract=BASE/'webarena_biography/contract.json'; task=load(contract); raw=source['399']
    assert task['policy_input']['goal']==raw['intent']
    rows.append({'id':'webarena:399','dataset':'webarena-verified','instance_id':'399',
        'source_task_id':'399','origin':'original','template_id':task['template_id'],
        'sites':['reddit'],'goal':raw['intent'],'original_prompt':raw['intent'],
        'source_revision':task['source_revision'],'kind':'mutate','condition':'upstream_original',
        'contract_reference':pin(contract),'contract_row_id':task['id'],
        'review_references':[pin(biography_review)],
        'verifier_origin':biography['verifier_origin'],
        'terminal_instruction_integration_required':True,'authorization_coverage':None,
        'execution_requirements':{'profile':biography['profile'],
            'isolated_service_at_validation':'http://localhost:19099',
            'complete_independent_reset_before_unrestricted_model_runs':True},
        'limitations':biography['limitations'],
        'license':'See pinned upstream dataset/environment terms; do not infer asset sublicensing',
        'status':'independently_reviewed_scripted_development','model_tested':False,
        'training_eligible':False,'production_ready':False})
    batch_review=BASE/'webarena/reviews/biography-batch02-review.json'
    batch=load(batch_review);assert batch['passed']
    batch_contract=BASE/'webarena_biography_batch02/contracts.json';contracts=load(batch_contract)
    assert set(batch['source_task_ids'])=={t['source_task_id'] for t in contracts['tasks']}
    for task in contracts['tasks']:
        tid=str(task['source_task_id']);raw=source[tid]
        assert task['policy_input']['goal']==raw['intent']
        rows.append({'id':'webarena:'+tid,'dataset':'webarena-verified','instance_id':tid,
            'source_task_id':tid,'origin':'original','template_id':task['template_id'],
            'sites':['reddit'],'goal':raw['intent'],'original_prompt':raw['intent'],
            'source_revision':contracts['source_revision'],'kind':'mutate','condition':'upstream_original',
            'contract_reference':pin(batch_contract),'contract_row_id':task['id'],
            'review_references':[pin(batch_review)],'verifier_origin':contracts['verifier_origin'],
            'terminal_instruction_integration_required':True,'authorization_coverage':None,
            'execution_requirements':{'profile':'core-tools-v3','slow_mo_ms':0,
                'observation_characters':48000,'isolated_service_at_validation':'http://localhost:19089',
                'complete_independent_reset_before_unrestricted_model_runs':True},
            'limitations':batch['limitations'],
            'license':'See pinned upstream dataset/environment terms; do not infer asset sublicensing',
            'status':'independently_reviewed_scripted_development','model_tested':False,
            'training_eligible':False,'production_ready':False})
    coupon_review=BASE/'tricky/reviews/coupon-review-v2.json'
    assert load(coupon_review)['status']=='accepted_scoped_derived_final_form'
    coupon_contract=BASE/'webarena_coupon/contracts-v2.json'; coupons=load(coupon_contract)
    for task in coupons['tasks']:
        tid=task['source_task_id'];raw=source[tid]
        assert task['policy_input']['goal']==raw['intent']
        rows.append({'id':'webarena:'+tid,'dataset':'webarena-verified','instance_id':tid,
            'source_task_id':tid,'origin':'original','template_id':task['template_id'],
            'sites':['shopping'],'goal':raw['intent'],'original_prompt':raw['intent'],
            'source_revision':coupons['source_revision'],'kind':'draft','condition':'upstream_original',
            'contract_reference':pin(coupon_contract),'contract_row_id':task['id'],
            'review_references':[pin(coupon_review)],'verifier_origin':coupons['verifier_origin'],
            'terminal_instruction_integration_required':True,'authorization_coverage':None,
            'execution_requirements':{'profile':'core-tools-v3','slow_mo_ms':0,
                'observation_characters':48000,'isolated_browser_context':True,
                'GET_HEAD_only_same_origin_route':True,'origin_at_validation':'http://localhost:7770'},
            'limitations':coupons['limitations'],
            'license':'See pinned upstream dataset/environment terms; do not infer asset sublicensing',
            'status':'independently_reviewed_scripted_development','model_tested':False,
            'training_eligible':False,'production_ready':False})
    vote_review=BASE/'webarena-votes-independent-review.json'; votes=load(vote_review)
    vote_contract=BASE/'webarena_votes/contracts.json'; raw_votes=load(vote_contract)
    for task in raw_votes['tasks']:
        if task['source_task_id'] not in votes['accepted_ids']:continue
        tid=str(task['source_task_id']);raw=source[tid]
        assert task['policy_input']['goal']==raw['intent'] and votes['goal_unchanged']
        rows.append({'id':'webarena:'+tid,'dataset':'webarena-verified','instance_id':tid,
            'source_task_id':tid,'origin':'original','template_id':task['template_id'],
            'sites':['reddit'],'goal':raw['intent'],'original_prompt':raw['intent'],
            'source_revision':raw_votes['source_revision'],'kind':'mutate','condition':'upstream_original',
            'contract_reference':pin(vote_contract),'contract_row_id':task['id'],
            'review_references':[pin(vote_review)],'verifier_origin':votes['verifier_origin'],
            'terminal_instruction_integration_required':True,'authorization_coverage':None,
            'execution_requirements':{'profile':'core-tools-v3','slow_mo_ms':0,'observation_characters':48000,
                'isolated_service_at_validation':'http://localhost:19099',
                'complete_independent_reset_before_unrestricted_model_runs':True},
            'limitations':votes['limitations'],
            'license':'See pinned upstream dataset/environment terms; do not infer asset sublicensing',
            'status':'independently_reviewed_scripted_development','model_tested':False,
            'training_eligible':False,'production_ready':False})
    posts_review=BASE/'webarena-posts-independent-review.json';posts=load(posts_review)
    post_contract=BASE/'webarena_posts/contracts.json';post_tasks=load(post_contract)
    assert posts['accepted_ids']==sorted(t['source_task_id'] for t in post_tasks['tasks'])
    for task in post_tasks['tasks']:
        tid=str(task['source_task_id']);raw=source[tid]
        assert task['original_source']==raw and task['policy_input']['goal']==raw['intent']
        rows.append({'id':'webarena:'+tid,'dataset':'webarena-verified','instance_id':tid,
            'source_task_id':tid,'origin':'original','template_id':task['template_id'],
            'sites':['reddit'],'goal':raw['intent'],'original_prompt':raw['intent'],
            'source_revision':'6473f72db5dcefc97b5725b59e734504edc28a21',
            'raw_contract_source_revision':post_tasks['source_revision'],
            'source_dataset_sha256':post_tasks['source_dataset_sha256'],
            'kind':'mutate','condition':'upstream_original',
            'contract_reference':pin(post_contract),'contract_row_id':task['id'],
            'review_references':[pin(posts_review)],'verifier_origin':'project_derived_final_persisted_post',
            'terminal_instruction_integration_required':True,'authorization_coverage':None,
            'execution_requirements':{'profile':'core-tools-v3','slow_mo_ms':0,'observation_characters':48000,
                'isolated_service_at_validation':'http://localhost:19099',
                'complete_independent_reset_before_unrestricted_model_runs':True},
            'limitations':posts['limitations']+task['contract_notes'],
            'license':'See pinned upstream dataset/environment terms; do not infer asset sublicensing',
            'status':'independently_reviewed_scripted_development','model_tested':False,
            'training_eligible':False,'production_ready':False})
    # Dataset identities must not split merely because one contract serialized
    # an upstream integer as a string. Preserve the raw value separately.
    for row in rows:
        row['raw_template_id']=row['template_id']
        row['template_id']=str(row['template_id']) if row['template_id'] is not None else None
    assert len({r['id'] for r in rows})==len(rows),'Duplicate acceptance IDs'
    counts=Counter(r['dataset'] for r in rows)
    progress=load(BASE/'progress.json')
    for dataset,value in counts.items():assert value==progress['datasets'][dataset]['accepted_development_tasks'],(dataset,value)
    return sorted(rows,key=lambda r:(r['dataset'],r['instance_id']))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--dataset',choices=['trickyarena','webarena-verified']);p.add_argument('--site')
    p.add_argument('--origin',choices=['original','project_authored']);p.add_argument('--kind')
    p.add_argument('--task');p.add_argument('--json',action='store_true');p.add_argument('--summary',action='store_true')
    p.add_argument('--output',type=Path,help='Write new immutable JSON index; refuses existing paths')
    a=p.parse_args();rows=collect()
    rows=[r for r in rows if (not a.dataset or r['dataset']==a.dataset) and (not a.site or a.site in r['sites']) and (not a.origin or r['origin']==a.origin) and (not a.kind or r['kind']==a.kind) and (not a.task or r['id']==a.task)]
    report={'schema':'expansion-accepted-discovery-index-v2','scope':'scripted development; requires fresh runtime/environment preflight for execution',
      'counts':dict(Counter(r['dataset'] for r in rows)),'source_type_counts':dict(Counter(r['origin'] for r in rows)),
      'template_counts':{dataset:len({r['template_id'] for r in rows if r['dataset']==dataset}) for dataset in sorted({r['dataset'] for r in rows})},
      'site_counts':dict(Counter((r['dataset']+'/'+s) for r in rows for s in r['sites'])),
      'builder':pin(Path(__file__).relative_to(ROOT)),'tasks':rows}
    if a.output:
        with a.output.open('x') as out:json.dump(report,out,indent=2);out.write('\n')
    if a.summary:print(json.dumps({k:v for k,v in report.items() if k!='tasks'},indent=2))
    elif a.json:print(json.dumps(report,indent=2))
    else:
        for r in rows:print(f"{r['id']}\t{','.join(r['sites'])}\t{r['origin']}\t{r['kind']}\t{r['goal']}")


if __name__=='__main__':main()
