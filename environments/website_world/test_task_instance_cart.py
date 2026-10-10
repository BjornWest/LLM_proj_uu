"""Independent allocation controls for saved cart task permutations."""
from copy import deepcopy
import pytest
from . import task_instance_cart as native


def instance(monkeypatch, *, prices=(9, 2, 5), capacities=(2, 1, 2), max_lines=64):
    world = {'world_id': 'authored-cart', 'retailers': [{'retailer_id': 'shop', 'offers': [
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


@pytest.mark.parametrize('change', ['none', 'delivery_selection', 'other_address_status', 'unfinished'])
def test_checkout_preserves_delivery_selection_and_other_form_readiness(monkeypatch, change):
    w, d = instance(monkeypatch)
    address = {'recipient': 'Alex'}
    task = {'task_id': 'existing-delivery', 'scope': 'existing_cart_only', 'initial_cart': 'preserve',
            'delivery_address': address, 'delivery_note': 'Side entrance'}
    expected = {'matching': {'requirements': []}, 'initial_quantities': {'c': 1}}
    before = {rid: {'cart': [{}] if rid == 'shop' else [], 'coupon': '', 'orders': [],
        'address': {}, 'remembered': {}, 'instructions': '', 'deliveryChoices': {},
        'split': False, 'basketSelection': None, 'revision': 1} for rid in ('shop', 'other')}
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
        capsule=capsule, episode_id='existing-delivery', main_trace_sha256='a'*64, policy_completed=change != 'unfinished', policy_outcome={'stop_reason': 'max_steps' if change == 'unfinished' else 'agent_finished'})
    assert result['components']['cart']['status'] == 'pass'
    assert result['task_completed'] is (None if change == 'delivery_selection' else change == 'none')
    assert result['components']['delivery_details']['status'] == ('fail' if change == 'other_address_status' else 'pass')
    assert result['components']['delivery_selection']['status'] == ('inconclusive' if change == 'delivery_selection' else 'pass')
    assert result['effects'] == 'unknown'


@pytest.mark.parametrize('initial,actual,expected', [
    (None, {'c': 'native-default'}, 'pass'),
    (None, {'c': 'other-option'}, 'fail'),
    ({'c': 'explicit'}, {'c': 'native-default'}, 'fail'),
    ({'c': 'explicit'}, {'c': 'explicit'}, 'pass')])
def test_only_bound_native_default_can_materialize_an_absent_selection(monkeypatch, initial, actual, expected):
    from types import SimpleNamespace
    w, d = instance(monkeypatch)
    before = {'shop': {'basketSelection': initial, 'split': False, 'deliveryChoices': {}}}
    after = {'shop': {**before['shop'], 'basketSelection': actual, 'revision': 2, 'coupon': '', 'address': {'city': 'known-home'}}}
    calls = []
    class QuoteContext:
        adapter = SimpleNamespace(world=w)
        domain = d
        plan_id = 'bound-plan'
        domain_id = 'bound-domain'
        def quote(self, retailer, request):
            calls.append((retailer, request))
            return {'quoteId': 'native-quote', 'selected': {'selection': {'c': 'native-default'}}}
    monkeypatch.setattr(native, 'Baskets', QuoteContext)
    result = native.delivery_selections(w, d, before, after, {'c': 1}, {'shop'}, QuoteContext())
    assert result['status'] == expected
    assert bool(calls) is (initial is None)
    if calls:
        assert calls[0][1]['selections'] is None
        assert calls[0][1]['lines'] == [{'line_id': 'c', 'offer_id': 'c', 'quantity': 1}]
        assert calls[0][1]['plan_id'] == 'bound-plan' and calls[0][1]['domain_id'] == 'bound-domain'


def test_missing_or_foreign_quote_context_never_qualifies_default(monkeypatch):
    from types import SimpleNamespace
    w, d = instance(monkeypatch)
    before = {'shop': {'basketSelection': None, 'split': False, 'deliveryChoices': {}}}
    after = {'shop': {**before['shop'], 'basketSelection': {'c': 'native-default'}}}
    assert native.delivery_selections(w, d, before, after, {'c': 1}, {'shop'})['status'] == 'inconclusive'
    class ForeignContext:
        adapter = SimpleNamespace(world={'world_id': 'foreign'})
        domain = d
        def quote(self, *args): raise AssertionError('Foreign quote must not run')
    monkeypatch.setattr(native, 'Baskets', ForeignContext)
    assert native.delivery_selections(w, d, before, after, {'c': 1}, {'shop'}, ForeignContext())['status'] == 'inconclusive'


@pytest.mark.parametrize('actual,selected,kind,status,expected', [
    (None, {'c': 'default'}, 'home', 'quoted', 'pass'),
    ({'c': 'economy'}, {'c': 'economy'}, 'home', 'quoted', 'pass'),
    ({'c': 'express'}, {'c': 'express'}, 'home', 'quoted', 'pass'),
    ({'c': 'pickup'}, {'c': 'pickup'}, 'retailer_branch', 'quoted', 'fail'),
    ({'c': 'invalid'}, {'c': 'default'}, 'home', 'quoted', 'fail'),
    (None, None, 'home', 'unavailable', 'fail')])
def test_home_scope_accepts_valid_services_without_price_ranking(monkeypatch, actual, selected, kind, status, expected):
    from types import SimpleNamespace
    w, d = instance(monkeypatch)
    before = {'shop': {'basketSelection': {'c': 'previous'}, 'split': False, 'deliveryChoices': {}}}
    after = {'shop': {**before['shop'], 'basketSelection': actual, 'revision': 2, 'coupon': '', 'address': {}}}
    class QuoteContext:
        adapter = SimpleNamespace(world=w)
        domain = d
        plan_id = 'plan'
        domain_id = 'domain'
        def quote(self, rid, request):
            assert request['selections'] == actual
            return {'quoteId': 'quoted-service', 'status': status, 'selected': None if selected is None else
                    {'selection': selected, 'shipments': [{'delivery': {'type': kind}}]}}
    monkeypatch.setattr(native, 'Baskets', QuoteContext)
    report = native.delivery_selections(w, d, before, after, {'c': 1}, {'shop'}, QuoteContext(), scope='valid_home_service')
    assert report['status'] == expected


@pytest.mark.parametrize('selection,ready_address,scope,accepted', [
    ({'c': 'explicit'}, False, 'preserve', False),
    (None, True, 'preserve', False),
    (None, False, 'preserve', True),
    ({'c': 'explicit'}, True, 'valid_home_service', True)])
def test_preparation_rejects_renderer_incompatible_strict_baselines(monkeypatch, selection, ready_address, scope, accepted):
    monkeypatch.setattr(native.details, 'make', lambda *a, **k: {'task_id': 'base', 'requirements': []})
    address = {k: 'present' if ready_address else '' for k in ('name', 'street', 'postcode', 'city')}
    states = {'shop': {'cart': [{}], 'basketSelection': selection, 'address': address}}
    monkeypatch.setattr(native, 'saved_baseline', lambda *a: (states, {'c': 1}))
    monkeypatch.setattr(native, '_initial', lambda *a: {'portable': 'frozen'})
    parameters = {'initial_storage': {}, 'scope': 'existing_cart_only', 'delivery_note': 'note', 'delivery_selection_scope': scope}
    if accepted:
        task = native.make({}, parameters, {}, baseline_task={'requirements': []}, checkout=True)
        assert task['delivery_selection_scope'] == scope
        assert ('Use any valid native home delivery service' in task['user_message']) is (scope == 'valid_home_service')
    else:
        with pytest.raises(ValueError, match='Strict delivery preservation'):
            native.make({}, parameters, {}, baseline_task={'requirements': []}, checkout=True)


@pytest.mark.parametrize('fault', ['lost_restoration', 'corrupt_baseline', 'stale_reference', 'malformed_binding', 'missing_binding', 'null_binding', 'malformed_after_arrays'])
def test_setup_faults_are_inconclusive_with_technical_error(monkeypatch, fault):
    w, d = instance(monkeypatch)
    task = {'task_id': 'setup-bound', 'scope': 'existing_cart_only', 'initial_cart': 'preserve'}
    expected = {'matching': {'requirements': []}, 'initial_quantities': {'c': 1}}
    binding = {'retailers': {}}
    def reference(*a, **k):
        if fault == 'corrupt_baseline': raise ValueError('Portable bytes changed')
        return {**expected, 'stale': True} if fault == 'stale_reference' else expected
    monkeypatch.setattr(native, 'reference', reference)
    def storage_binding(*a):
        if fault == 'malformed_binding': raise ValueError('Missing retailer binding')
        return binding
    monkeypatch.setattr(native.cart_grade, 'storage_binding', storage_binding)
    monkeypatch.setattr(native.cart_grade, '_decode', lambda *a: ({}, {}))
    capsule = {'schema_version': native.cart_grade.CAPSULE_VERSION, 'task_sha256': native.digest(task),
        'binding_sha256': native.digest(binding), 'episode_id': 'setup-bound', 'main_trace_sha256': 'a'*64,
        'before': {'phase': 'before_policy', 'storage_state': {}},
        'after': {'phase': 'after_policy_before_context_close', 'storage_state': {}}, 'effect_journal': None}
    if fault in ('missing_binding', 'null_binding'):
        binding = {} if fault == 'missing_binding' else None
    elif fault == 'malformed_after_arrays':
        expected['initial_quantities'] = {}
        capsule['after']['storage_state'] = {'cookies': [], 'origins': None}
    report = native.grade(w, task, expected, checkout_domain=d, binding=binding, capsule=capsule,
        episode_id='setup-bound', main_trace_sha256='a'*64, policy_completed=True)
    assert report['verdict'] == 'inconclusive' and report['task_completed'] is None
    assert report['components']['evidence']['status'] == 'inconclusive'
    assert report['technical_error']


@pytest.mark.parametrize('fault', ['legacy_choices', 'null_address'])
def test_unrestorable_baseline_fields_rejected_in_both_scopes(monkeypatch, fault):
    monkeypatch.setattr(native.details, 'make', lambda *a, **k: {'task_id': 'base', 'requirements': []})
    state = {'cart': [{}], 'basketSelection': None, 'address': {}, 'deliveryChoices': {}}
    state['deliveryChoices' if fault == 'legacy_choices' else 'address'] = {'group': 'old-choice'} if fault == 'legacy_choices' else None
    monkeypatch.setattr(native, 'saved_baseline', lambda *a: ({'shop': state}, {'c': 1}))
    for scope in ('preserve', 'valid_home_service'):
        parameters = {'initial_storage': {}, 'scope': 'existing_cart_only', 'delivery_note': 'note', 'delivery_selection_scope': scope}
        with pytest.raises(ValueError):
            native.make({}, parameters, {}, baseline_task={'requirements': []}, checkout=True)


@pytest.mark.parametrize('outcome,completed,expected', [
    ({'stop_reason': 'agent_finished'}, True, True),
    ({'stop_reason': 'max_steps'}, False, False),
    ({'stop_reason': 'max_input_tokens'}, False, False),
    ({'stop_reason': 'error', 'error': 'Provider transport failed'}, False, None),
    ({'stop_reason': 'agent_finished', 'error': 'Cleanup failed'}, False, None),
    ({'stop_reason': 'agent_finished', 'cleanup_errors': ['browser close timeout']}, True, None),
    ({'stop_reason': 'max_steps', 'execution_error': 'Runner failed'}, False, None),
    ({'stop_reason': 'unclassified'}, False, None)])
def test_terminal_infrastructure_errors_do_not_become_model_failures(monkeypatch, outcome, completed, expected):
    w, d = instance(monkeypatch, max_lines=1)
    req = [{'requirement_id': 'A', 'quantity': 1, 'offer_ids': ['a', 'b']}]
    task = {'task_id': 'terminal-bound', 'scope': 'new_additions', 'initial_cart': 'preserve'}
    reference = {'matching': {'requirements': req}, 'initial_quantities': {'c': 1}}
    baseline = {'shop': {key: [] if key == 'orders' else '' for key in native.cart_grade.PROTECTED}}
    binding = {'retailers': {}}
    monkeypatch.setattr(native, 'reference', lambda *a, **k: reference)
    monkeypatch.setattr(native.cart_grade, 'storage_binding', lambda *a: binding)
    monkeypatch.setattr(native.cart_grade, '_decode', lambda *a: (baseline, {'c': 1}))
    capsule = {'schema_version': native.cart_grade.CAPSULE_VERSION,
        'task_sha256': native.digest(task), 'binding_sha256': native.digest(binding),
        'episode_id': 'terminal-bound', 'main_trace_sha256': 'a'*64,
        'before': {'phase': 'before_policy', 'storage_state': {}},
        'after': {'phase': 'after_policy_before_context_close', 'storage_state': {}}, 'effect_journal': None}
    report = native.grade(w, task, reference, checkout_domain=d, binding=binding, capsule=capsule,
        episode_id='terminal-bound', main_trace_sha256='a'*64, policy_completed=completed, policy_outcome=outcome)
    assert report['task_completed'] is expected and report['structured_claims_correct'] is expected
    assert bool(report.get('technical_error')) is (expected is None)
    if expected is None:assert report['verdict'] == 'inconclusive'


def test_inconclusive_price_search_is_technical_evidence_fault(monkeypatch):
    w, d = instance(monkeypatch, max_lines=1)
    req = [{'requirement_id': 'A', 'quantity': 1, 'offer_ids': ['a', 'b']}]
    task = {'task_id': 'undefined-price', 'scope': 'new_additions', 'initial_cart': 'preserve'}
    reference = {'matching': {'requirements': req}, 'initial_quantities': {'c': 1}}
    baseline = {'shop': {key: [] if key == 'orders' else '' for key in native.cart_grade.PROTECTED}}
    binding = {'retailers': {}}
    monkeypatch.setattr(native, 'reference', lambda *a, **k: reference)
    monkeypatch.setattr(native.cart_grade, 'storage_binding', lambda *a: binding)
    monkeypatch.setattr(native.cart_grade, '_decode', lambda *a: (baseline, {'c': 1}))
    calls = []
    def search(*a, **k):
        calls.append(None)
        return {'status': 'no_match', 'total_minor': None} if len(calls) == 1 else {'status': 'inconclusive', 'reason': 'exact_cart_search_budget_exhausted'}
    monkeypatch.setattr(native, 'cheapest_additions', search)
    capsule = {'schema_version': native.cart_grade.CAPSULE_VERSION,
        'task_sha256': native.digest(task), 'binding_sha256': native.digest(binding),
        'episode_id': 'undefined-price', 'main_trace_sha256': 'a'*64,
        'before': {'phase': 'before_policy', 'storage_state': {}},
        'after': {'phase': 'after_policy_before_context_close', 'storage_state': {}}, 'effect_journal': None}
    report = native.grade(w, task, reference, checkout_domain=d, binding=binding, capsule=capsule,
        episode_id='undefined-price', main_trace_sha256='a'*64, policy_completed=True)
    assert report['task_completed'] is None and report['verdict'] == 'inconclusive'
    assert 'exact_cart_search_budget_exhausted' in report['technical_error']
