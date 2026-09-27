"""Store-first planning, coherent shared assortment, then independent offer state.

Only family scope and optional model identities influence coverage. No task predicates are inputs.
"""
import copy
from collections import Counter, defaultdict

from .config import FAMILY_IDS, resolve_config, _number, _weights
from .generator import generate_catalog, digest, rng, weighted
from .validation import validate_catalog
from .naming import retailer_name, naming_locale

VERSION = 'product-store-world-v1'
PROFILES = {
    'footwear': {'label': 'Footwear specialist', 'suffix': 'Skor', 'families': ['footwear']},
    'electronics': {'label': 'Computer specialist', 'suffix': 'Datorbutik', 'families': ['laptops']},
    'pets': {'label': 'Pet supplies', 'suffix': 'Djurbutik', 'families': ['dog_food', 'cat_food']},
    'drinks': {'label': 'Beer and wine specialist', 'suffix': 'Drycker', 'families': ['beer', 'wine']},
    'marketplace': {'label': 'General marketplace', 'suffix': 'Marknad', 'families': ['footwear', 'laptops', 'dog_food', 'cat_food']},
}
CITIES = ('Uppsala', 'Stockholm', 'Göteborg', 'Malmö', 'Örebro', 'Umeå')
SPECIALIST = {f: p for p, spec in PROFILES.items() if p != 'marketplace' for f in spec['families']}


def store_defaults():
    return {'relevant_stores_per_family': 2, 'generalist_probability': .08,
            'profile_weights': {p: 1.0 for p in PROFILES if p != 'marketplace'},
            'model_overlap_probability': .5, 'variant_carry_probability': .7,
            'stockout_probability': 1/6, 'footwear_size_surcharge_probability': .1}


def resolve_store_config(patch=None):
    result = store_defaults()
    if patch is None: return result
    if not isinstance(patch, dict) or set(patch) - set(result): raise ValueError('Unknown store config field')
    for key, value in patch.items():
        if key == 'profile_weights': result[key] = _weights(result[key], value, key)
        elif key == 'relevant_stores_per_family':
            if type(value) is not int or not 1 <= value <= 4: raise ValueError('relevant_stores_per_family must be 1..4')
            result[key] = value
        else:
            _number(value, key, probability=True); result[key] = value
    return copy.deepcopy(result)


