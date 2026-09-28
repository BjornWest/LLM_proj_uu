"""Public comparison identities: footwear models, other families' exact SKUs.

Entry SKUs are navigation bindings, never model price/stock evidence. Published
base prices may differ from a selected retailer variant; do not derive them from
current offers when an explicit comparison export is supplied.
"""
from copy import deepcopy
from urllib.parse import quote


def build(world):
    public=world['public'];products={p['product_id']:p for p in public['products']}
    groups={g['group_id']:g for g in public['product_groups']}
    offers={(o['retailer_id'],o['product_id']):o for o in public['offers']}
    model_for={v['product_id']:g['group_id'] for g in groups.values() for v in g['variants']}
    expected={(sid,model_for[sku]) for sid,sku in offers if products[sku]['category']=='footwear'}
    explicit='comparison_listings' in public
    listings=deepcopy(public.get('comparison_listings',[]))
    if not explicit:
        for sid,mid in sorted(expected):
            candidates=[o for (s,sku),o in offers.items() if s==sid and model_for[sku]==mid]
            first=min(candidates,key=lambda o:(o['price_minor'],o['product_id']))
            listings.append({'retailer_id':sid,'model_id':mid,'advertised_price_minor':first['price_minor'],'entry_product_id':first['product_id']})
    seen=set()
    for row in listings:
        key=(row['retailer_id'],row['model_id']);sku=row['entry_product_id']
        if key in seen or key not in expected:raise ValueError('Invalid or duplicate comparison retailer/model')
        if (key[0],sku) not in offers or model_for.get(sku)!=key[1]:raise ValueError('Comparison entry is not a listed model variant')
        if type(row['advertised_price_minor']) is not int or row['advertised_price_minor']<0:raise ValueError('Invalid advertised price')
        seen.add(key)
    if seen!=expected:raise ValueError('Comparison listing coverage differs from store models')
    entries=[]
    for g in groups.values():
        if g['family']!='footwear':continue
        variants=[products[v['product_id']] for v in g['variants']]
        excluded={a['field'] for a in g['axes']}|{'size_eu','colour','width'}
        shared={k:deepcopy(v) for k,v in variants[0]['attributes'].items() if k not in excluded and all(p['attributes'].get(k)==v for p in variants)}
        entries.append({'id':g['group_id'],'name':g['name'],'category':'footwear','attributes':shared,'kind':'model','path':'/models/'+quote(g['group_id'],safe=''),'listings':[r for r in listings if r['model_id']==g['group_id']],'price_basis':'advertised' if explicit else 'legacy_from'})
    for p in products.values():
        if p['category']!='footwear':entries.append({**deepcopy(p),'id':p['product_id'],'kind':'sku','path':'/products/'+quote(p['product_id'],safe='')})
    return entries
