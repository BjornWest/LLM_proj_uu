from contextlib import contextmanager
import json
from types import SimpleNamespace
import pytest
from environments.website_world import catalog_basket_execution as execution
from experiments.footwear_world_pilot.test_basket_quote import world


def setup_run(tmp_path, monkeypatch, *, admission):
    output = tmp_path/'world'; output.mkdir()
    (output/'execution.private.json').write_text(json.dumps({'validation': 'off',
        'runtime_options': {'lazy_publication': True}, 'answer_grading': {'mode': 'subscription-post-run'}}))
    if admission: (output/'delivery-plan.private.json').write_text('{}')
    events = []; discovery = object()
    class Episode:
        def __init__(self, *a, **kw):
            self.task = SimpleNamespace(files={}, make_env=lambda: None, site_discovery_callback=discovery)
            self.profile = SimpleNamespace(name='basket+site-discovery')
        def __enter__(self): return self
        def __exit__(self, *a): events.append('runtime-close')
        def export_private_runtime(self, path): path.mkdir()
    monkeypatch.setattr(execution, 'CatalogBasketEpisode', Episode)
    monkeypatch.setattr(execution.lifecycle.shared, 'load', lambda p: {'source_sha256': {}})
    monkeypatch.setattr(execution.lifecycle, 'provenance', lambda p: {'fixture': True})
    @contextmanager
    def policy(*, before_dispatch):
        before_dispatch(); events.append('policy-open')
        try: yield object()
        finally: events.append('policy-close')
    def runner(*a, **kw):
        assert kw['site_discovery'] is discovery
        trace = kw['output']/'actual'; trace.mkdir(parents=True)
        events.append('policy-result'); return trace, {'stop_reason': 'agent_finished'}
    def grade(**kw):
        assert 'policy-close' in events
        assert kw['inputs']['task'] == output/'catalog-basket-task.private.json'
        assert kw['inputs']['reference'] == output/'catalog-basket-reference.private.json'
        assert kw['inputs']['plan'] == output/'basket-plan.private.json'
        assert kw['inputs']['checkout_domain'] == output/'checkout-domain.private.json'
        assert kw['inputs']['bindings'] == tmp_path/'run/runtime-binding/bindings.private.json'
        assert 'site_registry' not in kw['inputs']
        assert ('admission_plan' in kw['inputs']) == admission
        if admission: assert kw['inputs']['admission_plan'] == output/'delivery-plan.private.json'
        assert kw['trace'] == tmp_path/'run/runs/actual'
        assert kw['grader_factory'] is execution.CatalogBasketAnswerGrader
        events.append('basket-extraction'); return {'structured_claims_correct': True}
    monkeypatch.setattr(execution.task_answer, 'grade_saved_once', grade)
    return output, events, policy, runner


@pytest.mark.parametrize('admission', [False, True])
def test_full_quote_inputs_actual_trace_and_once_only_after_close(tmp_path, monkeypatch, admission):
    output, events, policy, runner = setup_run(tmp_path, monkeypatch, admission=admission)
    kwargs = dict(policy_session=policy, metadata={}, runner_options={'max_steps': 5, 'max_input_tokens': 100000},
        quota_guard=lambda: None, extraction_backend_factory=lambda p: object(), runner=runner)
    result = execution.run(output, tmp_path/'run', **kwargs)
    assert result['answer_grading']['task_completed'] is True
    assert events == ['policy-open', 'policy-result', 'policy-close', 'basket-extraction', 'runtime-close']
    with pytest.raises(FileExistsError): execution.run(output, tmp_path/'run', **kwargs)


def test_incomplete_reference_with_incumbent_rejects_before_runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(execution.shared, 'load', lambda p: {'recipe': 'website-catalog-basket-publication-v1'})
    for name, value in [('episode.json', {}), ('catalog-basket-task.private.json', {}),
            ('catalog-basket-reference.private.json', {'result': {'complete': False, 'status': 'work_limit', 'total_minor': 71800}}),
            ('catalog-basket-binding.private.json', {'status': 'bound_exact_reference', 'world_repaired': False})]:
        (tmp_path/name).write_text(json.dumps(value))
    import environments.website_world.runtime as runtime
    def forbidden(*a, **kw): raise AssertionError('Runtime must not start')
    monkeypatch.setattr(runtime, 'Runtime', forbidden)
    with pytest.raises(ValueError, match='inconclusive'): execution.CatalogBasketEpisode(tmp_path)


def test_foreign_returned_trace_cannot_grade(tmp_path, monkeypatch):
    output, events, policy, _ = setup_run(tmp_path, monkeypatch, admission=False)
    def foreign(*a, **kw): return tmp_path/'foreign', {'stop_reason': 'agent_finished'}
    with pytest.raises(ValueError, match='outside this execution'):
        execution.run(output, tmp_path/'run', policy_session=policy, metadata={},
            runner_options={'max_steps': 5, 'max_input_tokens': 100000}, quota_guard=lambda: None, runner=foreign)
    assert 'basket-extraction' not in events


def test_natural_plan_cannot_reuse_one_unit_for_overlapping_requirements(world):
    """Authored finite native fixture, separate from the two saved merchant worlds."""
    from copy import deepcopy
    from decimal import Decimal
    from experiments.accepted_catalog_commerce.execution import _bind
    from environments.website_world.test_catalog_basket_task import fixture
    from environments.website_world.test_catalog_basket_answer_grading import sample
    grader, text, claims = _bind(sample, fixture=lambda w: fixture(w, overlap=True))(world)
    assert grader.grade(claims, text)['structured_claims_correct']
    broken = deepcopy(claims)
    broken['orders'] = broken['orders'][:1]
    broken['orders'][0]['lines'] = broken['orders'][0]['lines'][:1]
    line = broken['orders'][0]['lines'][0]
    line['quantity'] = {'value': 1, 'evidence': 'one sale unit: 1'}
    order = grader._order(broken['orders'][0])
    assert order is not None
    native_lines = [{'line_id': l['offer_id'], 'offer_id': l['offer_id'], 'quantity': l['quantity']} for l in order['lines']]
    selected = grader.quotes.quote(order['retailer_id'], native_lines,
        selections=order['selections'], split=order['split'])['selected']
    amount = f"{Decimal(selected['total_minor'])/100:.2f}"
    quote = 'incomplete order total: ' + amount + ' SEK'
    broken['total'] = {'amount': amount, 'currency': 'SEK', 'evidence': quote}
    grade = grader.grade(broken, text + '; one sale unit: 1; ' + quote)
    assert not grade['structured_claims_correct']
    assert grade['derivations'][0]['native_report']['verdict'] == 'fail'
