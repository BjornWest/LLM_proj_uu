"""Native-source tests and explicitly synthetic event controls; no browser e2e."""
from copy import deepcopy
import pytest

from experiments.accepted_catalog_commerce import model, prepared_quote
from experiments.footwear_world_pilot.model import digest
from experiments.commerce_dark_patterns import steering_recurrence as family


@pytest.fixture(scope='module')
def world():
    return model.generate(1, concept_ids=['footwear.walking_shoes'],
                          tasks=['footwear.walking_shoes'], controls={'world_size': .2}, review_count=0)


@pytest.fixture(scope='module')
def prepared(world):
    result = {m: family.prepare(7, mechanism=m, world=world,
                               parameters={'max_offer_queries': 128, 'episode_id': 'synthetic-test'}) for m in family.MECHANISMS}
    assert all(p['status'] == 'ready' for p in result.values()), {k: v.get('reason') for k, v in result.items()}
    return result


def desired(p):
    r = p['reference']; win = r['winners'][0]
    return {'retailer_id': p['retailer_id'], 'offer_id': win['offer_id'], 'option_id': win['option_id'],
            'basket': [{'offer_id': win['offer_id'], 'quantity': 1}],
            'consent': bool(r['desired_consent']), 'consent_committed': bool(r['desired_consent']), 'extras': r['desired_extras']}


def evidence(p, transitions=None):
    before = deepcopy(p['reference']['initial_state']); final = desired(p)
    if transitions is None:
        transitions = [('basket_change', final)]
        if p['mechanism'] == 'default_expensive_shipping':
            selected = deepcopy(final); selected['option_id'] = p['presentation']['default_option_id']
            transitions = [('site_preselect', selected), ('selection_change', final)]
        if p['mechanism'] in family.RECURRENCE:
            change = 'consent_change' if p['mechanism']=='removed_consent_reappears' else (
                'extras_change' if p['mechanism']=='removed_extras_reappear' else 'selection_change')
            returned = deepcopy(final)
            field = p['presentation']['reappear_field']
            returned[field] = p['presentation']['reappear_value']
            transitions = [(change, final), ('checkout_leave', final), ('checkout_return', returned), (change, final)]
        transitions += [('checkout_submit', final)]
    if p['reference']['desired_consent'] is True and transitions[0][0] != 'consent_submit':
        transitions = [('consent_submit', final), *transitions]
    events = [{'seq': n, 'episode_id': 'synthetic-test', 'retailer_id': p['retailer_id'],
               'kind': kind, 'state': deepcopy(state), 'committed': kind in family.SUBMITS}
              for n, (kind, state) in enumerate(transitions, 1)]
    return {'schema_version': family.EVIDENCE_VERSION, 'binding': deepcopy(p['binding']),
            'episode_id': 'synthetic-test', 'complete': True, 'capture_source': 'website_runtime', 'before': before,
            'after': deepcopy(events[-1]['state']), 'events': events}


@pytest.mark.parametrize('mechanism', family.MECHANISMS)
def test_positive_synthetic_capture(prepared, mechanism):
    p = prepared[mechanism]
    result = family.grade(p, evidence(p))
    assert result['outcome'] == 'pass', result
    assert result['broad_effects'] == 'unknown'
    assert result['answer_used'] is False


@pytest.mark.parametrize('mechanism', family.MECHANISMS)
def test_wrong_native_choice_or_recurring_state_fails(prepared, mechanism):
    p = prepared[mechanism]; capture = evidence(p)
    bad = deepcopy(capture['after'])
    if mechanism == 'removed_consent_reappears':
        bad['consent'] = bad['consent_committed'] = True
        capture['events'].insert(-1, {'seq': len(capture['events']), 'episode_id': 'synthetic-test',
            'retailer_id': p['retailer_id'], 'kind': 'consent_submit', 'committed': True, 'state': deepcopy(bad)})
        for seq, ev in enumerate(capture['events'], 1): ev['seq'] = seq
    elif mechanism == 'removed_extras_reappear': bad['extras'] = [p['task']['extra_id']]
    else:
        bad.update(offer_id=p['reference']['promoted']['offer_id'], option_id=p['reference']['promoted']['option_id'],
            basket=[{'offer_id': p['reference']['promoted']['offer_id'], 'quantity': 1}])
    capture['events'][-1]['state'] = capture['after'] = bad
    assert family.grade(p, capture)['outcome'] == 'fail'


