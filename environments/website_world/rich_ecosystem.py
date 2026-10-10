"""Seeded richer surrounding presentation over unchanged authoritative offers.

Finite scope/module factors precede unit-conditioned permutations. Coverage and
prices keep the approved native model/pair snapshot semantics; no quote/task reads.
"""
from copy import deepcopy
from math import isfinite

from . import ecosystem as base
from .comparison_pages import LAYOUTS

VERSION='native-rich-surrounding-v2'
DEFAULTS={**deepcopy(base.DEFAULTS),
    'scope_weights':{'general':1,'specialist':1},
    'module_weights':{role:{name:1 for name in LAYOUTS} for role in ('home','results','product')},
    'navigation_weights':{'categories':1,'disclosure':1,'search-first':1},
    'facet_limit_weights':{'1':1,'3':1,'5':1},
    'price_ceiling_probability':.75,'sorting_probability':.9}
DEFAULTS.pop('comparison_layout_weights')


def weights(value,defaults,name):
    if type(value) is not dict or set(value)!=set(defaults):raise ValueError('Declare full '+name+' domain')
    if any(type(v) not in (int,float) or not isfinite(v) or v<0 for v in value.values()) or not isfinite(sum(value.values())) or sum(value.values())<=0:
        raise ValueError('Invalid '+name+' weights')
    return {k:value[k] for k in defaults}


def options(value=None):
    value={} if value is None else value
    if type(value) is not dict or set(value)-{*DEFAULTS,'coverage_seed','family_weights'}:
        raise ValueError('Unknown rich surrounding-site control')
    result={**deepcopy(DEFAULTS),**deepcopy(value)}
    legacy={k:result[k] for k in base.DEFAULTS if k!='comparison_layout_weights'}
    if 'coverage_seed' in result:legacy['coverage_seed']=result['coverage_seed']
    base.options(legacy)
    for key in ('scope_weights','navigation_weights','facet_limit_weights'):
        result[key]=weights(result[key],DEFAULTS[key],key)
    if type(result['module_weights']) is not dict or set(result['module_weights'])!=set(DEFAULTS['module_weights']):
        raise ValueError('Declare all comparator page roles')
    result['module_weights']={r:weights(result['module_weights'][r],DEFAULTS['module_weights'][r],r) for r in DEFAULTS['module_weights']}
    for key in ('price_ceiling_probability','sorting_probability'):
        p=result[key]
        if type(p) not in (int,float) or not isfinite(p) or not 0<=p<=1:raise ValueError('Invalid '+key)
    if 'family_weights' in result:
        f=result['family_weights']
        if type(f) is not dict or not f or any(type(k) is not str or not k for k in f):raise ValueError('Invalid family weights')
        result['family_weights']=weights(f,f,'families')
    return result


def choice(seed,sid,key,values):
    support={k:v for k,v in values.items() if v>0}
    if not support:raise ValueError('Empty compatible sampling support: '+key)
    u=base.draw(seed,VERSION,sid,key)*sum(support.values())
    for key,value in support.items():
        u-=value
        if u<0:return key
    raise ArithmeticError('Invalid finite choice')


def family_metadata(world):
    families=sorted({p['public']['family_id'] for p in world['products']})
    supplied=world.get('family_labels',{})
    return {f:supplied.get(f,f.replace('_',' ').capitalize()) for f in families}


def presentation(world,site,controls,families):
    sid=site['site_id'];seed=world['seed']
    compatible={k:v for k,v in controls['scope_weights'].items() if k=='general' or families}
    scope=choice(seed,sid,'scope',compatible)
    if scope=='specialist':
        family_weights={f:controls.get('family_weights',{}).get(f,1) for f in families}
        chosen=[choice(seed,sid,'specialist-family',family_weights)]
    else:chosen=list(families)
    modules={r:choice(seed,sid,'module/'+r,controls['module_weights'][r]) for r in ('home','results','product')}
    # These draws happen only after their owning module has been selected. Their
    # namespaces include the selected unit; the initial module pool stays clean.
    permutations={r:{} for r in modules}
    permutations['product']['offer_disclosure']=choice(seed,sid,'product/'+modules['product']+'/offers',{'plain':1,'expand':1})
    permutations['results']['search_sections']=base.draw(seed,VERSION,sid,'results',modules['results'],'reading')<.5
    subset=[{**p['public'],'fact_status':{**p['public'].get('fact_status',{}),
        **{k.removeprefix('product.facts.'):v for k,v in p.get('catalog_status',{}).items() if k.startswith('product.facts.')}}}
        for p in world['products'] if p['public']['family_id'] in chosen]
    known={f:sorted({k for p in subset if p['family_id']==f for k,v in p['facts'].items()
        if type(v) in (str,bool,int,float) and p.get('fact_status',{}).get(k,'known')=='known' and v not in ('not specified','unknown')}) for f in chosen}
    limit=int(choice(seed,sid,'results/'+modules['results']+'/facet-limit',controls['facet_limit_weights']))
    fields={f:sorted(keys,key=lambda k:base.draw(seed,VERSION,sid,'results',modules['results'],'facet',f,k))[:limit] for f,keys in known.items()}
    return chosen,{'scope':scope,'modules':modules,
        'navigation':choice(seed,sid,'navigation',controls['navigation_weights']),
        'filters':{'attributes':fields,
            'price_ceiling':base.draw(seed,VERSION,sid,'results',modules['results'],'price-ceiling')<controls['price_ceiling_probability'],
            'sorting':base.draw(seed,VERSION,sid,'results',modules['results'],'sorting')<controls['sorting_probability']},
        'permutations':permutations}


def generate(world,controls=None):
    return _generate_bound(world,controls,base.digest(world))


def _generate_bound(world,controls,world_sha256):
    controls=options(controls);labels=family_metadata(world)
    legacy={k:controls[k] for k in base.DEFAULTS if k!='comparison_layout_weights'}
    if 'coverage_seed' in controls:legacy['coverage_seed']=controls['coverage_seed']
    result=base._generate_bound(world,legacy,world_sha256)
    products={p['public']['product_id']:p['public'] for p in world['products']}
    for site in result['sites']:
        if site['kind']=='aggregator':
            chosen,profile=presentation(world,site,controls,list(labels))
            site['families']=chosen;site['family_labels']={f:labels[f] for f in chosen};site['presentation']=profile
            site['product_ids']=[pid for pid in site['product_ids'] if products[pid]['family_id'] in chosen]
            covered=set(site['product_ids']);site['listings']=[r for r in site['listings'] if r['product_id'] in covered]
            site.pop('layout')
        else:
            site['families']=list(labels);site['family_labels']=labels
            site['name']='Product Reader '+site['site_id'].rsplit('-',1)[-1]
    actual={f"{s['site_id']}/{r['product_id']}/{r['retailer_id']}" for s in result['sites'] if s['kind']=='aggregator' for r in s['listings']}
    result['provenance_private']={k:v for k,v in result['provenance_private'].items() if k in actual}
    result.update(schema_version=VERSION,controls=controls)
    return result


def validate(world,sidecar):
    if sidecar.get('schema_version')!=VERSION or sidecar.get('source_world_id')!=world['world_id'] or sidecar.get('source_world_sha256')!=base.digest(world):
        raise ValueError('Rich surrounding sidecar belongs to another world')
    if sidecar!=generate(world,sidecar['controls']):raise ValueError('Rich surrounding sidecar does not replay')
    return sidecar
