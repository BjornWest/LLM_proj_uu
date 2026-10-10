"""Predeclare one topic passage; preserve the ordinary catalog population draw."""
from copy import deepcopy

from . import unified_generation, review_passage_task as native
from .catalog_review_task import ReviewInventory
from .native_review_ecosystem import VERSION as REVIEW_ROUTES

VERSION = 'website-review-passage-generation-v1'


def compile_request(request):
    if type(request) is not dict or request.get('schema') != unified_generation.VERSION:
        raise ValueError('Declare a unified accepted-catalog request')
    spec = request.get('task')
    if type(spec) is not dict or spec.get('kind') != native.KIND:
        raise ValueError('Declare one customer-review passage task')
    inventory = ReviewInventory(spec.get('concept_id'))
    # This public text is authored, rather than a generated coaching template.
    # The actual instance suitability gate still checks its bound subject/topic.
    proxy = deepcopy(request)
    proxy['task'] = {'user_message': spec.get('public_request'), 'memories': []}
    world = proxy.setdefault('world', {})
    if type(world) is not dict:
        raise ValueError('World options must be an object')
    world.setdefault('tasks', [inventory.concept_id])
    config = unified_generation.compile_request(proxy)
    selection = native.resolve(spec, inventory=inventory, concept_ids=config['world']['concept_ids'])
    surrounding = config['surrounding_options']
    if not surrounding['enabled'] or not surrounding['review_count'] or surrounding['version'] != REVIEW_ROUTES:
        raise ValueError('Enable native v3 reader-note publication before sampling')
    return {'proxy_request': proxy, 'selection': selection, 'inventory': inventory}


def generate(request, *, world_factory=None):
    config = compile_request(request)
    result = unified_generation.generate(config['proxy_request'], world_factory=world_factory)
    spec = config['selection']
    products = sorted((p['public'] for p in result['world']['products']
        if p['public']['concept_id'] == spec['concept_id']), key=lambda p: p['product_id'])
    task = reference = None
    binding = {'status': 'unsupported_no_manufactured_subject', 'world_repaired': False}
    if spec['product_index'] < len(products):
        task = native.make(result['world'], spec, inventory=config['inventory'])
        reference = native.reference(result['world'], task, inventory=config['inventory'])
        covered = [s['site_id'] for s in result['surrounding']['sites']
            if s['kind'] == 'product_reviews' and task['subject']['product_id'] in s['product_ids']]
        binding = {'status': 'bound' if covered else 'unsupported_no_review_publication',
            'publication_ids': covered, 'world_repaired': False}
    result.update(review_passage_task=task, review_passage_reference=reference,
                  review_passage_binding=binding)
    result['episode'].update(task_id=task['task_id'] if task else None,
        manual_task={'user_message': task['user_message'], 'memories': task['memories']}
                    if binding['status'] == 'bound' else None)
    result['resolved_configuration'].update(request=deepcopy(request), task=deepcopy(spec))
    result['audit']['proxy_request_sha256'] = result['audit']['request_sha256']
    result['audit']['request_sha256'] = unified_generation.shared.digest(request)
    return result
