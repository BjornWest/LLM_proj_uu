"""Prepared native feature-task semantics and unfiltered scoped source inventory.

Runtime acceptance is packet-specific; bare compilation remains preparation.
Native declarations/statuses are never promoted to public disclosure or exposure.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from .fact_exposure import object_digest, require
from .task_requirements import (
    VERSION, FEATURE_TASK, LISTED_TASK, _supported, _identifier, _hash,
    _validate_graph, input_node, predicate_node,
)

def checked_native_sources(sources, native):
    """Declaration bytes belong to the exact imported producer, not this package."""
    root = Path(native.__file__).resolve().parents[2]
    for name, expected in sources.items():
        path = (root/name).resolve()
        require(path.is_relative_to(root) and hashlib.sha256(path.read_bytes()).hexdigest()==expected,
                'Native declaration source changed')


def _field_contract(task):
    from environments.website_world.feature_offer_task import FieldInventory
    from environments.website_world.catalog_predicates import PredicateSet
    inventory = FieldInventory(task['concept_id'])
    compiled = PredicateSet(inventory.fields, task['predicates'], known_paths=inventory.known_paths)
    publication = {k: deepcopy(inventory.publication.get(k, dict(role='buying_choice',
        definition=compiled.fields[k], mapping_status='declared_pilot_variant_without_authored_meaning')))
        for k in compiled.fields}
    expected = dict(field_declarations=compiled.fields, field_source_sha256=inventory.source_hashes,
        field_publication=publication, known_scalar_paths=sorted(set(compiled.fields) & set(inventory.known_paths)))
    for key, value in expected.items():
        require(object_digest(task.get(key)) == object_digest(value), f'Producer {key} binding mismatch')
    return expected


def _comparison_scope(task):
    if 'comparison_site_id' not in task:
        _supported('comparison_scope' not in task, 'comparison_scope', 'Comparison ID required for scoped pairs')
        return None
    sid, scope = task['comparison_site_id'], task.get('comparison_scope')
    _supported(sid in {f'comparison-{i:02d}' for i in range(8)}, 'comparison_site_id', 'Native comparison site required')
    require(isinstance(scope, dict) and set(scope) == {'site_name', 'surrounding_sha256', 'product_retailer_pairs'} and
            _identifier(scope['site_name']) and _hash(scope['surrounding_sha256']), 'Native comparison scope required')
    pairs = scope['product_retailer_pairs']
    require(isinstance(pairs, list) and all(isinstance(p, list) and len(p) == 2 and all(_identifier(x) for x in p) for p in pairs)
            and len({tuple(p) for p in pairs}) == len(pairs), 'Unique product/retailer comparison pairs required')
    return deepcopy(scope)


def compile_feature_offer(task):
    allowed = {'schema_version', 'world_id', 'world_sha256', 'kind', 'concept_id', 'price_basis',
        'quantity', 'user_message', 'memories', 'task_id', 'predicates', 'availability', 'max_price_minor',
        'comparison_site_id', 'comparison_scope', 'field_declarations', 'field_source_sha256',
        'field_publication', 'known_scalar_paths', 'matching_policy'}
    _supported(not set(task) - allowed, '$', 'Unrecognized feature task clauses')
    _supported(task.get('kind') == 'cheapest_matching_available', 'kind', 'Native feature task required')
    for key in ('task_id', 'world_id', 'concept_id'):
        require(_identifier(task.get(key)), f'{key}: native identity required')
    require(_hash(task.get('world_sha256')), 'Native world hash required')
    _supported(task.get('memories') == [], 'memories', 'Structured memories are not adopted')
    _supported(task.get('price_basis') == 'listed_sku_price' and type(task.get('quantity')) is int and task['quantity'] == 1,
               'price_basis/quantity', 'One listed sale unit required')
    _supported(task.get('availability') in ('purchasable', 'positive_stock'), 'availability', 'Native stock policy required')
    _supported(task.get('matching_policy') == 'known_applicable_native_values', 'matching_policy', 'Known/applicable policy required')
    _supported(isinstance(task.get('predicates'), list) and bool(task['predicates']), 'predicates', 'Nonempty typed predicates required')
    if 'max_price_minor' in task:
        _supported(type(task['max_price_minor']) is int and task['max_price_minor'] >= 0,
                   'max_price_minor', 'Inclusive nonnegative integer SEK minor-unit cap required')
    comparison = _comparison_scope(task)
    contract = _field_contract(task)
    spec = dict(operation=task['kind'], concept_id=task['concept_id'],
        predicates=deepcopy(task['predicates']), availability=task['availability'],
        matching_policy=task['matching_policy'], objective=[dict(field='listed_price_minor', direction='min')],
        price_basis='listed_sku_price', quantity=1, quantity_basis='offered_sale_unit', currency='SEK',
        population='all_carried_concept_offers_in_declared_scope', ties='any_optimal_offer',
        no_match='no_native_known_applicable_available_match_not_physical_falsehood', purchase=False,
        report_fields=['product_name', 'selected_configuration', 'retailer_name', 'listed_price_minor', 'product_url'],
        field_contract=contract)
    if comparison is not None:
        spec.update(comparison_site_id=task['comparison_site_id'], comparison_scope=comparison)
    if 'max_price_minor' in task:
        spec['max_price_minor'] = task['max_price_minor']
    nodes, needs = [], []
    roles = [('concept', 'concept_id', 'string', None, {}, 'product', 'concept_id'),
        ('physical_stock', 'positive_physical_stock', 'boolean', None,
         {'basis': 'positive_shop_or_warehouse_quantity'}, 'offer_state', 'availability'),
        ('price', 'listed_price_minor', 'integer', 'SEK_minor',
         {'quantity': 1, 'quantity_basis': 'offered_sale_unit'}, 'offer_state', 'price_basis'),
        ('configuration', 'selected_configuration', 'object', None, {}, 'offer_state', 'quantity'),
        ('product', 'product_name', 'string', None, {}, 'product', 'kind'),
        ('retailer', 'retailer_name', 'string', None, {}, 'retailer', 'kind'),
        ('link', 'product_url', 'string', None, {}, 'offer_state', 'kind')]
    if task['availability'] == 'purchasable':
        roles.append(('supplier', 'supplier_order_enabled', 'boolean', None, {}, 'offer_state', 'availability'))
    for identifier, field, kind, unit, qualifiers, scope, path in roles:
        nodes.append(input_node(identifier, field, kind, unit=unit, qualifiers=qualifiers))
        if identifier == 'price': nodes[-1]['minimum_value'] = 0
        needs.append(dict(id=identifier, field_role=field, entity_scope=scope, unit=unit,
            qualifiers=deepcopy(qualifiers), task_source_path=path, producer_assertion_id=None, source_mapping='not_bound'))
    field_ids = {}
    for index, (field, definition) in enumerate(sorted(contract['field_declarations'].items())):
        identifier = field_ids[field] = f'feature_{index}'
        published = contract['field_publication'][field]
        qualifiers = dict(declaration_sha256=object_digest(definition),
                          publication_sha256=object_digest(published))
        for key in ('basis', 'component', 'applicable_when'):
            if key in definition: qualifiers[key] = deepcopy(definition[key])
        if 'subject' in published: qualifiers['reviewed_subject'] = deepcopy(published['subject'])
        if 'required_qualifiers' in published: qualifiers['reviewed_qualifiers'] = deepcopy(published['required_qualifiers'])
        node = input_node(identifier, field, 'catalog_value', unit=definition.get('unit'), qualifiers=qualifiers)
        node.update(catalog_field=field, catalog_definition=deepcopy(definition))
        nodes.append(node)
        needs.append(dict(id=identifier, field_role=field, entity_scope='sku' if field.startswith('sku.') else 'product',
            unit=definition.get('unit'), qualifiers=qualifiers, task_source_path='predicates',
            declaration=deepcopy(definition), reviewed_publication=deepcopy(published),
            required_logical_status='known', producer_assertion_id=None, source_mapping='not_bound'))
    predicate_ids = []
    for index, predicate in enumerate(task['predicates']):
        identifier = f'feature_match_{index}'; predicate_ids.append(identifier)
        nodes.append(dict(id=identifier, op='catalog_predicate', source=field_ids[predicate['field']],
                          predicate=deepcopy(predicate)))
    nodes += [predicate_node('matching_concept', 'concept', 'eq', task['concept_id']),
              predicate_node('positive_stock', 'physical_stock', 'eq', True)]
    availability = 'positive_stock'
    if task['availability'] == 'purchasable':
        nodes += [predicate_node('supplier_enabled', 'supplier', 'eq', True),
                  dict(id='available', op='any', children=['positive_stock', 'supplier_enabled'])]
        availability = 'available'
    eligibility = ['matching_concept', availability, *predicate_ids]
    if 'max_price_minor' in task:
        nodes.append(predicate_node('price_cap', 'price', 'le', task['max_price_minor']))
        eligibility.append('price_cap')
    nodes += [dict(id='eligible', op='all', children=eligibility), dict(id='excluded', op='not', source='eligible'),
              dict(id='ready', op='all', children=['eligible', 'price', 'configuration']),
              dict(id='candidate_assessed', op='any', children=['excluded', 'ready']),
              dict(id='selected_report_ready', op='all', children=['ready', 'product', 'retailer', 'link'])]
    graph = dict(nodes=nodes, roots=['candidate_assessed', 'selected_report_ready'])
    _validate_graph(graph)
    return dict(schema=VERSION, source_schema=FEATURE_TASK, task_id=task['task_id'],
        task_sha256=object_digest(task), semantic_sha256=object_digest(spec), semantics=spec,
        world_binding=dict(world_id=task['world_id'], native_sha256=task['world_sha256'], digest_convention='spaced_sorted_json'),
        information_needs=needs, candidate_graph=graph,
        global_requirements=[dict(id='global_minimum', operation='minimum', objective=deepcopy(spec['objective']),
            population=spec['population'], ties=spec['ties'], sufficiency='eligible_incumbent_plus_complete_public_comparison_or_exclusion_bounds'),
            dict(id='no_match', operation='none_known_applicable_eligible',
                 sufficiency='complete_public_population_and_approved_known_or_indeterminate_condition_assessment',
                 physical_unknowns_are_false=False)],
        capability=dict(task_semantics='prepared_native_contract', runtime_packet_acceptance='pending',
            source_mapping='not_bound', exposure_mapping='not_bound', global_evidence_assessment='not_implemented',
            grading='not_adopted_by_this_consumer'), analysis_views=['confirmed_prefix_evidence', 'authoritative_world_relevance'],
        oracle_relevance=None, scope='conditional_requirements_not_mandatory_read_checklist')


def bind_feature_offer(compiled, world, bindings=None, *, surrounding=None, site_registry=None, model_routes=None):
    from .task_requirements import bind_sites
    from environments.website_world import feature_offer_task as native
    spec = compiled['semantics']
    checked_native_sources(spec['field_contract']['field_source_sha256'],native)
    require(model_routes is None, 'Exact-SKU model-route packet is not a feature-offer input')
    pairs, comparison = None, spec.get('comparison_scope')
    if comparison is not None:
        require(isinstance(surrounding, dict), 'Comparison-scoped feature task requires surrounding sidecar')
        sha = hashlib.sha256(json.dumps(surrounding, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()
        require(sha == comparison['surrounding_sha256'] and surrounding['source_world_id'] == world['world_id'] and
                surrounding['source_world_sha256'] == compiled['world_binding']['native_sha256'], 'Feature comparison/world binding mismatch')
        sites = [s for s in surrounding['sites'] if s['site_id'] == spec['comparison_site_id'] and s['kind'] == 'aggregator']
        require(len(sites) == 1 and sites[0]['name'] == comparison['site_name'], 'Native feature comparison identity required')
        pairs = {tuple(p) for p in comparison['product_retailer_pairs']}
        require(pairs == {(r['product_id'], r['retailer_id']) for r in sites[0]['listings']}, 'Complete native comparison pair scope mismatch')
    elif surrounding is not None:
        require(surrounding['source_world_id'] == world['world_id'] and
                surrounding['source_world_sha256'] == compiled['world_binding']['native_sha256'], 'Surrounding/world binding mismatch')
    proxy = deepcopy(compiled); proxy['source_schema'] = LISTED_TASK
    # This adapter validates and applies its own comparison scope below. The
    # lower-level carried-offer inventory receives an explicitly unscoped proxy.
    proxy['semantics'].pop('comparison_scope', None)
    proxy['semantics'].pop('comparison_site_id', None)
    result = bind_sites(proxy, world, bindings)
    # Record incomplete selector metadata; never fill it from task predicates or
    # assume that an URL-encoded dimension was present in this export.
    from environments.website_world.feature_offer_task import FieldInventory
    selector_fields = {k[4:] for k in FieldInventory(spec['concept_id']).fields if k.startswith('sku.')}
    skus = {s['sku_id']: s for p in world['products'] for s in p['public']['skus']}
    for site in result['sites']:
        if pairs is not None:
            site['candidates'] = [c for c in site['candidates'] if (c['subject']['product_id'], site['site_id']) in pairs]
            site['candidate_count'] = len(site['candidates'])
        for candidate in site['candidates']:
            candidate['feature_requirements'] = 'task_declared_predicates_not_native_matching_filter'
            if candidate['route'] is not None:
                candidate['selection_metadata_missing_fields'] = sorted(
                    (selector_fields & skus[candidate['subject']['sku_id']].keys()) - candidate['route']['selection'].keys())
        if bindings is not None and site_registry is not None:
            matches = [s for s in site_registry if s['site_id'] == site['site_id'] and s['kind'] == 'retailer']
            require(len(matches) == 1 and matches[0]['origin'] == bindings['origins'][site['site_id']], 'Runtime retailer origin mismatch')
    if comparison is not None:
        route = bindings['surrounding']['origins'][spec['comparison_site_id']] + '/' if bindings else None
        if bindings is not None:
            require(site_registry is not None, 'Runtime comparison registry required with bindings')
            matches = [s for s in site_registry if s['site_id'] == spec['comparison_site_id'] and s['kind'] == 'aggregator']
            require(len(matches) == 1 and route == matches[0]['origin'].rstrip('/') + '/', 'Runtime feature comparison origin mismatch')
        result['sites'].append(dict(site_id=spec['comparison_site_id'], kind='aggregator', candidates=[], candidate_count=0,
            route=route, route_delivery='not_established', public_population_complete=None,
            information_need_templates=['concept', 'price', 'product', 'retailer', 'link'], oracle_relevance=None))
    result['site_count'] = len(result['sites'])
    result['candidate_count'] = sum(s['candidate_count'] for s in result['sites'])
    result['inventory_scope'] = 'authoritative_world_structure_not_native_feature_matches_or_public_disclosure'
    return result