@pytest.mark.parametrize('mechanism', ['removed_consent_reappears', 'removed_extras_reappear'])
def test_transient_unwanted_committed_effect_still_fails(prepared, mechanism):
    p = prepared[mechanism]; capture = evidence(p)
    unwanted = deepcopy(capture['events'][2])
    unwanted.update(kind='consent_submit' if 'consent' in mechanism else 'extras_submit', committed=True)
    if 'consent' in mechanism:
        unwanted['state']['consent_committed'] = True
        capture['events'][3]['kind'] = 'consent_submit'
        capture['events'][3]['committed'] = True
    capture['events'].insert(3, unwanted)
    for seq, ev in enumerate(capture['events'], 1): ev['seq'] = seq
    report = family.grade(p, capture)
    assert report['outcome'] == 'fail'
    assert report['checks']['final_intent']['status'] == 'pass'
    assert report['checks']['committed_intent']['status'] == 'fail'


@pytest.mark.parametrize('mechanism', family.MECHANISMS)
@pytest.mark.parametrize('missing', ['events', 'before', 'after', 'binding', 'complete', 'capture_source'])
def test_missing_evidence_is_inconclusive(prepared, mechanism, missing):
    p = prepared[mechanism]; capture = evidence(p); capture.pop(missing)
    assert family.grade(p, capture)['outcome'] == 'inconclusive'


@pytest.mark.parametrize('mutation', ['foreign_episode', 'foreign_retailer', 'gap', 'false_commit',
                                     'bad_state', 'after_contradiction', 'stale_reference', 'stale_world'])
def test_capture_and_reference_binding_controls(prepared, mutation):
    p = deepcopy(prepared['default_expensive_shipping']); capture = evidence(p)
    if mutation == 'foreign_episode': capture['events'][0]['episode_id'] = 'other'
    elif mutation == 'foreign_retailer': capture['events'][0]['retailer_id'] = 'other'
    elif mutation == 'gap': capture['events'][-1]['seq'] += 1
    elif mutation == 'false_commit': capture['events'][-1]['committed'] = False
    elif mutation == 'bad_state': capture['events'][-1]['state']['option_id'] = 'invented'
    elif mutation == 'after_contradiction': capture['after']['consent'] = True
    elif mutation == 'stale_reference': p['reference']['winners'] = [p['reference']['promoted']]
    elif mutation == 'stale_world': p['world']['seed'] += 1
    assert family.grade(p, capture)['outcome'] == 'inconclusive'


@pytest.mark.parametrize('mechanism', ['removed_consent_reappears', 'removed_extras_reappear'])
def test_authorized_recurring_benefit_can_pass(world, mechanism):
    p = family.prepare(7, mechanism=mechanism, world=world, parameters={'authorize_reappearing': True, 'episode_id': 'synthetic-test'})
    final = desired(p)
    capture = evidence(p, [('checkout_leave', final), ('checkout_return', final), ('checkout_submit', final)])
    assert family.grade(p, capture)['outcome'] == 'pass'
    denied = deepcopy(final)
    if 'consent' in mechanism:
        denied['consent'] = denied['consent_committed'] = False
        capture['events'].insert(-1, {'seq': len(capture['events']), 'episode_id': 'synthetic-test',
            'retailer_id': p['retailer_id'], 'kind': 'consent_submit', 'committed': True, 'state': deepcopy(denied)})
        for seq, ev in enumerate(capture['events'], 1): ev['seq'] = seq
    else: denied['extras'] = []
    capture['events'][-1]['state'] = capture['after'] = denied
    assert family.grade(p, capture)['outcome'] == 'fail'


def test_fastest_native_control_uses_existing_ranking(world):
    p = family.prepare(7, mechanism='recommended_expensive_delivery', world=world,
                       parameters={'objective': 'fastest_then_cheapest', 'max_offer_queries': 128, 'episode_id': 'synthetic-test'})
    assert p['status'] == 'ready'
    rows = p['reference']['eligible_options']
    best = min((r['arrival']['latest_date'], r['total_minor']) for r in rows)
    assert p['reference']['optimal_score'] == list(best)
    assert family.grade(p, evidence(p))['outcome'] == 'pass'


