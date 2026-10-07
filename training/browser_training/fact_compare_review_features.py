"""Narrow formal composite obligations → qualified native observation features.

No answer/reasoning parsing, corpus-truth exposure, invented assertion identities,
or cross-SKU joins. Complete compound slots can support their explicit scoped
native scalar records; partial compound reads remain unknown per scalar.
"""
from collections import Counter
from copy import deepcopy

from .fact_exposure import object_digest, require

TASK='website-catalog-compare-review-task-v1'
_BASIS='all_recorded_ratings_all_options_including_silent'
_REVIEW_COUNTS={'summary.rating_count':'rating_count',
                'summary.written_review_count':'written_review_count',
                'summary.rating_only_count':'rating_only_count'}


def compile_roles(task):
    require(task.get('schema_version')==TASK and task.get('kind')=='compare_facts_and_reviews',
            'Unsupported structured task')
    models=task['comparison_task']['models']
    subjects={m['product_id'] for m in models}
    require(len(models)==len(subjects)==2,'Exact two-model task required')
    roles=deepcopy(task['required_obligations']);ids=set()
    for role in roles:
        require(role['role_id'] not in ids and role['product_id'] in subjects,'Invalid task role identity')
        ids.add(role['role_id']);field=role['field']
        if role['source_family']=='retailer':
            require(field in task['comparison_task']['fields'] and field.startswith('product.facts.'),
                    'Undeclared model field')
            role['dependencies']=[[{'kind':'retailer_scalar','field':field}]]
        elif role['source_family']=='product_reviews' and role.get('operation')=='rating_summary':
            if field in _REVIEW_COUNTS:
                role['dependencies']=[[{'kind':'review_aggregate','field':_REVIEW_COUNTS[field]}]]
            elif field.startswith('summary.star_counts.') and field.rsplit('.',1)[-1] in tuple('12345'):
                role['dependencies']=[[{'kind':'review_aggregate','field':'star_counts',
                                        'stars':int(field.rsplit('.',1)[-1])}]]
            elif field=='summary.mean_rounded':
                # All labelled histogram cells establish the exact numerator and
                # denominator for native half-up rounding, including silent votes.
                role['dependencies']=[[{'kind':'review_aggregate','field':'star_counts','stars':s}
                                       for s in range(1,6)]]
            else:role['dependencies']=[]
        else:role['dependencies']=[] # Topic classification needs its own public-text dependency adapter.
    return roles


def bind_obligations(task,obligations):
    """The Website private file is the exact native roles, not a rewritten plan."""
    require(isinstance(obligations,list) and obligations==task['required_obligations'],
            'Private obligations/task mismatch')
    return {'schema':'compare-review-obligations-binding-v1','task_id':task['task_id'],
            'task_sha256':object_digest(task),'obligations_sha256':object_digest(obligations),
            'required_role_count':len(compile_roles(task)),
            'qualification':'identity_binding_not_public_or_delivery_acceptance'}


def _matches(record,role,dependency):
    b=record['binding'];pid=role['product_id']
    if b.get('source_family')!=role['source_family'] or b.get('product_id')!=pid:return None
    if record['effective_state'].get('product_id')!=pid:return None
    field=dependency['field']
    if dependency['kind']=='review_aggregate':
        if (b.get('authority')!='renderer_native_review_aggregate' or b.get('grain')!='model'
                or b.get('basis')!=_BASIS or b.get('field')!=field
                or ('stars' in dependency and b.get('stars')!=dependency['stars'])):return None
        return record['status']
    if b.get('authority')=='native_public_field':
        if (b.get('field')!=field or b.get('subject_type')!='product' or b.get('subject_id')!=pid
                or b.get('status') not in (None,'known') or b.get('unit')!=role.get('unit')):return None
        if role.get('basis') is not None:return None # No producer-bound qualifier part yet.
        return record['status']
    if b.get('authority')=='selected_slot':
        for assertion in b.get('assertions',[]):
            if (assertion.get('field')==field and assertion.get('subject')=={'kind':'product','id':pid}
                    and assertion.get('status')=='known' and assertion.get('unit')==role.get('unit')
                    and assertion.get('qualifiers',{}).get('basis')==role.get('basis')
                    and assertion.get('mapping_status') in ('authored_scalar_assertion','native_scalar_field_without_authored_meaning')):
                # These are explicitly declared native records, not arbitrary
                # prose entailment. Their complete producer slot is conjunctive.
                return 'complete' if record['status']=='complete' else 'unknown'
    return None


def project(task,native):
    require(native['schema']=='native-fact-delivery-features-v1','Unsupported transport features')
    records=native['records'];rows=[]
    for role in compile_roles(task):
        alternatives=[];used=set()
        states={object_digest(r['effective_state']) for r in records}
        for conjunction in role['dependencies']:
            for state in states:
                statuses=[]
                for dependency in conjunction:
                    matches=[]
                    for record in records:
                        if object_digest(record['effective_state'])!=state:continue
                        status=_matches(record,role,dependency)
                        if status is not None:
                            matches.append(status);used.add(record['id'])
                    statuses.append('complete' if 'complete' in matches else 'partial' if 'partial' in matches else 'unknown')
                alternatives.append('complete' if all(s=='complete' for s in statuses) else
                                    'partial' if any(s!='unknown' for s in statuses) else 'unknown')
        status='complete' if 'complete' in alternatives else 'partial' if 'partial' in alternatives else 'unknown'
        rows.append({**role,'observation_status':status,'native_record_ids':sorted(used),
                     'qualification':'native_field_transport_not_recall_or_answer_correctness',
                     'reason':None if role['dependencies'] else 'public_dependency_adapter_unbound'})
    counts=Counter(r['observation_status'] for r in rows)
    return {'schema':'compare-review-required-observed-v1','task_id':task['task_id'],
        'task_sha256':object_digest(task),'recipient':native['recipient'],'prefix_step':native['prefix_step'],
        'roles':rows,'features':{'required_role_count':len(rows),
            **{f'{s}_role_count':counts[s] for s in ('complete','partial','unknown')}},
        'producer_qualified':False,'inventory_complete':False,
        'scope':'bounded_native_task_projection_pending_runtime_source_and_public_sufficiency_acceptance'}
