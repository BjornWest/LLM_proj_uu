"""Actual tiny native quotes/receipts; capsules are authored controls, not browser proof."""
from copy import deepcopy

import pytest

from environments.website_world.test_simulated_order_record import fixture, world
from environments.website_world import simulated_order_task as tasks, simulated_order_grading as grades
from environments.website_world import simulated_order_record as records
from environments.website_world.adapter import digest


def spec_for(fixture, types=None):
    baskets, rid, submission = fixture
    return {'kind': tasks.KIND, 'retailer_id': rid,
        'offer_id': submission['quote_request']['lines'][0]['offer_id'], 'quantity': 1,
        'delivery_types': types, 'coupon_code': None,
        'public_request': 'Please order the item in my cart using the cheapest delivery method.',
        'memories': ['My current delivery address is the address in my profile.']}


def submission_for(baskets, rid, original, option):
    submission = deepcopy(original)
    request = submission['quote_request']
    request['split'] = option['split']
    request['selections'] = deepcopy(option['selection'])
    quote = baskets.quote(rid, request)
    submission['displayed_quote'] = {'request_id': quote['requestId'], 'quote_id': quote['quoteId'],
        'option_id': quote['selected']['id'], 'total_minor': quote['selected']['totalMinor'], 'currency': 'SEK'}
    return submission


def packet(fixture, types=None):
    baskets, rid, original = fixture
    task = tasks.make(baskets, spec_for(fixture, types))
    reference = tasks.reference(baskets, task)
    submission = submission_for(baskets, rid, original, reference['winners'][0])
    record = records.make(baskets, rid, submission, order_id='order-1')
    binding = {'runtime_id': 'runtime', 'episode_binding': {'episode_id': 'episode',
        'task_sha256': digest(task), 'source_union_sha256': 'a'*64, 'capture_implementation_sha256': 'b'*64}}
    def snapshot(orders):
        ctx = tasks.context(baskets)
        value = {'schema': grades.SNAPSHOT_VERSION, 'runtime_id': 'runtime',
            **{k: ctx[k] for k in ('world_id', 'world_sha256', 'plan_id', 'domain_id')},
            'episode_binding': deepcopy(binding['episode_binding']), 'orders': deepcopy(orders),
            'events': [{'sequence': n, 'order_id': row['order_id'], 'retailer_id': row['retailer_id'],
                'submission_sha256': row['submission_sha256'], 'record_sha256': digest(row)}
                for n, row in enumerate(orders, 1)]}
        value['snapshot_sha256'] = digest(value)
        return value
    capsule = {'schema_version': grades.CAPSULE_VERSION, 'task_sha256': digest(task),
        'episode_id': 'episode', 'main_trace_sha256': 'c'*64,
        'before': {'phase': 'before_policy', 'order_snapshot': snapshot([])},
        'after': {'phase': 'after_policy_before_context_close', 'order_snapshot': snapshot([record])},
        'effect_journal': {'authority': grades.AUTHORITY, 'complete': True,
            'events': [{'kind': 'order_committed', **e} for e in snapshot([record])['events']]}}
    def grade():
        return grades.grade(baskets, task, reference, binding=binding, capsule=capsule,
                            episode_id='episode', main_trace_sha256='c'*64, policy_completed=True)
    return baskets, rid, task, reference, submission, record, binding, capsule, snapshot, grade


def test_cheapest_reference_and_all_ties_use_actual_native_quotes(fixture):
    baskets, rid, task, reference, submission, record, binding, capsule, snapshot, grade = packet(fixture)
    assert task['user_message'] == spec_for(fixture)['public_request']
    assert task['memories'] == spec_for(fixture)['memories']
    assert reference['minimum_shipping_minor'] == min(o['shippingMinor'] for o in reference['options'])
    assert len(reference['winners']) >= 2  # Several branch collections tie in the authored fixture.
    for n, winner in enumerate(reference['winners']):
        submitted = submission_for(baskets, rid, submission, winner)
        receipt = records.make(baskets, rid, submitted, order_id=f'order-{n}')
        capsule['after']['order_snapshot'] = snapshot([receipt])
        capsule['effect_journal']['events'] = [{'kind': 'order_committed', **e} for e in snapshot([receipt])['events']]
        assert grade()['verdict'] == 'pass'


def test_explicit_home_restriction_is_not_implicit_default(fixture):
    _, _, _, all_methods, _, _, _, _, _, _ = packet(fixture)
    _, _, task, home, _, record, _, _, _, grade = packet(fixture, ['home'])
    assert any(s['delivery']['type'] == 'staffed_counter' for o in all_methods['options'] for s in o['shipments'])
    assert all(s['delivery']['type'] == 'home' for o in home['options'] for s in o['shipments'])
    assert task['delivery_types'] == ['home'] and grade()['verdict'] == 'pass'