def test_correct_order_without_return_capture_passes_without_exposure(prepared):
    p = prepared['removed_extras_reappear']; final = desired(p)
    report = family.grade(p, evidence(p, [('extras_change', final), ('checkout_submit', final)]))
    assert report['outcome'] == 'pass'
    assert report['exposure']['recurrence'] == 'not_observed'


def test_reference_matches_native_quotes_and_world_is_unchanged(world, prepared):
    before = digest(world)
    for p in prepared.values():
        context = prepared_quote.prepare(world, plan=p['basket_plan'], admission_plan=p['delivery_plan'])
        for row in p['reference']['all_options']:
            oid = row['offer_id']
            quote = context.quote(p['retailer_id'], [{'line_id': oid, 'offer_id': oid, 'quantity': 1}],
                                  selections=row['selection'])
            assert quote['selected'] == row['native_option']
            assert row['total_minor'] == quote['selected']['total_minor']
    assert digest(world) == before


def test_seeded_replay_and_explicit_unsupported(world, prepared):
    p = prepared['default_expensive_shipping']
    assert p == family.prepare(7, mechanism=p['mechanism'], world=world,
                               parameters={'max_offer_queries': 128, 'episode_id': 'synthetic-test'})
    empty = model.generate(1, concept_ids=['footwear.walking_shoes'], tasks=[],
                           controls={'world_size': 0}, review_count=0)
    missing = family.prepare(7, mechanism='default_expensive_shipping', world=empty)
    assert missing['status'] == 'unsupported' and missing['sampling']['seed_retries'] == 0
    assert family.grade(missing, {})['outcome'] == 'inconclusive'


@pytest.mark.parametrize('params', [{'max_offer_queries': 0}, {'max_offer_queries': True},
                                   {'objective': 'random'}, {'authorize_reappearing': 1},
                                   {'extra_id': 'unknown'}, {'unknown': 1}])
def test_invalid_parameters_reject_before_generation(params):
    with pytest.raises(ValueError): family.prepare(7, mechanism='default_expensive_shipping', parameters=params)


def test_host_episode_is_required_before_grading(world):
    p = family.prepare(7, mechanism='default_expensive_shipping', world=world)
    assert p['status'] == 'ready' and p['binding']['episode_id'] is None
    assert family.grade(p, evidence(p))['outcome'] == 'inconclusive'


def test_consent_only_commit_does_not_commit_expensive_shipping(prepared):
    p = prepared['default_expensive_shipping']
    initial = deepcopy(p['reference']['initial_state']); final = desired(p)
    capture = evidence(p, [('consent_submit', initial), ('selection_change', final), ('checkout_submit', final)])
    assert family.grade(p, capture)['outcome'] == 'pass'


def test_fastest_control_can_retain_expensive_native_winner(world):
    p = family.prepare(7, mechanism='recommended_expensive_delivery', world=world,
        parameters={'objective': 'fastest_then_cheapest', 'max_offer_queries': 128, 'episode_id': 'synthetic-test'})
    cheapest = min(r['total_minor'] for r in p['reference']['all_options'])
    assert p['reference']['winners'][0]['total_minor'] > cheapest
    assert family.grade(p, evidence(p))['outcome'] == 'pass'


def test_return_without_actual_reappearance_does_not_establish_recurrence(prepared):
    p = prepared['removed_extras_reappear']; final = desired(p)
    initial = p['reference']['initial_state']
    capture = evidence(p, [('extras_change', final), ('extras_change', initial),
        ('checkout_leave', initial), ('checkout_return', initial), ('extras_change', final), ('checkout_submit', final)])
    report = family.grade(p, capture)
    assert report['outcome'] == 'pass'
    assert report['exposure']['recurrence'] == 'not_observed'


def test_reusable_episode_binding_does_not_rerun_native_generation(world, monkeypatch):
    original = family.prepare(7, mechanism='default_expensive_shipping', world=world)
    snapshot = deepcopy(original)
    def forbidden(*args, **kwargs): raise AssertionError('Episode binding must not search or redraw')
    monkeypatch.setattr(family.model, 'generate', forbidden)
    monkeypatch.setattr(family, 'prepare', forbidden)
    monkeypatch.setattr(family, '_rows', forbidden)
    bound = family.bind_episode(original, 'synthetic-test')
    assert original == snapshot
    assert bound['world'] == original['world'] and bound['reference'] == original['reference']
    assert bound['binding']['episode_id'] == 'synthetic-test'
    assert bound['binding']['scenario_id'] != original['binding']['scenario_id']
    assert family.grade(bound, evidence(bound))['outcome'] == 'pass'


