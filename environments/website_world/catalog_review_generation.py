"""Additive source-bound review task over unchanged accepted catalog sampling."""
from copy import deepcopy
from . import catalog_review_task as native, unified_generation

VERSION = 'website-catalog-review-generation-v1'


def compile_request(request):
    if type(request) is not dict or request.get('schema') != unified_generation.VERSION:
        raise ValueError('Declare a unified accepted-catalog request')
    spec = request.get('task')
    if type(spec) is not dict or spec.get('kind') != native.KIND: raise ValueError('Declare a review summary task')
    inventory = native.ReviewInventory(spec.get('concept_id'))
    proxy = deepcopy(request); proxy['task'] = {'user_message':'Browse the generated review publications. Do not place an order.','memories':[]}
    world = proxy.setdefault('world',{})
    if type(world) is not dict: raise ValueError('World options must be an object')
    world.setdefault('tasks',[inventory.concept_id])
    config = unified_generation.compile_request(proxy)
    selection = native.resolve(spec,inventory=inventory,concept_ids=config['world']['concept_ids'])
    if not config['surrounding_options']['enabled'] or config['surrounding_options']['review_count'] == 0:
        raise ValueError('Enable a real review publication before sampling')
    return {'proxy_request':proxy,'selection':selection,'inventory':inventory}


def generate(request,*,world_factory=None):
    config = compile_request(request)
    result = unified_generation.generate(config['proxy_request'],world_factory=world_factory)
    spec = config['selection']
    products = sorted((p['public'] for p in result['world']['products'] if p['public']['concept_id']==spec['concept_id']),key=lambda p:p['product_id'])
    if spec['product_index'] >= len(products) or spec['subject_scope']=='sku' and spec['sku_index'] >= len(products[spec['product_index']]['skus']):
        result['review_task_binding'] = {'status':'unsupported_no_manufactured_subject','world_repaired':False}
        result['catalog_review_task'] = result['catalog_review_reference'] = None
    else:
        task = native.make(result['world'],spec,inventory=config['inventory'])
        reference = native.reference(result['world'],task,inventory=config['inventory'])
        covered = [s['site_id'] for s in result['surrounding']['sites'] if s['kind']=='product_reviews' and task['subject']['product_id'] in s['product_ids']]
        result.update(catalog_review_task=task,catalog_review_reference=reference,
            review_task_binding={'status':'bound' if covered else 'unsupported_no_review_publication','publication_ids':covered,'world_repaired':False})
        result['episode'].update(task_id=task['task_id'],manual_task={'user_message':task['user_message'],'memories':task['memories']})
    result['resolved_configuration'].update(request=deepcopy(request),task=deepcopy(spec))
    result['audit']['proxy_request_sha256'] = result['audit']['request_sha256']
    result['audit']['request_sha256'] = unified_generation.shared.digest(request)
    return result
