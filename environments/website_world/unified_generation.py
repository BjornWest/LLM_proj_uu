"""Explicit multi-family recipe through the shared website-generation entrypoint.

Finite presentation conditions retain upstream completion-mass weighting.
No native task/reference/grader is relabelled as accepted-catalog commerce.
"""
from copy import deepcopy
from math import exp,isfinite,log
from pathlib import Path
import json,random
from time import monotonic
from hashlib import sha256

from experiments.accepted_catalog_commerce import model,basket_quote,package_export
from . import generation as shared, requirements, surrounding_config, catalog_checkout_domain, basic_offer_task, generation_configs
from .adapter import ROOT,browser_address,supported_destination
from .presentation import VERSION as PRESENTATION,site_plan

VERSION='website-world-generation-v2'


def compile_request(request):
    allowed={'schema','seed','world','realism','difficulty','requirements','budget','episode','surrounding_sites','checkout_domain','task'}
    if type(request) is not dict or request.get('schema')!=VERSION or set(request)-allowed:raise ValueError('Invalid unified generation request')
    request=deepcopy(request);world=request.get('world',{})
    if type(world) is not dict or set(world)-{'concept_ids','tasks','controls','city_id','review_count'}:raise ValueError('Unknown accepted-catalog world option')
    explicit_concentration = 'tasks' in world
    world={'concept_ids':list(package_export.CONCEPTS),'tasks':['footwear.walking_shoes'],'city_id':'uppsala','review_count':2,**world}
    if type(world['concept_ids']) is not list or not world['concept_ids'] or len(set(world['concept_ids']))!=len(world['concept_ids']) or set(world['concept_ids'])-set(package_export.SUPPORTED_CONCEPTS):raise ValueError('Declare a supported unique concept slice')
    basic_selection = None
    if type(request.get('task')) is dict and request['task'].get('kind') == basic_offer_task.KIND:
        basic_selection = basic_offer_task.resolve(request['task'], seed=request['seed'], concept_ids=world['concept_ids'])
        if not explicit_concentration:
            world['tasks'] = [basic_selection['concept_id']]
    if type(world['tasks']) is not list or set(world['tasks'])-set(world['concept_ids']):raise ValueError('Concentration concepts must belong to the slice')
    if type(world['review_count']) is not int or not 0<=world['review_count']<=1000:raise ValueError('Declare finite review_count0..1000')
    if 'address_probabilities' in request.get('difficulty',{}):raise ValueError('Accepted-catalog address-probability pass-through is not released')
    task=request.get('task',{'user_message':'Browse the generated retailers, compare product information and inspect cart and delivery details. Do not complete a purchase.','memories':[]})
    if basic_selection is None and (type(task) is not dict or set(task)!={'user_message','memories'} or type(task['user_message']) is not str or not task['user_message'].strip() or type(task['memories']) is not list or any(type(x) is not str for x in task['memories'])):raise ValueError('Supply a manual task message and text memories, or a cheapest_available template')
    proxy={k:deepcopy(v) for k,v in request.items() if k not in ('task','checkout_domain')}
    episode = request.get('episode', {})
    start = episode.get('start', {}) if isinstance(episode, dict) else {}
    tool_start = isinstance(start, dict) and start.get('kind') == 'tool_discovery'
    if tool_start:
        if set(episode) - {'start', 'readable_origins'} or start != {'kind': 'tool_discovery'}:
            raise ValueError('Tool discovery requires only its start kind')
        proxy['episode'] = {**deepcopy(episode), 'start': {'kind': 'directory'}}
    surrounding = request.get('surrounding_sites', {})
    if isinstance(surrounding, dict) and 'version' not in surrounding and 'comparison_layout_weights' not in surrounding:
        # Fresh accepted-catalog defaults adopt the three native review designs.
        # An explicit historic review-weight domain preserves its v2 recipe.
        review_weights = surrounding.get('review_layout_weights', {})
        historical_reviews = isinstance(review_weights, dict) and set(review_weights) == {'journal', 'community'}
        if not historical_reviews:
            proxy['surrounding_sites'] = {**deepcopy(surrounding), 'version': 'native-rich-surrounding-v3'}
    if 'realism' in proxy:
        if not isinstance(proxy['realism'], dict):
            raise ValueError('Realism must be an object')
        proxy['realism'].pop('selected_content', None)
        proxy['realism'].pop('product_disclosure', None)
    proxy.update(schema=shared.VERSION,world={k:deepcopy(world[k]) for k in ('controls','city_id') if k in world})
    config=shared.compile_request(proxy)
    if basic_selection is not None and 'comparison_site_id' in basic_selection:
        surrounding_options = config['surrounding_options']
        if (not surrounding_options['enabled'] or basic_selection['comparison_site_id'] not in
                {f'comparison-{i:02d}' for i in range(surrounding_options['comparison_count'])}):
            raise ValueError('Task comparison site must be enabled in surrounding_sites')
    if tool_start:
        config['episode'] = deepcopy(request['episode'])
    if any(r['target']['kind'] in ('world_reference','best_matching_retailers') for r in config['requirements']):raise ValueError('Accepted-catalog matching/reference selectors are not released; use explicit, scale or all-retailer targets')
    if config['surrounding_options']['version'] not in ('native-rich-surrounding-v2', 'native-rich-surrounding-v3'):raise ValueError('Accepted-catalog worlds require family-aware surrounding v2/v3')
    world['controls']=config['world']['controls'];config['world']=world
    selected_content=request.get('realism',{}).get('selected_content',False)
    if type(selected_content) is not bool:raise ValueError('selected_content must be boolean')
    from .product_disclosure import options as disclosure_options
    disclosure=disclosure_options(request['realism']['product_disclosure']) if 'product_disclosure' in request.get('realism',{}) else None
    if disclosure is not None:
        if request.get('realism',{}).get('selected_content') is False:raise ValueError('Count-first disclosure requires selected content')
        selected_content=True
    config['selected_content']=selected_content
    config['product_disclosure']=disclosure
    config['task']=task;config['checkout_domain_options']=catalog_checkout_domain.options(request.get('checkout_domain'))
    if basic_selection is not None:config['basic_offer_selection']=basic_selection
    config['request']=request
    return config


