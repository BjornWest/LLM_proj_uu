"""Task semantics -> conditional evidence dependencies -> scoped site inventory.

Task-local field roles are not producer assertion IDs. Public realization and
delivery mapping remain separate capabilities. This module never reads an answer,
oracle reference, offer prices or stock to select a requirement set.
"""
from copy import deepcopy
import hashlib
import json
import math

from .fact_exposure import object_digest, require

VERSION = 'compiled-task-requirements-v1'
LISTED_TASK = 'website-basic-listed-offer-task-v1'
COMPARISON_STOCK_TASK = 'website-comparison-sku-stock-task-v1'
FEATURE_TASK = 'website-feature-listed-offer-task-v1'
QUOTE_TASK = 'website-single-item-quote-task-v1'
MEMORY_TASK = 'website-memory-feature-task-v1'
HIDDEN_TASK = 'website-hidden-feature-task-v1'
REVIEW_TASK = 'website-catalog-review-task-v1'
STATISTICS_TASK = 'website-catalog-statistics-task-v1'
BASKET_TASK = 'website-catalog-basket-task-v1'
SHORTLIST_TASK = 'website-catalog-shortlist-task-v1'
RELAXATION_TASK = 'website-catalog-relaxation-task-v1'
UNIT_PRICE_TASK = 'website-catalog-unit-price-task-v2'
PRIORITY_TASK = 'website-catalog-priority-task-v2'
MODEL_COMPARISON_TASK = 'website-catalog-comparison-task-v1'
CARRIER_REVIEW_TASK = 'website-carrier-review-task-v1'
SHIPPING_CLAIM_TASK = 'website-catalog-shipping-claim-task-v1'
CART_TASK = 'website-catalog-cart-task-v1'
CHECKOUT_DETAILS_TASK = 'website-catalog-checkout-details-task-v1'
BRANCH_STOCK_TASK = 'website-catalog-branch-stock-task-v1'
RESET_TASK = 'website-variant-reset-task-v1'
ORDER_TASK = 'website-simulated-order-task-v1'


class UnsupportedTask(ValueError):
    """An unimplemented semantic construct, distinct from a missing source."""
    def __init__(self, path, reason):
        self.path, self.reason = path, reason
        super().__init__(f'{path}: {reason}')


def _supported(condition, path, reason):
    if not condition:
        raise UnsupportedTask(path, reason)


def _identifier(value):
    return isinstance(value, str) and bool(value.strip())


