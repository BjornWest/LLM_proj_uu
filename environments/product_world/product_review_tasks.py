"""Trusted corpus consumption and bounded review-count tasks for exact products."""
from copy import deepcopy

from environments.product_review_sites.evidence import validate_evidence,ASPECTS,PUBLISHER
from environments.shopping_intent.review_evidence import summarize,grade_counts
from .generator import rng,digest


def summaries_for(world,export,requirements):
    validate_evidence(world,export)
    public=export['public'];scopes={(c['sku_id'],c['aspect_id'],c['context_id']):c['status'] for c in public['coverage']}
    reports={}
    for report in public['reviews']:reports.setdefault(report['subject']['id'],[]).append(report)
    results={}
    for p in world['public']['products']:
        sku=p['product_id'];results[sku]={}
        for req in requirements:
            aspect=req['aspect_id'];context=req['context_id'];spec=ASPECTS.get(aspect)
            if req['publisher_id']!=PUBLISHER or not spec or context!=spec['context'] or p['category'] not in spec['families']:continue
            results[sku][aspect+'@'+context]=summarize(reports.get(sku,[]),sku_id=sku,aspect_id=aspect,
                context_id=context,complete=scopes.get((sku,aspect,context))=='complete')
    return results


def sample_count_task(world,*,seed=0,sku_id=None,aspect_id=None):
    """Named-product authoring: uses catalog identity only, never sampled opinions."""
    r=rng(seed,'product-review-count-task-v1');products=sorted(world['public']['products'],key=lambda p:p['product_id'])
    p=r.choice(products) if sku_id is None else next((p for p in products if p['product_id']==sku_id),None)
    if p is None:raise ValueError('Unknown count-task SKU')
    aspects=[k for k,v in ASPECTS.items() if p['category'] in v['families']]
    aspect=r.choice(aspects) if aspect_id is None else aspect_id
    if aspect not in aspects:raise ValueError('Aspect does not apply to product family')
    spec=ASPECTS[aspect]
    requirement={'publisher_id':PUBLISHER,'aspect_id':aspect,'context_id':spec['context']}
    text=r.choice((f'For {p["name"]}, how many reader reviews support or contradict {spec["label"]}? Keep mixed views separate.',
        f'Can you count what readers say about {spec["label"]} for {p["name"]}? I want the positive, negative and mixed counts.'))
    task={'schema_version':'product-review-count-task-v1','sku_id':p['product_id'],'requirement':requirement,
        'unit':'canonical_review','public':{'user_message':text,'sku_id':p['product_id'],'memories':{'profile':[],'episodes':[]},
        'environment_context':'Use the published corpus as of its stated date, for this exact SKU and actual use in the named context. Count each canonical review once. Missing coverage is unknown; absence of a claim is not its negation.',
        'answer_contract':{'status':'review_counts | uncertain','review_counts':'Integer counts: positive, negative, neutral, mixed, not_assessed. Positive means the named claim is supported, including when that claim describes a complaint.'}}}
    task['task_sha256']=digest(task)
    return task


def grade_count_task(world,export,task,answer,*,effects):
    unsigned={k:v for k,v in task.items() if k!='task_sha256'}
    if task.get('schema_version')!='product-review-count-task-v1' or task['task_sha256']!=digest(unsigned):raise ValueError('Count task fingerprint mismatch')
    if not isinstance(effects,list):raise ValueError('Trusted effects ledger required')
    req=task['requirement'];summary=summaries_for(world,export,[req])[task['sku_id']][req['aspect_id']+'@'+req['context_id']]
    return {'structured_claims_correct':not effects and grade_counts(summary,answer),'full_response_evaluated':False,
        'reference':deepcopy(summary),'scope':'Structured review counts only; free-text extraction and source-link grading are not implemented.'}
