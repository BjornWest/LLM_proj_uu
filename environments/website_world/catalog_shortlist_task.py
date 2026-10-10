"""Distinct-model enumeration/top-N using existing feature eligibility."""
from copy import deepcopy

from . import feature_offer_task as feature
from .adapter import digest

VERSION = 'website-catalog-shortlist-task-v1'
KIND = 'shortlist_matching_models'


def resolve(spec, *, inventory, concept_ids):
    if type(spec) is not dict or spec.get('kind') != KIND:
        raise ValueError('Declare a matching-model shortlist task')
    limit = spec.get('limit')
    if limit is not None and (type(limit) is not int or not 1 <= limit <= 10):
        raise ValueError('Limit must be integer1–10 or null for all models')
    inner = {k: deepcopy(v) for k, v in spec.items() if k != 'limit'}
    inner['kind'] = feature.KIND
    return {**feature.resolve(inner, inventory=inventory, concept_ids=concept_ids),
            'kind': KIND, 'limit': limit}


def _inner(selection):
    return {**{k: deepcopy(v) for k, v in selection.items() if k != 'limit'}, 'kind': feature.KIND}


def make(world, spec, *, inventory, surrounding=None):
    selection = resolve(spec, inventory=inventory, concept_ids=world['config']['concept_ids'])
    inner = feature.make(world, _inner(selection), inventory=inventory, surrounding=surrounding)
    message = inner['user_message'].replace('Find the cheapest available', 'Find available', 1)
    message += (' List all distinct qualifying manufactured models. ' if selection['limit'] is None else
                f" List the cheapest {selection['limit']} distinct qualifying manufactured models. ")
    message += ('Use each model\'s cheapest eligible matching variant/retailer listed price. '
                'Include every model tied at the last included price, even if the list exceeds the requested count. '
                'If fewer models qualify, list all of them. Different colours, sizes or retailers are not different models. '
                'Give exactly one row per model, in increasing price order, with its model and retailer names, '
                'explicit matching variant, retailer product link and listed SEK price. '
                'Do not place an order. Say no match only if no model establishes all requirements.')
    task = {'schema_version': VERSION, **selection, 'world_id': world['world_id'],
            'world_sha256': digest(world), 'feature_task': inner,
            'grain': 'manufactured_product_model', 'tie_policy': 'include_cutoff_price_ties',
            'user_message': message, 'memories': []}
    task['task_id'] = 'catalog-shortlist-' + digest(task)[:24]
    return task


def reference(world, task, *, inventory, surrounding=None):
    spec = {k: deepcopy(task[k]) for k in ('kind', 'concept_id', 'predicates', 'availability',
            'max_price_minor', 'comparison_site_id', 'limit') if k in task}
    if task != make(world, spec, inventory=inventory, surrounding=surrounding):
        raise ValueError('Shortlist task/world/declaration binding changed')
    inner = feature.reference(world, task['feature_task'], inventory=inventory, surrounding=surrounding)
    groups = {}
    for row in inner['candidates']:
        groups.setdefault(row['product_id'], []).append(deepcopy(row))
    models = []
    for pid, offers in groups.items():
        price = min(o['price_minor'] for o in offers)
        models.append({'product_id': pid, 'price_minor': price,
                       'winners': [o for o in offers if o['price_minor'] == price]})
    models.sort(key=lambda m: (m['price_minor'], m['product_id']))
    limit = task['limit']
    cutoff = models[min(limit, len(models))-1]['price_minor'] if limit is not None and models else None
    selected = [m for m in models if cutoff is None or m['price_minor'] <= cutoff]
    return {'schema_version': VERSION, 'task_id': task['task_id'], 'world_id': world['world_id'],
            'status': 'match' if models else 'no_match', 'population_count': len(models),
            'cutoff_price_minor': cutoff, 'selected_models': selected, 'all_models': models,
            'feature_reference': inner, 'grain': task['grain'], 'tie_policy': task['tie_policy'],
            'evidence_coverage': 'not_inferred_from_native_truth'}
