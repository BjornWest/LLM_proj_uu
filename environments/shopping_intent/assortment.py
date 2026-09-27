"""Physical-branch assortment intent and exact distinct-model reference counts."""
from copy import deepcopy
from .generator import stream,atom
from .catalog import attribute_for
from .semantics import conflicts


def configure(bundle,price_range_sek=None):
    request=bundle['request'];line=request['lines'][0]
    if len(request['lines'])!=1 or line['family_id']!='footwear' or line['model'] is not None:
        raise ValueError('Assortment currently requires a footwear category')
    bounds=(1000,2000) if price_range_sek is None else price_range_sek
    if not isinstance(bounds,(list,tuple)) or len(bounds)!=2 or any(type(x) is not int for x in bounds) or not 0<=bounds[0]<=bounds[1] or bounds[1]<=0:
        raise ValueError('price_range_sek must be two ordered nonnegative integer SEK values, with a positive upper bound')
    request['constraints']={'price_min_minor':bounds[0]*100,'budget_minor':bounds[1]*100}
    request['query'].update(operation='assortment',activity='inspect',objective=[{'field':'matching_model_count','direction':'max'}],
        assortment={'group_by':'physical_branch','count':'distinct_model','availability':'local_saleable_stock_and_inspection',
                    'variant_rule':'at_least_one_matching_sku','price_basis':'listed_item_price','zero_population':'no_match'})
    request['context']['price_basis']='listed_item_price_per_pair'
    bundle['settings']['price_range_sek']=list(bounds)
    # Keep a concrete purpose without duplicating a shoe-type requirement that
    # already implies the activity. Selection depends on intent, never on stock.
    resolved=bundle['resolved_task']['lines'][0]['requirements']
    if not any(p['field'] in ('activity','shoe_type') for p in resolved):
        attr=attribute_for('footwear','activity','eq')
        values=[v for v in attr.values if not conflicts('footwear',resolved+[atom(attr,v)])]
        p=atom(attr,stream(bundle['seed'],'assortment-purpose').choice(values))
        mode=bundle['settings']['resolved_memory_mode']
        if mode=='none':
            line['explicit_requirements'].append(p);source={'kind':'request'}
        else:
            channel=mode if mode in ('profile','episodic') else stream(bundle['seed'],'assortment-purpose-channel').choice(('profile','episodic'))
            fact={'id':'assortment-purpose-memory','subject':line['subject'],'family_id':'footwear','channel':channel,
                  'scope':'durable_family_requirement','predicate':deepcopy(p),'provenance':'synthetic_prior_user_statement'}
            bundle['memory_facts'].append(fact);source={'kind':'memory','id':fact['id'],'channel':channel}
        for key in ('initial_accessible_task','resolved_task'):
            bundle[key]['lines'][0]['requirements'].append({**deepcopy(p),'source':source.copy()})
            bundle[key]['lines'][0]['requirements'].sort(key=lambda p:(p['field'],p['operator']))


def analyze_assortment(task,candidates,*,coverage_complete=False):
    """Count models per branch; unknown variants cannot invent or duplicate models.

    These are private reference facts, not an answer extractor or response grader.
    """
    from .oracle import candidate_checks
    if type(coverage_complete) is not bool:raise ValueError('coverage_complete must be boolean')
    if len({c.get('candidate_id') for c in candidates})!=len(candidates):raise ValueError('Duplicate candidate IDs')
    item_task=deepcopy(task);item_task['query']['operation']='select';item_task['query']['objective']=[]
    rows={};assessments=[]
    for c in candidates:
        if not isinstance(c.get('branch_id'),str) or not c['branch_id'] or len(c['lines'])!=1:
            raise ValueError('Assortment candidates require one SKU at an identified physical branch')
        line=c['lines'][0];sid=line['retailer_id'];bid=c['branch_id'];model=line.get('model_id')
        if not isinstance(model,str) or not model:raise ValueError('Assortment requires canonical model identities')
        row=rows.setdefault((sid,bid),{'retailer_id':sid,'branch_id':bid,'models':{},'unknown_models':set(),
                                    'travel_minutes':c.get('travel_minutes'),'travel_mode':c.get('world_facts',{}).get('travel_mode')})
        assessment=candidate_checks(item_task,c);checks=assessment['requirements']
        stock=c.get('world_facts',{}).get('branch_stock_quantity')
        if stock is not None and (type(stock) is not int or stock<0):raise ValueError('Branch stock must be a nonnegative integer or unknown')
        checks['local_saleable_stock']=None if stock is None else stock>=line['quantity']
        checks['listed_price_known']=None if c.get('total_minor') is None else True
        assessment['status']='ineligible' if False in checks.values() else 'unknown' if None in checks.values() else 'eligible'
        assessments.append(assessment)
        if assessment['status']=='eligible':row['models'].setdefault(model,[]).append(c['candidate_id'])
        elif assessment['status']=='unknown':row['unknown_models'].add(model)
    branches=[]
    for _,row in sorted(rows.items()):
        models=row.pop('models');unknown=row.pop('unknown_models')-models.keys()
        branches.append({**row,'model_count_min':len(models),'model_count_max':len(models)+len(unknown),
                         'matching_model_ids':sorted(models),'unknown_model_ids':sorted(unknown),
                         'matching_candidates_by_model':{k:sorted(v) for k,v in sorted(models.items())}})
    complete=coverage_complete and all(b['model_count_min']==b['model_count_max'] for b in branches)
    result={'status':'determined' if complete else 'uncertain','coverage_complete':coverage_complete,
            'candidate_assessments':assessments,'eligible_candidate_ids':[a['candidate_id'] for a in assessments if a['status']=='eligible'],
            'branches':branches,'count_unit':'distinct_model','best_branch_ids':[],'max_model_count':None}
    if not complete:
        result['reason']='incomplete_population_or_unknown_matching_model_counts'
        return result
    count=max((b['model_count_min'] for b in branches),default=0);result['max_model_count']=count
    if count==0:result['status']='no_match'
    else:result['best_branch_ids']=[b['branch_id'] for b in branches if b['model_count_min']==count]
    return result
