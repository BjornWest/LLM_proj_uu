"""Strict per-site membership and discovery capabilities; no world sampling here."""
from copy import deepcopy


def membership(owner,coverage=None):
    if coverage is None:return deepcopy(owner.comparisons),None
    if set(coverage)!={'site_id','families','comparison_ids','listings'}:raise ValueError('Unknown coverage fields')
    if not isinstance(coverage['site_id'],str) or not coverage['site_id']:raise ValueError('Missing site identity')
    for key in ('families','comparison_ids'):
        rows=coverage[key]
        if not isinstance(rows,list) or not all(isinstance(v,str) for v in rows) or len(set(rows))!=len(rows):raise ValueError('Invalid membership list')
    if not coverage['families'] or set(coverage['families'])-set(owner.families):raise ValueError('Invalid covered families')
    by_id={i['id']:i for i in owner.comparisons}
    if set(coverage['comparison_ids'])-set(by_id):raise ValueError('Unknown comparison product')
    items=[deepcopy(by_id[i]) for i in coverage['comparison_ids']]
    if any(i['category'] not in coverage['families'] for i in items):raise ValueError('Product outside covered family')
    valid=set()
    for i in items:
        if i['kind']=='model':valid.update((i['id'],r['retailer_id']) for r in i['listings'])
        else:valid.update((i['id'],o['retailer_id']) for o in owner.offers.values() if o['product_id']==i['id'])
    pairs=set()
    for row in coverage['listings']:
        if set(row)!={'comparison_id','retailer_id'}:raise ValueError('Invalid listing fields')
        pair=(row['comparison_id'],row['retailer_id'])
        if pair not in valid or pair in pairs:raise ValueError('Unknown or duplicate listing pair')
        pairs.add(pair)
    return items,pairs


def filter_profile(owner,config):
    if config is None:return None
    if set(config)!={'attributes','price_ceiling','sorting'}:raise ValueError('Invalid filter profile fields')
    if type(config['price_ceiling']) is not bool or type(config['sorting']) is not bool:raise ValueError('Boolean filter capabilities required')
    if not isinstance(config['attributes'],dict) or set(config['attributes'])-set(owner.families):raise ValueError('Unknown filter family')
    for family,fields in config['attributes'].items():
        available={k for item in owner.comparisons if item['category']==family for k in item['attributes']}
        if not isinstance(fields,list) or any(not isinstance(k,str) for k in fields) or len(set(fields))!=len(fields) or set(fields)-available:raise ValueError('Invalid filter attribute')
        if family=='footwear' and set(fields)&{'size_eu','colour','width'}:raise ValueError('Retailer-only footwear selection')
    return deepcopy(config)