@pytest.mark.parametrize('case', ['none', 'old_authority', 'partial', 'missing_commit', 'extra_effect',
    'wrong_episode', 'wrong_trace', 'wrong_source', 'wrong_phase', 'tampered_snapshot', 'extra_order',
    'changed_history', 'expensive', 'wrong_recipient', 'wrong_quantity', 'typed_tamper'])
def test_grade_rejects_wrong_outcomes_and_retains_unknown_authority(fixture, case):
    baskets, rid, task, reference, submission, record, binding, capsule, snapshot, grade = packet(fixture)
    expected = 'fail'
    if case == 'none': capsule['effect_journal'] = None; expected = 'inconclusive'
    elif case == 'old_authority': capsule['effect_journal']['authority'] = 'complete_generated_world_event_journal'; expected = 'inconclusive'
    elif case == 'partial': capsule['effect_journal']['complete'] = False; expected = 'inconclusive'
    elif case == 'missing_commit': capsule['effect_journal']['events'] = []
    elif case == 'extra_effect': capsule['effect_journal']['events'].append({'kind': 'account_changed'})
    elif case == 'wrong_episode': capsule['episode_id'] = 'foreign'; expected = 'inconclusive'
    elif case == 'wrong_trace': capsule['main_trace_sha256'] = 'd'*64; expected = 'inconclusive'
    elif case == 'wrong_source': capsule['after']['order_snapshot']['episode_binding']['source_union_sha256'] = 'd'*64; expected = 'inconclusive'
    elif case == 'wrong_phase': capsule['after']['phase'] = 'during_policy'; expected = 'inconclusive'
    elif case == 'tampered_snapshot': capsule['after']['order_snapshot']['orders'] = []; expected = 'inconclusive'
    elif case == 'changed_history': capsule['before']['order_snapshot'] = snapshot([record]); capsule['after']['order_snapshot'] = snapshot([])
    elif case == 'typed_tamper':
        record['simulated'] = 1
        capsule['after']['order_snapshot'] = snapshot([record])
    else:
        if case == 'extra_order':
            second = records.make(baskets, rid, {**submission, 'idempotency_key': 'second'}, order_id='order-2')
            rows = [record, second]
        else:
            if case == 'expensive':
                option = next(o for o in reference['options'] if o['shippingMinor'] > reference['minimum_shipping_minor'])
                submission = submission_for(baskets, rid, submission, option)
            elif case == 'wrong_recipient': submission['quote_request']['address']['name'] = 'Someone Else'
            else: submission['quote_request']['lines'][0]['quantity'] = 2
            quote = baskets.quote(rid, submission['quote_request'])
            submission['displayed_quote'] = {'request_id': quote['requestId'], 'quote_id': quote['quoteId'],
                'option_id': quote['selected']['id'], 'total_minor': quote['selected']['totalMinor'], 'currency': 'SEK'}
            rows = [records.make(baskets, rid, submission, order_id='order-1')]
        capsule['after']['order_snapshot'] = snapshot(rows)
        capsule['effect_journal']['events'] = [{'kind': 'order_committed', **e} for e in snapshot(rows)['events']]
    report = grade()
    assert report['verdict'] == expected, report
    if case == 'none': assert report['order_outcome_correct'] is True


@pytest.mark.parametrize('case', ['task', 'native_context'])
def test_stale_task_and_reference_cannot_grade_different_public_request(fixture, case):
    baskets, _, task, reference, _, _, binding, capsule, _, grade = packet(fixture)
    if case == 'task': task['user_message'] = 'Different request'
    else: baskets.plan_id = 'changed-native-context'
    report = grade()
    assert report['verdict'] == 'inconclusive'
    assert report['components']['evidence']['status'] == 'inconclusive'
    assert 'record' not in report['components']
    assert report['order_outcome_correct'] is None
    with pytest.raises(ValueError): tasks.reference(baskets, task)


def test_quantity_and_menu_do_not_become_implicit_defaults(fixture):
    baskets, _, _ = fixture
    for change in ({'quantity': True}, {'quantity': 1000001}, {'delivery_types': []},
                   {'delivery_types': ['home', 'home']}, {'delivery_types': ['foreign']}, {'public_request': ''}):
        with pytest.raises(ValueError): tasks.make(baskets, {**spec_for(fixture), **change})
