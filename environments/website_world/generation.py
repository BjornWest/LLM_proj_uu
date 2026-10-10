"""Additive native footwear world → sampled websites → episode setup.

Upstream proposals are accepted with their website completion mass before any
page draw. Resource exhaustion never returns an unconditioned fallback world.
"""
from copy import deepcopy
from hashlib import sha256
from math import exp, isfinite, log
from pathlib import Path
import ast
import json
import random
from time import monotonic

from experiments.footwear_world_pilot import model as producer
from experiments.footwear_world_pilot import difficulty_generation as address_stage
from experiments.address_checkout_pilot.model import parameters as address_parameters
from experiments.world_sampling_defaults import model as population
from environments.product_world.geography import cities
from environments.website_drafts.component_sampling import canonical, load_priors, probabilities
from .adapter import ROOT
from .presentation import VERSION as PRESENTATION, RESET_WEIGHTS, POLICY_WEIGHTS, site_plan
from . import requirements as constraints
from . import surrounding_config as ecosystem
from . import checkout_domain
from experiments.footwear_world_pilot import basket_quote, order_set_task, order_set_grader

VERSION = 'website-world-generation-v1'
QUOTE_SOURCES = (
    'experiments/footwear_world_pilot/model.py', 'experiments/address_checkout_pilot/model.py',
    'experiments/carrier_service_pilot/model.py', 'experiments/carrier_location_pilot/model.py',
)


class SamplingBudgetExceeded(RuntimeError):
    def __init__(self, audit):
        super().__init__('Conditioned sampling budget exhausted; feasibility is unknown')
        self.audit = audit


def digest(value):
    return sha256(canonical(value).encode()).hexdigest()


def full_weights(value, defaults, name):
    if not isinstance(value, dict) or set(value) != set(defaults):
        raise ValueError('Declare the complete weight domain: ' + name)
    probabilities(value)
    # JSON object order is not a sampling parameter. Keep the versioned domain
    # order so semantically identical configs use the same seeded CDF.
    return {key: deepcopy(value[key]) for key in defaults}


def probability(value, name):
    if type(value) not in (int, float) or not isfinite(value) or not 0 <= value <= 1:
        raise ValueError('Expected probability in [0, 1]: ' + name)
    return value


