"""A bounded conjunction of existing model-fact and review-summary contracts."""
from copy import deepcopy

from .adapter import digest
from . import catalog_comparison_task as comparison, catalog_review_task as reviews
from experiments import source_binding

VERSION = 'website-catalog-compare-review-task-v1'
KIND = 'compare_facts_and_reviews'


def resolve(spec, *, inventory, review_inventory, concept_ids):
    if (type(spec) is not dict or set(spec) != {'kind', 'concept_id', 'fields', 'review'}
            or spec['kind'] != KIND or spec['concept_id'] != inventory.concept_id
            or review_inventory.concept_id != inventory.concept_id
            or type(spec['fields']) is not list or not 3 <= len(spec['fields']) <= 5
            or type(spec['review']) is not dict or 'operation' not in spec['review']
            or set(spec['review']) - {'operation', 'topic', 'min_assessed'}):
        raise ValueError('Declare one concept, three to five model facts and an existing review operation')
    compared = comparison.resolve({'kind': comparison.KIND, 'concept_id': spec['concept_id'],
        'fields': spec['fields'], 'model_limit': 2}, inventory=inventory, concept_ids=concept_ids)
    reviewed = reviews.resolve({'kind': reviews.KIND, 'concept_id': spec['concept_id'],
        'subject_scope': 'product', **deepcopy(spec['review'])},
        inventory=review_inventory, concept_ids=concept_ids)
    return {'kind': KIND, 'concept_id': spec['concept_id'], 'fields': compared['fields'],
        'review': {k: deepcopy(reviewed[k]) for k in ('operation', 'topic', 'min_assessed') if k in reviewed}}


def make(world, spec, *, inventory, review_inventory):
    spec = resolve(spec, inventory=inventory, review_inventory=review_inventory,
                   concept_ids=world['config']['concept_ids'])
    compared = comparison.make(world, {'kind': comparison.KIND,
        'concept_id': spec['concept_id'], 'fields': deepcopy(spec['fields']), 'model_limit': 2}, inventory=inventory)
    if len(compared['models']) != 2:
        raise ValueError('This instrumentation task requires two carried manufactured models')
    # Preserve comparison's keyed model order. Review selectors are identity
    # indices in its own existing native population, never outcome-based picks.
    ids = sorted(p['public']['product_id'] for p in world['products']
                 if p['public']['concept_id'] == spec['concept_id'])
    review_tasks = {}
    obligations = []
    for n, model in enumerate(compared['models'], 1):
        role = 'model_' + str(n)
        review = reviews.make(world, {'kind': reviews.KIND, 'concept_id': spec['concept_id'],
            'subject_scope': 'product', 'product_index': ids.index(model['product_id']),
            **deepcopy(spec['review'])}, inventory=review_inventory)
        if review['subject']['product_id'] != model['product_id']:
            raise ValueError('Review identity index differs from comparison model')
        review_tasks[role] = review
        for field in compared['fields']:
            obligations.append({'role_id': role + '.fact.' + field,
                'product_id': model['product_id'], 'grain': 'manufactured_product_model',
                'source_family': 'retailer', 'field': field,
                'unit': compared['field_declarations'][field].get('unit'),
                'basis': compared['measurement_scopes'].get(field, {}).get('basis'),
                'status_policy': 'known_unknown_not_applicable_are_distinct'})
        paths = (['summary.rating_count', 'summary.written_review_count', 'summary.rating_only_count',
                  *['summary.star_counts.' + str(k) for k in range(1, 6)], 'summary.mean_rounded']
                 if review['operation'] == 'rating_summary' else
                 ['counts.' + k for k in reviews.COUNTS] + ['written_review_count', 'assessed_count', 'verdict'])
        for field in paths:
            obligations.append({'role_id': role + '.review.' + field,
                'product_id': model['product_id'], 'grain': 'canonical_review_corpus',
                'source_family': 'product_reviews', 'field': field,
                'operation': review['operation'], 'topic': deepcopy(review.get('topic'))})
    task = {'schema_version': VERSION, 'kind': KIND, 'spec': deepcopy(spec),
        'concept_id': spec['concept_id'], 'world_id': world['world_id'], 'world_sha256': digest(world),
        'comparison_task': compared, 'review_tasks': review_tasks,
        'required_obligations': obligations, 'memories': [],
        'user_message': 'Complete both parts for the same two named models. Use retailer product pages '
            'for the factual comparison and independent product-review pages for the review summaries.\n\n'
            + compared['user_message'] + '\n\n' + '\n\n'.join(t['user_message'] for t in review_tasks.values())}
    task['task_id'] = 'catalog-compare-review-' + digest(task)[:24]
    return task


def reference(world, task, *, inventory, review_inventory):
    if not source_binding.compatible(task, make(world, task['spec'], inventory=inventory, review_inventory=review_inventory)):
        raise ValueError('Compound task/world/declaration/subject binding changed')
    return {'schema_version': VERSION, 'task_id': task['task_id'], 'world_sha256': task['world_sha256'],
        'comparison': comparison.reference(world, task['comparison_task'], inventory=inventory),
        'reviews': {role: reviews.reference(world, t, inventory=review_inventory)
                    for role, t in task['review_tasks'].items()},
        'completion': 'all_comparison_and_same_model_review_requirements',
        'exposure': 'not_inferred_from_correct_answer_or_citation'}
