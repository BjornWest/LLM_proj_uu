"""Consumer guards; actual browser/once-only checks live in frozen receipts."""
from copy import deepcopy
from contextlib import contextmanager
from types import SimpleNamespace
import pytest
from . import atomic_address_publication as publication
from . import atomic_address_execution as execution


def world():
    address = {'recipient': 'Alex Lind', 'street': 'Björkvägen', 'house_number': '12',
               'unit': '24', 'postcode': '61363', 'city': 'Uppsala', 'country': 'SE'}
    return {'world_id': 'test', 'address_context': {'addresses': [
        {'address_id': 'user-home', 'address': address}]}, 'retailers': [
        {'retailer_id': 'shop', 'name': 'Shop', 'offers': [
            {'offer_id': 'shop/sku', 'stock_by_source': {'branch': 1},
             'supplier_order': {'enabled': False}}]}]}


SPEC = {'kind': 'save_delivery_address', 'retailer_id': 'shop'}


def test_native_memories_cart_start_and_no_error_hint():
    task = publication.compile_setup(world(), SPEC, [{'offer_id': 'shop/sku', 'quantity': 1}])
    assert task['start'] == {'kind': 'cart'}
    assert task['expected_address']['unit'] == '24'
    assert 'apartment/unit 24' in task['memories'][0]
    assert 'old address' not in task['user_message'] and 'autofill' not in task['user_message']


@pytest.mark.parametrize('rows', [[], None, [{'offer_id': 'shop/sku', 'quantity': True}],
    [{'offer_id': 'other/sku', 'quantity': 1}], [{'offer_id': 'shop/sku', 'quantity': 0}],
    [{'offer_id': 'shop/sku', 'quantity': 1}]*2])
def test_bad_setup_rejected_before_publication(rows):
    with pytest.raises(ValueError):publication.compile_setup(world(), SPEC, rows)


def test_branch_only_orderable_and_unavailable_distinction():
    original = world();copy = deepcopy(original)
    publication.compile_setup(copy, SPEC, [{'offer_id': 'shop/sku', 'quantity': 1}])
    assert copy == original
    copy['retailers'][0]['offers'][0]['stock_by_source']['branch'] = 0
    with pytest.raises(ValueError, match='Unavailable'):
        publication.compile_setup(copy, SPEC, [{'offer_id': 'shop/sku', 'quantity': 1}])
    copy['retailers'][0]['offers'][0]['supplier_order']['enabled'] = True
    publication.compile_setup(copy, SPEC, [{'offer_id': 'shop/sku', 'quantity': 1}])


@pytest.mark.parametrize('options', [{}, {'max_steps': True, 'max_input_tokens': 1},
    {'max_steps': 1, 'max_input_tokens': 0},
    {'max_steps': 1, 'max_input_tokens': 1, 'observation_pipeline': 'other'}])
def test_finite_runner_binding_guards(options, tmp_path):
    with pytest.raises(ValueError):execution.run('not-used', tmp_path/'not-created',
        policy_session=lambda: None, metadata={}, runner_options=options)
    assert not (tmp_path/'not-created').exists()


def test_saved_world_hash_guard_precedes_output(tmp_path):
    saved = tmp_path/'saved';saved.mkdir();(saved/'world.private.json').write_text('{}')
    with pytest.raises(ValueError, match='fixture'):
        publication.prepare_saved(saved, tmp_path/'output', spec=SPEC,
            prepared_cart=[{'offer_id': 'shop/sku', 'quantity': 1}], expected_world_sha256='0'*64)
    assert not (tmp_path/'output').exists()


def test_quota_exhausted_after_last_call_does_not_suppress_saved_grade(monkeypatch, tmp_path):
    # Plumbing control only: scripted actual native/capture proof is separate.
    events = [];counts = [0]
    def quota():
        counts[0] += 1
        if counts[0] > 2:raise RuntimeError('No dispatch quota remains')
    class Episode:
        def __init__(self, *a, **kw):
            self.task = SimpleNamespace(files={}, make_env=None)
            self.profile = None;self.site_discovery = None;self.capture = None
            self.runtime = SimpleNamespace(world={}, baskets=SimpleNamespace(domain={}))
            self.native_task = {};self.reference = {}
        def __enter__(self):return self
        def __exit__(self, *a):events.append('runtime-close')
        def export_private_runtime(self, *a):pass
    @contextmanager
    def session(*, before_dispatch):
        before_dispatch();events.append('last-authorized-call')
        try:yield None
        finally:events.append('lease-close')
    def runner(*a, output, **kw):
        trace = output/'actual-return';trace.mkdir(parents=True)
        return trace, {'stop_reason': 'agent_finished'}
    def grade(*a, **kw):events.append('grade');return {'verdict': 'inconclusive'}
    monkeypatch.setattr(execution, 'AddressEpisode', Episode)
    monkeypatch.setattr(execution.grading, 'grade_saved_return', grade)
    result = execution.run('unused', tmp_path/'run', policy_session=session,
        metadata={}, runner_options={'max_steps': 1, 'max_input_tokens': 1},
        quota_guard=quota, runner=runner)
    assert counts == [2]
    assert events == ['last-authorized-call', 'lease-close', 'grade', 'runtime-close']
    assert result['state_grading']['verdict'] == 'inconclusive'