def compile_request(request):
    if not isinstance(request, dict) or request.get('schema') != VERSION or set(request) - {
            'schema', 'seed', 'world', 'realism', 'difficulty', 'requirements', 'budget', 'episode', 'surrounding_sites', 'basket_shipping', 'checkout_domain', 'order_set_task', 'order_set_search'}:
        raise ValueError('Invalid generation request')
    request = deepcopy(request)
    basket_options = request.get('basket_shipping', {'enabled': False})
    if not isinstance(basket_options, dict) or set(basket_options) != {'enabled'} or type(basket_options['enabled']) is not bool:
        raise ValueError('Basket shipping requires an explicit boolean enabled field')
    domain_options = None
    if 'checkout_domain' in request:
        if not basket_options['enabled'] or type(request['checkout_domain']) is not dict:
            raise ValueError('Explicit checkout domain requires basket shipping')
        domain_options = checkout_domain.options(request['checkout_domain'])
    native_task = order_set_task.validate(request['order_set_task']) if 'order_set_task' in request else None
    if native_task is not None and domain_options is None:
        raise ValueError('Order-set tasks require an explicit shared checkout_domain and basket shipping')
    search = request.get('order_set_search', {})
    if type(search) is not dict or set(search)-{'max_work','max_seconds','max_solutions'}:
        raise ValueError('Unknown order-set search control')
    if search and native_task is None:
        raise ValueError('Order-set search controls require an order-set task')
    from experiments.footwear_world_pilot.order_set_optimizer import _Work
    search_budget = _Work({k:v for k,v in search.items() if k!='max_solutions'}).budget
    max_solutions = search.get('max_solutions',100)
    if type(max_solutions) is not int or max_solutions<1:
        raise ValueError('max_solutions must be positive')
    if 'surrounding_sites' in request and not isinstance(request['surrounding_sites'], dict):
        raise ValueError('Surrounding-site controls must be an object')
    surrounding_options = ecosystem.options(request.get('surrounding_sites'))
    seed = request.get('seed')
    if type(seed) is not int or not 0 <= seed < 2**31:
        raise ValueError('Expected nonnegative 31-bit seed')
    world = request.get('world', {})
    if not isinstance(world, dict) or set(world) - {'objective', 'concept_id', 'city_id', 'controls'}:
        raise ValueError('Unknown world option')
    world = {'objective': 'cheapest_delivered', 'concept_id': 'footwear.walking_shoes',
             'city_id': 'uppsala', **world}
    if world['objective'] not in producer.OBJECTIVES or world['concept_id'] not in (
            'footwear.walking_shoes', 'footwear.walking_sandals') or world['city_id'] not in cities():
        raise ValueError('Unsupported native footwear world recipe')
    defaults = population.load()[0]['controls']
    controls = world.get('controls', {})
    if not isinstance(controls, dict) or set(controls) - set(defaults):
        raise ValueError('Unknown population control')
    controls = {**defaults, **controls}
    if any(type(v) not in (int, float) or not isfinite(v) or v < 0 for v in controls.values()):
        raise ValueError('Population controls must be finite nonnegative numbers')
    if not controls['product_concentration'] or not controls['within_store_task_concentration']:
        raise ValueError('Population concentrations must be positive')
    world['controls'] = controls

    realism = request.get('realism', {})
    if not isinstance(realism, dict) or set(realism) - {'family_weights', 'convention_weights', 'icon_cart_probability', 'page_variations', 'selected_content', 'delivery_options', 'component_ordering'}:
        raise ValueError('Unknown website realism control')
    ordering = realism.get('component_ordering', 'legacy-v1')
    if ordering not in ('legacy-v1', 'canonical-v2'):
        raise ValueError('Unknown component ordering mode')
    priors = load_priors(version=2 if ordering == 'canonical-v2' else 1)
    families = realism.get('family_weights', {})
    if not isinstance(families, dict) or set(families) - set(priors['profiles']):
        raise ValueError('Unknown architecture profile')
    for profile, weights in families.items():
        priors['profiles'][profile]['family_weights'] = full_weights(
            weights, priors['profiles'][profile]['family_weights'], profile)
    if 'convention_weights' in realism:
        priors['site_choices']['global'] = full_weights(realism['convention_weights'],
            priors['site_choices']['global'], 'conventions')
    if 'icon_cart_probability' in realism:
        p = probability(realism['icon_cart_probability'], 'icon_cart_probability')
        priors['site_choices']['iconCart'] = {'true': p, 'false': 1-p}

    from environments.website_drafts.component_sampling import factors
    from environments.website_drafts.variation_sampling import normalize
    variation_priors=normalize(realism['page_variations'],factors('typical',priors)) if 'page_variations' in realism else None
    if type(realism.get('selected_content',False)) is not bool:raise ValueError('selected_content must be boolean')
    if request.get('schema')==VERSION and realism.get('selected_content',False):raise ValueError('Selected content requires accepted-catalog commerce')

    from .delivery_options import options as delivery_options
    delivery_settings = delivery_options(realism['delivery_options']) if 'delivery_options' in realism else None

    difficulty = request.get('difficulty', {})
    if not isinstance(difficulty, dict) or set(difficulty) - {
            'reset_weights', 'variant_url_weights', 'policy_entry_weights', 'search_probabilities',
            'coupon_opacity_probability', 'address_probabilities'}:
        raise ValueError('Unknown or not yet supported difficulty control')
    address_options = None
    if 'address_probabilities' in difficulty:
        if not isinstance(difficulty['address_probabilities'], dict):
            raise ValueError('Address probabilities must be an object')
        address_options = address_parameters(difficulty['address_probabilities'])
    resets = full_weights(difficulty.get('reset_weights', RESET_WEIGHTS), RESET_WEIGHTS, 'reset_weights')
    policies = full_weights(difficulty.get('policy_entry_weights', POLICY_WEIGHTS), POLICY_WEIGHTS, 'policy_entry_weights')
    priors['site_choices']['url'] = full_weights(difficulty.get('variant_url_weights',
        priors['site_choices']['url']), priors['site_choices']['url'], 'variant_url_weights')
    searches = difficulty.get('search_probabilities', {})
    if not isinstance(searches, dict) or set(searches) - set(priors['profiles']):
        raise ValueError('Unknown search profile')
    for profile, value in searches.items():
        priors['profiles'][profile]['search_probability'] = probability(value, 'search/' + profile)
    opacity = probability(difficulty.get('coupon_opacity_probability', 0), 'coupon_opacity_probability')
    if opacity:
        raise ValueError('Fresh-world coupon producer is not integrated; frozen coupon pins cannot be rebound')
    # Capability restriction defines this native slice's base distribution; it
    # is not multiplied into the mass again for each otherwise ordinary site.
    priors['site_choices']['opaque'] = {'true': 0, 'false': 1}
    r = probabilities(resets)
    priors['site_choices']['reset'] = {'false': r['preserve'], 'true': 1-r['preserve']}
    compiled = constraints.validate(request.get('requirements', []), priors, resets, policies, variation_priors=variation_priors, delivery_options=delivery_settings)
    if native_task is not None and any(r['target']['kind'] in ('world_reference','best_matching_retailers') for r in compiled):
        raise ValueError('Single-offer winner selectors cannot target an order-set task; use all/scale/explicit retailer scopes until order-set selectors are implemented')
    if world['objective'] == 'widest_assortment' and any('best_offer_count' in r for r in compiled):
        raise ValueError('Widest-assortment reference ranks branches, not individual offers')
    budget = request.get('budget', {})
    if not isinstance(budget, dict) or set(budget) - {'max_proposals', 'max_seconds'}:
        raise ValueError('Unknown sampling budget')
    budget = {'max_proposals': 64, 'max_seconds': 60, **budget}
    if type(budget['max_proposals']) is not int or budget['max_proposals'] <= 0:
        raise ValueError('max_proposals must be a positive integer')
    if type(budget['max_seconds']) not in (int, float) or not isfinite(budget['max_seconds']) or budget['max_seconds'] <= 0:
        raise ValueError('max_seconds must be positive and finite')
    episode = request.get('episode', {'start': {'kind': 'directory'}})
    if not isinstance(episode, dict) or 'start' not in episode or set(episode) - {'start', 'readable_origins'}:
        raise ValueError('Episode must declare one start descriptor')
    if 'readable_origins' in episode and type(episode['readable_origins']) is not bool:
        raise ValueError('Episode readable_origins must be boolean')
    start = episode['start']
    if not isinstance(start, dict):
        raise ValueError('Invalid episode start')
    if start.get('kind') == 'directory':
        if set(start) != {'kind'}:
            raise ValueError('Unexpected directory start field')
    elif start.get('kind') == 'retailer_home':
        if set(start) != {'kind', 'retailer_id'} or not isinstance(start['retailer_id'], str) or not start['retailer_id']:
            raise ValueError('Retailer home requires an explicit retailer ID')
    else:
        raise ValueError('Supported starts: directory, retailer_home')
    return {'request': request, 'world': world, 'priors': priors, 'resets': resets,
            'policies': policies, 'variation_priors':variation_priors, 'delivery_options':delivery_settings, 'requirements': compiled, 'budget': budget, 'episode': episode,
            'address_options': address_options, 'surrounding_options': surrounding_options,
            'basket_enabled': basket_options['enabled'], 'checkout_domain_options': domain_options, 'order_set_task': native_task,
            'order_set_search': search_budget, 'max_solutions': max_solutions}