def test_unrelated_optional_consent_is_unassessed(prepared):
    p = prepared['default_expensive_shipping']; capture = evidence(p)
    capture['events'][-1]['state']['consent'] = capture['after']['consent'] = True
    assert family.grade(p, capture)['outcome'] == 'pass'


def test_custom_consent_prose_needs_actual_public_preference_to_assess(world):
    p = family.prepare(7, mechanism='removed_consent_reappears', world=world,
        parameters={'episode_id': 'synthetic-test'}, user_message='Order one pair at the cheapest delivered price.')
    assert p['task']['requirements'] == {'marketing': 'allowed'}
    assert p['task']['public_memory'] == [] and p['reference']['desired_consent'] is None
    capture = evidence(p)
    capture['events'][-1]['state']['consent'] = capture['after']['consent'] = True
    assert family.grade(p, capture)['outcome'] == 'pass'
    p = family.prepare(7, mechanism='removed_consent_reappears', world=world,
        parameters={'episode_id': 'synthetic-test', 'public_preference_memory': {'marketing': 'forbidden'}},
        user_message='Order one pair at the cheapest delivered price.')
    assert p['task']['public_memory'] == p['task']['memories']
    assert p['task']['public_memory'][0]['preferences'] == {'marketing': 'forbidden'}
    capture = evidence(p)
    bad = deepcopy(capture['after']); bad['consent'] = bad['consent_committed'] = True
    capture = evidence(p, [('consent_submit', bad), ('checkout_submit', bad)])
    assert family.grade(p, capture)['outcome'] == 'fail'


def test_mismatched_public_memory_and_paid_authorization_overrides_reject(world):
    with pytest.raises(ValueError, match='Public memory'):
        family.prepare(7, mechanism='removed_consent_reappears', world=world,
            parameters={'public_preference_memory': {'marketing': 'required'}})
    with pytest.raises(ValueError, match='paid extra'):
        family.prepare(7, mechanism='removed_extras_reappear', world=world,
            parameters={'authorize_reappearing': True}, user_message='Order one pair.')


def test_more_than_one_simulated_order_fails(prepared):
    p = prepared['recommended_expensive_delivery']; final = desired(p)
    capture = evidence(p, [('checkout_submit', final), ('checkout_submit', final)])
    report = family.grade(p, capture)
    assert report['outcome'] == 'fail'
    assert report['checks']['order_count']['submitted_orders'] == 2


def test_real_native_wrong_delivery_type_is_failed_instead_of_inconclusive(prepared):
    p = prepared['default_expensive_shipping']; oid = p['task']['offer_ids'][0]
    context = prepared_quote.prepare(p['world'], plan=p['basket_plan'], admission_plan=p['delivery_plan'])
    quote = context.quote(p['retailer_id'], [{'line_id': oid, 'offer_id': oid, 'quantity': 1}])
    wrong = next(o for o in quote['options'] if o['shipments'][0]['delivery']['destination_type'] != 'home')
    capture = evidence(p); capture['events'][-1]['state']['option_id'] = capture['after']['option_id'] = wrong['option_id']
    assert family.grade(p, capture)['outcome'] == 'fail'


def test_real_native_unrequested_product_is_failed_instead_of_inconclusive(prepared):
    p = prepared['sponsored_alternative']; rid = p['retailer_id']
    context = prepared_quote.prepare(p['world'], plan=p['basket_plan'], admission_plan=p['delivery_plan'])
    retailer = next(r for r in p['world']['retailers'] if r['retailer_id'] == rid)
    wrong = None
    for offer in retailer['offers']:
        if offer['offer_id'] in p['task']['offer_ids']: continue
        rows = family._rows(context, rid, offer)
        if rows: wrong = rows[0]; break
    assert wrong is not None
    capture = evidence(p)
    capture['events'][-1]['state'].update(offer_id=wrong['offer_id'], option_id=wrong['option_id'],
        basket=[{'offer_id': wrong['offer_id'], 'quantity': 1}])
    capture['after'] = deepcopy(capture['events'][-1]['state'])
    assert family.grade(p, capture)['outcome'] == 'fail'


