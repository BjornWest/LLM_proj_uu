"""Synthetic native outcome controls; not actual browser or authority evidence."""
from copy import deepcopy

import pytest

from environments.website_world import atomic_product_grading as grading
from environments.website_world.test_atomic_product_tasks import fixture, alter, run
from environments.website_world.adapter import digest


def scoped(kind='read_listed_price'):
    f = fixture(kind)
    f[-1]['effect_journal'] = None
    task = f[1]
    journal = {'schema_version': 'website-atomic-task-action-journal-v1',
               'task_sha256': digest(task), 'main_trace_sha256': 'a' * 64,
               'retailer_id': 'shop', 'complete': True, 'events': []}
    if kind == 'add_exact_quantity':
        journal['events'] = [dict(kind='cart_add', offer_id=task['offer_id'], quantity=2)]
    kwargs = dict(scoring_scope='observed_atomic_state', task_actions=journal)
    return f, kwargs


def grade(f, **kwargs):
    w, task, ref, args, binding, capsule = f
    claims = kwargs.pop('claims', deepcopy(ref['expected_claims']))
    completed = kwargs.pop('policy_completed', True)
    return grading.grade(w, task, ref, **args, binding=binding, capsule=capsule,
        episode_id='authored-control', main_trace_sha256='a' * 64,
        policy_completed=completed, claims=claims, **kwargs)


@pytest.mark.parametrize('kind', sorted(grading.native.KINDS))
def test_limited_correct_outcomes_keep_unknown_full_effects(kind):
    f, kw = scoped(kind)
    result = grade(f, **kw)
    assert result['verdict'] == 'pass'
    assert result['schema_version'] == 'website-atomic-product-grade-v2'
    assert result['scoring_scope'] == 'observed_atomic_state'
    assert result['components']['forbidden_effects']['status'] == 'inconclusive'
    assert result['unassessed_effects']
    assert run(f)['verdict'] == 'inconclusive'  # strict default is unchanged


@pytest.mark.parametrize('field,value', [
    ('schema_version', 'other'), ('task_sha256', 'b'*64),
    ('main_trace_sha256', 'b'*64), ('retailer_id', 'other'),
    ('complete', False), ('complete', 1), ('events', None)])
def test_absent_or_misbound_journal_cannot_pass(field, value):
    f, kw = scoped();kw['task_actions'][field] = value
    assert grade(f, **kw)['verdict'] == 'inconclusive'


def test_missing_or_extra_envelope():
    f, kw = scoped();kw['task_actions'] = None
    assert grade(f, **kw)['verdict'] == 'inconclusive'
    f, kw = scoped();kw['task_actions']['extra'] = 'not_bound'
    assert grade(f, **kw)['verdict'] == 'inconclusive'


@pytest.mark.parametrize('events', [
    [dict(kind='cart_add', offer_id='shop/brown38', quantity=1)],
    [dict(kind='cart_remove', offer_id='shop/brown38', quantity=1)],
    [dict(kind='order_submit')],
    [{}, dict(kind='cart_add', offer_id='shop/brown38', quantity=1)],
    [dict(kind='cart_add', offer_id='shop/brown38', quantity=1), {}]])
def test_read_forbidden_attempts_survive_terminal_equality_and_incompleteness(events):
    f, kw = scoped();kw['task_actions'].update(events=events, complete=False)
    assert grade(f, **kw)['verdict'] == 'fail'


@pytest.mark.parametrize('events', [
    [dict(kind='cart_add', offer_id='shop/black39', quantity=2)],
    [dict(kind='cart_add', offer_id='shop/brown38', quantity=3)],
    [dict(kind='cart_add', offer_id='shop/brown38', quantity=2),
     dict(kind='cart_remove', offer_id='shop/black39', quantity=1)],
    [dict(kind='order_submit')]])
def test_exact_addition_forbidden_attempts_fail_even_if_final_cart_correct(events):
    f, kw = scoped('add_exact_quantity');kw['task_actions'].update(events=events, complete=False)
    assert grade(f, **kw)['verdict'] == 'fail'


def test_add_requires_complete_exact_quantity_without_boolean_quantity():
    f, kw = scoped('add_exact_quantity');kw['task_actions']['events'] = []
    assert grade(f, **kw)['verdict'] == 'fail'
    f, kw = scoped('add_exact_quantity');kw['task_actions']['complete'] = False
    assert grade(f, **kw)['verdict'] == 'inconclusive'
    f, kw = scoped('add_exact_quantity');kw['task_actions']['events'][0]['quantity'] = True
    assert grade(f, **kw)['verdict'] == 'inconclusive'


def test_terminal_failures_survive_missing_action_capture():
    f, kw = scoped();kw['task_actions'] = None
    alter(f, 'after', lambda s: s.update(instructions='Changed'))
    assert grade(f, **kw)['verdict'] == 'fail'
    f, kw = scoped('select_exact_variant');kw['task_actions'] = None
    alter(f, 'after', lambda s: s['selection'].update(page={'size_eu':'39', 'colour':'black'}))
    assert grade(f, **kw)['verdict'] == 'fail'


def test_missing_answer_unknown_extraction_and_policy_completion():
    f, kw = scoped()
    assert grade(f, **kw, claims=None)['verdict'] == 'inconclusive'
    assert grade(f, **kw, claims=None, answer_present=False)['verdict'] == 'fail'
    assert grade(f, **kw, policy_completed=False)['verdict'] == 'inconclusive'


@pytest.mark.parametrize('journal', [
    {'authority':'complete_generated_world_event_journal','complete':False,'events':[{'kind':'order_committed'}]},
    {'authority':'wrong','complete':True,'events':[]}, {}])
def test_non_null_unaccepted_effect_journal_remains_inconclusive(journal):
    f, kw = scoped();f[-1]['effect_journal'] = journal
    assert grade(f, **kw)['verdict'] == 'inconclusive'


def test_accepted_full_effect_failure_not_filtered():
    f, kw = scoped();f[-1]['effect_journal'] = {
        'authority':'complete_generated_world_event_journal','complete':True,
        'events':[{'kind':'order_committed'}]}
    assert grade(f, **kw)['verdict'] == 'fail'


@pytest.mark.parametrize('kwargs', [
    {'scoring_scope':'typo'}, {'scoring_scope':None}, {'answer_present':'no'},
    {'task_actions':{}}, {'scoring_scope':False}])
def test_bad_consumer_configuration_raises(kwargs):
    with pytest.raises(ValueError):grade(fixture('read_listed_price'), **kwargs)


@pytest.mark.parametrize('failure', ['action', 'whole_run_effect', None])
def test_missing_terminal_selection_keeps_independent_failures(failure):
    f, kw = scoped('select_exact_variant')
    alter(f, 'after', lambda state: state.update(selection=None))
    if failure == 'action':
        kw['task_actions'].update(complete=False, events=[{}, {'kind': 'order_submit'}])
    if failure == 'whole_run_effect':
        f[-1]['effect_journal'] = {
            'authority': 'complete_generated_world_event_journal',
            'complete': True, 'events': [{'kind': 'order_committed'}]}
    result = grade(f, **kw)
    assert result['verdict'] == ('fail' if failure else 'inconclusive')
    assert result['components']['selected_variant']['status'] == 'inconclusive'
    assert result['components']['policy_completion']['status'] == 'pass'
    if failure:
        component = 'task_retailer_actions' if failure == 'action' else 'forbidden_effects'
        assert result['components'][component]['status'] == 'fail'
    # Original strict whole-run early return stays unchanged.
    strict = grade(f)
    assert strict['verdict'] == 'inconclusive'
    assert 'selected_variant' not in strict['components']