def generate(request, *, world_factory=None):
    """Exact rejection method with directly factored downstream masses.

    Probabilities use floating point/log arithmetic and purpose-keyed PRNGs.
    This is not a claim of exact enumeration of all 31-bit seed assignments.
    The first proposal retains the requested world seed; further proposals are
    uniform pseudorandom seeds. The complete proposal trace is kept private.
    """
    if isinstance(request, dict) and request.get('schema') == 'website-world-generation-v2':
        from . import unified_generation
        return unified_generation.generate(request,world_factory=world_factory)
    config = compile_request(request)
    if config['delivery_options'] is not None and config['order_set_task'] is None:
        raise ValueError('Sampled delivery menus require accepted-catalog v2 or a native order-set task; original native reference is separate')
    factory = world_factory or (producer.generate if config['address_options'] is None else address_stage.generate)
    world_options = deepcopy(config['world'])
    if config['address_options'] is not None:
        world_options['address_options'] = deepcopy(config['address_options'])
    started = monotonic()
    stream = random.Random(int(digest([VERSION, request['seed'], 'world-proposals']), 16))
    acceptance = random.Random(int(digest([VERSION, request['seed'], 'acceptance']), 16))
    upper = constraints.log_upper_bound(config['requirements'])
    audit = {'schema': VERSION, 'request_sha256': digest(request), 'status': 'sampling',
             'algorithm': 'factored-completion-mass/upstream-rejection',
             'solver': None, 'log_acceptance_upper_bound': upper, 'proposals': [],
             'natural_address_parameters': deepcopy(config['address_options'])}
    for attempt in range(config['budget']['max_proposals']):
        if monotonic()-started >= config['budget']['max_seconds']:
            break
        seed = request['seed'] if attempt == 0 else stream.randrange(2**31)
        world = factory(seed, **world_options)
        basket_plan=None;delivery_plan=None;oracle=basket_quote;checker=None;delivery_supported=True
        if config['delivery_options'] is not None:
            from experiments.accepted_catalog_commerce import delivery_admission
            from functools import partial
            from .delivery_options import producer_weights
            from .unified_generation import initial_home_delivery_available
            basket_plan=basket_quote.make_plan(world)
            try:delivery_plan=delivery_admission.make_plan(world,basket_plan,seed=world['seed'],count_weights=producer_weights(config['delivery_options']))
            except ValueError as error:
                if str(error)!='No positive count mass within the real route bound':raise
                delivery_supported=False
            if delivery_supported:
                oracle=delivery_admission.Oracle(world,basket_plan,delivery_plan)
                checker=partial(initial_home_delivery_available,oracle=oracle,plan=basket_plan)
        completion = constraints.evaluate(world, config['requirements'], config['priors'],
                                          config['resets'], config['policies'],variation_priors=config['variation_priors'],
                                          home_delivery_checker=checker,delivery_options=config['delivery_options'])
        if not delivery_supported:completion.update(log_mass=float('-inf'),reason='delivery_count_support')
        start = config['episode']['start']
        if start['kind'] == 'retailer_home' and start['retailer_id'] not in {r['retailer_id'] for r in world['retailers']}:
            completion.update(log_mass=float('-inf'), reason='missing_episode_retailer')
        value = completion['log_mass']
        if value > upper + 1e-10:
            raise ArithmeticError('Invalid rejection envelope')
        chance = acceptance.random()
        accepted = value != float('-inf') and (chance == 0 or log(chance) < min(0., value-upper))
        audit['proposals'].append({'seed': seed, 'world_id': world['world_id'],
            'log_completion_mass': value if isfinite(value) else None,
            'completion_mass': exp(value), 'reason': completion['reason'],
            'acceptance_probability': exp(min(0., value-upper)), 'accepted': accepted})
        if not accepted:
            continue
        presentation = {'schema': PRESENTATION, 'world_id': world['world_id'],
            'reset_weights': config['resets'], 'policy_weights': config['policies'],
            'component_priors': config['priors'],
            'sites': {sid: {'conditions': c, 'initial_form': 'producer'}
                      for sid, c in completion['conditions'].items()}}
        if config['variation_priors'] is not None:presentation['variation_priors']=config['variation_priors']
        if config['delivery_options'] is not None:presentation['delivery_options']=config['delivery_options']
        basket_plan = basket_plan or (basket_quote.make_plan(world) if config['basket_enabled'] else None)
        domain = checkout_domain.make(world, config['checkout_domain_options']) if config['checkout_domain_options'] is not None else None
        native_reference = None
        matching = None
        if config['order_set_task'] is not None:
            matching = order_set_task.match(world, config['order_set_task'])
            remaining = config['budget']['max_seconds'] - (monotonic()-started)
            if remaining <= 0:
                audit.update(status='budget_exhausted', feasibility='unknown')
                raise SamplingBudgetExceeded(audit)
            search_budget = {**config['order_set_search'], 'max_seconds':min(config['order_set_search']['max_seconds'],remaining)}
            native_reference = order_set_task.reference(world, config['order_set_task'], plan=basket_plan, domain=domain,
                budget=search_budget,max_solutions=config['max_solutions'],admission_plan=delivery_plan)
            if not native_reference['result']['complete']:
                audit.update(status='order_set_search_exhausted',feasibility='unknown',order_set_reference=native_reference)
                raise SamplingBudgetExceeded(audit)
        plans = {r['retailer_id']: site_plan(world, r, presentation,
                 basket_policy=oracle.public_policy(basket_plan,r['retailer_id']) if basket_plan else None)
                 for r in world['retailers']}
        audit.update(status='accepted', selected_seed=seed, resolved=completion['resolved'],
                     elapsed_seconds=monotonic()-started)
        result={'schema': VERSION, 'request': deepcopy(request), 'world': world,
                'presentation': presentation, 'compositions': plans,
                'episode': config['episode'], 'audit': audit,
                'checkout_domain': domain, 'order_set_task':config['order_set_task'],
                'order_set_matching':matching, 'order_set_reference':native_reference,
                'surrounding': ecosystem.generate(world, config['surrounding_options'])}
        if delivery_plan is not None:result.update(delivery_plan=delivery_plan,basket_plan=basket_plan)
        return result
    audit.update(status='budget_exhausted', feasibility='unknown', elapsed_seconds=monotonic()-started)
    raise SamplingBudgetExceeded(audit)