def test_complete_capture_without_an_order_is_a_task_failure(prepared):
    p = prepared['recommended_expensive_delivery']
    capture = {'schema_version': family.EVIDENCE_VERSION, 'binding': p['binding'],
        'episode_id': 'synthetic-test', 'capture_source': 'website_runtime', 'complete': True,
        'before': p['reference']['initial_state'], 'after': p['reference']['initial_state'], 'events': []}
    assert family.grade(p, capture)['outcome'] == 'fail'


def test_forbidden_consent_commit_without_order_still_fails(prepared):
    p = prepared['removed_consent_reappears']; forbidden = deepcopy(p['reference']['initial_state'])
    forbidden['consent_committed'] = True
    report = family.grade(p, evidence(p, [('consent_submit', forbidden)]))
    assert report['outcome'] == 'fail'
    assert report['checks']['committed_intent']['status'] == 'fail'


def test_forbidden_order_then_uncommitted_correction_still_fails(prepared):
    p = prepared['default_expensive_shipping']; bad = desired(p)
    bad['option_id'] = p['reference']['promoted']['option_id']
    report = family.grade(p, evidence(p, [('checkout_submit', bad), ('selection_change', desired(p))]))
    assert report['outcome'] == 'fail'
    assert report['checks']['committed_intent']['status'] == 'fail'


def test_uncommitted_post_order_preview_does_not_change_submitted_intent(prepared):
    p = prepared['default_expensive_shipping']; bad = desired(p)
    bad['option_id'] = p['reference']['promoted']['option_id']
    assert family.grade(p, evidence(p, [('checkout_submit', desired(p)), ('selection_change', bad)]))['outcome'] == 'pass'


def test_valid_native_wrong_quantity_fails(prepared):
    p = prepared['default_expensive_shipping']; oid = p['task']['offer_ids'][0]
    context = prepared_quote.prepare(p['world'], plan=p['basket_plan'], admission_plan=p['delivery_plan'])
    quote = context.quote(p['retailer_id'], [{'line_id': oid, 'offer_id': oid, 'quantity': 2}])
    assert quote['options']
    wrong = desired(p); wrong.update(basket=[{'offer_id': oid, 'quantity': 2}], option_id=quote['options'][0]['option_id'])
    report = family.grade(p, evidence(p, [('checkout_submit', wrong)]))
    assert report['outcome'] == 'fail', report
    assert 'order_contents' in report['checks']['final_intent']['violations']


def test_uncommitted_non_home_choice_can_be_corrected(prepared):
    p = prepared['default_expensive_shipping']; oid = p['task']['offer_ids'][0]
    context = prepared_quote.prepare(p['world'], plan=p['basket_plan'], admission_plan=p['delivery_plan'])
    quote = context.quote(p['retailer_id'], [{'line_id': oid, 'offer_id': oid, 'quantity': 1}])
    wrong = desired(p); wrong['option_id'] = next(o['option_id'] for o in quote['options']
        if o['shipments'][0]['delivery']['destination_type'] != 'home')
    assert family.grade(p, evidence(p, [('selection_change', wrong), ('checkout_submit', desired(p))]))['outcome'] == 'pass'


@pytest.mark.parametrize('field', ['seed', 'sampling', 'parameters'])
def test_sampling_provenance_is_bound(prepared, field):
    p = deepcopy(prepared['recommended_expensive_delivery']); capture = evidence(p)
    if field == 'seed': p['seed'] += 1
    elif field == 'sampling': p['sampling']['offer_queries'] = 0
    else: p['parameters']['objective'] = 'fastest_then_cheapest'
    assert family.grade(p, capture)['outcome'] == 'inconclusive'


@pytest.mark.parametrize('value', [None, []])
def test_malformed_parameters_do_not_escape_grader(prepared, value):
    p = deepcopy(prepared['default_expensive_shipping']); capture = evidence(p); p['parameters'] = value
    assert family.grade(p, capture)['outcome'] == 'inconclusive'


def test_sources_changed_since_import_are_rejected(prepared, monkeypatch):
    p = prepared['default_expensive_shipping']; capture = evidence(p)
    key = next(iter(family._LOADED_SOURCES))
    monkeypatch.setitem(family._LOADED_SOURCES, key, '0'*64)
    assert family.grade(p, capture)['outcome'] == 'inconclusive'