def generate_store_world(seed=0, store_count=6, models_per_store=5, focus_families=None, config=None, store_config=None,
                         *, model_references=None, geographic_plan=None, merchant_plan=None, footwear_depth=None):
    if type(seed) is not int: raise ValueError('seed must be an integer')
    if type(store_count) is not int or not 1 <= store_count <= 16: raise ValueError('store_count must be 1..16')
    if type(models_per_store) is not int or not 1 <= models_per_store <= 20: raise ValueError('models_per_store must be 1..20')
    focus = ['footwear'] if focus_families is None else focus_families
    if not isinstance(focus, list) or not focus or any(f not in FAMILY_IDS for f in focus) or len(set(focus)) != len(focus):
        raise ValueError('focus_families must be a nonempty list of distinct supported families')
    cfg, scfg = resolve_config(config), resolve_store_config(store_config)
    references = {} if model_references is None else model_references
    expected_ids = {f'store-{i+1:03d}' for i in range(store_count)}
    if merchant_plan is not None and set(merchant_plan) != expected_ids:
        raise ValueError('Merchant plan must cover every store')
    geography = {} if geographic_plan is None else {m['retailer_id']: m for m in geographic_plan['merchants']}
    if geographic_plan is not None and set(geography) != expected_ids:
        raise ValueError('Geographic plan must cover every store')
    if not isinstance(references, dict) or set(references) - set(focus):
        raise ValueError('Model references must belong to focused families')
    if any(cfg['family_weights'][f] <= 0 for f in focus): raise ValueError('A focus family has zero catalog weight')
    enabled = {f for f in FAMILY_IDS if cfg['family_weights'][f] > 0}
    eligible_profiles = [p for p in SPECIALIST.values() if scfg['profile_weights'][p] > 0 and enabled.intersection(PROFILES[p]['families'])]
    eligible_profiles = sorted(set(eligible_profiles))
    relevant = scfg['relevant_stores_per_family']
    required_profiles = sorted({SPECIALIST[f] for f in focus})
    if any(scfg['profile_weights'][p] <= 0 for p in required_profiles): raise ValueError('Focus family requires a disabled specialist profile')
    if store_count < relevant * len(required_profiles): raise ValueError('Store count too small for requested specialist family coverage')
    if any(sum(SPECIALIST[f] == p for f in focus) > models_per_store for p in required_profiles):
        raise ValueError('models_per_store too small for focused families in a specialist store')

    # Stage 1: identities, specialization and geographic metadata, before any product.
    profile_plan = [p for p in required_profiles for _ in range(relevant)]
    generalists = 0
    while len(profile_plan) < store_count:
        i = len(profile_plan)
        allow_broad = store_count >= 3 and not generalists and enabled.intersection(PROFILES['marketplace']['families'])
        if allow_broad and rng(seed, f'stores/{i}/broad').random() < scfg['generalist_probability']:
            profile_plan.append('marketplace'); generalists += 1
        else:
            profile_plan.append(weighted(rng(seed, f'stores/{i}/profile'), eligible_profiles,
                                         [scfg['profile_weights'][p] for p in eligible_profiles]))
    rng(seed, 'stores/profile-order').shuffle(profile_plan)
    stores = []
    for i, profile in enumerate(profile_plan):
        id = f'store-{i+1:03d}'
        country = geography[id]['headquarters']['country'] if id in geography else 'SE'
        city_id = geography[id]['headquarters']['city_id'] if id in geography else None
        stores.append({'retailer_id': id, 'name': retailer_name(seed,id,i+1,profile,country,city_id),
                       'profile_id': profile, 'specialization': PROFILES[profile]['label'],
                       'families': sorted(enabled.intersection(PROFILES[profile]['families'])),
                       'location': {'country': 'SE', 'city': rng(seed, id+'/city').choice(CITIES)},
                       'warehouse_location': {'country': 'SE', 'city': rng(seed, id+'/warehouse').choice(CITIES)},
                       'site_url': f'https://{id}.shops.example.test/'})
        if id in geography:
            for field, source in (('location','headquarters'),('warehouse_location','warehouse')):
                stores[-1][field] = {key: geography[id][source][key] for key in ('country','city')}
        if merchant_plan is not None:
            stores[-1]['business_profile'] = {key: merchant_plan[id][key] for key in ('profile_id','label')}

    # Stage 2: store demand/model assignments. A shared canonical model per focused
    # family anchors overlap in the relevant specialist stores, not a winning SKU.
    family_plan, assignments, anchors = [], {s['retailer_id']: [] for s in stores}, {}
    for f in sorted(focus):
        index = len(family_plan); family_plan.append(f)
        carriers = [s for s in stores if s['profile_id'] == SPECIALIST[f]][:relevant]
        for s in carriers: assignments[s['retailer_id']].append(index)
        anchors[f] = {'model_index': index, 'stores': [s['retailer_id'] for s in carriers]}
    model_counts = {}
    for store in stores:
        id = store['retailer_id']; chosen = assignments[id]
        model_counts[id] = max(len(chosen), merchant_plan[id]['model_count'] if merchant_plan is not None else models_per_store)
        for slot in range(len(chosen), model_counts[id]):
            family = weighted(rng(seed, f'{id}/family/{slot}'), store['families'], [cfg['family_weights'][f] for f in store['families']])
            pool = [i for i, f in enumerate(family_plan) if f == family and i not in chosen]
            if pool and rng(seed, f'{id}/overlap/{slot}').random() < scfg['model_overlap_probability']:
                index = rng(seed, f'{id}/reuse/{slot}').choice(pool)
            else:
                index = len(family_plan); family_plan.append(family)
            chosen.append(index)
    identities = [None] * len(family_plan)
    blueprints = None;depth_details = None
    if footwear_depth is not None:
        from .footwear_depth import plan_depth
        family_plan,assignments,anchors,identities,blueprints,depth_details = plan_depth(
            seed,footwear_depth,stores,family_plan,assignments,anchors,model_counts)
        model_counts = {sid:len(indices) for sid,indices in assignments.items()}
    for family, identity in references.items(): identities[anchors[family]['model_index']] = identity
    catalog = generate_catalog(seed, len(family_plan), cfg, model_families=family_plan,
                               model_identities=identities if references or blueprints is not None else None,
                               model_blueprints=blueprints)
    groups = catalog['public']['product_groups']
    products = {p['product_id']: p for p in catalog['public']['products']}

    # Stage 3: listed variants, then offer prices and stock. Stock never feeds back.
    assortments, offers, comparison_listings = [], [], []
    shared_skus = {f: groups[a['model_index']]['variants'][0]['product_id'] for f, a in anchors.items()}
    if blueprints is not None:
        for family,a in anchors.items():
            blueprint=blueprints[a['model_index']]
            if blueprint is not None:
                shared_skus[family]=next(v['product_id'] for v in groups[a['model_index']]['variants']
                    if all(products[v['product_id']]['attributes'][k]==value for k,value in blueprint['anchor_attributes'].items()))
    for store in stores:
        id = store['retailer_id']
        residual = rng(seed, id+'/price-level').randint(-600, 600)
        for index in assignments[id]:
            group = groups[index]
            forced_shared = group['family'] in anchors and index == anchors[group['family']]['model_index'] and id in anchors[group['family']]['stores']
            anchor = shared_skus[group['family']] if forced_shared else rng(seed, id+'/'+group['group_id']+'/variant-anchor').choice(group['variants'])['product_id']
            if blueprints is not None and blueprints[index] is not None:
                wanted = blueprints[index]['anchor_attributes']
                anchor = next(v['product_id'] for v in group['variants']
                    if all(products[v['product_id']]['attributes'][k]==value for k,value in wanted.items()))
            carried = []
            if group['family']=='footwear':
                namespace=id+'/'+group['group_id']
                noise=rng(seed,namespace+'/price').randint(-400,400)
                reference=products[group['variants'][0]['product_id']]['reference_price_minor']
                advertised=max(100,((reference*(10000+residual+noise)//10000+50)//100)*100)
                size_surcharge=rng(seed,namespace+'/size-surcharge').random()<scfg['footwear_size_surcharge_probability']
                surcharge_size=max(products[v['product_id']]['attributes']['size_eu'] for v in group['variants'])
            for variant in group['variants']:
                sku = variant['product_id']; ns = id+'/'+sku
                if sku != anchor and rng(seed, ns+'/carried').random() >= scfg['variant_carry_probability']: continue
                carried.append(sku)
                if group['family']=='footwear':
                    extra=1 if size_surcharge and products[sku]['attributes']['size_eu']==surcharge_size else 0
                    price=advertised+(max(100,((advertised+500)//1000)*100) if extra else 0)
                else:
                    noise = rng(seed, ns+'/price').randint(-400, 400)
                    price = max(100, ((products[sku]['reference_price_minor'] * (10000+residual+noise)//10000 + 50)//100)*100)
                stock = 0 if rng(seed, ns+'/stockout').random() < scfg['stockout_probability'] else rng(seed, ns+'/quantity').randint(1, merchant_plan[id]['stock_max'] if merchant_plan is not None else 12)
                offers.append({'offer_id': f'offer-{id}-{sku}', 'retailer_id': id, 'product_id': sku,
                               'price_minor': price, 'stock_quantity': stock,
                               'dispatch_days': rng(seed, ns+'/dispatch').randint(0, 4),
                               'extra_name': None, 'extra_price_minor': None, 'extra_preselected': False})
            assortments.append({'retailer_id': id, 'model_id': group['group_id'], 'product_ids': carried})
            if group['family']=='footwear':
                comparison_listings.append({'retailer_id':id,'model_id':group['group_id'],
                    'advertised_price_minor':advertised,'entry_product_id':carried[0]})
    web_index = [{'site_id': s['retailer_id'], 'kind': 'retailer', 'url': s['site_url'], 'title': s['name'],
                  'description': s['specialization'] + ' based in ' + s['location']['city'] + '.',
                  'product_families': s['families']} for s in stores]
    public = {**copy.deepcopy(catalog['public']), 'retailers': stores, 'assortments': assortments,
              'offers': offers, 'web_index': web_index, 'comparison_listings':comparison_listings}
    bundle = {'schema_version': VERSION, 'seed': seed, 'store_count': store_count, 'models_per_store': models_per_store,
              'catalog': catalog, 'config': cfg, 'store_config': scfg, 'public': public, 'world_sha256': digest(public),
              'private_provenance': {'family_scope': focus, 'generation_order': ['stores', 'model_assortment_plan', 'canonical_catalog', 'variant_assortments', 'offer_prices_and_stock', 'index_manifest'],
                   'overlap_anchors': {f: {'model_id': groups[a['model_index']]['group_id'], 'product_id': shared_skus[f], 'retailer_ids': a['stores']} for f,a in anchors.items()},
                   'model_counts_by_store': model_counts,
                   'merchant_plan': copy.deepcopy(merchant_plan),
                   'naming_locales': {s['retailer_id']: naming_locale(s['location']['country'], geography[s['retailer_id']]['headquarters']['city_id'] if s['retailer_id'] in geography else None) for s in stores},
                   'index_binding': 'Reserved .test origins; not registered or hosted storefronts',
                   'relevance_contract': 'Family-level coverage and shared SKU listing only; no exact-requirement, in-stock or affordable-offer guarantee'}}
    if depth_details is not None:
        bundle['private_provenance']['footwear_depth']=depth_details
        bundle['private_provenance']['relevance_contract']='Family coverage, distinct footwear models and configured size listing anchors; no qualifying, in-stock or affordable-offer guarantee'
    validate_store_world(bundle)
    return bundle


def validate_store_world(bundle):
    if bundle.get('schema_version') != VERSION: raise ValueError('Unsupported store world')
    validate_catalog(bundle['catalog'])
    public = bundle['public']; products = {p['product_id']:p for p in public['products']}
    required={'products', 'product_groups', 'retailers', 'assortments', 'offers', 'web_index'}
    if not required<=set(public) or set(public)-required-{'comparison_listings'}:
        raise ValueError('Unexpected public world fields')
    groups = {g['group_id']:g for g in public['product_groups']}
    if public['products'] != bundle['catalog']['public']['products'] or public['product_groups'] != bundle['catalog']['public']['product_groups']:
        raise ValueError('Canonical catalog drift')
    stores = {s['retailer_id']:s for s in public['retailers']}
    if len(stores) != len(public['retailers']) or len(stores) != bundle['store_count']: raise ValueError('Duplicate/missing store')
    if sum(s['profile_id'] == 'marketplace' for s in stores.values()) > (1 if len(stores)>=3 else 0): raise ValueError('Too many generalists')
    for s in stores.values():
        if s['profile_id'] not in PROFILES or not s['families'] or set(s['families']) - set(PROFILES[s['profile_id']]['families']): raise ValueError('Invalid store specialization')
    listed = set(); models_by_store = defaultdict(set)
    for a in public['assortments']:
        if a['retailer_id'] not in stores or a['model_id'] not in groups: raise ValueError('Unknown assortment identity')
        group = groups[a['model_id']]; store = stores[a['retailer_id']]
        if group['family'] not in store['families']: raise ValueError('Product outside specialization')
        if a['model_id'] in models_by_store[a['retailer_id']]: raise ValueError('Duplicate model assortment')
        models_by_store[a['retailer_id']].add(a['model_id'])
        if not a['product_ids'] or set(a['product_ids']) - {v['product_id'] for v in group['variants']}: raise ValueError('Invalid carried SKU')
        for sku in a['product_ids']:
            pair = (a['retailer_id'],sku)
            if pair in listed: raise ValueError('Duplicate listing')
            listed.add(pair)
    counts = bundle['private_provenance'].get('model_counts_by_store', {})
    if any(len(models_by_store[s]) != counts.get(s, bundle['models_per_store']) for s in stores): raise ValueError('Incorrect store model count')
    pairs=set();offer_ids=set()
    for o in public['offers']:
        pair=(o['retailer_id'],o['product_id'])
        if pair not in listed or pair in pairs or o['offer_id'] in offer_ids: raise ValueError('Offer/listing mismatch')
        pairs.add(pair);offer_ids.add(o['offer_id'])
        for key in ('price_minor','stock_quantity','dispatch_days'):
            if type(o[key]) is not int or o[key]<0 or (key=='price_minor' and o[key]==0): raise ValueError('Invalid offer number')
    if listed != pairs: raise ValueError('Listed SKU missing offer')
    if 'comparison_listings' in public:
        expected={(a['retailer_id'],a['model_id']) for a in public['assortments'] if groups[a['model_id']]['family']=='footwear'}
        seen=set()
        for row in public['comparison_listings']:
            if set(row)!={'retailer_id','model_id','advertised_price_minor','entry_product_id'}:raise ValueError('Invalid comparison listing fields')
            pair=(row['retailer_id'],row['model_id'])
            if pair not in expected or pair in seen:raise ValueError('Invalid/duplicate comparison model')
            seen.add(pair)
            if (row['retailer_id'],row['entry_product_id']) not in listed or row['entry_product_id'] not in {v['product_id'] for v in groups[row['model_id']]['variants']}:
                raise ValueError('Invalid comparison navigation SKU')
            if type(row['advertised_price_minor']) is not int or row['advertised_price_minor']<=0:raise ValueError('Invalid advertised price')
        if seen!=expected:raise ValueError('Missing comparison listing')
    index = public['web_index']
    if len(index)!=len(stores) or {i['site_id'] for i in index} != set(stores): raise ValueError('Web index/store mismatch')
    for entry in index:
        s=stores[entry['site_id']]
        if entry['url']!=s['site_url'] or entry['product_families']!=s['families'] or entry['title']!=s['name']: raise ValueError('Index metadata drift')
    if set(bundle['private_provenance']['overlap_anchors']) != set(bundle['private_provenance']['family_scope']):
        raise ValueError('Missing scoped-family anchor')
    for f,a in bundle['private_provenance']['overlap_anchors'].items():
        if products[a['product_id']]['category']!=f or len(set(a['retailer_ids']))<bundle['store_config']['relevant_stores_per_family']: raise ValueError('Missing family coverage')
        if any((id,a['product_id']) not in pairs for id in a['retailer_ids']): raise ValueError('Missing guaranteed overlap')
    if bundle['world_sha256'] != digest(public): raise ValueError('World digest mismatch')
    return {'valid':True,'stores':len(stores),'offers':len(pairs)}


def summarize_stores(bundle):
    public=bundle['public']; products={p['product_id']:p for p in public['products']}
    carriers=defaultdict(set)
    for o in public['offers']:carriers[o['product_id']].add(o['retailer_id'])
    rows=[]
    for s in public['retailers']:
        offers=[o for o in public['offers'] if o['retailer_id']==s['retailer_id']]
        rows.append({'retailer_id':s['retailer_id'],'name':s['name'],'specialization':s['specialization'],
                     'models':sum(a['retailer_id']==s['retailer_id'] for a in public['assortments']),
                     'listed_skus':len(offers),'in_stock_skus':sum(o['stock_quantity']>0 for o in offers),
                     'shared_skus':sum(len(carriers[o['product_id']])>1 for o in offers),
                     'families':dict(Counter(products[o['product_id']]['category'] for o in offers))})
    return {'stores':rows,'store_count':len(rows),'canonical_models':len(public['product_groups']),
            'canonical_skus':len(products),'offers':len(public['offers']),
            'shared_skus':sum(len(v)>1 for v in carriers.values()),'world_sha256':bundle['world_sha256']}


def generate_world_task(bundle, seed=0, family='random', query='cheapest', **options):
    from .tasks import generate_task
    from environments.shopping_intent.generator import QUERY_PRESETS,stream
    scope=bundle['private_provenance']['family_scope']
    resolved=stream(seed,'query').choice(sorted(QUERY_PRESETS)) if query=='random' else query
    if resolved not in QUERY_PRESETS:raise ValueError('Unknown query')
    count=QUERY_PRESETS[resolved]['line_count']
    if family=='random':
        if len(scope)<count:raise ValueError('Choose enough focus families before generating stores for this query')
        family=','.join(rng(seed,'task-scope-families').sample(sorted(scope),count))
    else:
        selected = [f.strip() for f in family.split(',')]
        if len(selected) == 1 and count > 1:
            others = sorted(set(scope) - set(selected))
            if len(others)<count-1: raise ValueError('Choose enough focus families before generating stores for this query')
            selected += rng(seed,'task-scope-families').sample(others,count-1)
        family=','.join(selected)
    if not set(family.split(','))<=set(scope):raise ValueError('Task family outside planned store scope; choose the scope before generating stores')
    # Model binding uses only canonical catalog, never offer prices or inventory.
    task=generate_task(bundle['catalog'],seed=seed,family=family,query=query,**options)
    if any(l['family_id'] not in scope for l in task['request']['lines']):raise ValueError('Basket families must be explicitly included in the planned store scope')
    task['store_world_binding']={'world_sha256':bundle['world_sha256'],'scope_families':scope,
                                 'index_site_ids':[s['retailer_id'] for s in bundle['public']['retailers']]}
    return task
