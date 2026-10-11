"""Prepared single-item delivery requirements; runtime adoption remains pending.

Central native quote arithmetic is not reimplemented. Offer inventory remains
unfiltered; admitted service identities need a later frozen consumer packet.
"""
from copy import deepcopy
import hashlib
from pathlib import Path

from .fact_exposure import object_digest, require
from .feature_offer_requirements import compile_feature_offer, bind_feature_offer, checked_native_sources
from .task_requirements import QUOTE_TASK, _supported, _hash, _identifier, _typed, _validate_graph, input_node, predicate_node


def compile_quote_offer(task):
    from environments.website_world.quote_offer_task import resolve
    from environments.website_world.feature_offer_task import FieldInventory
    allowed = {'schema_version', 'world_id', 'world_sha256', 'kind', 'concept_id', 'price_basis', 'quantity',
        'user_message', 'memories', 'predicates', 'availability', 'field_declarations', 'field_source_sha256',
        'field_publication', 'known_scalar_paths', 'matching_policy', 'objective', 'destination', 'delivery_types',
        'arrival_deadline', 'max_total_minor', 'destination_address', 'quote_binding', 'destination_sha256',
        'quote_as_of', 'feature_task', 'order_domain', 'task_id', 'comparison_site_id', 'comparison_scope'}
    _supported(not set(task) - allowed, '$', 'Unrecognized single-item delivery clauses')
    require(task.get('schema_version') == QUOTE_TASK and task.get('kind') == 'matching_single_item_delivery' and
            _identifier(task.get('task_id')), 'Native single-item delivery task required')
    require(task.get('price_basis') == 'complete_single_item_payable' and type(task.get('quantity')) is int and
            task['quantity'] == 1 and task.get('order_domain') ==
                dict(quantity=1, extra_items=False, new_memberships=False, coupons=False) and
            type(task['order_domain']['quantity']) is int and
            all(type(task['order_domain'][k]) is bool for k in ('extra_items', 'new_memberships', 'coupons')),
            'Exactly one sale unit without extras/coupons/new memberships required')
    base_task = task.get('feature_task'); require(isinstance(base_task, dict), 'Embedded source-bound feature task required')
    same = ['world_id', 'world_sha256', 'concept_id', 'quantity', 'memories', 'predicates', 'availability',
        'field_declarations', 'field_source_sha256', 'field_publication', 'known_scalar_paths', 'matching_policy',
        'comparison_site_id', 'comparison_scope']
    require(all(object_digest(task.get(k)) == object_digest(base_task.get(k)) for k in same) and
            'max_price_minor' not in base_task, 'Outer quote/embedded feature task mismatch')
    selection_keys = ('kind', 'concept_id', 'predicates', 'availability', 'comparison_site_id', 'objective',
                      'destination', 'delivery_types', 'max_total_minor', 'arrival_deadline')
    selection = {k: deepcopy(task[k]) for k in selection_keys if k in task}
    resolved = resolve(selection, inventory=FieldInventory(task['concept_id']), concept_ids=[task['concept_id']])
    require(resolved == selection, 'Canonical native quote selection required')
    require(_typed(task.get('quote_as_of'), 'iso_date') and _hash(task.get('destination_sha256')) and
            isinstance(task.get('destination_address'), dict) and
            set(task['destination_address']) == {'name', 'street', 'postcode', 'city'} and
            all(_identifier(v) for v in task['destination_address'].values()), 'Bound scenario date/public destination required')
    binding = task.get('quote_binding')
    require(isinstance(binding, dict) and set(binding) == {'schema_version', 'world_id', 'world_sha256',
        'basket_plan_sha256', 'admission_plan_sha256', 'quote_plan_sha256', 'source_sha256'} and
        binding['schema_version'] == 'accepted-catalog-prepared-quote-v1' and binding['world_id'] == task['world_id'] and
        all(_hash(binding[k]) for k in ('world_sha256', 'basket_plan_sha256', 'quote_plan_sha256')) and
        (binding['admission_plan_sha256'] is None or _hash(binding['admission_plan_sha256'])) and
        isinstance(binding['source_sha256'], dict) and binding['source_sha256'] and
        all(_hash(v) for v in binding['source_sha256'].values()), 'Complete persistent prepared quote binding required')
    base = compile_feature_offer(base_task)
    result = deepcopy(base)
    spec = result['semantics']
    objective = [dict(field='complete_payable_minor', direction='min')]
    timing = task['objective'] == 'fastest_then_cheapest' or 'arrival_deadline' in task
    if task['objective'] == 'fastest_then_cheapest':
        objective.insert(0, dict(field='latest_estimated_arrival', direction='min'))
    spec.update(operation=task['kind'], price_basis=task['price_basis'], objective=objective,
        population='all_carried_concept_offers_and_their_complete_admitted_delivery_menus_in_declared_scope',
        destination=task['destination'], destination_address=deepcopy(task['destination_address']),
        destination_sha256=task['destination_sha256'], quote_as_of=task['quote_as_of'],
        quote_binding=deepcopy(binding), order_domain=deepcopy(task['order_domain']), delivery_types=task['delivery_types'][:],
        arrival_is_estimate_not_guarantee=True, service_identity='resolved_sku_then_entire_admitted_menu_without_price_or_winner_repair',
        report_fields=['product_name', 'selected_configuration', 'retailer_name', 'product_url',
            'complete_payable_minor', 'carrier_name', 'service_tier', 'delivery_method', 'collection_point_if_used'] +
            (['latest_estimated_arrival'] if timing else []))
    for key in ('max_total_minor', 'arrival_deadline'):
        if key in task: spec[key] = task[key]
    # Stock anywhere is insufficient for delivery. Replace the listed-price and
    # generic stock roles with state-bound payable/service/fulfilment roles.
    removed = {'physical_stock', 'supplier', 'price', 'positive_stock', 'supplier_enabled', 'available',
               'eligible', 'excluded', 'ready', 'candidate_assessed', 'selected_report_ready'}
    nodes = [n for n in result['candidate_graph']['nodes'] if n['id'] not in removed]
    needs = [n for n in result['information_needs'] if n['id'] not in removed]
    qualifiers = dict(quantity=1, quantity_basis='offered_sale_unit', split=False,
        destination_sha256=task['destination_sha256'], quote_as_of=task['quote_as_of'],
        quote_binding_sha256=object_digest(binding), order_domain_sha256=object_digest(task['order_domain']))
    roles = [('payable', 'complete_payable_minor', 'integer', 'SEK_minor'),
        ('feasible', 'single_item_delivery_feasible', 'boolean', None),
        ('method', 'delivery_method', 'string', None), ('carrier', 'carrier_name', 'string', None),
        ('tier', 'service_tier', 'string', None),
        ('point', 'collection_point_identity', 'object', None)]
    if task['availability'] == 'positive_stock': roles.append(('on_hand', 'delivery_all_items_on_hand', 'boolean', None))
    if timing:
        roles += [('arrival_status', 'arrival_status', 'string', None),
                  ('latest', 'latest_estimated_arrival', 'iso_date', 'ISO_calendar_date')]
    for identifier, field, kind, unit in roles:
        node = input_node(identifier, field, kind, unit=unit, qualifiers=qualifiers)
        node['required_scope_fields'] = ['quote_id', 'option_id']
        if identifier == 'payable': node['minimum_value'] = 0
        if identifier == 'method': node['allowed_values'] = ['home', 'parcel_locker', 'staffed_counter', 'retailer_branch']
        if identifier == 'arrival_status': node['allowed_values'] = ['estimated', 'unknown']
        nodes.append(node)
        needs.append(dict(id=identifier, field_role=field, entity_scope='quote_option_state', unit=unit,
            qualifiers=deepcopy(qualifiers), task_source_path='quote_binding', producer_assertion_id=None, source_mapping='not_bound'))
    nodes.append(predicate_node('delivery_feasible', 'feasible', 'eq', True))
    methods = []
    for index, method in enumerate(task['delivery_types']):
        key = f'allowed_method_{index}'; methods.append(key); nodes.append(predicate_node(key, 'method', 'eq', method))
    nodes.append(dict(id='allowed_delivery', op='any', children=methods))
    eligibility = ['matching_concept', *[n['id'] for n in nodes if n['op'] == 'catalog_predicate'],
                   'delivery_feasible', 'allowed_delivery']
    if task['availability'] == 'positive_stock':
        nodes.append(predicate_node('physical_fulfilment', 'on_hand', 'eq', True)); eligibility.append('physical_fulfilment')
    if 'max_total_minor' in task:
        nodes.append(predicate_node('total_cap', 'payable', 'le', task['max_total_minor'])); eligibility.append('total_cap')
    if timing:
        nodes.append(predicate_node('estimated_arrival', 'arrival_status', 'eq', 'estimated'))
        eligibility += ['estimated_arrival', 'latest']
        if 'arrival_deadline' in task:
            nodes.append(predicate_node('meets_deadline', 'latest', 'le', task['arrival_deadline'])); eligibility.append('meets_deadline')
    nodes += [predicate_node('home_method', 'method', 'eq', 'home'),
        dict(id='point_report_ready', op='any', children=['home_method', 'point']),
        dict(id='eligible', op='all', children=eligibility), dict(id='excluded', op='not', source='eligible'),
        dict(id='ready', op='all', children=['eligible', 'payable', 'configuration']),
        dict(id='candidate_assessed', op='any', children=['excluded', 'ready']),
        dict(id='selected_report_ready', op='all', children=['ready', 'product', 'retailer', 'link', 'carrier', 'tier',
            'point_report_ready'])]
    graph = dict(nodes=nodes, roots=['candidate_assessed', 'selected_report_ready'],
        required_scope_fields=['retailer_id', 'product_id', 'sku_id', 'offer_id', 'state_id'])
    _validate_graph(graph)
    result.update(source_schema=QUOTE_TASK, task_id=task['task_id'], task_sha256=object_digest(task),
        semantic_sha256=object_digest(spec), information_needs=needs, candidate_graph=graph,
        feature_inventory_template=base, global_requirements=[dict(id='global_optimum', operation='lexicographic_minimum',
            objective=deepcopy(objective), population=spec['population'], ties=spec['ties'],
            sufficiency='eligible_incumbent_plus_complete_public_population_menu_and_exclusion_or_objective_bounds'),
            dict(id='no_match', operation='none_known_applicable_feasible_eligible',
                 sufficiency='complete_public_offer_and_admitted_service_population_with_supported_conditional_assessments',
                 physical_unknowns_are_false=False)])
    result['capability'].update(task_semantics='prepared_native_contract', runtime_packet_acceptance='pending',
        service_inventory='awaiting_frozen_admitted_menu_packet', quote_arithmetic='central_native_api_not_reimplemented')
    return result


