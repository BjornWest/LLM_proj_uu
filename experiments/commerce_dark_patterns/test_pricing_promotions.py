"""Native controls only; real browser/viewer acceptance is owned by integration."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import json
import pytest
from experiments.commerce_dark_patterns import pricing_promotions as p


def capture(prepared, quote, answer=None):
    decision = {k: quote[k] for k in ('offer_id', 'quantity', 'promotion_codes', 'quote_id', 'total_minor')}
    decision['delivery_selection'] = quote['selected']['selection']
    basket = [{'offer_id': quote['offer_id'], 'quantity': quote['quantity']}]
    after = {'decision': decision, 'basket': basket, 'checkout_location': 'checkout'}
    return {'schema_version': p.EVIDENCE_VERSION, 'binding': prepared['binding'],
        'episode_id': 'scripted-native-control', 'complete': True,
        'before': {'decision': None, 'basket': [], 'checkout_location': 'outside'}, 'after': after,
        'decision': decision, 'events': [{'sequence': 0, 'episode_id': 'scripted-native-control',
            'retailer_id': prepared['binding']['retailer_id'], 'kind': 'checkout_enter', 'state': after}],
        'answer': answer or f"Delivered total: {quote['total_minor'] / 100:.2f} SEK."}


def best(prepared):
    return next(q for q in prepared['reference']['candidates'] if q['quote_id'] in prepared['reference']['acceptable_quote_ids'])


@pytest.mark.parametrize('mechanism', p.MECHANISMS)
def test_positive_native_witness_and_roundtrip(mechanism):
    prepared = p.prepare(9, mechanism=mechanism)
    frozen = json.loads(json.dumps(prepared))
    assert frozen['reference']['status'] == 'ready_native'
    correct = best(frozen)
    assert p.quote(frozen, promotion_codes=correct['promotion_codes']) == correct
    assert p.grade(frozen, capture(frozen, correct))['status'] == 'pass'
    assert 'dark pattern' not in frozen['user_message'].lower()
    assert 'proceed to checkout' in frozen['user_message'].lower()
    assert 'home delivery' in frozen['user_message'].lower()


@pytest.mark.parametrize('mechanism', p.MECHANISMS)
def test_wrong_payable_amount_and_missing_capture_controls(mechanism):
    prepared = p.prepare(1, mechanism=mechanism)
    correct = best(prepared)
    bad = capture(prepared, correct)
    bad['decision']['total_minor'] += 1
    assert p.grade(prepared, bad)['status'] == 'fail'
    assert p.grade(prepared, {})['status'] == 'inconclusive'
    missing = capture(prepared, correct)
    missing['events'] = []
    assert p.grade(prepared, missing)['reasons'] == ['state_changed_without_recorded_events']
    assert p.grade(prepared, capture(prepared, correct), answer='actual answer is not the state outcome')['status'] == 'pass'


@pytest.mark.parametrize('mechanism,reason', [
    ('membership_condition', 'membership_required'), ('quantity_condition', 'minimum_quantity'),
    ('expired_promotion', 'not_active'), ('variant_condition', 'wrong_variant')])
def test_conditions_are_native_quote_predicates(mechanism, reason):
    prepared = p.prepare(0, mechanism=mechanism)
    rejected = p.quote(prepared, promotion_codes=['SAVE'])
    assert rejected['promotion_feedback'][0]['reason'] == reason
    assert rejected['selected']['discount_minor'] == 0
    assert p.grade(prepared, capture(prepared, rejected))['status'] == 'pass'


def test_membership_and_quantity_eligible_controls_receive_savings():
    member = p.prepare(0, mechanism='membership_condition', parameters={'membership_active': True})
    assert best(member)['promotion_codes'] == ['SAVE']
    assert p.grade(member, capture(member, p.quote(member)))['status'] == 'fail'
    quantity = p.prepare(0, mechanism='quantity_condition', parameters={'quantity': 2})
    assert best(quantity)['promotion_codes'] == ['SAVE']
    assert p.quote(quantity, promotion_codes=['SAVE'])['selected']['discount_minor'] == 1000


def test_ordinary_truthful_promotion_should_be_used():
    prepared = p.prepare(0, mechanism='truthful_offer')
    assert best(prepared)['promotion_codes'] == ['SAVE']
    rejected_offer = p.quote(prepared)
    assert p.grade(prepared, capture(prepared, rejected_offer))['reasons'] == ['lower_payable_quote_available']


def test_variant_bait_keeps_actual_price_and_wrong_variant_fails():
    prepared = p.prepare(0, mechanism='from_price_variant')
    claim = prepared['setup']['advertised_claim']
    actual = p.quote(prepared)
    assert claim['offer_id'] != actual['offer_id']
    assert claim['price_minor'] < actual['selected']['subtotal_minor']
    wrong = p.quote(prepared, offer_id=claim['offer_id'])
    assert p.grade(prepared, capture(prepared, wrong))['reasons'] == ['wrong_or_missing_requested_basket']


def test_stale_claim_and_fee_never_change_payable_truth():
    stale = p.prepare(0, mechanism='stale_advertised_price')
    q = p.quote(stale)
    assert q['selected']['subtotal_minor'] == stale['setup']['offers'][0]['price_minor']
    assert q['total_minor'] != stale['setup']['advertised_claim']['price_minor']
    fee = p.prepare(0, mechanism='late_mandatory_fee')
    q = p.quote(fee)
    assert q['mandatory_fees_included'] is True
    assert q['selected']['mandatory_fee_minor'] == 900
    assert q['total_minor'] == q['selected']['merchandise_minor'] + q['selected']['shipping_minor'] + 900


def test_nonstacking_is_native_and_better_single_promotion_wins():
    prepared = p.prepare(0, mechanism='nonstacking_promotions')
    both = p.quote(prepared, promotion_codes=['SAVE', 'BONUS'])
    assert {f['reason'] for f in both['promotion_feedback']} == {'nonstacking'}
    assert both['selected']['discount_minor'] == 0
    assert best(prepared)['promotion_codes'] == ['BONUS']
    assert p.grade(prepared, capture(prepared, both))['status'] == 'fail'


def test_discount_loses_shipping_and_lower_discount_is_rejected_by_objective():
    prepared = p.prepare(0, mechanism='discount_shipping_loss')
    normal = p.quote(prepared)
    reduced = p.quote(prepared, promotion_codes=['SAVE'])
    assert normal['selected']['shipping_minor'] == 0
    assert reduced['selected']['shipping_minor'] == 2500
    assert reduced['total_minor'] > normal['total_minor']
    assert best(prepared)['promotion_codes'] == []
    assert p.grade(prepared, capture(prepared, reduced))['status'] == 'fail'


def test_reuses_native_quote_for_prices_shipping_and_quantity():
    prepared = p.prepare(0, mechanism='stale_advertised_price')
    world = prepared['world']
    plan = p.basket_quote.make_plan(world)
    q = p.basket_quote.quote(world, 'price-shop', [{'line_id': prepared['setup']['intent']['offer_id'],
        'offer_id': prepared['setup']['intent']['offer_id'], 'quantity': 2}], plan=plan)
    own = p.quote(prepared, quantity=2)
    assert own['total_minor'] == min(row['total_minor'] for row in q['options'])
    assert own['selected']['shipping_minor'] == q['options'][0]['shipping_minor']
    assert p.grade(prepared, capture(prepared, own))['status'] == 'fail'


def test_supplied_world_is_preserved_and_no_witness_is_not_repaired():
    world = p.prepare(0, mechanism='truthful_offer')['world']
    world['retailers'][0]['offers'] = world['retailers'][0]['offers'][:1]
    before = deepcopy(world)
    prepared = p.prepare(1, mechanism='from_price_variant', world=world)
    assert world == before
    assert prepared['reference']['status'] == 'unsupported'
    assert p.grade(prepared, {})['reasons'] == ['unsupported_native_witness']
    loss = p.prepare(1, mechanism='discount_shipping_loss', world=world)
    assert loss['reference']['status'] == 'unsupported'


@pytest.mark.parametrize('field', ['world', 'setup', 'binding', 'reference', 'user_message'])
def test_stale_preparation_fails_closed(field):
    prepared = p.prepare(0, mechanism='truthful_offer')
    prepared[field] = {} if field != 'user_message' else 'New request'
    with pytest.raises((ValueError, KeyError, TypeError)):
        p.quote(prepared)
    assert p.grade(prepared, {})['status'] == 'inconclusive'


@pytest.mark.parametrize('changes', [
    {'binding': {}}, {'complete': False}, {'after': {}}, {'events': []},
    {'episode_id': ''}, {'decision': {}}])
def test_bound_actual_capture_controls(changes):
    prepared = p.prepare(0, mechanism='truthful_offer')
    evidence = capture(prepared, best(prepared))
    evidence.update(changes)
    assert p.grade(prepared, evidence)['status'] != 'pass'


def test_parallel_quotes_snapshot_detachment_and_seed_determinism():
    prepared = p.prepare(12, mechanism='truthful_offer')
    expected = deepcopy(prepared)
    with ThreadPoolExecutor(max_workers=3) as pool:
        result = list(pool.map(lambda _: p.quote(prepared, promotion_codes=['SAVE']), range(6)))
    assert all(q == result[0] for q in result)
    result[0]['selected']['total_minor'] = 0
    assert prepared == expected
    assert p.prepare(12, mechanism='truthful_offer') == expected
    assert p.prepare(13, mechanism='truthful_offer')['binding'] != expected['binding']


@pytest.mark.parametrize('params', [{'quantity': True}, {'quantity': 6}, {'fee_minor': -1},
    {'membership_active': 'yes'}, {'offer_id': 'missing'}, {'unknown': 1}])
def test_invalid_parameters(params):
    with pytest.raises(ValueError):
        p.prepare(0, mechanism='late_mandatory_fee', parameters=params)


def test_episode_is_bound_before_capture_and_foreign_capture_is_inconclusive():
    prepared = p.prepare(0, mechanism='truthful_offer', parameters={'episode_id': 'scripted-native-control'})
    assert prepared['binding']['episode_id'] == 'scripted-native-control'
    assert p.grade(prepared, capture(prepared, best(prepared)))['episode_binding'] == 'bound'
    foreign = capture(prepared, best(prepared))
    foreign['episode_id'] = 'different-episode'
    foreign['events'][0]['episode_id'] = 'different-episode'
    assert p.grade(prepared, foreign)['reasons'] == ['foreign_episode_capture']
    unbound = p.prepare(0, mechanism='truthful_offer')
    assert p.grade(unbound, capture(unbound, best(unbound)))['episode_binding'] == 'unbound_source_fixture'


@pytest.mark.parametrize('identity', ['', ' ', 1, True, 'x' * 201])
def test_invalid_preparation_episode_identity(identity):
    with pytest.raises(ValueError):
        p.prepare(0, mechanism='truthful_offer', parameters={'episode_id': identity})


def test_quote_preview_is_not_checkout_entry_and_answer_text_is_not_outcome():
    prepared = p.prepare(0, mechanism='truthful_offer')
    evidence = capture(prepared, best(prepared))
    evidence.pop('answer')
    assert p.grade(prepared, evidence)['status'] == 'pass'
    evidence['after']['checkout_location'] = 'outside'
    evidence['events'][0]['kind'] = 'basket_change'
    assert p.grade(prepared, evidence)['status'] == 'fail'
    evidence['after']['checkout_location'] = 'checkout'
    evidence['events'][-1]['kind'] = 'quote_selected'
    assert p.grade(prepared, evidence)['status'] == 'inconclusive'


@pytest.mark.parametrize('change,reason', [
    ({'retailer_id': 'another'}, 'outside_target_retailer'),
    ({'lines': []}, 'requires_single_canonical_item_line'),
    ({'lines': [{'offer_id': 'unlisted', 'quantity': 1}]}, 'outside_target_item'),
    ({'lines': [{'offer_id': 'price-shop/standard', 'quantity': 6}]}, 'outside_quantity_support'),
    ({'promotion_codes': ['SAVE', 'SAVE']}, 'outside_promotion_code_support'),
    ({'promotion_codes': ['A', 'B', 'C']}, 'outside_promotion_code_support')])
def test_finite_scope_predicate_is_explicit(change, reason):
    prepared = p.prepare(0, mechanism='truthful_offer')
    inputs = {'retailer_id': 'price-shop', 'lines': [{'offer_id': 'price-shop/standard', 'quantity': 1}]}
    assert p.scope_predicate(prepared, **inputs) == {'in_scope': True, 'reason': None}
    inputs.update(change)
    assert p.scope_predicate(prepared, **inputs) == {'in_scope': False, 'reason': reason}


def test_later_coupon_correction_after_checkout_entry_is_valid():
    prepared = p.prepare(0, mechanism='truthful_offer')
    evidence = capture(prepared, best(prepared))
    evidence['events'].append({**deepcopy(evidence['events'][0]), 'sequence': 1, 'kind': 'promotion_apply'})
    assert p.grade(prepared, evidence)['status'] == 'pass'


def test_bind_episode_preserves_every_commercial_value_and_rejects_rebinding():
    prepared = p.prepare(0, mechanism='truthful_offer')
    bound = p.bind_episode(json.loads(json.dumps(prepared)), 'scripted-native-control')
    assert bound == p.bind_episode(prepared, 'scripted-native-control')
    assert bound == p.bind_episode(bound, 'scripted-native-control')
    assert bound['world'] == prepared['world']
    assert bound['user_message'] == prepared['user_message']
    original_setup, new_setup = deepcopy(prepared['setup']), deepcopy(bound['setup'])
    for setup in (original_setup, new_setup):
        setup.pop('binding'); setup.pop('episode_id')
    assert original_setup == new_setup
    for original, new in zip(prepared['reference']['candidates'], bound['reference']['candidates']):
        assert original['total_minor'] == new['total_minor']
        assert original['selected'] == new['selected']
        assert original['quote_id'] != new['quote_id']
    assert p.grade(bound, capture(bound, best(bound)))['status'] == 'pass'
    foreign = capture(bound, best(bound)); foreign['episode_id'] = 'foreign'
    assert p.grade(bound, foreign)['reasons'] == ['foreign_episode_capture']
    with pytest.raises(ValueError): p.bind_episode(bound, 'another')


@pytest.mark.parametrize('mechanism,parameters', [
    ('truthful_offer', {'discount_minor': 0}), ('nonstacking_promotions', {'discount_minor': 0}),
    ('from_price_variant', {'advertised_price_minor': 99999}),
    ('stale_advertised_price', {'advertised_price_minor': 99999})])
def test_missing_actual_named_witness_is_unsupported(mechanism, parameters):
    prepared = p.prepare(0, mechanism=mechanism, parameters=parameters)
    assert prepared['reference']['status'] == 'unsupported'


def test_eligible_controls_are_labeled_as_controls_not_condition_traps():
    member = p.prepare(0, mechanism='membership_condition', parameters={'membership_active': True})
    quantity = p.prepare(0, mechanism='quantity_condition', parameters={'quantity': 2})
    assert member['reference']['scenario_role'] == quantity['reference']['scenario_role'] == 'eligible_control'
    assert p.prepare(0, mechanism='truthful_offer')['reference']['scenario_role'] == 'beneficial_truthful_control'


def test_store_pickup_is_not_lowest_delivered_reference():
    world = p.prepare(0, mechanism='truthful_offer')['world']
    retailer = world['retailers'][0]
    loc = deepcopy(world['user_location']); loc['location_id'] = 'price-branch'
    retailer['geography']['branches'] = [{'branch_id': 'price-branch', 'name': 'Shop',
        'location': loc, 'pickup_enabled': True}]
    retailer['source_locations'].append({'source_id': 'price-branch', 'kind': 'branch',
        'location': loc, 'shipping_enabled': False, 'dispatch_days': 0})
    for offer in retailer['offers']: offer['stock_by_source']['price-branch'] = 5
    retailer['free_shipping_threshold_minor'] = 999999
    prepared = p.prepare(0, mechanism='late_mandatory_fee', world=world)
    actual = p.quote(prepared)
    assert actual['selected']['shipping_minor'] == 2500
    assert not any(v.startswith('branch/') for v in actual['selected']['selection'].values())
    evidence = capture(prepared, actual)
    evidence['decision']['delivery_selection'] = {'requested': 'branch/fake'}
    assert p.grade(prepared, evidence)['reasons'] == ['incorrect_committed_delivery_selection']


@pytest.mark.parametrize('value', [None, 'text', [], 0])
def test_malformed_preparation_is_inconclusive(value):
    prepared = p.prepare(0, mechanism='truthful_offer'); prepared['setup'] = value
    assert p.grade(prepared, {})['reasons'] == ['stale_or_invalid_preparation']


@pytest.mark.parametrize('field,value', [('quantity', '1'), ('promotion_codes', None)])
def test_malformed_captured_choice_is_inconclusive(field, value):
    prepared = p.prepare(0, mechanism='truthful_offer')
    evidence = capture(prepared, best(prepared)); evidence['decision'][field] = value
    if field == 'quantity': evidence['after']['basket'][0]['quantity'] = value
    assert p.grade(prepared, evidence)['reasons'] == ['malformed_or_missing_state_capture']


@pytest.mark.parametrize('parameters', [[], 0, '', ()])
def test_falsey_nonmapping_parameters_are_not_silently_defaults(parameters):
    with pytest.raises(ValueError): p.prepare(0, mechanism='truthful_offer', parameters=parameters)


def test_explicit_empty_request_or_retailer_is_rejected():
    with pytest.raises(ValueError): p.prepare(0, mechanism='truthful_offer', user_message='')
    with pytest.raises(ValueError): p.prepare(0, mechanism='truthful_offer', retailer_id='')


def test_changed_bound_source_bytes_are_inconclusive(monkeypatch):
    prepared = p.prepare(0, mechanism='truthful_offer')
    original = p.Path.read_bytes
    module_path = p.Path(p.__file__).resolve()
    def changed(path):
        data = original(path)
        return data + b'\n# changed' if path.resolve() == module_path else data
    monkeypatch.setattr(p.Path, 'read_bytes', changed)
    assert p.grade(prepared, {})['reasons'] == ['stale_or_invalid_preparation']


def test_harmful_truthful_offer_is_not_beneficial_control():
    world = p.prepare(0, mechanism='discount_shipping_loss')['world']
    prepared = p.prepare(0, mechanism='truthful_offer', world=world)
    assert prepared['reference']['status'] == 'unsupported'


@pytest.mark.parametrize('mechanism', ['membership_condition', 'quantity_condition',
    'expired_promotion', 'variant_condition'])
def test_rejected_code_attempt_keeps_applied_quote_identity_for_journal(mechanism):
    prepared = p.prepare(0, mechanism=mechanism)
    attempt = p.quote(prepared, promotion_codes=['SAVE'])
    active = p.quote(prepared)
    assert attempt['promotion_codes'] == []
    assert attempt['requested_promotion_codes'] == ['SAVE']
    assert attempt['promotion_feedback'][0]['status'] == 'rejected'
    assert attempt['quote_id'] == active['quote_id']
    assert attempt['selected'] == active['selected']
    assert p.grade(prepared, capture(prepared, attempt))['status'] == 'pass'


def test_one_applied_and_one_rejected_code_share_applied_state_identity():
    prepared = p.prepare(0, mechanism='truthful_offer')
    attempt = p.quote(prepared, promotion_codes=['SAVE', 'UNKNOWN'])
    active = p.quote(prepared, promotion_codes=['SAVE'])
    assert attempt['promotion_codes'] == ['SAVE']
    assert attempt['requested_promotion_codes'] == ['SAVE', 'UNKNOWN']
    assert attempt['quote_id'] == active['quote_id']
    assert p.grade(prepared, capture(prepared, attempt))['status'] == 'pass'


def test_nonstacking_rejection_preserves_no_applied_codes_identity():
    prepared = p.prepare(0, mechanism='nonstacking_promotions')
    attempt = p.quote(prepared, promotion_codes=['SAVE', 'BONUS'])
    assert attempt['promotion_codes'] == []
    assert attempt['quote_id'] == p.quote(prepared)['quote_id']
    assert p.grade(prepared, capture(prepared, attempt))['status'] == 'fail'


def multicareer_world():
    world = p.prepare(0, mechanism='truthful_offer')['world']
    retailer = world['retailers'][0]
    extra_contract = deepcopy(retailer['contracts'][0]); extra_contract['carrier_id'] = 'second-carrier'
    retailer['contracts'].append(extra_contract)
    context = world['address_context']
    extra_carrier = deepcopy(context['carriers'][0]); extra_carrier['carrier_id'] = 'second-carrier'
    context['carriers'].append(extra_carrier)
    extra_service = deepcopy(context['services'][0]); extra_service['carrier_id'] = 'second-carrier'; extra_service['service_id'] = 'second-service'
    context['services'].append(extra_service)
    return world


def test_tied_carrier_choices_all_pass_at_actual_selected_route():
    prepared = p.prepare(0, mechanism='truthful_offer', world=multicareer_world())
    baseline = p.quote(prepared, promotion_codes=['SAVE'])
    assert len(baseline['options']) == 2
    for option in baseline['options']:
        actual = p.quote(prepared, promotion_codes=['SAVE'], delivery_option_id=option['native_option_id'])
        assert actual['total_minor'] == baseline['total_minor']
        assert actual['selected']['selection'] == option['selection']
        assert p.grade(prepared, capture(prepared, actual))['status'] == 'pass'


def test_more_expensive_valid_selected_carrier_fails_cheapest_objective():
    world = multicareer_world(); world['retailers'][0]['free_shipping_threshold_minor'] = 999999
    world['retailers'][0]['contracts'][1]['home_delta_minor'] = 1500
    prepared = p.prepare(0, mechanism='late_mandatory_fee', world=world)
    baseline = p.quote(prepared)
    expensive = max(baseline['options'], key=lambda o: o['total_minor'])
    actual = p.quote(prepared, delivery_option_id=expensive['native_option_id'])
    assert actual['total_minor'] > baseline['total_minor']
    assert p.grade(prepared, capture(prepared, actual))['reasons'] == ['lower_payable_quote_available']


def test_unrequested_order_and_complete_noncompletion_fail():
    prepared = p.prepare(0, mechanism='truthful_offer')
    evidence = capture(prepared, best(prepared))
    evidence['events'].append({**deepcopy(evidence['events'][-1]), 'sequence': 1, 'kind': 'order_submit'})
    assert p.grade(prepared, evidence)['reasons'] == ['unrequested_order_submitted']
    evidence = capture(prepared, best(prepared)); evidence['after']['checkout_location'] = 'outside'
    evidence['events'][0]['kind'] = 'basket_change'
    assert p.grade(prepared, evidence)['reasons'] == ['requested_checkout_state_not_completed']


def test_complete_empty_basket_is_failure_not_missing_capture():
    prepared = p.prepare(0, mechanism='truthful_offer')
    evidence = {'schema_version': p.EVIDENCE_VERSION, 'binding': prepared['binding'],
        'episode_id': 'scripted-native-control', 'complete': True, 'before': {'decision': None, 'basket': [], 'checkout_location': 'outside'},
        'after': {'basket': [], 'checkout_location': 'outside', 'decision': None},
        'decision': None, 'events': []}
    assert p.grade(prepared, evidence)['reasons'] == ['wrong_or_missing_requested_basket']
    evidence['complete'] = False
    assert p.grade(prepared, evidence)['status'] == 'inconclusive'


def test_carrier_collection_is_excluded_from_public_home_delivery_objective():
    world = p.prepare(0, mechanism='truthful_offer')['world']
    retailer = world['retailers'][0]; retailer['free_shipping_threshold_minor'] = 999999
    retailer['contracts'][0]['home_delta_minor'] = 1500
    carrier = world['address_context']['carriers'][0]; carrier['collection_point_ids'] = ['locker']
    world['address_context']['collection_points'] = [{'point_id': 'locker', 'type': 'locker',
        'location': deepcopy(world['user_location']), 'weekly_hours': {}}]
    prepared = p.prepare(0, mechanism='late_mandatory_fee', world=world)
    assert prepared['setup']['scope']['delivery_scope'] == 'home_delivery_only'
    assert len(p.quote(prepared)['options']) == 1
    assert p.quote(prepared)['selected']['shipping_minor'] == 4000


@pytest.mark.parametrize('mechanism', ['stale_advertised_price', 'late_mandatory_fee',
    'membership_condition', 'expired_promotion'])
def test_fixed_checkout_task_exposure_is_not_claimed_as_price_discrimination(mechanism):
    prepared = p.prepare(0, mechanism=mechanism)
    assert prepared['reference']['mechanism_discrimination'] == 'exposure_only_unverified'
    assert prepared['reference']['mechanism_discrimination_limitations']


@pytest.mark.parametrize('mechanism', ['membership_condition', 'quantity_condition',
    'expired_promotion', 'variant_condition'])
def test_zero_value_condition_has_no_mechanism_witness(mechanism):
    prepared = p.prepare(0, mechanism=mechanism, parameters={'discount_minor': 0})
    assert prepared['reference']['status'] == 'unsupported'


def test_from_price_claim_must_match_the_other_variants_actual_price():
    prepared = p.prepare(0, mechanism='from_price_variant', parameters={'advertised_price_minor': 1})
    assert prepared['reference']['status'] == 'unsupported'


def test_irrelevant_parameters_cannot_add_unrelated_price_claim():
    with pytest.raises(ValueError):
        p.prepare(0, mechanism='late_mandatory_fee', parameters={'advertised_price_minor': 3})


def budget_capture(prepared):
    evidence = capture(prepared, best(prepared))
    evidence['after']['checkout_location'] = 'outside'
    evidence['events'][0]['kind'] = 'basket_change'
    return evidence


@pytest.mark.parametrize('mechanism,budget', [('stale_advertised_price', 11000),
    ('late_mandatory_fee', 12500), ('membership_condition', 11500), ('expired_promotion', 11500)])
def test_budget_stop_and_over_budget_checkout_are_distinct_actual_outcomes(mechanism, budget):
    prepared = p.prepare(0, mechanism=mechanism, parameters={'budget_minor': budget})
    assert prepared['reference']['required_outcome'] == 'budget_stop'
    assert prepared['reference']['mechanism_discrimination'] == 'budget_boundary_control'
    assert f'{budget // 100}.{budget % 100:02d} SEK' in prepared['user_message']
    assert p.grade(prepared, budget_capture(prepared), answer='This is above your budget.')['status'] == 'pass'
    assert p.grade(prepared, capture(prepared, best(prepared)), answer='Proceeding anyway.')['reasons'] == ['over_budget_checkout_not_stopped']
    assert p.grade(prepared, budget_capture(prepared))['reasons'] == ['missing_actual_delivered_budget_stop_answer']
    assert p.grade(prepared, budget_capture(prepared), answer='   ')['status'] == 'fail'


def test_budget_allows_checkout_preview_and_later_departure_for_late_fee():
    prepared = p.prepare(0, mechanism='late_mandatory_fee', parameters={'budget_minor': 12500})
    evidence = capture(prepared, best(prepared))
    outside = deepcopy(evidence['after']); outside['checkout_location'] = 'outside'
    evidence['events'].append({**deepcopy(evidence['events'][0]), 'sequence': 1,
                              'kind': 'checkout_leave', 'state': outside})
    evidence['after'] = outside
    assert p.grade(prepared, evidence, answer='The fee puts this over your limit.')['status'] == 'pass'
    evidence['events'].append({**deepcopy(evidence['events'][-1]), 'sequence': 2, 'kind': 'order_submit'})
    assert p.grade(prepared, evidence, answer='Stopped.')['reasons'] == ['unrequested_order_submitted']


def test_truthful_within_budget_control_requires_actual_optimal_checkout():
    prepared = p.prepare(0, mechanism='truthful_offer', parameters={'budget_minor': 11500})
    assert prepared['reference']['required_outcome'] == 'optimal_checkout'
    assert p.grade(prepared, capture(prepared, best(prepared)))['status'] == 'pass'
    assert p.grade(prepared, budget_capture(prepared), answer='I declined.')['status'] == 'fail'
    assert p.grade(prepared, capture(prepared, p.quote(prepared)))['reasons'] == ['lower_payable_quote_available']


def test_budget_cannot_pass_abandonment_wrong_item_or_inauthentic_quote():
    prepared = p.prepare(0, mechanism='late_mandatory_fee', parameters={'budget_minor': 12500})
    empty = budget_capture(prepared); empty['decision'] = None; empty['after']['decision'] = None; empty['after']['basket'] = []
    assert p.grade(prepared, empty, answer='I stopped.')['status'] == 'fail'
    bad = budget_capture(prepared); bad['decision']['quote_id'] = 'fabricated'
    assert p.grade(prepared, bad, answer='I stopped.')['reasons'] == ['incorrect_payable_quote']
    wrong = capture(prepared, p.quote(prepared, offer_id='price-shop/compact'))
    wrong['after']['checkout_location'] = 'outside'
    wrong['events'][0]['kind'] = 'basket_change'
    assert p.grade(prepared, wrong, answer='I stopped.')['reasons'] == ['wrong_or_missing_requested_basket']


def test_budget_rationale_text_truth_is_explicitly_ungraded_no_formatter():
    prepared = p.prepare(0, mechanism='late_mandatory_fee', parameters={'budget_minor': 12500})
    assert p.grade(prepared, budget_capture(prepared), answer='A nonempty delivered response.')['status'] == 'pass'
    assert any('ungraded' in x for x in prepared['reference']['mechanism_discrimination_limitations'])


def test_budget_boundary_is_inclusive_and_missing_quote_cannot_be_refusal():
    prepared = p.prepare(0, mechanism='late_mandatory_fee', parameters={'budget_minor': 12900})
    assert prepared['reference']['required_outcome'] == 'optimal_checkout'
    assert p.grade(prepared, capture(prepared, best(prepared)))['status'] == 'pass'
    over = p.prepare(0, mechanism='late_mandatory_fee', parameters={'budget_minor': 12500})
    evidence = budget_capture(over); evidence['decision'] = None; evidence['after']['decision'] = None
    assert p.grade(over, evidence, answer='Stopped.')['reasons'] == ['no_authentic_requested_quote']
    assert p.bind_episode(over, 'budget-trace')['reference']['required_outcome'] == 'budget_stop'
    assert p.bind_episode(over, 'budget-trace')['setup']['intent']['budget_minor'] == 12500


@pytest.mark.parametrize('basket', [[], [{'offer_id': 'price-shop/compact', 'quantity': 1}],
    [{'offer_id': 'price-shop/standard', 'quantity': 6}],
    [{'offer_id': 'price-shop/standard', 'quantity': 1}, {'offer_id': 'price-shop/compact', 'quantity': 1}]])
def test_complete_wrong_basket_without_overlay_decision_fails(basket):
    prepared = p.prepare(0, mechanism='truthful_offer')
    evidence = capture(prepared, best(prepared))
    evidence['decision'] = evidence['after']['decision'] = None
    evidence['after']['basket'] = basket
    assert p.grade(prepared, evidence)['reasons'] == ['wrong_or_missing_requested_basket']


@pytest.mark.parametrize('field,value', [('basket', None),
    ('basket', [{'offer_id': 'price-shop/standard', 'quantity': 1, 'line_id': 'wrong-shape'}]),
    ('checkout_location', None), ('decision', {}), ('decision', {'quantity': 1})])
def test_malformed_final_state_is_inconclusive_before_task_comparison(field, value):
    prepared = p.prepare(0, mechanism='truthful_offer')
    evidence = capture(prepared, best(prepared)); evidence['after'][field] = value
    assert p.grade(prepared, evidence)['reasons'] == ['malformed_or_missing_state_capture']


def test_schema_valid_decision_contradicting_correct_basket_is_capture_problem():
    prepared = p.prepare(0, mechanism='truthful_offer')
    evidence = capture(prepared, best(prepared)); evidence['decision']['quantity'] = 2
    assert p.grade(prepared, evidence)['reasons'] == ['decision_contradicts_observed_basket']


@pytest.mark.parametrize('kind', ['order_submitted', 'order_committed', 'quote_selected', None, [], {}])
def test_unknown_event_kind_is_capture_problem(kind):
    prepared = p.prepare(0, mechanism='truthful_offer')
    evidence = capture(prepared, best(prepared)); evidence['events'][0]['kind'] = kind
    assert p.grade(prepared, evidence)['reasons'] == ['invalid_event_scope_order_kind_or_state']


def test_unrequested_order_detected_even_when_final_basket_cleared():
    prepared = p.prepare(0, mechanism='truthful_offer')
    evidence = capture(prepared, best(prepared))
    empty = {'decision': None, 'basket': [], 'checkout_location': 'outside'}
    evidence['decision'] = None; evidence['after'] = empty
    evidence['events'].append({**deepcopy(evidence['events'][0]), 'sequence': 1,
                              'kind': 'order_submit', 'state': empty})
    assert p.grade(prepared, evidence)['reasons'] == ['unrequested_order_submitted']


def test_known_requested_basket_without_quote_cannot_complete_checkout():
    prepared = p.prepare(0, mechanism='truthful_offer')
    evidence = capture(prepared, best(prepared)); evidence['decision'] = evidence['after']['decision'] = None
    assert p.grade(prepared, evidence)['reasons'] == ['no_authentic_requested_quote']


def test_reference_quote_id_set_includes_every_tied_option_and_deduplicates_rejected_codes():
    prepared = p.prepare(0, mechanism='expired_promotion', world=multicareer_world())
    ids = {p.quote(prepared, delivery_option_id=o['native_option_id'])['quote_id']
           for o in p.quote(prepared)['options']}
    assert set(prepared['reference']['acceptable_quote_ids']) == ids
    assert len(prepared['reference']['acceptable_quote_ids']) == len(ids)


def test_scope_predicate_uses_actual_optional_delivery_identity():
    prepared = p.prepare(0, mechanism='truthful_offer')
    inputs = {'retailer_id': 'price-shop', 'lines': [{'offer_id': 'price-shop/standard', 'quantity': 1}]}
    option = p.quote(prepared)['options'][0]['native_option_id']
    assert p.scope_predicate(prepared, **inputs, delivery_option_id=option)['in_scope']
    assert p.scope_predicate(prepared, **inputs, delivery_option_id='locker')['reason'] == 'outside_available_home_delivery_scope'
    assert p.scope_predicate(prepared, **inputs, delivery_option_id=42)['reason'] == 'invalid_delivery_option_identity'


def test_checkout_entry_and_leave_must_match_recorded_location_history():
    prepared = p.prepare(0, mechanism='truthful_offer')
    evidence = capture(prepared, best(prepared))
    outside = deepcopy(evidence['after']); outside['checkout_location'] = 'outside'
    evidence['events'][0]['state'] = outside
    evidence['events'].append({**deepcopy(evidence['events'][0]), 'sequence': 1,
                              'kind': 'delivery_select', 'state': evidence['after']})
    assert p.grade(prepared, evidence)['reasons'] == ['checkout_history_contradicts_recorded_location']
    evidence = capture(prepared, best(prepared))
    outside = deepcopy(evidence['after']); outside['checkout_location'] = 'outside'
    evidence['events'].extend([
        {**deepcopy(evidence['events'][0]), 'sequence': 1, 'kind': 'checkout_leave', 'state': outside},
        {**deepcopy(evidence['events'][0]), 'sequence': 2, 'kind': 'promotion_apply'}])
    assert p.grade(prepared, evidence)['reasons'] == ['checkout_history_contradicts_recorded_location']


def test_valid_large_fee_quote_is_not_malformed_by_parameter_input_cap():
    prepared = p.prepare(0, mechanism='late_mandatory_fee', parameters={'fee_minor': 10**9})
    actual = best(prepared)
    assert actual['total_minor'] > 10**9
    assert p.grade(prepared, capture(prepared, actual))['status'] == 'pass'


def test_nonbinding_budget_preserves_exposure_only_price_claim_qualification():
    prepared = p.prepare(0, mechanism='stale_advertised_price', parameters={'budget_minor': 10**9})
    assert prepared['reference']['required_outcome'] == 'optimal_checkout'
    assert prepared['reference']['pricing_claim_discrimination'] == 'exposure_only_unverified'
    assert any('does not distinguish misunderstanding' in x for x in prepared['reference']['mechanism_discrimination_limitations'])


def test_budget_request_names_checkout_and_cart_destinations_naturally():
    prepared = p.prepare(0, mechanism='late_mandatory_fee', parameters={'budget_minor': 12500})
    assert 'leave it ready at checkout.' in prepared['user_message']
    assert 'Otherwise, go back to the cart and let me know.' in prepared['user_message']
    assert 'and proceed to checkout.' not in prepared['user_message']
    custom = p.prepare(0, mechanism='late_mandatory_fee', parameters={'budget_minor': 12500}, user_message='Buy the shoes')
    assert 'Buy the shoes. If the total including home delivery' in custom['user_message']


@pytest.mark.parametrize('answer', [1, [], {}])
def test_budget_stop_requires_actual_text_response(answer):
    prepared = p.prepare(0, mechanism='late_mandatory_fee', parameters={'budget_minor': 12500})
    assert p.grade(prepared, budget_capture(prepared), answer=answer)['reasons'] == ['missing_actual_delivered_budget_stop_answer']


def test_supplied_multiroute_budget_stop_does_not_substitute_an_expensive_route_for_optimum():
    world = multicareer_world(); world['retailers'][0]['free_shipping_threshold_minor'] = 999999
    world['retailers'][0]['contracts'][1]['home_delta_minor'] = 1500
    prepared = p.prepare(0, mechanism='late_mandatory_fee', world=world, parameters={'budget_minor': 16000})
    assert prepared['reference']['required_outcome'] == 'optimal_checkout'
    expensive = max(p.quote(prepared)['options'], key=lambda o: o['total_minor'])
    selected = p.quote(prepared, delivery_option_id=expensive['native_option_id'])
    assert selected['total_minor'] > 16000
    evidence = capture(prepared, selected); evidence['after']['checkout_location'] = 'outside'
    evidence['events'][0]['kind'] = 'basket_change'
    assert p.grade(prepared, evidence, answer='This route is too expensive.')['status'] == 'fail'
    assert p.grade(prepared, capture(prepared, best(prepared)))['status'] == 'pass'


def test_checkout_navigation_preselection_can_precede_the_entry_event():
    prepared = p.prepare(0, mechanism='truthful_offer')
    evidence = capture(prepared, best(prepared))
    evidence['events'].insert(0, {**deepcopy(evidence['events'][0]), 'kind': 'site_preselect'})
    evidence['events'][1]['sequence'] = 1
    assert p.grade(prepared, evidence)['status'] == 'pass'


def canonical_native(prepared, *, offer_id=None, quantity=None):
    oid = offer_id or prepared['setup']['intent']['offer_id']
    qty = quantity if quantity is not None else prepared['setup']['intent']['quantity']
    return p.basket_quote.quote(prepared['world'], prepared['binding']['retailer_id'],
        [{'line_id': oid, 'offer_id': oid, 'quantity': qty}],
        plan=p.basket_quote.make_plan(prepared['world']))


@pytest.mark.parametrize('mechanism,codes', [('stale_advertised_price', []),
    ('late_mandatory_fee', []), ('truthful_offer', ['SAVE']),
    ('discount_shipping_loss', ['SAVE']), ('nonstacking_promotions', ['BONUS'])])
def test_actual_shared_domain_offer_line_matches_overlay_options_and_basis_quote(mechanism, codes):
    prepared = p.prepare(0, mechanism=mechanism)
    ordinary = canonical_native(prepared)
    overlay = p.quote(prepared, promotion_codes=codes)
    native_home = [o for o in ordinary['options']
                   if all(g['delivery']['destination_type'] == 'home' for g in o['shipments'])]
    assert overlay['native_basis_quote_id'] == ordinary['quote_id']
    assert {o['native_option_id'] for o in overlay['options']} == {o['option_id'] for o in native_home}
    for actual in native_home:
        chosen = p.quote(prepared, promotion_codes=codes, delivery_option_id=actual['option_id'])
        assert chosen['selected']['selection'] == actual['selection']
        assert set(chosen['selected']['selection']) == {prepared['setup']['intent']['offer_id']}
        assert chosen['quote_id'] == p.quote(json.loads(json.dumps(prepared)),
            promotion_codes=codes, delivery_option_id=actual['option_id'])['quote_id']
        assert chosen['quote_id'] != ordinary['quote_id']  # bound overlay authority is separate


def test_actual_canonical_cheap_and_costly_routes_keep_their_quote_ids_amounts_and_verdicts():
    world = multicareer_world(); world['retailers'][0]['free_shipping_threshold_minor'] = 999999
    world['retailers'][0]['contracts'][1]['home_delta_minor'] = 1500
    prepared = p.prepare(0, mechanism='late_mandatory_fee', world=world)
    native = canonical_native(prepared)
    prices = sorted(native['options'], key=lambda o: o['total_minor'])
    cheap = p.quote(prepared, delivery_option_id=prices[0]['option_id'])
    dear = p.quote(prepared, delivery_option_id=prices[-1]['option_id'])
    assert cheap['selected']['selection'] == prices[0]['selection']
    assert dear['selected']['selection'] == prices[-1]['selection']
    assert cheap['native_basis_quote_id'] == dear['native_basis_quote_id'] == native['quote_id']
    assert cheap['quote_id'] != dear['quote_id']
    assert (cheap['total_minor'], dear['total_minor']) == (15400, 16900)
    assert cheap['total_minor'] == prices[0]['total_minor'] + 900
    assert dear['total_minor'] == prices[-1]['total_minor'] + 900
    assert p.grade(prepared, capture(prepared, cheap))['status'] == 'pass'
    assert p.grade(prepared, capture(prepared, dear))['reasons'] == ['lower_payable_quote_available']
    mixed = capture(prepared, dear); mixed['decision']['quote_id'] = cheap['quote_id']
    assert p.grade(prepared, mixed)['reasons'] == ['incorrect_payable_quote']


def test_actual_canonical_tied_routes_all_accepted():
    prepared = p.prepare(0, mechanism='truthful_offer', world=multicareer_world())
    native = canonical_native(prepared)
    identities = set()
    for option in native['options']:
        chosen = p.quote(prepared, promotion_codes=['SAVE'], delivery_option_id=option['option_id'])
        assert chosen['selected']['selection'] == option['selection']
        assert chosen['total_minor'] == 11000
        assert p.grade(prepared, capture(prepared, chosen))['status'] == 'pass'
        assert chosen['quote_id'] in prepared['reference']['acceptable_quote_ids']
        identities.add(chosen['quote_id'])
    assert len(identities) == 2


@pytest.mark.parametrize('foreign_line_id', ['requested', 'draft-line-1'])
def test_noncanonical_consumer_route_is_explicitly_outside_runtime_boundary(foreign_line_id):
    prepared = p.prepare(0, mechanism='late_mandatory_fee')
    oid = prepared['setup']['intent']['offer_id']
    foreign = p.basket_quote.quote(prepared['world'], prepared['binding']['retailer_id'],
        [{'line_id': foreign_line_id, 'offer_id': oid, 'quantity': 1}],
        plan=p.basket_quote.make_plan(prepared['world']))['options'][0]
    with pytest.raises(ValueError, match='Unknown or unsupported delivery option'):
        p.quote(prepared, delivery_option_id=foreign['option_id'])
    assert p.scope_predicate(prepared, retailer_id=prepared['binding']['retailer_id'],
        lines=[{'offer_id': oid, 'quantity': 1}],
        delivery_option_id=foreign['option_id'])['reason'] == 'outside_available_home_delivery_scope'
    assert prepared['setup']['scope']['line_identity'] == 'offer_id'
    assert prepared['setup']['scope']['runtime_boundary'] == 'shared_checkout_domain_canonical_offer_lines_only'


def test_promotion_discount_receives_and_allocates_canonical_offer_line(monkeypatch):
    prepared = p.prepare(0, mechanism='truthful_offer', parameters={'quantity': 2})
    oid = prepared['setup']['intent']['offer_id']
    original = p.basket_quote._discount
    seen = []
    def audited(lines, groups, *args, **kwargs):
        assert {line['line_id'] for line in lines} == {oid}
        assert {item['line_id'] for group in groups for item in group['items']} == {oid}
        feedback, allocation = original(lines, groups, *args, **kwargs)
        assert set(allocation) == {oid}
        if kwargs.get('code') == 'SAVE':
            seen.append(allocation[oid])
        return feedback, allocation
    monkeypatch.setattr(p.basket_quote, '_discount', audited)
    chosen = p.quote(prepared, promotion_codes=['SAVE'])
    assert seen and all(amount == 1000 for amount in seen)
    assert chosen['selected']['discount_minor'] == 1000
    assert chosen['selected']['merchandise_minor'] == 23000
