"""Feature-task winner conditioning through the existing finite mass sampler.

This additive caller binds the already released feature reference before each
proposal's acceptance test. It never adds that reference to the sampled world,
patches module globals, repairs a population, or labels public exposure as known.
"""
from copy import deepcopy
from types import SimpleNamespace

from experiments.accepted_catalog_commerce.execution import _bind
from . import feature_offer_generation, feature_offer_task, requirements, unified_generation
from .adapter import digest

VERSION = 'website-conditioned-feature-generation-v1'


def compile_request(request):
    # Remove only the conditions while the ordinary feature compiler validates
    # world/task/options. Revalidate the complete conjunction below, including
    # the two reference selectors not supported by the old unified caller.
    if type(request) is not dict:
        raise ValueError('Declare a feature generation request')
    proxy = deepcopy(request)
    declared = proxy.pop('requirements', [])
    prepared = feature_offer_generation.compile_request(proxy)
    config = unified_generation.compile_request(prepared['proxy_request'])
    compiled = requirements.validate(declared, config['priors'], config['resets'],
        config['policies'], variation_priors=config['variation_priors'],
        delivery_options=config['delivery_options'])
    config['requirements'] = compiled
    return {'selection': prepared['selection'], 'inventory': prepared['inventory'],
            'proxy_request': prepared['proxy_request'], 'configuration': config}


def completion(world, config, *, home_delivery_checker=None):
    """Compute one full conjunction, including intersecting ordinary selectors."""
    c = config['configuration']
    # Comparison membership is deterministic world content. Its generation
    # precedes reference evaluation, independently of presentation restrictions.
    surrounding = unified_generation.surrounding_config._generate_bound(
        world, c['surrounding_options'], digest(world))
    task = feature_offer_task.make(world, config['selection'],
        inventory=config['inventory'], surrounding=surrounding)
    reference = feature_offer_task.reference(world, task,
        inventory=config['inventory'], surrounding=surrounding)
    view = {**world, 'reference': reference}

    def home_checker(unused_view, retailer, selector_kind):
        checker = home_delivery_checker or unified_generation.initial_home_delivery_available
        if selector_kind != 'best_matching_retailers':
            return checker(world, retailer, selector_kind)
        # Preserve the older winner-selector meaning: every winning SKU at the
        # targeted retailer must have home delivery to its naturally saved form.
        winner_ids = {r['offer_id'] for r in reference['winners']
                      if r['retailer_id'] == retailer['retailer_id']}
        offers = [o for o in retailer['offers'] if o['offer_id'] in winner_ids]
        return bool(offers) and all(checker(world, {**retailer, 'offers': [offer]},
                                           selector_kind) for offer in offers)

    result = requirements.evaluate(view, c['requirements'], c['priors'], c['resets'],
        c['policies'], home_delivery_checker=home_checker,
        variation_priors=c['variation_priors'], delivery_options=c['delivery_options'])
    return result, task, reference, surrounding


def generate(request, *, world_factory=None):
    config = compile_request(request)
    last = {}

    def evaluate(world, compiled, priors, resets=None, policies=None, **kwargs):
        # These are the exact configuration arguments supplied by the retained
        # unified generation body, not a second independently sampled stage.
        expected = config['configuration']
        if (compiled != expected['requirements'] or priors != expected['priors'] or
                resets != expected['resets'] or policies != expected['policies'] or
                kwargs.get('variation_priors') != expected['variation_priors'] or
                kwargs.get('delivery_options') != expected['delivery_options']):
            raise ValueError('Conditioning configuration changed during generation')
        result, task, reference, surrounding = completion(world, config,
            home_delivery_checker=kwargs.get('home_delivery_checker'))
        last.clear()
        last.update(world=world, task=task, reference=reference, surrounding=surrounding)
        return result

    # Clone one existing producer function's namespace. All sampling, proposal
    # budgets, envelope checks, rejection RNG and page-plan construction remain
    # its unchanged body. No process-wide monkeypatch or separate rejection loop.
    produce = _bind(unified_generation.generate,
        compile_request=lambda unused: deepcopy(config['configuration']),
        requirements=SimpleNamespace(log_upper_bound=requirements.log_upper_bound,
                                     evaluate=evaluate))
    result = produce(config['proxy_request'], world_factory=world_factory)
    if last.get('world') is not result['world'] or last['surrounding'] != result['surrounding']:
        raise ValueError('Accepted proposal/reference/surrounding binding differs')
    task, reference = last['task'], last['reference']
    result.update(feature_offer_task=task, feature_offer_reference=reference,
                  feature_offer_request=deepcopy(request))
    result['resolved_configuration'].update(request=deepcopy(request),
                                            task=deepcopy(config['selection']))
    result['audit']['proxy_request_sha256'] = result['audit']['request_sha256']
    result['audit'].update(request_sha256=digest(request),
        task_conditioning={'version': VERSION, 'task_id': task['task_id'],
            'reference_sha256': digest(reference),
            'selectors': [deepcopy(r['target']) for r in config['configuration']['requirements']],
            'world_reference_added_to_world': False,
            'qualification': 'Finite presentation conjunction and declared reference predicates; no generic SAT or public-evidence guarantee.'})
    result['episode'].update(task_id=task['task_id'], manual_task={
        'user_message': task['user_message'], 'memories': task['memories']})
    return result
