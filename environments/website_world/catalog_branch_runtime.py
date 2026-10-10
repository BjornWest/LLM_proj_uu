"""Opt-in exact branch names/collection status over unchanged native stock.

The served renderer and public payload belong to this fresh runtime only. No
world record, quote, adapter, stock quantity or shared renderer is rewritten.
"""
from hashlib import sha256
import json

from experiments.accepted_catalog_commerce.execution import _bind
from .basket import basket_shop_source
from .runtime import Runtime

VERSION = 'website-catalog-branch-runtime-v1'

RENDER_EXTENSION = '''
import {data as branchCatalog} from './world-data.js';
const originalBranchServices=worldBinding.productServices;
worldBinding.productServices=function(args){
  const sourceStock=args.v.sourceStock.map(s=>s.kind==='branch'?{...s,
    name:`${s.branchName}, ${s.city}, ${s.country} · ${s.pickupEnabled?'Collection available':'Collection unavailable'}`}:s);
  return originalBranchServices.call(this,{...args,v:{...args.v,sourceStock}});
};
const originalBranchArticle=worldBinding.article;
worldBinding.article=function(id,args){
  if(id!=='stores')return originalBranchArticle.call(this,id,args);
  return Object.values(branchCatalog.branches).map(b=>`<section><h3>${args.e(b.name)}</h3><address>${args.e(b.address)}</address><p>${b.pickupEnabled?'Collection available':'Collection unavailable'}</p><p>${args.e(b.hours)}</p></section>`).join('');
};
'''


def branch_shop_source(source, *, canonical_domain=False):
    copied = basket_shop_source(source, canonical_domain=canonical_domain)
    hook = 'const site = worldBinding?.siteId'
    if copied.count(hook) != 1:
        raise ValueError('Branch renderer initialization hook changed')
    return copied.replace(hook, RENDER_EXTENSION+'\n'+hook)


def enrich_catalog(catalog, retailer):
    """Return a checked additive projection; all original public rows survive."""
    # Copy only modified paths; optional product content stays shared/read-only.
    result = {**catalog, 'branches': {bid: dict(b) for bid, b in catalog['branches'].items()},
        'products': [{**p, 'variants': [{**v, 'sourceStock': [dict(s) for s in v['sourceStock']]}
            for v in p['variants']]} for p in catalog['products']]}
    branches = {b['branch_id']: b for b in retailer['geography']['branches']}
    sources = {s['source_id']: s for s in retailer['source_locations']}
    offers = {o['offer_id']: o for o in retailer['offers']}
    if set(result['branches']) != set(branches):
        raise ValueError('Public branch inventory changed')
    for bid, branch in branches.items():
        if sources[bid]['kind'] != 'branch':
            raise ValueError('Branch/source identity changed')
        public = result['branches'][bid]
        if public['name'] != branch['name'] or public['address'] != branch['location']['city']+', '+branch['location']['country']:
            raise ValueError('Public branch name/locality changed')
        public.update(city=branch['location']['city'], country=branch['location']['country'],
                      pickupEnabled=branch['pickup_enabled'])
    seen = set()
    for product in result['products']:
        for variant in product['variants']:
            offer = offers[variant['offerId']]
            if offer['sku_id'] != variant['skuId'] or variant['offerId'] in seen:
                raise ValueError('Public branch offer/SKU identity changed')
            seen.add(variant['offerId'])
            rows = variant['sourceStock']
            if (len(rows) != len(offer['stock_by_source']) or
                    {s['sourceId']: s['quantity'] for s in rows} != offer['stock_by_source']):
                raise ValueError('Public physical stock changed')
            for row in rows:
                source = sources[row['sourceId']]
                if row['kind'] != source['kind'] or row['shippingEnabled'] != source['shipping_enabled']:
                    raise ValueError('Public source classification changed')
                if row['kind'] == 'branch':
                    branch = branches[row['sourceId']]
                    row.update(branchName=branch['name'], city=branch['location']['city'],
                               country=branch['location']['country'], pickupEnabled=branch['pickup_enabled'])
    if seen != set(offers):
        raise ValueError('Public branch offer coverage changed')
    return result


class BranchRuntime(Runtime):
    def __init__(self, *args, **kwargs):
        if kwargs.get('basket_plan') is None:
            raise ValueError('Branch runtime requires the frozen basket plan')
        _bind(Runtime.__init__, basket_shop_source=branch_shop_source)(self, *args, **kwargs)
        try:
            if self.catalog_backend is None:
                raise ValueError('Branch runtime requires accepted-catalog commerce')
            for retailer in self.world['retailers']:
                rid = retailer['retailer_id']
                self.public_catalogs[rid] = enrich_catalog(self.public_catalogs[rid], retailer)
            self.manifest['branch_stock_projection'] = {
                'version': VERSION,
                'public_catalog_sha256': {rid: sha256(json.dumps(value, sort_keys=True,
                    ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
                    for rid, value in self.public_catalogs.items()},
                'scope': 'all branch identities, exact SKU physical stock and collection capability; no route inference'}
        except BaseException:
            self.close()
            raise
