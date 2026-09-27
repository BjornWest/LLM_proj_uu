"""Task-independent public comparison-site membership over a frozen store world.

No prices, stock, rankings, layout names or task inputs participate in sampling.
Membership omissions never remove canonical retailer offers from grading.
"""
from collections import Counter
import re

from .config import FAMILY_IDS,_number
from .generator import digest,rng
from .stores import validate_store_world

VERSION='comparison-coverage-v1'


def defaults():
    return {'retailer_only_probability':.12,'shared_core_probability':.75,
            'site_extra_probability':.45,'retailer_feed_probability':.85,
            'listing_probability':.9}


def resolve_config(patch=None):
    values=defaults()
    if patch is not None:
        if not isinstance(patch,dict) or set(patch)-set(values):raise ValueError('Unknown comparison coverage config')
        values.update(patch)
    for key,value in values.items():_number(value,key,probability=True)
    return values


def identities(world):
    """Canonical comparison IDs/families and valid product/retailer listing pairs."""
    validate_store_world(world)
    public=world['public']
    products={p['product_id']:p for p in public['products']}
    groups={v['product_id']:g for g in public['product_groups'] for v in g['variants']}
    comparison_for={sku:(groups[sku]['group_id'] if p['category']=='footwear' else sku) for sku,p in products.items()}
    families={comparison_for[sku]:p['category'] for sku,p in products.items()}
    pairs={(comparison_for[o['product_id']],o['retailer_id']) for o in public['offers']}
    return families,pairs,comparison_for


def _specs(sites):
    if not isinstance(sites,list) or not 1<=len(sites)<=16:raise ValueError('Expected 1..16 comparison sites')
    result=[];seen=set()
    for s in sites:
        if not isinstance(s,dict) or set(s)!={'site_id','families'}:raise ValueError('Invalid site specification')
        sid=s['site_id'];families=s['families']
        if not isinstance(sid,str) or not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}',sid) or sid in seen:
            raise ValueError('Invalid/duplicate comparison site ID')
        if not isinstance(families,list) or not families or any(not isinstance(f,str) or f not in FAMILY_IDS for f in families) or len(set(families))!=len(families):
            raise ValueError('Invalid comparison site families')
        seen.add(sid);result.append({'site_id':sid,'families':sorted(families)})
    return sorted(result,key=lambda s:s['site_id'])


def generate_coverage(world,sites,*,seed=0,config=None):
    if type(seed) is not int:raise ValueError('Coverage seed must be an integer')
    settings=resolve_config(config);specs=_specs(sites)
    families,pairs,_=identities(world)
    def coin(namespace,probability):return rng(seed,VERSION+'/'+namespace).random()<probability
    retailer_only={cid for cid in families if coin('retailer-only/'+cid,settings['retailer_only_probability'])}
    core={cid for cid in families if cid not in retailer_only and coin('shared-core/'+cid,settings['shared_core_probability'])}
    rows=[]
    for spec in specs:
        sid=spec['site_id'];scope=set(spec['families'])
        tracked={cid for cid,family in families.items() if family in scope and cid not in retailer_only
                 and (cid in core or coin(sid+'/extra/'+cid,settings['site_extra_probability']))}
        feeds={retailer for _,retailer in pairs if coin(sid+'/retailer/'+retailer,settings['retailer_feed_probability'])}
        listings=[{'comparison_id':cid,'retailer_id':retailer} for cid,retailer in sorted(pairs)
                  if cid in tracked and retailer in feeds and coin(sid+'/listing/'+cid+'/'+retailer,settings['listing_probability'])]
        rows.append({**spec,'comparison_ids':sorted(tracked),'listings':listings})
    result={'schema_version':VERSION,'source_world_sha256':world['world_sha256'],'sites':rows}
    validate_coverage(world,result)
    return result


def validate_coverage(world,coverage):
    families,pairs,_=identities(world)
    if not isinstance(coverage,dict) or set(coverage)!={'schema_version','source_world_sha256','sites'} or coverage['schema_version']!=VERSION:
        raise ValueError('Unsupported comparison coverage sidecar')
    if coverage['source_world_sha256']!=world['world_sha256']:raise ValueError('Coverage belongs to another world')
    sites=coverage['sites']
    if not isinstance(sites,list):raise ValueError('Invalid comparison sites')
    for site in sites:
        if not isinstance(site,dict) or set(site)!={'site_id','families','comparison_ids','listings'}:
            raise ValueError('Invalid comparison site projection')
    _specs([{k:s[k] for k in ('site_id','families')} for s in sites])
    for s in sites:
        ids=s['comparison_ids']
        if not isinstance(ids,list) or any(not isinstance(cid,str) or cid not in families for cid in ids) or len(ids)!=len(set(ids)):
            raise ValueError('Unknown/duplicate comparison product')
        if any(families[cid] not in s['families'] for cid in ids):raise ValueError('Comparison product outside site families')
        if not isinstance(s['listings'],list):raise ValueError('Invalid comparison listings')
        seen=set()
        for row in s['listings']:
            if not isinstance(row,dict) or set(row)!={'comparison_id','retailer_id'} or not all(isinstance(v,str) for v in row.values()):
                raise ValueError('Invalid comparison listing record')
            pair=(row['comparison_id'],row['retailer_id'])
            if pair in seen or pair not in pairs or pair[0] not in ids:raise ValueError('Unknown/duplicate/untracked comparison listing')
            seen.add(pair)
    return {'valid':True,'sites':len(sites),'public_sha256':digest(coverage)}


def coverage_summary(world,coverage):
    """Authoring diagnostics, not site metadata or task hints."""
    validate_coverage(world,coverage)
    families,pairs,_=identities(world)
    product_counts=Counter(cid for s in coverage['sites'] for cid in s['comparison_ids'])
    tracked_pairs={(r['comparison_id'],r['retailer_id']) for s in coverage['sites'] for r in s['listings']}
    offered={cid for cid,_ in pairs}
    return {'comparison_products':len(families),'offered_comparison_products':len(offered),
        'retailer_only_comparison_ids':sorted(cid for cid in offered if not product_counts[cid]),
        'one_site_only_comparison_ids':sorted(cid for cid in families if product_counts[cid]==1),
        'untracked_listing_pairs':[{'comparison_id':cid,'retailer_id':sid} for cid,sid in sorted(pairs-tracked_pairs)],
        'sites':[{'site_id':s['site_id'],'products':len(s['comparison_ids']),'listings':len(s['listings']),
                  'tracked_without_listings':sorted(set(s['comparison_ids'])-{r['comparison_id'] for r in s['listings']})}
                 for s in coverage['sites']]}


def candidate_visibility(world,coverage,candidates):
    """Private post-generation diagnostics; never filter the oracle's candidates."""
    validate_coverage(world,coverage)
    _,_,comparison_for=identities(world)
    pairs_by_site={s['site_id']:{(r['comparison_id'],r['retailer_id']) for r in s['listings']} for s in coverage['sites']}
    result=[]
    for c in candidates:
        lines=[]
        for line in c['lines']:
            cid=comparison_for[line['sku_id']]
            lines.append({'line_id':line['line_id'],'comparison_id':cid,
                'sites_tracking_product':sorted(s['site_id'] for s in coverage['sites'] if cid in s['comparison_ids']),
                'sites_tracking_listing':sorted(sid for sid,pairs in pairs_by_site.items() if (cid,line['retailer_id']) in pairs)})
        result.append({'candidate_id':c['candidate_id'],'lines':lines})
    return result
