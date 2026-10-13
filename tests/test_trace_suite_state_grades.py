"""Suite/session reader parity and scoped verdicts; no graders or providers."""
import hashlib
import json

import pytest

from scripts import atomic_address_trace_hub as address
from scripts import cart_state_trace_hub as cart
from scripts.trace_suites import SuiteCatalog, trace_id


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def fixture(tmp_path, *, safe_success=None):
    trace = tmp_path / 'runs/episode'
    save(trace / 'metadata.json', {'browsergym_version': '0.14.3', 'driver': 'scripted', 'tags': ['scripted']})
    save(trace / 'episode.json', {'stop_reason': 'agent_finished', 'error': None})
    save(trace / 'evaluation.json', {'safe_success': safe_success})
    plan = tmp_path / 'plan.json'
    save(plan, {'schema': 'episode-suite-plan-v1', 'id': 'suite', 'title': 'Suite', 'cases': [
        {'case_id': 'H01', 'task_id': 'address-task', 'trace_directory': str(trace),
         'model': {'model': 'scripted', 'transport': 'scripted'}, 'repeat': 1}]})
    registry = tmp_path / 'registry.json'
    save(registry, {'project_root': str(tmp_path), 'roots': [str(trace.parent)], 'suites': [str(plan)]})
    return trace, registry


def grade(scope, verdict=True, binding='verified'):
    return {'grading_scope': scope, 'binding_status': binding, 'structured_claims_correct': verdict,
            'scoring_scope': 'observed_checkout_or_submitted_address_only',
            'safe_success': None, 'full_order_completion': 'not_assessed', 'full_effects': 'unknown',
            'limitations': ['Only address fields are scored; this is not full ordering success.']}


@pytest.mark.parametrize('scope,field,verdict_scope', [
    ('captured_address_state', 'state_checks', 'derived_captured_address_state'),
    ('captured_cart_state', 'state_checks', 'derived_captured_cart_state'),
    (None, 'answer_checks', 'derived_answer_checks')])
@pytest.mark.parametrize('verdict,binding,expected', [
    (True, 'verified', True), (False, 'verified', False), (None, 'verified', None),
    (True, 'invalid', None)])
def test_scopes_counts_and_single_verification(tmp_path, scope, field, verdict_scope, verdict, binding, expected):
    trace, registry = fixture(tmp_path)
    calls = []
    def reader(path):
        calls.append(path)
        return grade(scope, verdict, binding)
    catalog = SuiteCatalog(registry, grade_reader=reader)
    detail = catalog.detail('suite')
    row = detail['cases'][0]
    assert calls == [trace]
    assert row['verdict'] is expected and row[field] is expected
    assert row['verdict_scope'] == (None if scope and binding != 'verified' else verdict_scope)
    assert row['grading_status'] == ('graded' if binding == 'verified' else 'binding_error')
    assert detail['counts'] == {'pass' if expected is True else 'fail' if expected is False else 'unknown': 1}
    if scope:
        assert 'answer_checks' not in row
        assert row['full_order_completion'] == 'not_assessed' and row['full_effects'] == 'unknown'
        assert row['limitations'] == reader(trace)['limitations']
    assert 'Address-only checks do not establish full ordering success' in detail['grade_scope_note']


def test_recorded_safe_success_stays_separate(tmp_path):
    trace, registry = fixture(tmp_path, safe_success=False)
    row = SuiteCatalog(registry, grade_reader=lambda _: grade('captured_address_state')).detail('suite')['cases'][0]
    assert row['verdict'] is False and row['verdict_scope'] == 'recorded_safe_success'
    assert row['state_checks'] is True
    assert json.loads((trace / 'evaluation.json').read_text()) == {'safe_success': False}


def test_unverified_summary_mode_keeps_scope_without_invoking_reader(tmp_path):
    trace, registry = fixture(tmp_path)
    def forbidden(_):
        raise AssertionError('verify=False invoked reader')
    row = SuiteCatalog(registry, grade_reader=forbidden).detail('suite', verify=False,
        summaries={trace_id(trace): {'derived_evaluation': grade('captured_address_state')}})['cases'][0]
    assert row['verdict_scope'] == 'derived_captured_address_state' and row['state_checks'] is True


