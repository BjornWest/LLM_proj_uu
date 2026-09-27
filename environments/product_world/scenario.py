"""Task → store scope → independent catalog and inventory, with a frozen task.

Only family and optional named-model identities cross the generation boundary.
Detailed requirements, memories and hidden specifications never condition offers.
"""
import copy
import hashlib
import json

from environments.shopping_intent.generator import generate, stream
from .config import FAMILY_IDS
from .stores import generate_store_world, summarize_stores

VERSION = 'product-task-world-v1'


def sample_task(seed=0, family='random', query='cheapest', destination_city=None, destination_country=None, world_preferences='auto', cookie_preferences='auto', selection_link='retailer', product_review_preferences='none', retailer_preferences='none', retailer_ids=None, price_range_sek=None, **options):
    from environments.shopping_intent.world import QUERIES, UNIT_FAMILIES, INSPECTION_FAMILIES, extend
    if type(seed) is not int: raise ValueError('seed must be an integer')
    if query == 'random':
        # Cross-department baskets require deliberate author selection until a
        # coherent multi-line basket sampler is available.
        choices=['cheapest','fastest','average']
        if destination_city is not None or destination_country is not None:
            choices+=['cheapest_pickup','nearest_pickup','fastest_pickup']
            if family=='random' or family in INSPECTION_FAMILIES:choices.append('nearest_inspection')
            if family in ('random','footwear'):choices.append('widest_assortment')
        if family=='random' or family in UNIT_FAMILIES:choices.append('unit_price')
        query = stream(seed, 'scenario-query').choice(choices)
    if query in ('basket', 'split_basket'):
        if not isinstance(family, str) or len(family.split(',')) != 3:
            raise ValueError('Basket tasks require three explicitly chosen family IDs; unrelated families are never auto-filled')
    elif family == 'random':
        pool=('footwear',) if query=='widest_assortment' else INSPECTION_FAMILIES if query=='nearest_inspection' else UNIT_FAMILIES if query=='unit_price' else FAMILY_IDS
        family = stream(seed, 'scenario-family').choice(sorted(pool))
    if not isinstance(family, str) or any(f.strip() not in FAMILY_IDS for f in family.split(',')):
        raise ValueError('Choose families supported by the product-world generator')
    if query=='nearest_inspection' and options.get('budget_sek') is not None:
        raise ValueError('Inspection-only tasks do not support a purchase budget')
    if price_range_sek is not None and query!='widest_assortment':raise ValueError('Price ranges currently require widest_assortment')
    if query=='widest_assortment' and (family!='footwear' or options.get('target','category')!='category'):
        raise ValueError('Widest assortment currently compares footwear categories, not a named model')
    if query=='widest_assortment' and options.get('budget_sek') is not None:
        raise ValueError('Use price_range_sek for widest_assortment')
    task = generate(seed=seed, family=family, query=QUERIES.get(query,(query,))[0], **options)
    if destination_country is not None and destination_city is None:destination_city='random'
    if destination_city is not None:
        from .geography import user_location
        user = user_location(seed, destination_city, destination_country)
        for key in ('request','initial_accessible_task','resolved_task'):
            task[key]['context']['destination'] = user['country']
            task[key]['context']['destination_location'] = copy.deepcopy(user)
        task['settings']['destination_city'] = destination_city
        if destination_country is not None:task['settings']['destination_country'] = destination_country
        task['public']['environment_context']['shopping_scope'] = f"The provided shops, delivery to {user['city']}, {user['country']}. All scenario prices are in SEK. Compare currently purchasable offers."
        task['public']['environment_context']['user_location'] = copy.deepcopy(user)
        semantic = {k:task[k] for k in ('request','memory_facts','resolved_task')}
        semantic['hidden_user_specifications'] = [{k:v for k,v in h.items() if k!='reply'} for h in task['hidden_user_specifications']]
        task['semantic_sha256'] = hashlib.sha256(json.dumps(semantic,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    from environments.shopping_intent.consent import extend as extend_consent
    from environments.shopping_intent.answer_contract import extend as extend_answer
    from environments.shopping_intent.product_reviews import extend as extend_reviews
    from environments.shopping_intent.retailer_preferences import extend as extend_retailers
    return extend_retailers(extend_reviews(extend_answer(extend_consent(extend(task,query,world_preferences,price_range_sek=price_range_sek),cookie_preferences),selection_link),product_review_preferences),retailer_preferences,retailer_ids)


def task_scope(task):
    """Project the complete intent to the small allowed world-generation input."""
    lines = task['request']['lines']
    return {'focus_families': sorted({line['family_id'] for line in lines}),
            'model_references': {line['family_id']: copy.deepcopy(line['model'])
                                 for line in lines if line['model'] is not None}}


def generate_scenario(task_options=None, world_options=None, location_options=None, review_options=None, product_review_options=None, account_options=None):
    """Sample intent first; reproduce it unchanged for every independent world seed."""
    task_args = {} if task_options is None else copy.deepcopy(task_options)
    world_args = {} if world_options is None else world_options
    if not isinstance(task_args, dict) or not isinstance(world_args, dict):
        raise ValueError('Task and world options must be objects')
    coupon_disclosure=task_args.pop('coupon_disclosure','none')
    if coupon_disclosure not in ('none','auto','request','memory'):raise ValueError('Unknown coupon disclosure recipe')
    if coupon_disclosure!='none' and account_options is None:raise ValueError('Coupon disclosure requires account generation')
    if set(world_args) - {'seed', 'store_count', 'models_per_store', 'config', 'store_config', 'footwear_depth'}:
        raise ValueError('World scope is derived from the task; unknown world option')
    if task_args.get('retailer_preferences','none')!='none' and 'retailer_ids' not in task_args:
        task_args={**task_args,'retailer_ids':[f'store-{i+1:03d}' for i in range(world_args.get('store_count',6))]}
    task = sample_task(**task_args)
    scope = task_scope(task)
    geographic_plan = None
    merchant_plan = None
    if location_options is not None:
        from .geography import user_location
        from .locations import plan_locations, build_locations
        from .merchant_profiles import sample_profiles
        if not isinstance(location_options,dict) or set(location_options)-{'config','profile_weights','correlated_profiles','merchant_home_cities','branch_shipping'}:
            raise ValueError('Unknown location option')
        enabled = location_options.get('correlated_profiles',True)
        if type(enabled) is not bool: raise ValueError('correlated_profiles must be boolean')
        seed = world_args.get('seed',0)
        count = world_args.get('store_count',6)
        if type(count) is not int or not 1<=count<=16:raise ValueError('store_count must be 1..16')
        user = task['request']['context'].get('destination_location')
        if user is None:
            raise ValueError('Geographic scenarios require destination_city in task_options, sampled before the world')
        ids = [f'store-{i+1:03d}' for i in range(count)]
        profiles = sample_profiles(seed, ids, world_args.get('models_per_store',5), location_options.get('profile_weights'))
        if enabled:merchant_plan=profiles
        else:
            profiles={id:{'branch_count':3,'international_probability':.35} for id in ids}
        geographic_plan = plan_locations(seed,user,profiles,location_options.get('config'),location_options.get('merchant_home_cities'),location_options.get('branch_shipping'))
    extras = {} if geographic_plan is None else {'geographic_plan':geographic_plan,'merchant_plan':merchant_plan}
    world = generate_store_world(**world_args, **scope, **extras)
    if 'retailer_memory_facts' in task:
        from environments.shopping_intent.retailer_preferences import bind_names
        bind_names(task,world['public']['retailers'])
    from .reviews import generate_reviews
    if review_options is not None and (not isinstance(review_options,dict) or set(review_options)-{'seed','as_of','reviews_per_store','config'}):raise ValueError('Unknown review options')
    reviews=generate_reviews(world,**{'seed':world_args.get('seed',0),**(review_options or {})})
    from environments.product_review_sites.evidence import generate_evidence
    if product_review_options is not None and (not isinstance(product_review_options,dict) or set(product_review_options)-{'seed','as_of','reviews_per_sku','reviewed_variants_per_model'}):raise ValueError('Unknown product review options')
    product_reviews=generate_evidence(world,**{'seed':world_args.get('seed',0),'as_of':reviews['public']['as_of'],**(product_review_options or {})})
    result = {'schema_version': VERSION, 'task': task, 'bundle': world, 'merchant_reviews':reviews,'product_review_evidence':product_reviews,
            'summary': summarize_stores(world),
            'private_provenance': {'generation_order': ['structured_task_and_memories', 'task_scope',
                                  *world['private_provenance']['generation_order']],
                'world_inputs_from_task': scope, 'task_semantic_sha256': task['semantic_sha256'],
                'relevance_contract': 'Family coverage and named-model identity only; no guaranteed qualifying, affordable or in-stock offer'}}
    if geographic_plan is not None:
        result['locations'] = build_locations(world, geographic_plan)
        result['private_provenance']['generation_order'].insert(2,'merchant_scale_and_geographic_plan')
        result['private_provenance']['generation_order'].append('branch_inventory_and_offline_routes')
    if world_args.get('footwear_depth') is not None:
        result['private_provenance']['relevance_contract']=world['private_provenance']['relevance_contract']
    if account_options is not None:
        from .accounts import generate_accounts
        if not isinstance(account_options,dict) or set(account_options)-{'seed','as_of','config'}:raise ValueError('Unknown account generation option')
        result['accounts']=generate_accounts(world,**{'seed':world_args.get('seed',0),**account_options})
        result['private_provenance']['generation_order'].append('account_sessions_coupons_and_historical_orders')
        from environments.shopping_intent.account_hints import extend as extend_account_hints
        extend_account_hints(task,result['accounts'],world['public']['retailers'],coupon_disclosure)
        result['private_provenance']['task_semantic_sha256']=task['semantic_sha256']
    return result
