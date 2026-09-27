"""Typed retail collections and claim-supported, task-independent merchandising.

Public marketing metadata is a frozen synthetic snapshot. It is not current stock,
account history, review evidence, a discount or a transaction side effect.
"""
from copy import deepcopy
from datetime import date,timedelta
from .generator import digest,rng,weighted
from .config import _number,_weights
from .stores import validate_store_world
from .accounts import validate_accounts,iso

VERSION='shopping-storefront-content-v1'
KINDS=('featured','new_arrivals','bestsellers','editorial','promotion')
FACETS={'laptops':('ram_gb',lambda v:f'{v} GB RAM'),
        'beer':('beer_style',lambda v:'IPA' if v=='IPA' else str(v).capitalize()), 'wine':('wine_colour',lambda v:f'{str(v).capitalize()} wines'),
        'dog_food':('life_stage',lambda v:{'puppy':'Puppy food','adult':'Adult dog food','senior':'Senior dog food'}[v]),
        'cat_food':('life_stage',lambda v:{'kitten':'Kitten food','adult':'Adult cat food','senior':'Senior cat food'}[v])}
SHOES={'walking':'Walking shoes','running':'Running shoes','hiking':'Hiking shoes','formal':'Dress shoes','beach':'Flip-flops'}
DEPARTMENTS={'footwear':'Shoes','laptops':'Laptops','beer':'Beer','wine':'Wine','dog_food':'Dog food','cat_food':'Cat food'}
SALES_MAX={'local_shop':40,'regional_chain':150,'major_retailer':600,'online_specialist':250}


def resolve_config(patch=None):
    base={'section_count_weights':{'2':.5,'3':.5},'section_kind_weights':dict.fromkeys(KINDS,1),
          'products_per_section':4,'new_arrival_probability':.3,'new_arrival_days':30,
          'maximum_age_days':365,'sales_multiplier':1.0}
    if patch is None:patch={}
    if not isinstance(patch,dict) or set(patch)-set(base):raise ValueError('Unknown storefront configuration')
    result={**base,**deepcopy(patch)}
    for key in ('section_count_weights','section_kind_weights'):
        result[key]=_weights(base[key],patch.get(key,{}),key)
    for key,lo,hi in (('products_per_section',1,8),('new_arrival_days',1,90),('maximum_age_days',1,3650)):
        if type(result[key]) is not int or not lo<=result[key]<=hi:raise ValueError('Invalid '+key)
    if result['maximum_age_days']<result['new_arrival_days']:raise ValueError('Maximum age must cover the new-arrival window')
    _number(result['new_arrival_probability'],'new_arrival_probability',probability=True)
    _number(result['sales_multiplier'],'sales_multiplier')
    if result['sales_multiplier']>100:raise ValueError('sales_multiplier must be at most100')
    return result


def _facts(world):
    validate_store_world(world)
    stores={s['retailer_id']:s for s in world['public']['retailers']}
    products={p['product_id']:p for p in world['public']['products']}
    model_for={v['product_id']:g['group_id'] for g in world['public']['product_groups'] for v in g['variants']}
    carried={sid:sorted({o['product_id'] for o in world['public']['offers'] if o['retailer_id']==sid}) for sid in stores}
    groups={sid:{} for sid in stores}
    for sid,skus in carried.items():
        for sku in skus:groups[sid].setdefault(model_for[sku],[]).append(sku)
    return stores,products,model_for,carried,groups


def _collections(sid,skus,products):
    families=sorted({products[p]['category'] for p in skus});result=[]
    def add(family,field,value,title):
        members=[sku for sku in skus if products[sku]['category']==family and
                 (field=='category' or products[sku]['attributes'].get(field)==value)]
        if members:result.append({'collection_id':sid+'-collection-'+digest([family,field,value])[:12],
          'title':title,'product_ids':members,'rule':{'family':family,'field':field,'operator':'eq','value':value}})
    for family in families:
        if len(families)>1:add(family,'category',family,DEPARTMENTS[family])
        subset=[sku for sku in skus if products[sku]['category']==family]
        if family=='footwear':
            typed=all('shoe_type' in products[p]['attributes'] for p in subset)
            for activity,title in SHOES.items():add(family,'shoe_type' if typed else 'activity',title.lower() if typed else activity,title)
        elif family in FACETS:
            field,label=FACETS[family]
            for value in sorted({products[p]['attributes'][field] for p in subset}):add(family,field,value,label(value))
    return result