def bind_quote_offer(compiled, world, bindings=None, *, surrounding=None, site_registry=None, model_routes=None):
    from environments.website_world import quote_offer_task as native
    from experiments.accepted_catalog_commerce.basket_quote import model as shipping_model
    from environments.website_world.quote_offer_task import home_record
    from environments.website_world.adapter import browser_address, digest
    spec = compiled['semantics']; binding = spec['quote_binding']
    require(binding['world_sha256'] == shipping_model.digest(world) and spec['quote_as_of'] == world['quote_as_of'] and
            spec['destination_sha256'] == digest(home_record(world)['location']) and
            spec['destination_address'] == browser_address(home_record(world)), 'Quote world/date/destination binding mismatch')
    checked_native_sources(binding['source_sha256'],native)
    inventory = bind_feature_offer(compiled['feature_inventory_template'], world, bindings,
        surrounding=surrounding, site_registry=site_registry, model_routes=model_routes)
    inventory.update(task_id=compiled['task_id'], semantic_sha256=compiled['semantic_sha256'],
        capability=deepcopy(compiled['capability']), quote_binding=deepcopy(binding),
        service_inventory='unknown_until_complete_frozen_admitted_menus_are_bound')
    for site in inventory['sites']:
        site['information_need_templates'] = [n['id'] for n in compiled['information_needs']]
        site['global_dependencies'] = [n['id'] for n in compiled['global_requirements']]
        for candidate in site['candidates']:
            candidate.update(graph_template='candidate_graph_per_quote_option', admitted_options=None,
                admitted_options_complete=None, service_evidence_status='unknown')
    return inventory