def source_files():
    """Pin the bounded producer, public renderer and their local data recipes."""
    paths = set()
    pending = [Path(__file__).resolve(), ROOT/'environments/website_world/runtime.py',
               ROOT/'intent_browser/runner.py',
               ROOT/'experiments/world_sampling_defaults/execution.py']
    def enqueue(parts):
        if not parts or parts[0] not in ('environments', 'experiments', 'intent_browser'):
            return
        stem = ROOT.joinpath(*parts)
        for candidate in (stem.with_suffix('.py'), stem/'__init__.py'):
            if candidate.is_file() and candidate not in paths:
                pending.append(candidate)
        # Package initialization can affect either import form.
        for i in range(1, len(parts)):
            package = ROOT.joinpath(*parts[:i], '__init__.py')
            if package.is_file() and package not in paths:
                pending.append(package)
    while pending:
        path = pending.pop()
        if path in paths:
            continue
        paths.add(path)
        package = list(path.relative_to(ROOT).with_suffix('').parts[:-1])
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    enqueue(alias.name.split('.'))
            elif isinstance(node, ast.ImportFrom):
                base = package[:len(package)-node.level+1] if node.level else []
                base += node.module.split('.') if node.module else []
                enqueue(base)
                for alias in node.names:
                    if alias.name != '*':
                        enqueue(base + alias.name.split('.'))
    for folder in ('environments/website_world', 'environments/website_drafts'):
        paths.update(p for p in (ROOT/folder).iterdir() if p.suffix in ('.js', '.css')
                     and p.name not in ('generated-catalog.js', 'market-range-fixture.js', 'reviewer.js'))
    paths.update(p for folder in ('environments/product_world/data/footwear_context_pilot',
        'environments/product_world/data/concept_registry') for p in (ROOT/folder).rglob('*.json'))
    paths.update(ROOT/name for name in ('environments/product_world/data/europe_locations.json',
        'experiments/footwear_world_pilot/config.json', 'environments/website_drafts/shop.html',
        'intent_browser/model_tokenizers.json',
        'environments/website_drafts/component-priors-v1.json', 'docs/agents/world-sampling-defaults.json',
        'docs/agents/cross-family-store-theme-review.json',
        'environments/product_world/data/product_feature_policies/media_tablet_v1.json',
        'environments/product_world/data/product_feature_policies/retailer_disclosure_v1.json',
        'environments/product_world/data/product_feature_policies/catalogue_v1/manifest.json',
        'environments/product_world/data/product_feature_policies/catalogue_v1/tops.t_shirts.json',
        'environments/product_world/data/product_feature_policies/catalogue_v2/manifest.json',
        'environments/product_world/data/product_feature_policies/catalogue_v2/tablets.everyday_media_tablets.json'))
    return {str(p.relative_to(ROOT)): sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}


