"""Model-scoped factual comparison, independent of price and availability ranking."""
from copy import deepcopy

from .adapter import digest
from .catalog_predicates import PredicateSet, SCALAR, _lookup, _same
from .catalog_priority_task import _measurement_scope
from experiments import source_binding

VERSION = 'website-catalog-comparison-task-v1'
KIND = 'compare_product_facts'


def _probe(field, definition):
    sentinels = [*definition.get('unknown_values', []),
                 *definition.get('not_applicable_values', [])]
    typ = definition['type']
    if typ == 'boolean':
        values = [False, True]
    elif typ == 'enum':
        values = definition['values']
    elif typ == 'string':
        values = [definition.get('constant', '__observation__'),
                  *['__observation__'+str(i) for i in range(len(sentinels)+1)]]
    else:
        values = range(len(sentinels)+1)
    value = next((v for v in values if not any(_same(v, s) for s in sentinels)), None)
    if value is None:
        raise ValueError('No ordinary scalar value in the requested field declaration')
    return {'field': field, 'operator': 'ne', 'value': value,
            **({'unit': definition['unit']} if 'unit' in definition else {})}


def resolve(spec, *, inventory, concept_ids):
    if (type(spec) is not dict or set(spec)-{'kind', 'concept_id', 'fields', 'model_limit'}
            or not {'kind', 'concept_id', 'fields'} <= set(spec)
            or spec['kind'] != KIND or spec['concept_id'] != inventory.concept_id
            or spec['concept_id'] not in concept_ids):
        raise ValueError('Declare a comparison concept, fields and optional model_limit')
    limit = spec.get('model_limit', 2)
    fields = spec['fields']
    if type(limit) is not int or not 2 <= limit <= 4:
        raise ValueError('Compare up to two to four manufactured models')
    if (type(fields) is not list or not 1 <= len(fields) <= 5
            or any(type(f) is not str for f in fields) or len(set(fields)) != len(fields)):
        raise ValueError('Declare one to five unique public scalar fact paths')
    for field in fields:
        if (not field.startswith('product.facts.') or field not in inventory.fields
                or inventory.fields[field]['type'] not in SCALAR):
            raise ValueError('Comparison requires public model facts, not SKU, private or collection paths')
        definition = inventory.fields[field]
        PredicateSet(inventory.fields, [_probe(field, definition)], known_paths=inventory.known_paths)
        _measurement_scope(field, inventory)
    return {'kind': KIND, 'concept_id': inventory.concept_id,
            'fields': deepcopy(fields), 'model_limit': limit}


def make(world, spec, *, inventory):
    inventory.check_sources()
    selection = resolve(spec, inventory=inventory, concept_ids=world['config']['concept_ids'])
    carried = {o['product_id'] for r in world['retailers'] for o in r['offers']}
    products = {p['public']['product_id']: p['public'] for p in world['products']
                if p['public']['concept_id'] == selection['concept_id']
                and p['public']['product_id'] in carried}
    # Fixed keyed order reads only seed/concept/identity. Neither sampled facts,
    # prices nor stock help choose the comparison's named models.
    ids = sorted(products, key=lambda pid: (digest([VERSION, world['seed'],
        selection['concept_id'], 'model', pid]), pid))[:selection['model_limit']]
    models = [{'product_id': pid, 'name': products[pid]['name']} for pid in ids]
    definitions = {field: deepcopy(inventory.fields[field]) for field in selection['fields']}
    scopes = {field: scope for field in definitions
              if (scope := _measurement_scope(field, inventory)) is not None}
    labels = []
    for field, definition in definitions.items():
        label = field.removeprefix('product.facts.').replace('_', ' ')
        if 'unit' in definition:
            label += ' in '+definition['unit']
        if field in scopes:
            label += ' ('+scopes[field]['basis']+')'
        labels.append(label)
    message = ('Compare these manufactured product models: '+
        ', '.join(m['name'] for m in models)+'. ' if models else
        'Report that this generated catalog carries no models for the requested comparison. ')
    message += ('For each named model, report '+ '; '.join(labels)+'. '
        'Give exactly one row per named model and cite an exact retailer product page. '
        'Report known values literally with their declared units and measurement basis; '
        'distinguish unknown/not specified from not applicable. Do not invent missing values. '
        'These are model facts, so no specific size or colour selection is required. '
        'Models do not have to be in stock. Do not rank by price or purchase anything. '
        'If you cannot determine a requested fact, state that uncertainty; do not treat it '
        'as a false property. Broader explanation quality and browsing coverage are ungraded.')
    task = {'schema_version': VERSION, **selection, 'world_id': world['world_id'],
        'world_sha256': digest(world), 'models': models,
        'field_declarations': definitions, 'measurement_scopes': scopes,
        'field_source_sha256': deepcopy(inventory.source_hashes),
        'known_scalar_paths': sorted(set(definitions)&set(inventory.known_paths)),
        'population': 'carried_manufactured_models_regardless_stock_or_price',
        'user_message': message, 'memories': []}
    task['task_id'] = 'catalog-comparison-'+digest(task)[:24]
    return task


def reference(world, task, *, inventory):
    spec = {k: deepcopy(task[k]) for k in ('kind', 'concept_id', 'fields', 'model_limit')}
    if not source_binding.compatible(task, make(world, spec, inventory=inventory)):
        raise ValueError('Comparison task/world/declaration binding changed')
    products = {p['public']['product_id']: p for p in world['products']}
    probes = {field: PredicateSet(inventory.fields, [_probe(field, definition)],
        known_paths=task['known_scalar_paths']) for field, definition in task['field_declarations'].items()}
    rows = []
    for model in task['models']:
        item = products[model['product_id']]
        product = item['public']
        sku = product['skus'][0]  # Identity support only; requested facts are model-scoped.
        facts = {}
        for field, probe in probes.items():
            observation = probe.evaluate(product, sku, catalog_status=item.get('catalog_status', {}),
                sku_status=item.get('sku_status', {}).get(sku['sku_id'], {}))['predicates'][0]
            facts[field] = {'status': observation['status'],
                'value': deepcopy(_lookup({'product': product}, field))
                    if observation['status'] == 'known' else None,
                'unit': task['field_declarations'][field].get('unit'),
                'basis': task['measurement_scopes'].get(field, {}).get('basis')}
        rows.append({**deepcopy(model), 'facts': facts})
    return {'schema_version': VERSION, 'task_id': task['task_id'], 'world_id': world['world_id'],
        'status': 'comparison' if rows else 'no_models', 'models': rows,
        'grain': 'manufactured_product_model', 'selection': task['population'],
        'evidence_coverage': 'not_inferred_from_native_truth'}