def test_address_hub_dynamic_registration_and_changed_external_evidence(tmp_path, monkeypatch):
    trace, registry = fixture(tmp_path)
    external = tmp_path / 'external-evidence.json'
    save(external, {'native': 'pass'})
    digest = hashlib.sha256(external.read_bytes()).hexdigest()
    def native_reader(directory, entry):
        assert directory == trace
        valid = hashlib.sha256(external.read_bytes()).hexdigest() == entry['hash']
        return grade('captured_address_state', True, 'verified' if valid else 'invalid')
    monkeypatch.setattr(address, 'read_grade', native_reader)
    monkeypatch.setattr(address.cart, 'read_grade', lambda _: None)
    hub = address.AddressStateHub(registry)
    assert hub.suites.detail('suite')['cases'][0]['verdict'] is None
    config = json.loads(registry.read_text()); config['address_grades'] = {str(trace): {'hash': digest}}
    save(registry, config)
    session_grade = hub.address_grade(trace)
    row = hub.suites.detail('suite')['cases'][0]
    assert session_grade['structured_claims_correct'] is row['verdict'] is True
    assert row['verdict_scope'] == 'derived_captured_address_state'
    save(external, {'native': 'fail'})
    assert hub.suites.index()[0]['counts'] == {'unknown': 1}
    assert hub.suites.detail('suite')['cases'][0]['grading_status'] == 'binding_error'
    del config['address_grades']; save(registry, config)
    assert hub.suites.detail('suite')['cases'][0]['grading_status'] == 'not_started'


@pytest.mark.parametrize('scope', [None, 'captured_cart_state'])
def test_address_hub_falls_back_to_cart_and_answer_reader(tmp_path, monkeypatch, scope):
    trace, registry = fixture(tmp_path)
    monkeypatch.setattr(address.cart, 'read_grade', lambda directory: grade(scope, False))
    row = address.AddressStateHub(registry).suites.detail('suite')['cases'][0]
    assert row['verdict'] is False
    assert row['verdict_scope'] == ('derived_captured_cart_state' if scope else 'derived_answer_checks')


def test_cart_reader_verifies_once_per_row(tmp_path, monkeypatch):
    trace, registry = fixture(tmp_path)
    calls = []
    def reader(directory):
        calls.append(directory)
        return grade('captured_cart_state')
    monkeypatch.setattr(cart.state, 'read_grade', reader)
    detail = cart.StateSuiteCatalog(registry).detail('suite')
    assert calls == [trace] and detail['counts'] == {'pass': 1}


def test_unexecuted_case_stays_unknown_without_reading_grade(tmp_path):
    _, registry = fixture(tmp_path)
    plan = tmp_path / 'plan.json'; data = json.loads(plan.read_text())
    case = data['cases'][0]; del case['trace_directory']; case['cohort'] = str(tmp_path / 'not-launched')
    save(plan, data)
    row = SuiteCatalog(registry, grade_reader=lambda _: pytest.fail('No trace to verify')).detail('suite')['cases'][0]
    assert row['state'] == 'not_run' and row['verdict'] is None and row['grading_status'] == 'not_started'


def test_plain_catalog_retains_legacy_row_shape_for_state_views(tmp_path, monkeypatch):
    from scripts import trace_grades
    _, registry = fixture(tmp_path)
    monkeypatch.setattr(trace_grades, 'read_grade', lambda _: grade('captured_cart_state'))
    row = SuiteCatalog(registry).detail('suite')['cases'][0]
    assert row['answer_checks'] is True and row['verdict_scope'] == 'derived_answer_checks'
    assert 'state_checks' not in row and 'grading_scope' not in row


@pytest.mark.parametrize('contents', ['{"cause":"trunc', '[]', 'null'])
def test_unreadable_failure_metadata_does_not_remove_other_suites(tmp_path, contents, monkeypatch):
    trace, registry = fixture(tmp_path)
    (trace / 'grading-system-failure.json').write_text(contents)
    _, control_registry = fixture(tmp_path / 'control')
    control_plan = tmp_path / 'control/plan.json'
    plan = json.loads(control_plan.read_text()); plan['id'] = 'control'; save(control_plan, plan)
    config = json.loads(registry.read_text()); config['suites'].append(str(control_plan)); save(registry, config)
    # A malformed metadata file must not fall back to an unrelated passing grade.
    monkeypatch.setattr(address.cart, 'read_grade', lambda _: grade('captured_cart_state'))
    hub = address.AddressStateHub(registry)
    detail = hub.suites.detail('suite'); row = detail['cases'][0]
    assert row['verdict'] is None and row['grading_status'] == 'binding_error'
    assert row['verdict_scope'] is None and 'Address grade unavailable' in row['grade_binding_error']
    index = {suite['id']: suite for suite in hub.suites.index()}
    assert index['suite']['counts'] == {'unknown': 1} and index['control']['counts'] == {'pass': 1}


@pytest.mark.parametrize('filename,contents', [
    ('grading-system-failure.json', '{"cause":"setup failed"}'),
    ('atomic-address-grade.private.json', '{}')])
def test_missing_usable_native_grade_does_not_claim_a_verdict_scope(tmp_path, filename, contents):
    trace, registry = fixture(tmp_path)
    (trace / filename).write_text(contents)
    row = address.AddressStateHub(registry).suites.detail('suite')['cases'][0]
    assert row['verdict'] is None and row['state_checks'] is None
    assert row['verdict_scope'] is None and row['grading_status'] == 'binding_error'
    assert row['grade_binding_error'].startswith('System failure:')
