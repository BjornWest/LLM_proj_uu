"""Explicit lexicographic numeric feature priorities, without invented utility."""
from copy import deepcopy
from decimal import Decimal

from . import feature_offer_task as feature
from .adapter import digest
from .catalog_predicates import PredicateSet, _lookup

VERSION = 'website-catalog-priority-task-v2'
KIND = 'recommend_matching_by_priorities'

# Explicit semantic relationship from the pilot declaration, not a naming
# heuristic or an observation of the selected SKU's physical weight.
BASIS_FIELDS = {'product.facts.reference_mass_g': 'product.facts.mass_basis'}


def _measurement_scope(field, inventory):
    definition = inventory.fields[field]
    if 'basis' in definition:
        basis = definition['basis']
        if type(basis) is not str or not basis.strip():
            raise ValueError('Priority measurement basis must be explicit text')
        return {'basis': basis, 'origin': 'numeric_field_declaration'}
    basis_field = BASIS_FIELDS.get(field)
    if basis_field is None:
        return None
    declared = inventory.fields.get(basis_field)
    if declared is None:
        # Pruning can omit a constant from shopper-facing feature choices while
        # retaining it as the semantic scope of a numeric measurement. Load the
        # already pinned declaration once, without widening the public inventory.
        cache = getattr(inventory, '_measurement_basis_declarations', None)
        if cache is None:
            inventory.check_sources()
            directory = 'product_packages' if inventory.concept_id in feature.package_export.PILOTS else 'product_width'
            path = 'environments/product_world/data/'+directory+'/'+inventory.concept_id+'.json'
            if path not in inventory.source_hashes:
                raise ValueError('Measurement basis needs a pinned concept declaration')
            document = feature.load_document(feature.ROOT/path)
            inventory.check_sources()
            cache = {path: deepcopy(document['fields'].get(path, {}))
                     for path in BASIS_FIELDS.values()}
            inventory._measurement_basis_declarations = cache
        declared = cache.get(basis_field, {})
    basis = declared.get('constant')
    if declared.get('type') != 'string' or type(basis) is not str or not basis.strip():
        raise ValueError('Reference mass needs its declared constant measurement basis')
    return {'basis': basis, 'origin': 'registered_constant_field',
            'field': basis_field, 'declaration': deepcopy(declared)}


def _inner(spec):
    return {**{k:deepcopy(v) for k,v in spec.items() if k != 'priorities'},'kind':feature.KIND}


def _probe(priority, definition):
    # Evaluate status/type using the shared evaluator; the comparison's boolean
    # result is not an eligibility filter. Any typed nonsentinel operand suffices.
    value = 0
    sentinels = [*definition.get('unknown_values',[]),*definition.get('not_applicable_values',[])]
    while value in sentinels: value += 1
    return {'field':priority['field'],'operator':'ne','value':value,
            **({'unit':priority['unit']} if 'unit' in priority else {})}


def resolve(spec, *, inventory, concept_ids):
    if type(spec) is not dict or spec.get('kind') != KIND:
        raise ValueError('Declare a feature-priority recommendation')
    inner = feature.resolve(_inner(spec),inventory=inventory,concept_ids=concept_ids)
    rows = spec.get('priorities')
    if type(rows) is not list or not 1 <= len(rows) <= 3:
        raise ValueError('Declare one to three ordered numeric feature priorities')
    fields,normalized = set(),[]
    for row in rows:
        if (type(row) is not dict or set(row)-{'field','direction','unit'}
                or not {'field','direction'} <= set(row) or type(row['field']) is not str
                or row['field'] not in inventory.fields or row['field'] in fields
                or row['direction'] not in ('min','max')):
            raise ValueError('Each priority declares one unique public numeric field and min/max')
        definition = inventory.fields[row['field']]
        if definition['type'] not in ('integer','number') or row.get('unit') != definition.get('unit'):
            raise ValueError('Priorities need numeric fields and exact declared units')
        PredicateSet(inventory.fields,[_probe(row,definition)],known_paths=inventory.known_paths)
        _measurement_scope(row['field'], inventory)
        fields.add(row['field']);normalized.append(deepcopy(row))
    return {**inner,'kind':KIND,'priorities':normalized}


