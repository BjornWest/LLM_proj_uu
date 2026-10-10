"""Predeclare single-item quote objectives; late-bind natural address and quotes."""
from copy import deepcopy

from experiments.accepted_catalog_commerce.prepared_quote import prepare
from . import feature_offer_task, quote_offer_task, unified_generation

VERSION = 'website-single-item-quote-generation-v1'


def compile_request(request):
    if type(request) is not dict or request.get('schema') != unified_generation.VERSION:
        raise ValueError('Declare a unified accepted-catalog request')
    spec = request.get('task')
    if type(spec) is not dict or spec.get('kind') != quote_offer_task.KIND:
        raise ValueError('Declare a single-item quote task')
    inventory = feature_offer_task.FieldInventory(spec.get('concept_id'))
    proxy = deepcopy(request)
    proxy['task'] = {'user_message': 'Browse the generated retailers. Do not place an order.', 'memories': []}
    world = proxy.setdefault('world', {})
    if type(world) is not dict:
        raise ValueError('World options must be an object')
    if 'tasks' not in world:
        world['tasks'] = [inventory.concept_id]
    config = unified_generation.compile_request(proxy)
    selection = quote_offer_task.resolve(spec, inventory=inventory, concept_ids=config['world']['concept_ids'])
    if 'comparison_site_id' in selection:
        sites = config['surrounding_options']
        if not sites['enabled'] or selection['comparison_site_id'] not in {
                f'comparison-{i:02d}' for i in range(sites['comparison_count'])}:
            raise ValueError('Task comparison must be enabled before sampling')
    return {'proxy_request': proxy, 'selection': selection, 'inventory': inventory}


def generate(request, *, world_factory=None):
    config = compile_request(request)
    result = unified_generation.generate(config['proxy_request'], world_factory=world_factory)
    quotes = prepare(result['world'], plan=result['basket_plan'], admission_plan=result.get('delivery_plan'))
    task = quote_offer_task.make(result['world'], config['selection'], inventory=config['inventory'],
        quote_context=quotes, surrounding=result['surrounding'])
    reference = quote_offer_task.reference(result['world'], task, inventory=config['inventory'],
        quote_context=quotes, surrounding=result['surrounding'])
    result['quote_offer_task'], result['quote_offer_reference'] = task, reference
    result['quote_offer_request'] = deepcopy(request)
    result['resolved_configuration'].update(request=deepcopy(request), task=deepcopy(config['selection']))
    result['audit']['proxy_request_sha256'] = result['audit']['request_sha256']
    result['audit']['request_sha256'] = unified_generation.shared.digest(request)
    result['episode'].update(task_id=task['task_id'], manual_task={
        'user_message': task['user_message'], 'memories': task['memories']})
    return result
