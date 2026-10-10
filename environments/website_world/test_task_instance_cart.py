"""Independent allocation controls for saved cart task permutations."""
from copy import deepcopy
import pytest
from . import task_instance_cart as native


def instance(monkeypatch, *, prices=(9, 2, 5), capacities=(2, 1, 2), max_lines=64):
    world = {'retailers': [{'retailer_id': 'shop', 'offers': [
        {'offer_id': oid, 'price_minor': price} for oid, price in zip(('a', 'b', 'c'), prices)]}]}
    domain = {'options': {'max_lines_per_order': max_lines}}
    monkeypatch.setattr(native.cart, 'capacities', lambda w, d, initial: {
        oid: max(0, q - initial.get(oid, 0)) for oid, q in zip(('a', 'b', 'c'), capacities)})
    return world, domain


def test_overlap_requires_distinct_physical_units(monkeypatch):
    w, d = instance(monkeypatch)
    req = [{'requirement_id': 'A', 'quantity': 1, 'offer_ids': ['a', 'b']},
           {'requirement_id': 'B', 'quantity': 2, 'offer_ids': ['b', 'c']}]
    optimum = native.cheapest_additions(w, req, d, {})
    assert optimum['status'] == 'optimal'
    assert optimum['total_minor'] == 12
    assert optimum['witness_additions'] == {'b': 1, 'c': 2}
    assert native.coverage(req, optimum['witness_additions'])['covered']


def test_existing_units_consume_stock_and_require_additions(monkeypatch):
    w, d = instance(monkeypatch, capacities=(2, 1, 2))
    req = [{'requirement_id': 'A', 'quantity': 2, 'offer_ids': ['a', 'b']}]
    optimum = native.cheapest_additions(w, req, d, {'b': 1})
    assert optimum['total_minor'] == 18
    assert optimum['witness_additions'] == {'a': 2}


def test_final_line_limit_includes_unrelated_baseline(monkeypatch):
    w, d = instance(monkeypatch, max_lines=1)
    req = [{'requirement_id': 'A', 'quantity': 1, 'offer_ids': ['a', 'b']}]
    assert native.cheapest_additions(w, req, d, {'c': 1})['status'] == 'no_match'
    assert native.cheapest_additions(w, req, d, {'a': 1})['witness_additions'] == {'a': 1}


def test_search_exhaustion_never_becomes_price_optimum(monkeypatch):
    w, d = instance(monkeypatch)
    req = [{'requirement_id': 'A', 'quantity': 1, 'offer_ids': ['a', 'b']}]
    assert native.cheapest_additions(w, req, d, {}, max_states=1) == {
        'status': 'inconclusive', 'reason': 'exact_cart_search_budget_exhausted'}


def test_one_unit_cannot_satisfy_multiple_overlapping_requirements(monkeypatch):
    w, d = instance(monkeypatch, capacities=(0, 1, 0))
    req = [{'requirement_id': rid, 'quantity': 1, 'offer_ids': ['b']} for rid in ('A', 'B')]
    assert native.cheapest_additions(w, req, d, {})['status'] == 'no_match'


def test_exact_search_matches_exhaustive_independent_enumeration(monkeypatch):
    from itertools import product
    w, d = instance(monkeypatch)
    req = [{'requirement_id': 'A', 'quantity': 1, 'offer_ids': ['a', 'b']},
           {'requirement_id': 'B', 'quantity': 2, 'offer_ids': ['b', 'c']}]
    for initial in ({}, {'a': 1}, {'b': 1}, {'c': 2}):
        feasible = []
        for a, b, c in product(range(3), range(2), range(3)):
            quantities = dict(zip(('a', 'b', 'c'), (a, b, c)))
            if sum(quantities.values()) != 3: continue
            if any(q > cap for q, cap in zip((a, b, c), native.cart.capacities(w, d, initial).values())): continue
            if native.coverage(req, quantities)['covered']: feasible.append(9*a + 2*b + 5*c)
        optimum = native.cheapest_additions(w, req, d, initial)
        assert optimum['total_minor'] == (min(feasible) if feasible else None)


def test_portable_raw_baseline_remains_authenticated_without_original_file(tmp_path):
    import json
    from hashlib import sha256
    value = {'phase': 'before_policy', 'storage_state': {'cookies': [], 'origins': [
        {'origin': 'https://shop.test', 'localStorage': [
            {'name': 'website-drafts.state.shop', 'value': '{"version":2,"cart":[]}'}]}]}}
    payload = (json.dumps(value, indent=3) + '\n').encode()
    source = tmp_path/'before.json'
    source.write_bytes(payload)
    portable = native._initial({'initial_storage': {'path': str(source), 'sha256': sha256(payload).hexdigest()}})
    source.unlink()
    assert native._initial({'initial_storage': portable}) == portable
    corrupted = deepcopy(portable)
    corrupted['raw_utf8'] += ' '
    with pytest.raises(ValueError, match='bytes changed'):
        native._initial({'initial_storage': corrupted})
    corrupted = deepcopy(portable)
    corrupted['capture']['phase'] = 'different'
    with pytest.raises(ValueError, match='decoded/raw'):
        native._initial({'initial_storage': corrupted})


