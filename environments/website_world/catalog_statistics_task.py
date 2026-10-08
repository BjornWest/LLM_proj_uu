"""Explicit comparison-catalog population/grain and exact price aggregates."""
from collections import defaultdict
from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP

from .adapter import digest
from .feature_offer_task import FieldInventory
from .surrounding_config import validate

VERSION='website-catalog-statistics-task-v1'
KIND='comparison_catalog_statistics'
OPERATIONS=('count','mean','median','minimum','maximum')


def resolve(spec,*,concept_ids):
    if type(spec) is not dict or set(spec)-{'kind','concept_id','comparison_site_id','operation','grain'} or spec.get('kind')!=KIND:
        raise ValueError('Declare a comparison catalog statistics task')
    if spec.get('concept_id') not in concept_ids:raise ValueError('Target concept must belong to the world slice')
    if spec.get('operation') not in OPERATIONS or spec.get('grain','model') not in ('model','listing'):
        raise ValueError('Declare count/mean/median/minimum/maximum and model/listing grain')
    sid=spec.get('comparison_site_id')
    if type(sid) is not str or not sid.startswith('comparison-') or not sid.removeprefix('comparison-').isdigit():
        raise ValueError('Declare a comparison publication identity')
    return {**deepcopy(spec),'grain':spec.get('grain','model')}


def make(world,surrounding,spec,*,inventory=None):
    spec=resolve(spec,concept_ids=world['config']['concept_ids']);inventory=inventory or FieldInventory(spec['concept_id'])
    if inventory.concept_id!=spec['concept_id']:raise ValueError('Concept declaration binding changed')
    inventory.check_sources();validate(world,surrounding)
    sites=[s for s in surrounding['sites'] if s['site_id']==spec['comparison_site_id'] and s['kind']=='aggregator']
    if len(sites)!=1:raise ValueError('No selected comparison publication')
    site=sites[0];name=spec['concept_id'].split('.')[-1].replace('_',' ')
    grain=('each distinct priced model once, using its lowest advertised item price on this site' if spec['grain']=='model' else
        'each distinct product-model/retailer listing once, using that listing\'s advertised model item price')
    instruction=('Report the population count only.' if spec['operation']=='count' else
        'Report the population count and '+spec['operation']+' advertised price in SEK, rounded half up to two decimal places. '+
        ('For an even median, average the two middle prices. ' if spec['operation']=='median' else '')+
        'If the population is empty, say the statistic is undefined, not zero.')
    message=('Using only '+site['name']+', calculate catalog statistics for '+name+'. Count '+grain+'. '+instruction+
        'Include all such listings with a published price, irrespective of live stock or whether a particular variant is sold. '+
        'Do not count unpriced models, duplicate syndicated entries, individual SKUs, or other product concepts. '+
        'Do not apply filters or add retailers missing from this comparison site. Exclude shipping, coupons and cart deals. '+
        'Cite the comparison website. Do not place an order.')
    task={**spec,'schema_version':VERSION,'world_id':world['world_id'],'world_sha256':digest(world),
        'surrounding_sha256':digest(surrounding),'comparison_site_name':site['name'],
        'source_sha256':deepcopy(inventory.source_hashes),'user_message':message,'memories':[]}
    task['task_id']='catalog-statistics-'+digest(task)[:24]
    return task


def reference(world,surrounding,task,*,inventory=None):
    spec={k:task[k] for k in ('kind','concept_id','comparison_site_id','operation','grain')}
    if task!=make(world,surrounding,spec,inventory=inventory):raise ValueError('Statistics task/world/source binding changed')
    products={p['public']['product_id']:p['public'] for p in world['products']}
    site=next(s for s in surrounding['sites'] if s['site_id']==task['comparison_site_id'])
    listings={}
    for row in site['listings']:
        if products[row['product_id']]['concept_id']!=task['concept_id']:continue
        key=(row['product_id'],row['retailer_id'])
        if key in listings and listings[key]!=row:raise ValueError('Conflicting comparison listing copies')
        listings[key]=deepcopy(row)
    observations=[]
    if task['grain']=='listing':
        observations=[{'product_id':p,'retailer_id':r,'price_minor':v['price_minor']} for (p,r),v in sorted(listings.items())]
    else:
        groups=defaultdict(list)
        for (p,r),v in listings.items():groups[p].append(v['price_minor'])
        observations=[{'product_id':p,'price_minor':min(prices)} for p,prices in sorted(groups.items())]
    prices=sorted(x['price_minor'] for x in observations);n=len(prices);aggregate=None
    operation=task['operation']
    if prices and operation!='count':
        if operation=='mean':value=Decimal(sum(prices))/n
        elif operation=='median':value=(Decimal(prices[(n-1)//2])+prices[n//2])/2
        elif operation=='minimum':value=Decimal(prices[0])
        else:value=Decimal(prices[-1])
        aggregate=str((value/100).quantize(Decimal('.01'),rounding=ROUND_HALF_UP))
    return {'schema_version':VERSION,'task_id':task['task_id'],'world_id':world['world_id'],'operation':operation,
        'grain':task['grain'],'population_count':n,'observations':observations,'currency':'SEK','aggregate_sek':aggregate,
        'statistic_defined':True if operation=='count' else bool(prices),
        'scope':'complete_selected_comparison_priced_concept_population_not_live_stock','rounding':'two_decimal_half_up'}
