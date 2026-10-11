"""Recipe-bound suite adapters; native truth never establishes public delivery.

Factories come from the caller's checked frozen producer, not mutable imports.
The existing common compiler remains the default for established task schemas.
"""
from copy import deepcopy

from .fact_exposure import object_digest, require
from .task_requirements import compile_task, input_node, _validate_graph


def compile_suite_task(task, *, native_inputs=None, scoring_reference=None):
    schema = task.get('schema_version')
    if schema == 'website-atomic-product-task-v1':
        from .atomic_product_requirements import compile_atomic
        require(isinstance(native_inputs, dict) and set(native_inputs) ==
                {'native_make', 'world', 'catalog', 'bindings', 'checkout_domain'},
                'Exact checked atomic inputs required')
        require(scoring_reference is None, 'Atomic tasks do not accept order references')
        return compile_atomic(task, **native_inputs)
    if schema == 'website-variant-link-task-v1':
        from .action_task_requirements import compile_link
        require(isinstance(native_inputs, dict) and set(native_inputs) ==
                {'native_make', 'world', 'catalog', 'bindings', 'navigation_capability',
                 'acceptance_verified'}, 'Exact checked link/capability inputs required')
        require(scoring_reference is None, 'Link tasks do not accept order references')
        return compile_link(task, **native_inputs)
    if schema == 'website-cart-task-instance-v1':
        require(isinstance(native_inputs, dict) and set(native_inputs) ==
                {'native_make', 'world', 'checkout_domain'}, 'Exact checked cart-instance inputs required')
        require(scoring_reference is None, 'Cart instances do not accept order references')
        return compile_cart_instance(task, **native_inputs)
    return compile_task(task, action_inputs=native_inputs, scoring_reference=scoring_reference)


def compile_cart_instance(task, *, native_make, world, checkout_domain):
    """Validate the original constructor before deriving its two distinct scopes."""
    require(callable(native_make), 'Checked native instance factory required')
    checkout = task.get('scope') == 'existing_cart_only'
    require(checkout or task.get('scope') == 'new_additions', 'Supported explicit cart-instance scope required')
    canonical = native_make(world, task['parameters'], checkout_domain,
                          baseline_task=task['base_task'] if checkout else None, checkout=checkout)
    require(object_digest(canonical) == object_digest(task), 'Canonical instance/world/initial-storage mismatch')
    if checkout:
        from .checkout_details_requirements import compile_checkout_details
        result = deepcopy(compile_checkout_details(task['base_task']))
        # Native base contains historical matching requirements. This instance
        # expressly prohibits additions and has no new-product search obligation.
        result['information_needs'] = [n for n in result['information_needs']
            if n['entity_scope'] in ('self_current_address_memory', 'self_memory', 'retailer_cart_form_state')]
        result['candidate_graph'] = deepcopy(result['memory_graph'])
        result['global_requirements'] = [n for n in result['global_requirements']
            if n['id'] not in ('new_units_coverage', 'cart_feasibility')]
        result['semantics'].update(requirements=[], objective=None,
            mutable_retailer_rule='retailers_with_actual_initial_cart',
            delivery_selection_scope=task['delivery_selection_scope'],
            protected_cart_quantities=True, price_ranking=False)
        for need in result['information_needs']:
            if need['entity_scope'] == 'retailer_cart_form_state':
                need['qualifiers']['retailer_role'] = 'has_actual_initial_cart'
        for node in result['delivery_state_graph']['nodes']:
            if node.get('op') == 'input':
                node['qualifiers']['retailer_role'] = 'has_actual_initial_cart'
        if task['delivery_selection_scope'] == 'valid_home_service':
            result['information_needs'].append(dict(id='selected_home_service',
                field_role='cart_service_selections', entity_scope='retailer_cart_state', unit=None,
                qualifiers={'retailer_role': 'has_actual_initial_cart', 'allowed_modes': ['home']},
                task_source_path='delivery_selection_scope', producer_assertion_id=None,
                source_mapping='not_bound'))
            result['global_requirements'].append(dict(id='valid_home_service',
                operation='native_valid_selected_home_service_for_existing_cart',
                price_ranking=False, exposure_established=False))
        for rule in result['global_requirements']:
            if rule.get('scope') == 'retailers_receiving_new_requested_units':
                rule['scope'] = 'retailers_with_actual_initial_cart'
            if rule.get('mutable_retailer_rule') == 'retailers_receiving_new_requested_units':
                rule['mutable_retailer_rule'] = 'retailers_with_actual_initial_cart'
    else:
        from .cart_requirements import compile_cart
        result = deepcopy(compile_cart(task['base_task']))
        require(task['objective'] == 'minimum_item_subtotal_minor', 'Exact item-subtotal objective required')
        node = input_node('addition_item_price', 'listed_price_minor', 'integer', unit='SEK_minor',
                          qualifiers={'basis': 'new_additions_only', 'shipping_excluded': True})
        result['candidate_graph']['nodes'].append(node)
        result['information_needs'].append(dict(id=node['id'], field_role=node['field'],
            entity_scope='offer', unit=node['unit'], qualifiers=deepcopy(node['qualifiers']),
            task_source_path='objective', producer_assertion_id=None, source_mapping='not_bound'))
        result['semantics'].update(objective=task['objective'], price_ranking=True,
                                  initial_units_count_toward_new_demand=False)
        result['global_requirements'].append(dict(id='addition_item_subtotal',
            operation='minimum_item_subtotal_of_disjoint_new_unit_allocation',
            shipping_excluded=True, delivery_speed_excluded=True, observed_optimality=False))
    for need in result['information_needs']:
        if need['task_source_path'] not in ('objective', 'delivery_selection_scope'):
            need['task_source_path'] = 'base_task.' + need['task_source_path']
    result.update(source_schema=task['schema_version'], task_id=task['task_id'],
                  task_sha256=object_digest(task))
    result['semantics'].update(instance_scope=task['scope'],
        initial_storage_sha256=task['initial_storage_sha256'],
        parameters=deepcopy(task['parameters']), exposure_established=False)
    result['semantic_sha256'] = object_digest(result['semantics'])
    result['public_task_context'] = dict(user_message=task['user_message'], memories=deepcopy(task['memories']))
    _validate_graph(result['candidate_graph'])
    return result