def initial_home_delivery_available(world,retailer,selector_kind,*,oracle=None,plan=None):
    try:destination=supported_destination(world,browser_address(retailer['initial_form']))
    except ValueError:return False
    oracle=basket_quote if oracle is None else oracle
    plan=basket_quote.make_plan(world) if plan is None else plan
    for offer in retailer['offers']:
        oid=offer['offer_id'];quote=oracle.quote(world,retailer['retailer_id'],[{'line_id':oid,'offer_id':oid,'quantity':1}],plan=plan,destination=destination)
        if any(c['destination_type']=='home' for c in quote['delivery_choices']):return True
    return False


def generate(request,*,world_factory=None):
    config=compile_request(request);started=monotonic()
    stream=random.Random(int(shared.digest([VERSION,request['seed'],'world-proposals']),16))
    acceptance=random.Random(int(shared.digest([VERSION,request['seed'],'acceptance']),16))
    upper=requirements.log_upper_bound(config['requirements'])
    audit={'schema':VERSION,'request_sha256':shared.digest(request),'status':'sampling',
        'algorithm':'factored-completion-mass/upstream-rejection','solver':None,
        'log_acceptance_upper_bound':upper,'proposals':[]}
    factory=world_factory or model.generate
    for attempt in range(config['budget']['max_proposals']):
        if monotonic()-started>=config['budget']['max_seconds']:break
        seed=request['seed'] if attempt==0 else stream.randrange(2**31)
        world=factory(seed,**config['world'])
        delivery_plan = None
        basket_plan = None
        checker = initial_home_delivery_available
        delivery_supported = True
        if config['delivery_options'] is not None:
            from experiments.accepted_catalog_commerce import delivery_admission
            from functools import partial
            from .delivery_options import producer_plan_version, producer_weights
            basket_plan = basket_quote.make_plan(world)
            try:
                delivery_plan = delivery_admission.make_plan(world, basket_plan, seed=world['seed'],
                    count_weights=producer_weights(config['delivery_options']),
                    plan_version=producer_plan_version(config['delivery_options']))
            except ValueError as error:
                # The finite PMF can have no support below this world's actual
                # capacity. Reject only this declared zero-completion case;
                # propagate malformed source/plan/producer failures normally.
                if str(error) != 'No positive count mass within the real route bound':
                    raise
                delivery_supported = False
            if delivery_supported:
                oracle = delivery_admission.Oracle(world, basket_plan, delivery_plan)
                checker = partial(initial_home_delivery_available, oracle=oracle, plan=basket_plan)
        completion=requirements.evaluate(world,config['requirements'],config['priors'],config['resets'],config['policies'],home_delivery_checker=checker,delivery_options=config['delivery_options'],variation_priors=config['variation_priors'])
        if not delivery_supported:
            completion.update(log_mass=float('-inf'),reason='delivery_count_support')
        start=config['episode']['start']
        if start['kind']=='retailer_home' and start['retailer_id'] not in {r['retailer_id'] for r in world['retailers']}:completion.update(log_mass=float('-inf'),reason='missing_episode_retailer')
        value=completion['log_mass']
        if value>upper+1e-10:raise ArithmeticError('Invalid rejection envelope')
        chance=acceptance.random();accepted=value!=float('-inf') and (chance==0 or log(chance)<min(0.,value-upper))
        audit['proposals'].append({'seed':seed,'world_id':world['world_id'],'log_completion_mass':value if isfinite(value) else None,
            'completion_mass':exp(value),'reason':completion['reason'],'acceptance_probability':exp(min(0.,value-upper)),'accepted':accepted})
        if not accepted:continue
        presentation={'schema':PRESENTATION,'world_id':world['world_id'],'reset_weights':config['resets'],'policy_weights':config['policies'],
            'component_priors':config['priors'],'sites':{sid:{'conditions':c,'initial_form':'producer'} for sid,c in completion['conditions'].items()}}
        if config['variation_priors'] is not None:presentation['variation_priors']=config['variation_priors']
        if config['selected_content']:presentation['selected_content']=True
        if config['product_disclosure'] is not None:presentation['product_disclosure']=config['product_disclosure']
        from .product_disclosure import retailer_profiles
        profiles=retailer_profiles(world,config['product_disclosure'])
        if profiles is not None:presentation['retailer_disclosure_profiles']=profiles
        if config['delivery_options'] is not None:presentation['delivery_options']=config['delivery_options']
        basket_plan=basket_quote.make_plan(world) if basket_plan is None else basket_plan
        policy_oracle=basket_quote if delivery_plan is None else oracle
        plans={r['retailer_id']:site_plan(world,r,presentation,basket_policy=policy_oracle.public_policy(basket_plan,r['retailer_id'])) for r in world['retailers']}
        audit.update(status='accepted',selected_seed=seed,resolved=completion['resolved'],elapsed_seconds=monotonic()-started)
        checkout_domain=catalog_checkout_domain.make(world,config['checkout_domain_options'])
        # Checkout and surrounding use the same JSON digest format. Shipping
        # uses a different historical format; preserve both published bindings.
        # Reuse only within this call; never cache a mutable caller-owned world.
        world_sha256=checkout_domain['world_sha256']
        surrounding = surrounding_config._generate_bound(world,config['surrounding_options'],world_sha256)
        basic_task = None
        episode = {**config['episode'], 'manual_task': config['task']}
        if 'basic_offer_selection' in config:
            basic_task = basic_offer_task._make_bound(world, config['basic_offer_selection'], world_sha256,
                                                     surrounding=surrounding)
            episode.update(task_id=basic_task['task_id'], manual_task={
                'user_message': basic_task['user_message'], 'memories': basic_task['memories']})
            if 'comparison_scope' in basic_task:
                episode['shopping_scope'] = 'Products and retailer listings shown on ' + basic_task['comparison_scope']['site_name']
        result = {'world':world,'presentation':presentation,'compositions':plans,'audit':audit,
            'resolved_configuration':config,
            'episode':episode,'basket_plan':basket_plan,
            'checkout_domain':checkout_domain,
            'surrounding':surrounding}
        if delivery_plan is not None:result['delivery_plan']=delivery_plan
        if basic_task is not None:
            result['basic_offer_task'] = basic_task
            result['basic_offer_reference'] = basic_offer_task._reference_bound(world, basic_task)
        return result
    audit.update(status='budget_exhausted',feasibility='unknown',elapsed_seconds=monotonic()-started)
    raise shared.SamplingBudgetExceeded(audit)