def _window(today):
    return {'start_date':(today-timedelta(days=29)).isoformat(),'end_date':today.isoformat(),'days':30,
            'basis':'units_ordered_per_model','snapshot':'initial_world','cancelled_orders':'excluded'}


def _history(world,accounts,as_of,model_for):
    earliest={};minimum={}
    if accounts is None:return earliest,minimum
    validate_accounts(world,accounts)
    if accounts['as_of']!=as_of:raise ValueError('Accounts and merchandising must share a snapshot date')
    start=iso(as_of)-timedelta(days=29)
    for a in accounts['accounts']:
        for order in a['orders']:
            placed=iso(order['placed_date'])
            for line in order['lines']:
                key=a['retailer_id'],model_for[line['product_id']]
                earliest[key]=min(placed,earliest.get(key,placed))
                if placed>=start and order['status']!='cancelled':minimum[key]=minimum.get(key,0)+line['quantity']
    return earliest,minimum


def _words(kind,new_days,collection=None):
    if kind=='featured':return 'Featured picks','A selection from our range to explore.'
    if kind=='new_arrivals':return 'New arrivals',f'Explore ranges added in the last {new_days} days.'
    if kind=='bestsellers':return 'Bestsellers','Our most-ordered ranges over the last 30 days.'
    title=collection['title']
    if kind=='promotion':return title+' in focus','Take a closer look at our '+title.lower()+' collection.'
    if kind=='editorial':return 'Explore '+title.lower(),'Compare the options and specifications in this collection.'
    raise ValueError('Unknown section kind')


def _ranked(metadata,kind,today,new_days):
    if kind=='new_arrivals':
        return sorted((m for m in metadata if (today-iso(m['introduced_on'])).days<new_days),key=lambda m:(-iso(m['introduced_on']).toordinal(),m['model_id']))
    if kind=='bestsellers':return sorted((m for m in metadata if m['units_ordered_30d']>0),key=lambda m:(-m['units_ordered_30d'],m['model_id']))
    return sorted(metadata,key=lambda m:m['model_id'])


