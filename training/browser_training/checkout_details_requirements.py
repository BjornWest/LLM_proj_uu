"""Typed new-unit checkout requirements; public memories are not observed facts."""
from copy import deepcopy
import hashlib
from pathlib import Path

from .cart_requirements import compile_cart
from .commerce_state_requirements import bind_offer_universe
from .fact_exposure import object_digest, require
from .task_requirements import VERSION, _supported, _validate_graph, input_node, predicate_node

ROOT = Path(__file__).resolve().parents[2]


def compile_checkout_details(task):
    from environments.website_world import catalog_checkout_details_task as native
    from environments.website_world.catalog_basket_task import Inventory
    allowed = {'schema_version', 'kind', 'requirements', 'initial_cart', 'delivery_note', 'world_id', 'world_sha256',
        'checkout_domain_sha256', 'cart_task', 'delivery_address', 'delivery_location_id', 'quantity_basis', 'availability',
        'user_message', 'memories', 'memory_meanings', 'task_id'}
    _supported(isinstance(task, dict) and set(task) == allowed, '$', 'Exact native checkout-details clauses required')
    require(task['schema_version'] == native.VERSION and task['kind'] == native.KIND and
        task['quantity_basis'] == 'retail_sale_units' and task['availability'] == 'positive_dispatch_stock' and
        task['delivery_location_id'] == 'user-home', 'Known self-recipient dispatch checkout contract required')
    selection = native.selection(task)
    require(native.resolve(selection, concept_ids=sorted({r['concept_id'] for r in task['requirements']}), inventory=Inventory()) == selection,
        'Canonical typed checkout/cart selection required')
    cart = task['cart_task']; template = compile_cart(cart)
    require(all(cart[k] == task[k] for k in ('requirements', 'initial_cart', 'world_id', 'world_sha256',
        'checkout_domain_sha256', 'quantity_basis', 'availability')), 'Inner cart and outer task scope mismatch')
    address = task['delivery_address']; note = task['delivery_note']
    require(isinstance(address, dict) and set(address) == set(native.ADDRESS_FIELDS) and
        all(type(address[k]) is str and (bool(address[k].strip()) or k == 'unit') for k in native.ADDRESS_FIELDS) and
        address['country'] == 'SE', 'Complete declared current Swedish delivery address required')
    meanings = [dict(kind='current_delivery_address', recipient='self', value=deepcopy(address)),
        dict(kind='delivery_instructions', recipient='self', value=note)]
    memory = ('My current delivery address is ' + address['recipient'] + ', ' + address['street'] + ' ' + address['house_number'] +
        (', apartment/unit ' + address['unit'] if address['unit'] else '') + ', ' + address['postcode'] + ' ' + address['city'] + ', Sweden.')
    require(task['memory_meanings'] == meanings and task['memories'] == [memory,
        'My saved delivery note, to copy verbatim: ' + note], 'Original public memories and typed self meanings required')
    needs = deepcopy(template['information_needs'])
    for n in needs: n['task_source_path'] = 'cart_task.' + n['task_source_path']
    memory_nodes = []
    for field in native.ADDRESS_FIELDS:
        identifier = 'current_address_' + field
        qualifiers = dict(recipient='self', address_role='current_delivery_address', location_id='user-home',
            memory_index=0, private_meaning_path='memory_meanings[0].value.' + field)
        node = input_node(identifier, identifier, 'string', qualifiers=qualifiers)
        memory_nodes.append(node)
        needs.append(dict(id=identifier, field_role=identifier, entity_scope='self_current_address_memory', unit=None,
            qualifiers=deepcopy(qualifiers), task_source_path='delivery_address.' + field,
            producer_assertion_id=None, source_mapping='not_bound', exposure_status='unknown'))
    memory_nodes.append(input_node('current_delivery_note', 'current_verbatim_delivery_note', 'string',
        qualifiers=dict(recipient='self', memory_index=1, comparison='exact_text', private_meaning_path='memory_meanings[1].value')))
    needs.append(dict(id='current_delivery_note', field_role='current_verbatim_delivery_note', entity_scope='self_memory', unit=None,
        qualifiers=deepcopy(memory_nodes[-1]['qualifiers']), task_source_path='delivery_note', producer_assertion_id=None,
        source_mapping='not_bound', exposure_status='unknown'))
    memory_graph = dict(nodes=memory_nodes + [dict(id='current_details_available', op='all',
        children=[n['id'] for n in memory_nodes])], roots=['current_details_available'])
    _validate_graph(memory_graph)
    state_nodes = []
    native_root = Path(native.__file__).resolve().parents[2]
    native_sources = {n: hashlib.sha256((native_root / n).read_bytes()).hexdigest() for n in [
        'environments/website_world/catalog_checkout_details_task.py',
        'environments/website_world/catalog_checkout_details_grading.py']}
    for identifier, field in [('saved_address_match', 'actual_saved_address_matches_current_self_address'),
        ('remembered_address_match', 'actual_local_remembered_address_matches_current_self_address'),
        ('saved_valid_form', 'actual_saved_address_status_valid'),
        ('verbatim_delivery_note', 'actual_saved_instructions_equal_current_note')]:
        qualifier = dict(retailer_role='receives_requested_new_units', source='original_actual_storage_capture',
            address_comparison='native_address_matches_including_recipient_unit_and_location',
            note_comparison='exact_text', semantic_source_sha256=deepcopy(native_sources))
        state_nodes += [input_node(identifier, field, 'boolean', qualifiers=qualifier),
            predicate_node(identifier + '_passed', identifier, 'eq', True)]
        needs.append(dict(id=identifier, field_role=field, entity_scope='retailer_cart_form_state', unit=None,
            qualifiers=qualifier, task_source_path='kind', producer_assertion_id=None,
            source_mapping='not_bound', exposure_status='unknown'))
    state_nodes.append(dict(id='selected_retailer_details_ready', op='all',
        children=[n['id'] for n in state_nodes if n['op'] == 'predicate']))
    state_graph = dict(nodes=state_nodes, roots=['selected_retailer_details_ready'],
        required_scope_fields=['retailer_id', 'cart_id', 'state_id', 'capture_phase'])
    _validate_graph(state_graph)
    semantics = deepcopy(template['semantics'])
    semantics.update(operation=native.KIND, selection=selection, delivery_address=deepcopy(address), delivery_note=note,
        memory_meanings=deepcopy(meanings), semantic_source_sha256=native_sources,
        protected_fields=['coupon', 'orders'], selectively_mutable_fields=['address', 'remembered', 'instructions'],
        mutable_retailer_rule='retailers_receiving_new_requested_units',
        non_target_preserved_fields=['address', 'remembered', 'instructions'],
        non_target_address_status_graded=False, memory_presence_establishes_attention=False,
        address_comparison='native_address_matches_complete_recipient_unit_location_not_literal_format_only',
        instructions_comparison='verbatim', saved_form_status='valid', durable_user_memory_write=False,
        no_match='leave_all_actual_initial_baskets_and_delivery_details_unchanged')
    global_requirements = deepcopy(template['global_requirements'])
    for rule in global_requirements:
        if rule['id'] == 'cart_state':
            rule['protected_fields'] = ['coupon', 'orders']
            rule['selectively_mutable_fields'] = ['address', 'remembered', 'instructions']
            rule['mutable_retailer_rule'] = 'retailers_receiving_new_requested_units'
    global_requirements += [dict(id='selected_retailer_details', operation='native_saved_form_checks',
        scope='retailers_receiving_new_requested_units', graph='delivery_state_graph',
        raw_capture_required=True, answers_supply_state=False),
        dict(id='other_retailer_details', operation='actual_before_after_equality',
            fields=['address', 'remembered', 'instructions'], scope='all_other_retailers',
            address_status_graded=False),
        dict(id='current_memory_context', operation='typed_self_memory_delivery',
            graph='memory_graph', establishes_reading=False)]
    return dict(schema=VERSION, source_schema=native.VERSION, task_id=task['task_id'], task_sha256=object_digest(task),
        semantic_sha256=object_digest(semantics), semantics=semantics, world_binding=deepcopy(template['world_binding']),
        information_needs=needs, candidate_graph=deepcopy(template['candidate_graph']),
        cart_template=template, memory_graph=memory_graph, delivery_state_graph=state_graph,
        global_requirements=global_requirements,
        public_task_context=dict(user_message=task['user_message'], memories=deepcopy(task['memories'])),
        capability=dict(task_semantics='prepared_native_contract', runtime_packet_acceptance='pending',
            source_mapping='not_bound', exposure_mapping='not_bound', attention='unknown',
            global_evidence_assessment='not_implemented', original_effect_envelope=None,
            approved_saved_projection='not_adopted', state_grading='native_actual_capture_not_answer_extraction'),
        analysis_views=['confirmed_prefix_evidence', 'authoritative_world_relevance'], oracle_relevance=None)


def bind_checkout_details(compiled, world, bindings=None, *, surrounding=None, site_registry=None,
        model_routes=None, checkout_domain=None, basket_plan=None, admission_plan=None):
    from environments.website_world import catalog_checkout_details_task as native
    require(checkout_domain is not None and model_routes is None and admission_plan is None,
        'Checkout details require complete cart domain, not delivery-method/menu selection')
    require(object_digest(native.make(world, compiled['semantics']['selection'], checkout_domain=checkout_domain)) ==
        compiled['task_sha256'], 'Exact native checkout/world/domain/current-memory binding required')
    result = bind_offer_universe(compiled, world, bindings, checkout_domain,
        surrounding=surrounding, site_registry=site_registry)
    for site in result['sites']:
        site['delivery_details_dependency'] = dict(required_if='receives_requested_new_units',
            memory_scope='self', state_graph='delivery_state_graph', public_exposure='unknown')
        for candidate in site['candidates']:
            candidate['potential_requirements'] = [r['requirement_id'] for r in compiled['semantics']['requirements']
                if r['concept_id'] == candidate['concept_id']]
    result['current_memory_context'] = deepcopy(compiled['public_task_context'])
    result['memory_presence_is_attention'] = False
    return result
