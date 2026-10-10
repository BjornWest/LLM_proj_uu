"""Predeclared cart preparation on the unchanged ordinary catalog population."""
from copy import deepcopy

from . import catalog_basket_generation as basket_generation, catalog_cart_task as native

VERSION = 'website-catalog-cart-generation-v1'


def compile_request(request):
    if type(request) is not dict or type(request.get('task')) is not dict or 'basket_search' in request:
        raise ValueError('Declare a cart task; this contract does not optimize prices')
    spec = request['task']
    if (spec.get('kind') != native.KIND or 'requirements' not in spec
            or set(spec) - {'kind', 'requirements', 'initial_cart'}):
        raise ValueError('Unsupported cart task notation')
    proxy = deepcopy(request)
    proxy['task'] = native._inner(spec)
    config = basket_generation.compile_request(proxy)
    selection = native.resolve(spec, concept_ids=[r['concept_id'] for r in config['selection']['requirements']],
                               inventory=config['inventory'])
    return {**config, 'selection': selection}


def generate(request, *, world_factory=None):
    config = compile_request(request)
    result = basket_generation.unified.generate(config['proxy_request'], world_factory=world_factory)
    task = native.make(result['world'], config['selection'], checkout_domain=result['checkout_domain'],
                       inventory=config['inventory'])
    reference = native.reference(result['world'], task, checkout_domain=result['checkout_domain'],
                                 inventory=config['inventory'])
    result.update(catalog_cart_task=task, catalog_cart_reference=reference,
                  catalog_cart_binding={'status': 'requires_actual_browser_state_and_effect_adoption',
                                        'world_repaired': False})
    result['episode'].update(task_id=task['task_id'],
                            manual_task={'user_message': task['user_message'], 'memories': []})
    result['resolved_configuration'].update(request=deepcopy(request), task=deepcopy(config['selection']))
    result['audit']['proxy_request_sha256'] = result['audit']['request_sha256']
    result['audit']['request_sha256'] = basket_generation.unified.shared.digest(request)
    return result