def make(world, spec, *, inventory, surrounding=None):
    selection = resolve(spec,inventory=inventory,concept_ids=world['config']['concept_ids'])
    inner = feature.make(world,_inner(selection),inventory=inventory,surrounding=surrounding)
    message = inner['user_message'].replace('Find the cheapest available','Find a matching available',1)
    message += (' Rank qualifying options by these feature priorities in order; '
        'an earlier priority always takes precedence over every later one. ')
    definitions, scopes = {}, {}
    for row in selection['priorities']:
        d = inventory.fields[row['field']];definitions[row['field']] = deepcopy(d)
        scope = _measurement_scope(row['field'], inventory)
        if scope is not None:
            scopes[row['field']] = scope
        name = row['field'].removeprefix('product.facts.').removeprefix('sku.').replace('_',' ')
        message += ('Minimize ' if row['direction']=='min' else 'Maximize ')+name
        message += (' in '+d['unit'] if 'unit' in d else '')
        message += (' ('+scope['basis']+')' if scope is not None else '')+'. '
    message += ('Only after all these feature values tie, use the lowest listed whole-sale-unit SEK price. '
        'All prioritized features must be known and applicable; unknown/NA values cannot establish '
        'a ranked match. Do not substitute a weighted compromise or infer an unknown feature. '
        'Report the model, retailer, explicit variant, exact retailer product link and listed price. '
        'If no available option establishes both the requirements and prioritized features, say so. '
        'Do not place an order. Shipping, coupons and explanation quality are outside this recommendation.')
    task = {'schema_version':VERSION,**selection,'world_id':world['world_id'],
        'world_sha256':digest(world),'feature_task':inner,'priority_field_declarations':definitions,
        'priority_measurement_scopes': scopes,
        'priority_known_scalar_paths':sorted(set(definitions)&set(inventory.known_paths)),
        'ranking':'declared_numeric_priorities_lexicographic_then_listed_price',
        'tie_policy':'all_equal_priority_values_and_listed_price',
        'user_message':message,'memories':[]}
    task['task_id'] = 'catalog-priority-'+digest(task)[:24]
    return task


def reference(world, task, *, inventory, surrounding=None):
    spec = {k:deepcopy(task[k]) for k in ('kind','concept_id','predicates','availability',
        'max_price_minor','comparison_site_id','priorities') if k in task}
    if task != make(world,spec,inventory=inventory,surrounding=surrounding):
        raise ValueError('Priority task/world/declaration binding changed')
    inner = feature.reference(world,task['feature_task'],inventory=inventory,surrounding=surrounding)
    probes = [PredicateSet(inventory.fields,[_probe(p,inventory.fields[p['field']])],
        known_paths=task['priority_known_scalar_paths']) for p in task['priorities']]
    products = {p['public']['product_id']:p for p in world['products']}
    states,values = {},{}
    for item in products.values():
        product = item['public']
        if product['concept_id'] != task['concept_id']:continue
        for sku in product['skus']:
            observations = [probe.evaluate(product,sku,catalog_status=item.get('catalog_status',{}),
                sku_status=item.get('sku_status',{}).get(sku['sku_id'],{}))['predicates'][0] for probe in probes]
            states[sku['sku_id']] = observations
            if all(r['status']=='known' for r in observations):
                values[sku['sku_id']] = [_lookup({'product':product,'sku':sku},p['field']) for p in task['priorities']]
    candidates = [{**deepcopy(r),'priority_values':deepcopy(values[r['sku_id']])}
        for r in inner['candidates'] if r['sku_id'] in values]
    def key(row):
        return (*[Decimal(str(v))*(1 if p['direction']=='min' else -1)
            for v,p in zip(row['priority_values'],task['priorities'],strict=True)],row['price_minor'])
    candidates.sort(key=lambda r:(key(r),r['offer_id']))
    best = key(candidates[0]) if candidates else None
    return {'schema_version':VERSION,'task_id':task['task_id'],'world_id':world['world_id'],
        'status':'match' if candidates else 'no_match','candidates':candidates,
        'winners':[r for r in candidates if key(r)==best],
        'best_priority_values':deepcopy(candidates[0]['priority_values']) if candidates else None,
        'tie_price_minor':candidates[0]['price_minor'] if candidates else None,
        'priority_evaluations':states,'feature_reference':inner,'ranking':task['ranking'],
        'evidence_coverage':'not_inferred_from_native_truth'}