def prepare(request,output):
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
    shared.save(output/'request.json',request);before=shared.source_files()
    try:result=generate(request)
    except shared.SamplingBudgetExceeded as error:
        shared.save(output/'sampling-audit.private.json',error.audit);raise
    if before!=shared.source_files():raise RuntimeError('Generation sources changed during sampling')
    producer_manifest=model.freeze(result['world'],output/'pin')
    for name,key in [('presentation.json','presentation'),('compositions.private.json','compositions'),
        ('episode.json','episode'),('sampling-audit.private.json','audit'),('surrounding.private.json','surrounding'),
        ('basket-plan.private.json','basket_plan'),('checkout-domain.private.json','checkout_domain')]:shared.save(output/name,result[key])
    if 'delivery_plan' in result:shared.save(output/'delivery-plan.private.json',result['delivery_plan'])
    if 'basic_offer_task' in result:
        shared.save(output/'basic-offer-task.private.json', result['basic_offer_task'])
        shared.save(output/'basic-offer-reference.private.json', result['basic_offer_reference'])
    shared.save(output/'generation-config.private.json', generation_configs.capture(
        request,result['resolved_configuration'],world_id=result['world']['world_id'],
        selected_seed=result['audit']['selected_seed']))
    sources={**before,**producer_manifest['source_sha256']}
    for name,value in sources.items():
        if sha256((ROOT/name).read_bytes()).hexdigest()!=value:raise RuntimeError('Source changed before publication: '+name)
    manifest={'schema':VERSION,'world_id':result['world']['world_id'],'summary':result['world']['summary'],
        'files':{str(p.relative_to(output)):sha256(p.read_bytes()).hexdigest() for p in output.rglob('*') if p.is_file()},
        'source_sha256':sources,'surrounding_schema':result['surrounding']['schema_version'],
        'producer_schema':model.VERSION,'task_kind':'basic_listed_offer' if 'basic_offer_task' in result else 'manual_accepted_catalog','automatic_grader_supported':False,
        'structured_order_set_grader_supported':False,'model_runs':0,'purchases':0,
        'limitations':result['world']['limitations']+['Native footwear task/grader remains separate.','Address-probability overrides await a new producer binding.']}
    shared.save(output/'manifest.json',manifest);return manifest


def bind_task(runtime,episode):
    start=episode['start'];task=episode['manual_task']
    if start['kind'] == 'tool_discovery':
        if runtime.discovery_mode != 'tool':
            raise ValueError('Tool-discovery episode requires its matching runtime mode')
        start_url = runtime.research_origin + '/'
    else:
        start_url=runtime.index_origin+'/' if start['kind']=='directory' else runtime.origins[start['retailer_id']]+'/'
    return {'schema_version':'connected-world-manual-v1','task_id':episode.get('task_id','catalog-'+runtime.world['world_id'][:20]),
        'user_message':task['user_message'],'memories':deepcopy(task['memories']),
        'environment_context':{'currency':'SEK','shopping_scope':episode.get('shopping_scope','All retailers in this generated world'),
                               'scenario_date':runtime.world['quote_as_of']},'start_url':start_url}