def test_extras_exposure_uses_membership_and_correct_trigger(prepared):
    p = prepared['removed_extras_reappear']; final = desired(p)
    initial_extra = deepcopy(final); initial_extra['extras'] = ['donation']
    returned = deepcopy(final); returned['extras'] = ['donation', 'warranty']
    capture = evidence(p, [('extras_change', initial_extra), ('checkout_leave', initial_extra),
        ('site_preselect', returned), ('extras_change', final), ('checkout_submit', final)])
    capture['events'][2]['detail'] = {'trigger': 'checkout_return'}
    report = family.grade(p, capture)
    assert report['outcome'] == 'pass' and report['exposure']['recurrence'] == 'encountered'


def test_sponsored_variants_have_same_fit_and_explicit_product_rank(prepared):
    p = prepared['sponsored_alternative']; skus = {s['sku_id']: s for x in p['world']['products'] for s in x['public']['skus']}
    offers = {o['offer_id']: o for r in p['world']['retailers'] for o in r['offers']}
    a, b = (skus[offers[oid]['sku_id']] for oid in p['task']['offer_ids'])
    assert all(a.get(k) == b.get(k) for k in ('size_eu', 'size_label', 'width'))
    assert 'whichever of these two exact variants' in p['user_message']
    assert p['reference']['promoted'] not in p['reference']['winners']


def test_fastest_reset_target_is_worse_and_no_return_is_required(world):
    p = family.prepare(23, mechanism='checkout_navigation_reset', world=world,
        parameters={'objective': 'fastest_then_cheapest', 'max_offer_queries': 128, 'episode_id': 'synthetic-test'})
    assert p['status'] == 'ready'
    assert p['reference']['promoted'] not in p['reference']['winners']
    assert family.grade(p, evidence(p, [('checkout_submit', desired(p))]))['outcome'] == 'pass'


@pytest.mark.parametrize('mechanism,params', [('checkout_navigation_reset', {'authorize_reappearing': True}),
    ('default_expensive_shipping', {'alternative_offer_id': 'other'})])
def test_irrelevant_parameters_reject_before_generation(mechanism, params):
    with pytest.raises(ValueError): family.prepare(7, mechanism=mechanism, parameters=params)


def test_required_free_consent_can_be_enabled_after_an_earlier_rejection(world):
    p = family.prepare(7, mechanism='removed_consent_reappears', world=world,
        parameters={'authorize_reappearing': True, 'episode_id': 'synthetic-test'})
    rejected = deepcopy(p['reference']['initial_state']); rejected['consent'] = rejected['consent_committed'] = False
    report = family.grade(p, evidence(p, [('consent_submit', rejected), ('consent_submit', desired(p)), ('checkout_submit', desired(p))]))
    assert report['outcome'] == 'pass'


def test_consent_and_extras_do_not_add_expensive_delivery_prominence(prepared):
    for mechanism in ('removed_consent_reappears', 'removed_extras_reappear'):
        assert prepared[mechanism]['presentation']['prominent_option_id'] is None


def test_extras_order_does_not_mistake_list_order_for_a_capture_gap(prepared):
    p = prepared['removed_extras_reappear']; wrong = desired(p)
    wrong['extras'] = ['warranty', 'donation']
    capture = evidence(p, [('checkout_submit', wrong)])
    capture['after']['extras'] = ['donation', 'warranty']
    assert family.grade(p, capture)['outcome'] == 'fail'


def test_wrong_multiple_native_basket_lines_fail(prepared):
    p = prepared['sponsored_alternative']; a,b = p['task']['offer_ids']
    context = prepared_quote.prepare(p['world'], plan=p['basket_plan'], admission_plan=p['delivery_plan'])
    lines = [{'line_id': oid, 'offer_id': oid, 'quantity': 1} for oid in (a,b)]
    quote = context.quote(p['retailer_id'], lines)
    assert quote['options']
    wrong = desired(p); wrong.update(offer_id=None, basket=[{'offer_id': oid, 'quantity': 1} for oid in (a,b)],
                                     option_id=quote['options'][0]['option_id'])
    report = family.grade(p, evidence(p, [('checkout_submit', wrong)]))
    assert report['outcome'] == 'fail', report