def generate_storefront_content(world,*,seed=0,as_of='2026-09-27',config=None,accounts=None):
    if type(seed) is not int:raise ValueError('Storefront seed must be an integer')
    cfg=resolve_config(config);today=iso(as_of)
    if today<date(2,1,1) or (today-date.min).days<cfg['maximum_age_days']:raise ValueError('Snapshot must allow merchandising history')
    stores,products,model_for,carried,groups=_facts(world)
    earliest,minimum=_history(world,accounts,as_of,model_for);rows=[]
    for sid,store in sorted(stores.items()):
        collections=_collections(sid,carried[sid],products);metadata=[];ns=VERSION+'/'+sid
        for mid,skus in sorted(groups[sid].items()):
            r=rng(seed,ns+'/metadata/'+mid)
            age=r.randrange(cfg['new_arrival_days']) if r.random()<cfg['new_arrival_probability'] else r.randint(cfg['new_arrival_days'],cfg['maximum_age_days'])
            age=max(age,(today-earliest.get((sid,mid),today)).days)
            cap=SALES_MAX.get(store.get('business_profile',{}).get('profile_id'),100)
            units=max(minimum.get((sid,mid),0),int(r.randint(0,cap)*cfg['sales_multiplier']*min(30,age+1)/30))
            metadata.append({'model_id':mid,'product_ids':skus,'introduced_on':(today-timedelta(days=age)).isoformat(),
                             'units_ordered_30d':units,'sales_rank_30d':0})
        for m in metadata:m['sales_rank_30d']=1+sum(x['units_ordered_30d']>m['units_ordered_30d'] for x in metadata)
        count_weights=cfg['section_count_weights'];names=sorted(count_weights)
        wanted=int(weighted(rng(seed,ns+'/section-count'),names,[count_weights[k] for k in names]))
        wanted=min(wanted,len(metadata))
        pools={kind:_ranked(metadata,kind,today,cfg['new_arrival_days']) for kind in KINDS}
        remaining=[k for k in KINDS if pools[k] and cfg['section_kind_weights'][k]>0 and (k not in ('editorial','promotion') or collections)]
        sections=[]
        for i in range(min(wanted,len(remaining))):
            kind=weighted(rng(seed,ns+'/section-kind/'+str(i)),remaining,[cfg['section_kind_weights'][k] for k in remaining]);remaining.remove(kind)
            collection=rng(seed,ns+'/'+kind+'/collection').choice(collections) if kind in ('editorial','promotion') else None
            allowed=set(collection['product_ids']) if collection else set(carried[sid])
            pool=[m for m in pools[kind] if allowed.intersection(m['product_ids'])]
            if kind not in ('new_arrivals','bestsellers'):rng(seed,ns+'/'+kind+'/order').shuffle(pool)
            selected=[rng(seed,ns+'/'+kind+'/'+m['model_id']+'/variant').choice(sorted(allowed.intersection(m['product_ids']))) for m in pool[:cfg['products_per_section']]]
            title,body=_words(kind,cfg['new_arrival_days'],collection)
            sections.append({'section_id':sid+'-'+kind,'kind':kind,'title':title,'body':body,
                             'product_ids':selected,'collection_id':collection['collection_id'] if collection else None})
        rows.append({'retailer_id':sid,'collections':collections,'sections':sections,'merchandising':metadata})
    result={'schema_version':VERSION,'source_world_sha256':world['world_sha256'],
      'source_accounts_sha256':digest(accounts) if accounts is not None else None,'as_of':as_of,
      'new_arrival_days':cfg['new_arrival_days'],'sales_window':_window(today),'retailers':rows}
    validate_storefront_content(world,result,accounts=accounts)
    return result