def save(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def prepare(request, output):
    """Persist a fresh immutable pin plus origin-independent episode descriptor."""
    if isinstance(request, dict) and request.get('schema') == 'website-world-generation-v2':
        from . import unified_generation
        return unified_generation.prepare(request,output)
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    save(output/'request.json', request)
    before = source_files()
    try:
        result = generate(request)
    except SamplingBudgetExceeded as error:
        save(output/'sampling-audit.private.json', error.audit)
        raise
    if before != source_files():
        raise RuntimeError('Generation sources changed during sampling; refuse publication')
    pin = output/'pin'
    pin.mkdir()
    save(pin/'world.json', result['world'])
    save(pin/'manifest.json', {'schema': VERSION, 'world_id': result['world']['world_id'],
        'files': {'world.json': sha256((pin/'world.json').read_bytes()).hexdigest()},
        'current_source_sha256': before})
    for name, value in (
        ('presentation.json', result['presentation']), ('compositions.private.json', result['compositions']),
        ('reference.private.json', result['world']['reference']), ('episode.json', result['episode']),
        ('sampling-audit.private.json', result['audit']), ('surrounding.private.json', result['surrounding'])):
        save(output/name, value)
    basket_enabled = request.get('basket_shipping', {}).get('enabled', False)
    if basket_enabled:
        save(output/'basket-plan.private.json', result.get('basket_plan') or basket_quote.make_plan(result['world']))
    if 'delivery_plan' in result:save(output/'delivery-plan.private.json',result['delivery_plan'])
    if result['checkout_domain'] is not None:
        save(output/'checkout-domain.private.json', result['checkout_domain'])
    if result['order_set_task'] is not None:
        for name,value in (('order-set-task.private.json',result['order_set_task']),
            ('order-set-matching.private.json',result['order_set_matching']),
            ('order-set-reference.private.json',result['order_set_reference']),
            ('order-set-vocabulary.json',order_set_task.vocabulary())):
            save(output/name,value)
    files = {str(p.relative_to(output)): sha256(p.read_bytes()).hexdigest()
             for p in output.rglob('*') if p.is_file()}
    manifest = {'schema': VERSION, 'world_id': result['world']['world_id'], 'files': files,
        'source_sha256': before, 'summary': result['world']['summary'],
        'automatic_grader_supported': False, 'structured_order_set_grader_supported':result['order_set_task'] is not None,
        'task_kind':'native_order_set' if result['order_set_task'] is not None else 'native_individual_offer', 'model_runs': 0,
        'natural_address_difficulty': deepcopy(result['world']['provenance'].get('natural_address_difficulty')),
        'surrounding_schema': result['surrounding']['schema_version'],
        'basket_shipping': {'enabled': basket_enabled, 'origin': 'explicit_policy_fixture' if basket_enabled else None},
        'checkout_domain': deepcopy(result['checkout_domain']['options']) if result['checkout_domain'] is not None else None,
        'limitations': ['Walking shoes/sandals only; broader completed-product commerce is pending.',
            ('Basket checkout uses explicit default policies; fresh accounts/coupons are not integrated.'
             if basket_enabled else 'Quantity one; fresh-world coupon/account producer is not integrated.'),
            'All selected co-best retailers are constrained; no arbitrary tie breaker.',
            'Conjunctive finite conditions only; general relational SAT/counting is pending.',
            ('Native multi-item structured task/reference/grader; free-form answers still require manual review.'
             if result['order_set_task'] is not None else 'Producer task recipe is sampled jointly; no new task-predicate language or grader.'),
            'Natural address priors are producer-validated; no forced form examples.',
            'Time budget is checked between proposals, not a hard kill of a producer call.']}
    save(output/'manifest.json', manifest)
    return manifest


def load(output):
    output = Path(output).resolve()
    manifest = json.loads((output/'manifest.json').read_text())
    if manifest['schema'] not in (VERSION, 'website-world-generation-v2'):
        raise ValueError('Unsupported generation artifact')
    for name, expected in manifest['files'].items():
        path = (output/name).resolve()
        if not path.is_relative_to(output) or sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('Generated artifact changed: ' + name)
    for name, expected in manifest['source_sha256'].items():
        path = (ROOT/name).resolve()
        if not path.is_relative_to(ROOT) or sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('Generation source changed: ' + name)
    return manifest


def bind_task(runtime, episode, native_task=None):
    """Bind ephemeral origins at launch; never expose requirements/reference."""
    start = episode['start']
    start_url = runtime.index_origin+'/' if start['kind'] == 'directory' else runtime.origins[start['retailer_id']] + '/'
    task = runtime.world['task']
    return {'schema_version': 'connected-world-manual-v1',
        'task_id': 'generated-' + runtime.world['world_id'][:20],
        'user_message': (order_set_task.user_message(native_task) if native_task is not None else task['user_message']) + ' Inspect delivery and checkout details as needed, without completing a purchase.',
        'memories': (['My home address is '+', '.join(next(a for a in runtime.world['address_context']['addresses']
            if a['address_id']=='user-home')['display_lines'])+'.'] if native_task is not None else deepcopy(task['memories'])),
        'environment_context': {'currency': 'SEK', 'shopping_scope': 'All retailers in this generated world',
                                'scenario_date': runtime.world['quote_as_of']},
        'start_url': start_url}


class GeneratedEpisode:
    """Reusable runtime; listed-offer extraction requires an explicit backend."""
    def __init__(self, output, *, answer_extractor=None, lazy_publication=False):
        if type(lazy_publication) is not bool:
            raise ValueError('lazy_publication must be a bool')
        from .runtime import Runtime
        from intent_browser.connected_world_task import ConnectedWorldTask, public_projection
        from intent_browser.standard_profile import standard_profile
        self.output = Path(output).resolve()
        self.manifest = load(self.output)
        episode = json.loads((self.output/'episode.json').read_text())
        sidecar = self.output/'surrounding.private.json'
        self.runtime = Runtime(self.output/'pin', presentation=json.loads((self.output/'presentation.json').read_text()),
                               surrounding=json.loads(sidecar.read_text()) if sidecar.exists() else None,
                               basket_plan=json.loads((self.output/'basket-plan.private.json').read_text())
                               if (self.output/'basket-plan.private.json').exists() else None,
                               checkout_domain=json.loads((self.output/'checkout-domain.private.json').read_text())
                               if (self.output/'checkout-domain.private.json').exists() else None,
                               delivery_plan=json.loads((self.output/'delivery-plan.private.json').read_text())
                               if (self.output/'delivery-plan.private.json').exists() else None,
                               discovery_mode='tool' if episode['start']['kind'] == 'tool_discovery' else 'index',
                               readable_origins=episode.get('readable_origins', False),
                               lazy_publication=lazy_publication)
        try:
            expected = json.loads((self.output/'compositions.private.json').read_text())
            if expected != self.runtime.compositions:
                raise ValueError('Runtime composition differs from sampled plans')
            task_path=self.output/'order-set-task.private.json'
            self.order_set_task=json.loads(task_path.read_text()) if task_path.exists() else None
            if self.manifest['schema'] == 'website-world-generation-v2':
                from .unified_generation import bind_task as catalog_task
                self.public=public_projection(catalog_task(self.runtime,episode))
            else:
                self.public = public_projection(bind_task(self.runtime, episode, self.order_set_task))
            self.profile = standard_profile(navigation_origins=self.runtime.navigation_origins, helpers=False)
            self.site_discovery = None
            if episode['start']['kind'] == 'tool_discovery':
                from intent_browser.harness import with_site_discovery
                self.profile = with_site_discovery(self.profile)
                self.site_discovery = self.runtime.site_discovery.search
            reference = str(self.output/('order-set-reference.private.json' if self.order_set_task is not None else 'reference.private.json'))
            catalog_episode=self.manifest['schema']=='website-world-generation-v2'
            files = {} if catalog_episode else {reference: sha256(Path(reference).read_bytes()).hexdigest()}
            files.update({str(self.output/name): expected for name, expected in self.manifest['files'].items()})
            files.update({str(ROOT/name): expected for name, expected in self.manifest['source_sha256'].items()})
            runtime = self.runtime
            self.answer_grader = None
            basic_path = self.output/'basic-offer-task.private.json'
            task_base, grading_options = ConnectedWorldTask, {}
            if catalog_episode and basic_path.exists():
                from .listed_offer_grading import ListedOfferGrader
                from intent_browser.graded_world_task import GradedWorldTask
                self.answer_grader = ListedOfferGrader(runtime.world,
                    json.loads(basic_path.read_text()),
                    json.loads((self.output/'basic-offer-reference.private.json').read_text()),
                    runtime.bindings, surrounding=json.loads(sidecar.read_text()) if sidecar.exists() else None)
                task_base = GradedWorldTask
                grading_options = {'answer_grader': self.answer_grader,
                                   'answer_extractor': answer_extractor}
            elif answer_extractor is not None:
                raise ValueError('Answer extractor configured for an unsupported generated task')
            class NativeWorldTask(task_base):
                supports_observation_pipeline = 'native_full_only'

                def make_env(self, video=None):
                    env = super().make_env(video)
                    if runtime.origin_map is not None:
                        from browsergym.core.task import OpenEndedTask
                        class LocalWorldStart(OpenEndedTask):
                            def setup(self, page):
                                runtime.attach_browser(page.context)
                                return super().setup(page)
                        env.unwrapped.task_entrypoint = LocalWorldStart
                    return env

                def prepare(self, trace):
                    result = super().prepare(trace)
                    if runtime.origin_map is not None:
                        from intent_browser.trace import write_json
                        name = 'site-origins.private.json'
                        write_json(trace.directory/'manual-review-private'/name, runtime.origin_map.descriptor)
                        result['logical_origins_private_artifact'] = 'manual-review-private/' + name
                        result['private_attachment_sha256'][name] = sha256(
                            (trace.directory/'manual-review-private'/name).read_bytes()).hexdigest()
                    return result
            self.task = NativeWorldTask(self.public, origins=self.runtime.navigation_origins,
                files=files, attachments={} if catalog_episode else {'reference.private.json': reference},
                profile_name=self.profile.name, **grading_options)
        except BaseException:
            self.runtime.close()
            raise

    def export_private_runtime(self, output):
        output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
        for name,value in (('runtime.private.json',self.runtime.manifest),('bindings.private.json',self.runtime.bindings),
            ('task.public.json',self.public)):
            save(output/name,value)
        manifest={'schema_version':'website-accepted-catalog-runtime-binding-v1' if self.manifest['schema']=='website-world-generation-v2' else 'website-order-set-runtime-binding-v1','world_id':self.runtime.world['world_id'],
            'generation_manifest_sha256':sha256((self.output/'manifest.json').read_bytes()).hexdigest(),
            'files':{p.name:sha256(p.read_bytes()).hexdigest() for p in output.iterdir() if p.is_file()},
            'model_runs':0,'purchases':0}
        save(output/'manifest.json',manifest)
        return manifest

    def grade_structured(self, response):
        if self.order_set_task is None:
            return {'verdict':'inconclusive','reason':'No native order-set task in this episode'}
        return order_set_grader.grade(self.runtime.world,self.order_set_task,response,
            reference=json.loads((self.output/'order-set-reference.private.json').read_text()),
            plan=self.runtime.baskets.plan,domain=self.runtime.baskets.domain,
            url_bindings=self.runtime.bindings,admission_plan=self.runtime.delivery_plan)

    def grade_answer_claims(self, claims, final_answer):
        """Inference-free listed-offer grading; claims must be answer-grounded."""
        if self.answer_grader is None:
            raise ValueError('No supported native listed-offer task in this episode')
        return self.answer_grader.grade(claims, final_answer)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.runtime.close()
