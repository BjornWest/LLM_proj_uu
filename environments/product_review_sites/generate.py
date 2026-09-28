"""Exact-SKU catalog facts and separately labelled synthetic reader opinions.

This first export does NOT simulate lab measurements or infer product quality from
price, inventory, task feasibility or the sampled publisher's name/layout.
"""
from copy import deepcopy
from datetime import date, timedelta
from hashlib import sha256
import json
import random

VERSION = 'product-review-export-v1'
FAMILIES = ('footwear', 'laptops', 'dog_food', 'cat_food', 'beer', 'wine')
OPINIONS = {
    1: ('Not for me', 'This was not a choice I would repeat. This is my personal impression, not a specification.'),
    2: ('A mixed experience', 'It did not suit my preferences as well as I hoped. Other people may weigh things differently.'),
    3: ('Somewhere in the middle', 'I am undecided about choosing this again. I would compare alternatives before deciding.'),
    4: ('Happy with my choice', 'I liked this choice overall. My rating reflects my preferences, not a promise for everyone.'),
    5: ('A personal favourite', 'I would choose this again. This is an opinion about my own experience.'),
}


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()).hexdigest()


def stream(seed, key):
    return random.Random(int(sha256(f'{VERSION}:{seed}:{key}'.encode()).hexdigest(), 16))


def stats(comments):
    return {'count': len(comments), 'mean': sum(c['stars'] for c in comments)/len(comments) if comments else None,
            'histogram': {str(i): sum(c['stars']==i for c in comments) for i in range(1,6)}}


def generate_reviews(world, *, seed=0, as_of='2026-09-26', opinions_per_review=24):
    if type(seed) is not int or type(opinions_per_review) is not int or not 0 <= opinions_per_review <= 100:
        raise ValueError('Integer seed and 0..100 opinions per review required')
    today = date.fromisoformat(as_of)
    if today.isoformat()!=as_of: raise ValueError('ISO date required')
    public = world['public']
    products = public['products']; groups = public['product_groups']
    by_sku = {p['product_id']:p for p in products}
    if len(by_sku)!=len(products): raise ValueError('Duplicate product ID')
    articles=[]; variants=[]; seen_groups=set(); seen_skus=set()
    for group in sorted(groups, key=lambda g:g['group_id']):
        gid=group['group_id'];family=group['family']
        if gid in seen_groups or family not in FAMILIES: raise ValueError('Duplicate model or unsupported family')
        seen_groups.add(gid)
        if not group['variants']: raise ValueError('Model has no variants')
        group_rows=[]
        for variant in group['variants']:
            sku=variant['product_id']
            if sku in seen_skus or sku not in by_sku: raise ValueError('Missing or duplicate variant membership')
            seen_skus.add(sku);p=by_sku[sku]
            if p['category']!=family: raise ValueError('Variant family mismatch')
            row={'sku':sku,'model_id':gid,'name':p['name'],'family':family,'facts':deepcopy(p['attributes'])}
            group_rows.append(row)
        group_rows.sort(key=lambda r:r['sku']);variants.extend(group_rows)
        tested=stream(seed,gid+'/tested').choice(group_rows)
        age=min(today.toordinal()-1,stream(seed,gid+'/date').randint(20,300))
        published=today-timedelta(days=age)
        comments=[]
        for i in range(opinions_per_review):
            rng=stream(seed,f'{gid}/opinion/{i}');rating=rng.randint(1,5)
            title,body=OPINIONS[rating]
            comments.append({'id':'opinion-'+digest([gid,i])[:16], 'handle':f'Reader {digest([seed,gid,i])[:6]}',
                             'stars':rating,'title':title,'body':body,
                             'date':(published+timedelta(days=rng.randint(0,age))).isoformat()})
        articles.append({'id':gid,'model_name':group['name'],'family':family,'reviewed_sku':tested['sku'],
                         'published':published.isoformat(),'author':stream(seed,gid+'/author').choice(('Alex Lind','Sam Berg','Robin Dahl','Kim West')),
                         'reader_opinions':comments,'reader_statistics':stats(comments)})
    if seen_skus!=set(by_sku): raise ValueError('Every exported SKU needs exact group membership')
    payload={'as_of':as_of,'articles':articles,'variants':variants}
    return {'schema_version':VERSION,'public':payload,'private_provenance':{
        'seed':seed,'source_catalog_sha256':digest({'products':products,'product_groups':groups}),
        'public_sha256':digest(payload),'opinion_distribution':'authored_uniform_1_to_5_not_empirical',
        'facts_semantics':'exact_catalog_configuration_not_independent_lab_measurement',
        'source_policy':'no_task_stock_price_or_layout_input'}}