def _hash(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def input_node(identifier, field, value_type, *, unit=None, qualifiers=None):
    return dict(id=identifier, op='input', field=field, value_type=value_type,
                unit=unit, qualifiers=deepcopy(qualifiers or {}))


def predicate_node(identifier, source, operator, value):
    _supported(operator in ('eq', 'ge', 'le', 'contains', 'excludes'),
               identifier, 'Unsupported predicate operator')
    return dict(id=identifier, op='predicate', source=source,
                operator=operator, expected=deepcopy(value))


def compile_task(task, *, action_inputs=None, scoring_reference=None):
    """Dispatch native tasks, with explicit frozen inputs for action adapters.

    Ordinary task compilation remains independent of world values and prose.
    Action factories require caller-pinned callbacks and saved environment inputs.
    An address-only scoring reference selects that narrower inspection contract;
    it never implies full order completion or successful address persistence.
    """
    require(isinstance(task, dict), 'Structured task object required')
    schema = task.get('schema_version')
    if schema in (RESET_TASK, ORDER_TASK):
        from .action_task_requirements import compile_reset, compile_order, compile_order_address
        require(isinstance(action_inputs, dict), 'Explicit pinned action inputs required')
        if schema == RESET_TASK:
            require(scoring_reference is None, 'Reset tasks do not accept address scoring references')
            expected = {'native_make', 'world', 'catalog', 'bindings', 'checkout_domain'}
            adapter = compile_reset
        elif scoring_reference is not None:
            expected = {'baskets', 'native_make'}
            adapter = compile_order_address
        else:
            expected = {'baskets', 'native_make', 'native_reference'}
            adapter = compile_order
        require(set(action_inputs) == expected, 'Exact action input fields required: ' + ', '.join(sorted(expected)))
        require(callable(action_inputs['native_make']) and
                ('native_reference' not in action_inputs or callable(action_inputs['native_reference'])),
                'Pinned native factory/reference callbacks required')
        if scoring_reference is not None:
            return adapter(task, **action_inputs, scoring_reference=scoring_reference)
        return adapter(task, **action_inputs)
    require(action_inputs is None and scoring_reference is None,
            'Action inputs/scoring references require an action task adapter')
    from .comparison_stock_requirements import compile_comparison_stock
    from .feature_offer_requirements import compile_feature_offer
    from .quote_offer_requirements import compile_quote_offer
    from .memory_offer_requirements import compile_memory_offer
    from .hidden_offer_requirements import compile_hidden_offer
    from .review_summary_requirements import compile_review_summary
    from .statistics_requirements import compile_statistics
    from .basket_requirements import compile_basket
    from .shortlist_requirements import compile_shortlist
    from .relaxation_requirements import compile_relaxation
    from .unit_price_requirements import compile_unit_price
    from .priority_requirements import compile_priority
    from .model_comparison_requirements import compile_model_comparison
    from .carrier_review_requirements import compile_carrier_review
    from .shipping_claim_requirements import compile_shipping_claim
    from .cart_requirements import compile_cart
    from .checkout_details_requirements import compile_checkout_details
    from .branch_stock_requirements import compile_branch_stock
    adapters = {LISTED_TASK: _compile_listed_task,
                COMPARISON_STOCK_TASK: compile_comparison_stock,
                FEATURE_TASK: compile_feature_offer, QUOTE_TASK: compile_quote_offer,
                MEMORY_TASK: compile_memory_offer, HIDDEN_TASK: compile_hidden_offer,
                REVIEW_TASK: compile_review_summary, STATISTICS_TASK: compile_statistics, BASKET_TASK: compile_basket,
                SHORTLIST_TASK: compile_shortlist, RELAXATION_TASK: compile_relaxation, UNIT_PRICE_TASK: compile_unit_price, PRIORITY_TASK: compile_priority, MODEL_COMPARISON_TASK: compile_model_comparison, CARRIER_REVIEW_TASK: compile_carrier_review,
                SHIPPING_CLAIM_TASK: compile_shipping_claim, CART_TASK: compile_cart,
                CHECKOUT_DETAILS_TASK: compile_checkout_details, BRANCH_STOCK_TASK: compile_branch_stock}
    _supported(isinstance(schema, str) and schema in adapters,
               'schema_version', f'No task adapter for {schema!r}')
    return adapters[schema](task)


def _compile_listed_task(task):
    """Native schema adapter into shared typed roles and proof operations."""
    # Reuse the producer's adopted finite concept vocabulary, not prompt labels.
    from environments.website_world.basic_offer_task import LABELS
    allowed = {'schema_version', 'world_id', 'world_sha256', 'kind', 'concept_id',
               'price_basis', 'quantity', 'user_message', 'memories', 'task_id',
               'comparison_site_id', 'comparison_scope'}
    _supported(not set(task) - allowed, '$', 'Unrecognized task clauses: ' + ', '.join(sorted(set(task) - allowed)))
    for key in ('task_id', 'world_id'):
        require(_identifier(task.get(key)), f'{key}: task identity required')
    require(_hash(task.get('world_sha256')), 'world_sha256: native world binding required')
    _supported(task.get('kind') == 'cheapest_available', 'kind', 'Only cheapest_available is adopted')
    _supported(task.get('concept_id') in LABELS, 'concept_id', 'Unsupported producer concept')
    _supported(task.get('price_basis') == 'listed_sku_price', 'price_basis', 'Listed sale-unit price required')
    _supported(type(task.get('quantity')) is int and task['quantity'] == 1,
               'quantity', 'The native template declares one offered sale unit')
    _supported(task.get('memories') == [], 'memories', 'This native schema has no structured memory bindings')
    spec = dict(operation='minimum', concept_id=task['concept_id'],
        population='all_carried_offers_of_concept', scope='all_retailers',
        objective=[dict(field='listed_price_minor', direction='min')],
        availability='any_shop_or_warehouse_stock_or_supplier_order',
        quantity=1, quantity_basis='offered_sale_unit', currency='SEK',
        ties='any_optimal_offer', no_match='report_none_available',
        report_fields=['product_name', 'selected_configuration', 'retailer_name',
                       'listed_price_minor', 'product_url'], purchase=False)
    if 'comparison_site_id' in task or 'comparison_scope' in task:
        from .feature_offer_requirements import _comparison_scope
        comparison = _comparison_scope(task)
        require(comparison is not None, 'Complete comparison identity and population required')
        spec.update(population='all_advertised_product_retailer_pairs_of_concept',
                    scope='declared_comparison_site', comparison_site_id=task['comparison_site_id'],
                    comparison_scope=comparison)
    roles = [
        ('concept', 'concept_id', 'string', None, {}, 'product', 'concept_id'),
        ('availability', 'availability', 'string', None, {}, 'offer', 'kind'),
        ('price', 'listed_price_minor', 'integer', 'SEK_minor',
         {'quantity': 1, 'quantity_basis': 'offered_sale_unit'}, 'offer', 'price_basis'),
        ('configuration', 'selected_configuration', 'object', None, {}, 'offer_state', 'quantity'),
        ('product', 'product_name', 'string', None, {}, 'product', 'kind'),
        ('retailer', 'retailer_name', 'string', None, {}, 'retailer', 'kind'),
        ('link', 'product_url', 'string', None, {}, 'offer_state', 'kind'),
    ]
    nodes, needs = [], []
    for identifier, field, value_type, unit, qualifiers, scope, path in roles:
        nodes.append(input_node(identifier, field, value_type, unit=unit, qualifiers=qualifiers))
        if identifier == 'availability':
            nodes[-1]['allowed_values'] = ['in_stock', 'backorder', 'unavailable']
        if identifier == 'price':
            nodes[-1]['minimum_value'] = 0
        needs.append(dict(id=identifier, field_role=field, entity_scope=scope,
            unit=unit, qualifiers=qualifiers, task_source_path=path,
            producer_assertion_id=None, source_mapping='not_bound'))
    nodes += [predicate_node('matching_concept', 'concept', 'eq', spec['concept_id']),
              predicate_node('in_stock', 'availability', 'eq', 'in_stock'),
              predicate_node('supplier_order', 'availability', 'eq', 'backorder'),
              dict(id='available', op='any', children=['in_stock', 'supplier_order']),
              dict(id='eligible', op='all', children=['matching_concept', 'available']),
              dict(id='excluded', op='not', source='eligible'),
              dict(id='ready', op='all', children=['eligible', 'price', 'configuration']),
              dict(id='candidate_assessed', op='any', children=['excluded', 'ready']),
              dict(id='selected_report_ready', op='all',
                   children=['ready', 'product', 'retailer', 'link'])]
    graph = dict(nodes=nodes, roots=['candidate_assessed', 'selected_report_ready'])
    _validate_graph(graph)
    return dict(schema=VERSION, task_id=task['task_id'], source_schema=LISTED_TASK,
        task_sha256=object_digest(task), semantic_sha256=object_digest(spec),
        world_binding=dict(world_id=task['world_id'], native_sha256=task['world_sha256']),
        semantics=spec, information_needs=needs, candidate_graph=graph,
        global_requirements=[dict(id='global_minimum', operation='minimum',
            population=spec['population'], objective=spec['objective'], ties=spec['ties'],
            sufficiency='eligible_incumbent_plus_complete_public_comparison_or_exclusion_bounds'),
            dict(id='no_match', operation='none_eligible',
                 sufficiency='complete_public_population_and_supported_exclusion_of_every_candidate')],
        capability=dict(task_semantics='supported', source_mapping='not_bound',
                        exposure_mapping='not_bound', global_evidence_assessment='not_implemented',
                        grading='not_adopted_by_this_consumer'),
        analysis_views=['confirmed_prefix_evidence', 'authoritative_world_relevance'],
        oracle_relevance=None, scope='conditional_requirements_not_mandatory_read_checklist')


def bind_sites(compiled, world, bindings=None, *, surrounding=None, site_registry=None,
               model_routes=None, checkout_domain=None, basket_plan=None, admission_plan=None):
    """Inventory all carried concept offers, including unavailable/losing options.

    Native concept membership is a source-routing annotation, not policy proof.
    No price/stock values or private optimality are exported here. Optional route
    records carry configuration selectors, not proof of the policy's selected state.
    Public population completeness still needs independently delivered evidence.
    """
    require(compiled['schema'] == VERSION, 'Compiled requirement schema required')
    if compiled['source_schema'] in (RESET_TASK, ORDER_TASK):
        from .action_task_requirements import bind_action_sites
        require(model_routes is None and checkout_domain is None and basket_plan is None and admission_plan is None,
                'Action environment inputs belong at compilation, not inventory binding')
        return bind_action_sites(compiled, world, bindings, surrounding=surrounding, site_registry=site_registry)
    if compiled['source_schema'] in (SHIPPING_CLAIM_TASK, CART_TASK, CHECKOUT_DETAILS_TASK):
        if compiled['source_schema'] == SHIPPING_CLAIM_TASK:
            from .shipping_claim_requirements import bind_shipping_claim as bind
        elif compiled['source_schema'] == CHECKOUT_DETAILS_TASK:
            from .checkout_details_requirements import bind_checkout_details as bind
        else:
            from .cart_requirements import bind_cart as bind
        return bind(compiled, world, bindings, surrounding=surrounding, site_registry=site_registry,
            model_routes=model_routes, checkout_domain=checkout_domain, basket_plan=basket_plan, admission_plan=admission_plan)
    if compiled['source_schema'] == BASKET_TASK:
        from .basket_requirements import bind_basket
        return bind_basket(compiled, world, bindings, surrounding=surrounding, site_registry=site_registry,
            model_routes=model_routes, checkout_domain=checkout_domain, basket_plan=basket_plan, admission_plan=admission_plan)
    require(checkout_domain is None and basket_plan is None and admission_plan is None,
        'Basket inputs require the basket task adapter')
    if compiled['source_schema'] == SHORTLIST_TASK:
        from .shortlist_requirements import bind_shortlist
        return bind_shortlist(compiled, world, bindings, surrounding=surrounding,
            site_registry=site_registry, model_routes=model_routes)
    if compiled['source_schema'] == CARRIER_REVIEW_TASK:
        from .carrier_review_requirements import bind_carrier_review
        return bind_carrier_review(compiled, world, bindings, surrounding=surrounding, site_registry=site_registry, model_routes=model_routes)
    if compiled['source_schema'] == PRIORITY_TASK:
        from .priority_requirements import bind_priority
        return bind_priority(compiled, world, bindings, surrounding=surrounding, site_registry=site_registry, model_routes=model_routes)
    if compiled['source_schema'] == MODEL_COMPARISON_TASK:
        from .model_comparison_requirements import bind_model_comparison
        return bind_model_comparison(compiled, world, bindings, surrounding=surrounding, site_registry=site_registry, model_routes=model_routes)
    if compiled['source_schema'] == BRANCH_STOCK_TASK:
        from .branch_stock_requirements import bind_branch_stock
        return bind_branch_stock(compiled, world, bindings, surrounding=surrounding,
            site_registry=site_registry, model_routes=model_routes)
    if compiled['source_schema'] == UNIT_PRICE_TASK:
        from .unit_price_requirements import bind_unit_price
        return bind_unit_price(compiled, world, bindings, surrounding=surrounding,
            site_registry=site_registry, model_routes=model_routes)
    if compiled['source_schema'] == RELAXATION_TASK:
        from .relaxation_requirements import bind_relaxation
        return bind_relaxation(compiled, world, bindings, surrounding=surrounding,
            site_registry=site_registry, model_routes=model_routes)
    if compiled['source_schema'] == COMPARISON_STOCK_TASK:
        from .comparison_stock_requirements import bind_comparison_stock
        return bind_comparison_stock(compiled, world, surrounding, bindings,
                                     site_registry=site_registry, model_routes=model_routes)
    if compiled['source_schema'] == FEATURE_TASK:
        from .feature_offer_requirements import bind_feature_offer
        return bind_feature_offer(compiled, world, bindings, surrounding=surrounding,
                                  site_registry=site_registry, model_routes=model_routes)
    if compiled['source_schema'] == QUOTE_TASK:
        from .quote_offer_requirements import bind_quote_offer
        return bind_quote_offer(compiled, world, bindings, surrounding=surrounding,
                                site_registry=site_registry, model_routes=model_routes)
    if compiled['source_schema'] == MEMORY_TASK:
        from .memory_offer_requirements import bind_memory_offer
        return bind_memory_offer(compiled, world, bindings, surrounding=surrounding,
                                site_registry=site_registry, model_routes=model_routes)
    if compiled['source_schema'] == HIDDEN_TASK:
        from .hidden_offer_requirements import bind_hidden_offer
        return bind_hidden_offer(compiled, world, bindings, surrounding=surrounding,
                                 site_registry=site_registry, model_routes=model_routes)
    if compiled['source_schema'] == STATISTICS_TASK:
        from .statistics_requirements import bind_statistics
        return bind_statistics(compiled, world, bindings, surrounding=surrounding,
            site_registry=site_registry, model_routes=model_routes)
    if compiled['source_schema'] == REVIEW_TASK:
        from .review_summary_requirements import bind_review_summary
        return bind_review_summary(compiled, world, bindings, surrounding=surrounding,
                                   site_registry=site_registry, model_routes=model_routes)
    require(model_routes is None, 'Exact-SKU model routes are not listed-offer inputs')
    comparison = compiled['semantics'].get('comparison_scope')
    pairs = None
    if comparison is not None:
        require(isinstance(surrounding, dict), 'Comparison-scoped listed task requires surrounding sidecar')
        surrounding_hash = hashlib.sha256(json.dumps(surrounding, sort_keys=True,
            ensure_ascii=False, allow_nan=False).encode()).hexdigest()
        require(surrounding_hash == comparison['surrounding_sha256'] and
                surrounding.get('source_world_id') == world['world_id'] and
                surrounding.get('source_world_sha256') == compiled['world_binding']['native_sha256'],
                'Listed comparison/world binding mismatch')
        selected = [s for s in surrounding['sites']
                    if s['site_id'] == compiled['semantics']['comparison_site_id'] and s['kind'] == 'aggregator']
        require(len(selected) == 1 and selected[0]['name'] == comparison['site_name'],
                'Exact listed comparison site identity required')
        pairs = set(map(tuple, comparison['product_retailer_pairs']))
        require(pairs == {(r['product_id'], r['retailer_id']) for r in selected[0]['listings']},
                'Complete advertised listed comparison population required')
    else:
        require(surrounding is None and site_registry is None,
                'Unscoped listed inventory does not accept comparison inputs')
    binding = compiled['world_binding']
    require(world['world_id'] == binding['world_id'], 'Task/world identity mismatch')
    native_hash = hashlib.sha256(json.dumps(world, sort_keys=True, ensure_ascii=False,
                                            allow_nan=False).encode()).hexdigest()
    require(native_hash == binding['native_sha256'], 'Task/world native hash mismatch')
    products = {p['public']['product_id']: p['public'] for p in world['products']}
    require(len(products) == len(world['products']), 'Duplicate product identity')
    skus = {}
    for product in products.values():
        for sku in product['skus']:
            require(sku['sku_id'] not in skus and sku['product_id'] == product['product_id'], 'Invalid SKU identity')
            skus[sku['sku_id']] = sku
    seen, sites, retailer_ids = set(), [], set()
    for retailer in sorted(world['retailers'], key=lambda r: r['retailer_id']):
        rid = retailer['retailer_id']
        require(_identifier(rid) and rid not in retailer_ids, 'Duplicate/invalid retailer identity')
        retailer_ids.add(rid)
        candidates = []
        for offer in sorted(retailer['offers'], key=lambda o: o['offer_id']):
            oid, pid, sid = offer['offer_id'], offer['product_id'], offer['sku_id']
            require(oid not in seen and pid in products and sid in skus and
                    skus[sid]['product_id'] == pid, 'Invalid carried offer identity')
            seen.add(oid)
            if products[pid]['concept_id'] != compiled['semantics']['concept_id']:
                continue
            if pairs is not None and (pid, rid) not in pairs:
                continue
            subject = dict(retailer_id=rid, product_id=pid, sku_id=sid, offer_id=oid)
            route = None
            if bindings is not None:
                record = bindings['retailer_offers'].get(oid)
                require(record is not None and all(record.get(k) == subject[k]
                        for k in ('retailer_id', 'product_id', 'sku_id')), 'Offer route identity mismatch')
                route = {k: deepcopy(record[k]) for k in
                         ('url', 'required_selection', 'selection', 'url_behavior')}
            candidates.append(dict(subject=subject, graph_template='candidate_graph',
                route=route, route_delivery='not_established', evidence_status='unknown',
                oracle_relevance=None))
        sites.append(dict(site_id=rid, candidates=candidates,
            candidate_count=len(candidates), information_need_templates=[n['id'] for n in compiled['information_needs']],
            global_dependencies=[r['id'] for r in compiled['global_requirements']],
            inventory_scope='authoritative_world_structure',
            public_population_complete=None, exclusion_status='unknown'))
    if comparison is not None:
        route = None
        if bindings is not None:
            require(site_registry is not None, 'Actual comparison registry required with runtime bindings')
            registry = {s['site_id']: s for s in site_registry}
            require(len(registry) == len(site_registry), 'Duplicate actual site registry identity')
            for site in sites:
                runtime = registry.get(site['site_id'])
                require(runtime is not None and runtime['kind'] == 'retailer' and
                        runtime['origin'] == bindings['origins'][site['site_id']],
                        'Listed retailer publication origin mismatch')
            sid = compiled['semantics']['comparison_site_id']; runtime = registry.get(sid)
            origin = bindings['surrounding']['origins'][sid]
            require(runtime is not None and runtime['kind'] == 'aggregator' and
                    runtime['name'] == comparison['site_name'] and
                    origin.rstrip('/') == runtime['origin'].rstrip('/'),
                    'Listed comparison publication identity mismatch')
            route = origin.rstrip('/') + '/'
        sites.append(dict(site_id=compiled['semantics']['comparison_site_id'], kind='aggregator',
            candidates=[], candidate_count=0, route=route, route_delivery='not_established',
            information_need_templates=['concept', 'price', 'product', 'retailer', 'link'],
            public_population_complete=None, oracle_relevance=None))
    return dict(schema='task-site-requirement-inventory-v1', task_id=compiled['task_id'],
        semantic_sha256=compiled['semantic_sha256'], world_binding=deepcopy(binding), sites=sites,
        site_count=len(sites), candidate_count=sum(s['candidate_count'] for s in sites),
        capability=deepcopy(compiled['capability']), oracle_relevance=None)


def _validate_graph(graph):
    nodes = {n['id']: n for n in graph['nodes']}
    require(len(nodes) == len(graph['nodes']) and nodes, 'Unique nonempty graph nodes required')
    visiting, visited = set(), set()
    def visit(key):
        require(key in nodes, 'Unknown dependency node')
        require(key not in visiting, 'Cyclic requirement graph')
        if key in visited:
            return
        visiting.add(key)
        node = nodes[key]
        require(node['op'] in ('input', 'predicate', 'catalog_predicate', 'all', 'any', 'not'), 'Unsupported dependency operation')
        if node['op'] == 'input':
            require(_identifier(node['field']) and node['value_type'] in
                    ('number', 'integer', 'string', 'iso_date', 'boolean', 'string_set', 'object', 'catalog_value'), 'Typed field role required')
            require(isinstance(node['qualifiers'], dict) and
                    (node['unit'] is None or _identifier(node['unit'])), 'Valid field qualifiers/unit required')
            if node['value_type'] == 'catalog_value':
                require(node.get('catalog_field') == node['field'] and isinstance(node.get('catalog_definition'), dict) and
                        node['unit'] == node['catalog_definition'].get('unit'), 'Exact catalogue declaration and unit required')
            if 'allowed_values' in node:
                require(isinstance(node['allowed_values'], list) and node['allowed_values'], 'Explicit value domain required')
            if 'minimum_value' in node:
                require(node['value_type'] in ('integer', 'number') and _typed(node['minimum_value'], 'number'),
                        'Numeric field bound required')
        if node['op'] == 'predicate':
            _supported(node['operator'] in ('eq', 'ge', 'le', 'contains', 'excludes'),
                       key, 'Unsupported predicate operator')
        if node['op'] == 'catalog_predicate':
            from .catalog_evidence import compile_predicate
            source = nodes.get(node['source'])
            require(source is not None and source['op'] == 'input' and source['value_type'] == 'catalog_value' and
                    source['catalog_field'] == node['predicate']['field'], 'Exact declared catalogue predicate source required')
            compile_predicate(source['catalog_definition'], node['predicate'])
            if 'requires_delivered_input' in node:
                gate = nodes.get(node['requires_delivered_input'])
                require(gate is not None and gate['op'] == 'input' and gate['value_type'] == 'boolean',
                        'Hidden predicate requires a typed delivered-reply input')
                visit(node['requires_delivered_input'])
        if node['op'] in ('all', 'any'):
            children = node['children']
            require(children and len(set(children)) == len(children), 'Nonempty unique dependencies required')
        else:
            children = [node['source']] if node['op'] != 'input' else []
        for child in children:
            visit(child)
        visiting.remove(key)
        visited.add(key)
    for key in nodes:
        visit(key)
    require(graph['roots'] and set(graph['roots']) <= nodes.keys(), 'Valid graph roots required')
    return nodes


def _typed(value, kind):
    if kind == 'number':
        return type(value) is int or (type(value) is float and math.isfinite(value))
    if kind == 'integer':
        return type(value) is int
    if kind == 'string':
        return _identifier(value)
    if kind == 'iso_date':
        from datetime import date
        if type(value) is not str:
            return False
        try:
            return date.fromisoformat(value).isoformat() == value
        except ValueError:
            return False
    if kind == 'boolean':
        return type(value) is bool
    if kind == 'string_set':
        return isinstance(value, list) and all(isinstance(v, str) for v in value) and len(set(value)) == len(value)
    if kind == 'object':
        return isinstance(value, dict) and bool(value)
    raise ValueError('Unsupported field value type')


def evaluate_graph(graph, observations, *, prefix_step, scope):
    """Three-valued proof evaluation over TRUSTED normalized prefix observations.

    This is not a raw-trace normalizer. The caller must verify assertion meanings,
    part coverage, state and receipt pins upstream. Each record declares confirmed
    delivery, exact candidate/state scope, unit/qualifiers and evidence references.
    No oracle input or inference from reasoning is accepted as prefix evidence.
    """
    require(type(prefix_step) is int and prefix_step >= 0 and isinstance(scope, dict) and scope,
            'Nonnegative prefix and exact candidate/state scope required')
    require(all(_identifier(scope.get(k)) for k in graph.get('required_scope_fields', [])),
            'Quote assessment requires exact candidate and effective-state scope')
    nodes = _validate_graph(graph)
    result = {}
    def evaluate(key):
        if key in result:
            return result[key]
        node = nodes[key]
        op, value, refs, pending, reason = node['op'], None, [], [], None
        if op == 'input':
            record = observations.get(node['field'])
            status = 'unknown'
            if record is None:
                reason = 'missing_evidence'
            elif (not isinstance(record, dict) or
                  not all(_identifier(scope.get(k)) for k in node.get('required_scope_fields', [])) or
                  record.get('scope') != scope or record.get('authority') != 'confirmed_model_request_delivery' or
                  type(record.get('delivered_step')) is not int or record['delivered_step'] < 0 or
                  record['delivered_step'] > prefix_step or record.get('parts_complete') is not True or
                  record.get('unit') != node['unit'] or
                  not isinstance(record.get('qualifiers'), dict) or
                  not all(type(record.get('qualifiers', {}).get(k)) is type(v) and
                          record['qualifiers'][k] == v for k, v in node['qualifiers'].items()) or
                  not isinstance(record.get('evidence_refs'), list) or not record['evidence_refs'] or
                  not all(_identifier(r) for r in record['evidence_refs'])):
                reason = 'unconfirmed_incomplete_or_incompatible_evidence'
            elif node['value_type'] == 'catalog_value' and record.get('logical_status') not in ('known', 'unknown', 'not_applicable'):
                reason = 'invalid_or_missing_logical_status'
            elif node['value_type'] == 'catalog_value' and record.get('logical_status') != 'known':
                reason = 'logical_status_' + str(record.get('logical_status', 'missing'))
            elif node['value_type'] == 'catalog_value' and not _valid_catalog_value(node, record.get('value')):
                reason = 'invalid_or_sentinel_catalog_value'
            elif node['value_type'] != 'catalog_value' and not _typed(record.get('value'), node['value_type']):
                reason = 'invalid_typed_value'
            elif ('allowed_values' in node and record['value'] not in node['allowed_values']) or (
                    'minimum_value' in node and record['value'] < node['minimum_value']):
                reason = 'unsupported_or_invalid_field_value'
            else:
                status, value, refs = 'true', deepcopy(record['value']), list(record['evidence_refs'])
            if status == 'unknown':
                pending = [key]
        elif op == 'predicate':
            child = evaluate(node['source'])
            status, refs, pending = child['status'], child['evidence_refs'], child['pending_inputs']
            if status == 'true':
                actual, expected, operator = child['value'], node['expected'], node['operator']
                _supported(operator in ('eq', 'ge', 'le', 'contains', 'excludes'), key, 'Unsupported predicate operator')
                if operator in ('contains', 'excludes'):
                    compatible = isinstance(actual, list) and isinstance(expected, str)
                    truth = expected in actual if compatible else None
                    if operator == 'excludes' and compatible:
                        truth = not truth
                elif operator in ('ge', 'le'):
                    compatible = (_typed(actual, 'number') and _typed(expected, 'number')) or (
                        nodes[node['source']].get('value_type') == 'iso_date' and
                        _typed(actual, 'iso_date') and _typed(expected, 'iso_date'))
                    truth = (actual >= expected if operator == 'ge' else actual <= expected) if compatible else None
                else:
                    compatible = type(actual) is type(expected) or (_typed(actual, 'number') and _typed(expected, 'number'))
                    truth = actual == expected if compatible else None
                status = 'true' if truth is True else 'false' if truth is False else 'unknown'
                if not compatible:
                    reason, pending = 'incompatible_predicate_types', [node['source']]
        elif op == 'catalog_predicate':
            from .catalog_evidence import compare
            child = evaluate(node['source'])
            status, refs, pending = child['status'], child['evidence_refs'], child['pending_inputs']
            if status == 'true':
                truth = compare(nodes[node['source']]['catalog_definition'], node['predicate'], child['value'])
                status = 'true' if truth is True else 'false' if truth is False else 'unknown'
            if 'requires_delivered_input' in node:
                gate = evaluate(node['requires_delivered_input'])
                if gate['status'] != 'true' or gate['value'] is not True:
                    status, value, reason = 'unknown', None, 'personal_requirement_not_delivered'
                    pending = [node['requires_delivered_input']]
                    refs = gate['evidence_refs']
                else:
                    refs = list(dict.fromkeys([*refs, *gate['evidence_refs']]))
        elif op == 'not':
            child = evaluate(node['source'])
            status = {'true': 'false', 'false': 'true', 'unknown': 'unknown'}[child['status']]
            refs, pending = child['evidence_refs'], child['pending_inputs']
        else:
            children = [evaluate(c) for c in node['children']]
            decisive = 'false' if op == 'all' else 'true'
            proof = next((c for c in children if c['status'] == decisive), None)
            if proof is not None:
                status, refs = decisive, proof['evidence_refs']
            else:
                status = 'unknown' if any(c['status'] == 'unknown' for c in children) else 'true' if op == 'all' else 'false'
                refs = [r for c in children for r in c['evidence_refs']]
                pending = [p for c in children for p in c['pending_inputs']]
        result[key] = dict(status=status, value=value, evidence_refs=sorted(set(refs)),
                           pending_inputs=sorted(set(pending)), reason=reason)
        if op == 'input' and node['value_type'] == 'catalog_value':
            record = observations.get(node['field'])
            result[key]['logical_status'] = (record.get('logical_status') if isinstance(record, dict)
                and (status == 'true' or reason.startswith('logical_status_')) else None)
        return result[key]
    roots = {key: evaluate(key) for key in graph['roots']}
    return dict(schema='conditional-requirement-assessment-v1', prefix_step=prefix_step,
        scope=deepcopy(scope), roots=roots, nodes=result,
        assessment_scope='trusted_prefix_evidence_not_oracle_or_policy_belief')


def _valid_catalog_value(node, value):
    from .catalog_evidence import valid_value
    return valid_value(value, node['catalog_definition'], node['catalog_field'])