def test_proven_line_limit_infeasibility_accepts_unchanged_cart(monkeypatch):
    w, d = instance(monkeypatch, max_lines=1)
    req = [{'requirement_id': 'A', 'quantity': 1, 'offer_ids': ['a', 'b']}]
    task = {'task_id': 'line-bound', 'scope': 'new_additions', 'initial_cart': 'preserve'}
    expected = {'matching': {'requirements': req}, 'initial_quantities': {'c': 1}}
    baseline = {'shop': {key: [] if key == 'orders' else '' for key in native.cart_grade.PROTECTED}}
    binding = {'retailers': {}}
    # Isolate source/capture authentication; exercise the actual native grader,
    # exact feasibility, allocation and price-objective paths together.
    monkeypatch.setattr(native, 'reference', lambda *a, **k: expected)
    monkeypatch.setattr(native.cart_grade, 'storage_binding', lambda *a: binding)
    monkeypatch.setattr(native.cart_grade, '_decode', lambda *a: (baseline, {'c': 1}))
    capsule = {'schema_version': native.cart_grade.CAPSULE_VERSION,
        'task_sha256': native.digest(task), 'binding_sha256': native.digest(binding),
        'episode_id': 'line-bound', 'main_trace_sha256': 'a'*64,
        'before': {'phase': 'before_policy', 'storage_state': {}},
        'after': {'phase': 'after_policy_before_context_close', 'storage_state': {}},
        'effect_journal': None}
    result = native.grade(w, task, expected, checkout_domain=d, binding=binding,
        capsule=capsule, episode_id='line-bound', main_trace_sha256='a'*64, policy_completed=True)
    assert result['components']['cart']['feasibility'] == 'no_match'
    assert result['components']['cart']['completion'] == 'unchanged_infeasible'
    assert result['components']['price_objective']['status'] == 'pass'
    assert result['task_completed'] is True
    assert result['effects'] == 'unknown'


@pytest.mark.parametrize('change', ['none', 'delivery_selection', 'other_address_status'])
def test_checkout_preserves_delivery_selection_and_other_form_readiness(monkeypatch, change):
    w, d = instance(monkeypatch)
    address = {'recipient': 'Alex'}
    task = {'task_id': 'existing-delivery', 'scope': 'existing_cart_only', 'initial_cart': 'preserve',
            'delivery_address': address, 'delivery_note': 'Side entrance'}
    expected = {'matching': {'requirements': []}, 'initial_quantities': {'c': 1}}
    before = {rid: {'cart': [{}] if rid == 'shop' else [], 'coupon': '', 'orders': [],
        'address': {}, 'remembered': {}, 'instructions': '', 'deliveryChoices': {},
        'split': False, 'basketSelection': None} for rid in ('shop', 'other')}
    after = deepcopy(before)
    after['shop'].update(address=address, remembered=address, instructions='Side entrance', addressStatus='valid')
    if change == 'delivery_selection':
        after['shop']['basketSelection'] = {'c': 'different-delivery'}
    elif change == 'other_address_status':
        after['other']['addressStatus'] = 'unvalidated'
    binding = {'retailers': {}}
    monkeypatch.setattr(native, 'reference', lambda *a, **k: expected)
    monkeypatch.setattr(native.cart_grade, 'storage_binding', lambda *a: binding)
    monkeypatch.setattr(native.cart_grade, '_decode', lambda storage, *a:
        (before if storage['phase'] == 'before' else after, {'c': 1}))
    monkeypatch.setattr(native.details_grade, 'address_matches', lambda world, actual, required: actual == required)
    capsule = {'schema_version': native.cart_grade.CAPSULE_VERSION,
        'task_sha256': native.digest(task), 'binding_sha256': native.digest(binding),
        'episode_id': 'existing-delivery', 'main_trace_sha256': 'a'*64,
        'before': {'phase': 'before_policy', 'storage_state': {'phase': 'before'}},
        'after': {'phase': 'after_policy_before_context_close', 'storage_state': {'phase': 'after'}},
        'effect_journal': None}
    result = native.grade(w, task, expected, checkout_domain=d, binding=binding,
        capsule=capsule, episode_id='existing-delivery', main_trace_sha256='a'*64, policy_completed=True)
    assert result['components']['cart']['status'] == 'pass'
    assert result['task_completed'] is (change == 'none')
    assert result['components']['delivery_details']['status'] == ('pass' if change == 'none' else 'fail')
    assert result['effects'] == 'unknown'