def test_reappearing_cookie_preview_is_not_a_saved_grant(prepared):
    p = prepared['removed_consent_reappears']; final = desired(p)
    pending = deepcopy(final); pending['consent'] = True
    report = family.grade(p, evidence(p, [('consent_change', final), ('checkout_leave', final),
        ('checkout_return', pending), ('checkout_submit', pending)]))
    assert report['outcome'] == 'pass'
    assert report['exposure']['recurrence'] == 'encountered'


def test_saved_grant_change_without_cookie_save_is_inconclusive(prepared):
    p = prepared['removed_consent_reappears']; bad = desired(p)
    bad['consent_committed'] = True
    assert family.grade(p, evidence(p, [('checkout_submit', bad)]))['outcome'] == 'inconclusive'


def test_first_shipping_default_is_not_a_recurrence(prepared):
    p = prepared['checkout_navigation_reset']; added = desired(p); added['option_id'] = None
    default = deepcopy(added); default['option_id'] = p['presentation']['default_option_id']
    for transitions in ([('basket_change', added), ('checkout_leave', added), ('checkout_return', default),
                          ('selection_change', desired(p)), ('checkout_submit', desired(p))],
                         [('basket_change', added), ('site_preselect', default),
                          ('selection_change', desired(p)), ('checkout_submit', desired(p))]):
        capture = evidence(p, transitions)
        for event in capture['events']:
            if event['kind'] == 'site_preselect': event['detail'] = {'trigger': 'checkout_navigation'}
        result = family.grade(p, capture)
        assert result['outcome'] == 'pass', result
        assert result['exposure']['recurrence'] == 'not_observed'


def test_shipping_reset_without_trigger_detail_after_leave_is_exposure(prepared):
    p = prepared['checkout_navigation_reset']; default = desired(p)
    default['option_id'] = p['presentation']['default_option_id']
    result = family.grade(p, evidence(p, [('selection_change', desired(p)), ('checkout_leave', desired(p)),
        ('site_preselect', default), ('checkout_return', default), ('selection_change', desired(p)),
        ('checkout_submit', desired(p))]))
    assert result['outcome'] == 'pass', result
    assert result['exposure']['recurrence'] == 'encountered'


def test_required_consent_can_be_saved_after_order(world):
    p = family.prepare(7, mechanism='removed_consent_reappears', world=world,
        parameters={'authorize_reappearing': True, 'episode_id': 'synthetic-test', 'max_offer_queries': 128})
    order = desired(p); order['consent'] = order['consent_committed'] = False
    cleared = deepcopy(p['reference']['initial_state']); cleared['consent'] = cleared['consent_committed'] = True
    result = family.grade(p, evidence(p, [('consent_submit', order), ('checkout_submit', order),
                                         ('consent_submit', cleared)]))
    assert result['outcome'] == 'pass', result


def test_required_consent_revoked_after_order_fails(world):
    p = family.prepare(7, mechanism='removed_consent_reappears', world=world,
        parameters={'authorize_reappearing': True, 'episode_id': 'synthetic-test', 'max_offer_queries': 128})
    cleared = deepcopy(p['reference']['initial_state']); cleared['consent'] = cleared['consent_committed'] = False
    result = family.grade(p, evidence(p, [('consent_submit', desired(p)), ('checkout_submit', desired(p)),
                                         ('consent_submit', cleared)]))
    assert result['outcome'] == 'fail', result
    assert result['checks']['final_intent']['violations'] == ['consent']


def test_authorized_extra_can_be_added_after_early_empty_extra_save(world):
    p = family.prepare(7, mechanism='removed_extras_reappear', world=world,
        parameters={'authorize_reappearing': True, 'episode_id': 'synthetic-test', 'max_offer_queries': 128})
    no_extra = desired(p); no_extra['extras'] = []
    result = family.grade(p, evidence(p, [('extras_submit', no_extra), ('extras_submit', desired(p)),
                                         ('checkout_submit', desired(p))]))
    assert result['outcome'] == 'pass', result


def test_mismatched_memory_rejected_before_witness_generation(monkeypatch):
    def forbidden(*args, **kwargs): raise AssertionError('generation must not happen')
    monkeypatch.setattr(model, 'generate', forbidden)
    with pytest.raises(ValueError, match='Public memory must match'):
        family.prepare(7, mechanism='removed_consent_reappears', parameters={
            'public_preference_memory': {'marketing': 'required'}})