def validate_storefront_content(world,data,*,accounts=None):
    stores,products,model_for,carried,groups=_facts(world)
    fields={'schema_version','source_world_sha256','source_accounts_sha256','as_of','new_arrival_days','sales_window','retailers'}
    if not isinstance(data,dict) or set(data)!=fields or data['schema_version']!=VERSION:raise ValueError('Unsupported storefront sidecar')
    if data['source_world_sha256']!=world['world_sha256']:raise ValueError('Storefront belongs to another world')
    if data['source_accounts_sha256']!=(digest(accounts) if accounts is not None else None):raise ValueError('Storefront historical accounts binding mismatch')
    today=iso(data['as_of'])
    if today<date(2,1,1):raise ValueError('Snapshot must allow merchandising history')
    days=data['new_arrival_days']
    if type(days) is not int or not 1<=days<=90:raise ValueError('Invalid new-arrival window')
    if data['sales_window']!=_window(today) or type(data['sales_window'].get('days')) is not int:raise ValueError('Invalid sales window or claim basis')
    earliest,minimum=_history(world,accounts,data['as_of'],model_for)
    if not isinstance(data['retailers'],list):raise ValueError('Invalid retailer contents')
    seen=set();sections_count=0;collections_count=0
    def product_list(values,sid):
        if not isinstance(values,list) or not values or any(not isinstance(v,str) or v not in carried[sid] for v in values) or len(values)!=len(set(values)):
            raise ValueError('Content must reference distinct carried SKUs')
    for row in data['retailers']:
        if not isinstance(row,dict) or set(row)!={'retailer_id','collections','sections','merchandising'}:raise ValueError('Invalid retailer row')
        sid=row['retailer_id']
        if not isinstance(sid,str) or sid not in stores or sid in seen:raise ValueError('Invalid retailer identity')
        seen.add(sid)
        if row['collections']!=_collections(sid,carried[sid],products):raise ValueError('Collections contradict typed membership or omit carried variants')
        collections={c['collection_id']:c for c in row['collections']};collections_count+=len(collections)
        if not isinstance(row['merchandising'],list):raise ValueError('Invalid merchandising facts')
        metadata={}
        for m in row['merchandising']:
            if not isinstance(m,dict) or set(m)!={'model_id','product_ids','introduced_on','units_ordered_30d','sales_rank_30d'}:raise ValueError('Invalid merchandising row')
            mid=m['model_id']
            if not isinstance(mid,str) or mid not in groups[sid] or mid in metadata or m['product_ids']!=groups[sid][mid]:raise ValueError('Merchandising model/variant scope mismatch')
            introduced=iso(m['introduced_on'])
            if introduced>today or introduced>earliest.get((sid,mid),today):raise ValueError('Introduction date contradicts snapshot or historical orders')
            if type(m['units_ordered_30d']) is not int or m['units_ordered_30d']<minimum.get((sid,mid),0):raise ValueError('Sales count contradicts known history')
            if type(m['sales_rank_30d']) is not int or m['sales_rank_30d']<1:raise ValueError('Invalid sales rank')
            metadata[mid]=m
        if set(metadata)!=set(groups[sid]):raise ValueError('Missing merchandising model coverage')
        for m in metadata.values():
            if m['sales_rank_30d']!=1+sum(x['units_ordered_30d']>m['units_ordered_30d'] for x in metadata.values()):raise ValueError('Sales rank contradicts counts')
        if not isinstance(row['sections'],list) or len(row['sections'])>min(3,len(metadata)):
            raise ValueError('Too many sections for available models')
        kinds=set()
        for section in row['sections']:
            if not isinstance(section,dict) or set(section)!={'section_id','kind','title','body','product_ids','collection_id'}:raise ValueError('Invalid section fields')
            kind=section['kind']
            if not isinstance(kind,str) or kind not in KINDS or kind in kinds or section['section_id']!=sid+'-'+kind:raise ValueError('Invalid or repeated section kind')
            kinds.add(kind);product_list(section['product_ids'],sid)
            mids=[model_for[p] for p in section['product_ids']]
            if len(mids)>8 or len(set(mids))!=len(mids):raise ValueError('Section repeats a model across variants or exceeds card limit')
            cid=section['collection_id']
            if kind in ('editorial','promotion'):
                if not isinstance(cid,str) or cid not in collections or not set(section['product_ids'])<=set(collections[cid]['product_ids']):raise ValueError('Spotlight contradicts collection membership')
                collection=collections[cid]
            else:
                if cid is not None:raise ValueError('Unexpected collection target')
                collection=None
            if (section['title'],section['body'])!=_words(kind,days,collection):raise ValueError('Unsupported merchandising claim or wording')
            if kind in ('new_arrivals','bestsellers'):
                ranked=_ranked(list(metadata.values()),kind,today,days)
                if mids!=[m['model_id'] for m in ranked[:len(mids)]]:raise ValueError('Section contradicts newness or bestseller evidence')
            sections_count+=1
    if seen!=set(stores):raise ValueError('Missing retailer storefront')
    return {'valid':True,'retailers':len(seen),'collections':collections_count,'sections':sections_count,'public_sha256':digest(data)}


def attach_storefront_content(scenario,*,seed=0,as_of=None,config=None):
    result=deepcopy(scenario)
    as_of=as_of or scenario.get('accounts',{}).get('as_of') or scenario['merchant_reviews']['public']['as_of']
    result['storefront_content']=generate_storefront_content(result['bundle'],seed=seed,as_of=as_of,config=config,accounts=result.get('accounts'))
    return result
