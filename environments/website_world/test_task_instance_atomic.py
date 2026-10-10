"""Native atomic permutations with truthful saved catalog and scope bindings."""
from copy import deepcopy
import json

import pytest

from .task_instance_atomic import ADAPTER
from .test_atomic_product_tasks import fixture


def inputs(kind, **extras):
    world, task, reference, args, *_ = fixture(kind)
    records = {'atomic-product-catalog.private.json': args['catalog'],
               'atomic-product-bindings.private.json': args['bindings'],
               'checkout-domain.private.json': args['checkout_domain'],
               'atomic-product-runtime-options.private.json': {'selector_capture': {
                   'shop': {'page_id': 'page', 'control_token': 'a' * 32, 'task_actions': True}}},
               'atomic-product-assets.private.json': {'shop.js': 'b' * 64,
                                                      'selector-action-capture.js': 'c' * 64},
               'execution.private.json': {'answer_grading': {'mode': 'subscription-post-run',
                                                            'model': 'offline'}}}
    snapshot = (None, {}, {name: json.dumps(value).encode() for name, value in records.items()})
    parameters = {**task['spec'], 'scoring_scope': 'observed_atomic_state', **extras}
    instance = {'parameters': parameters}
    return world, task, reference, args, snapshot, instance


@pytest.mark.parametrize('kind', ['read_listed_price', 'read_public_fact',
                                 'select_exact_variant', 'add_exact_quantity'])
def test_construct_and_authored_records_bind_existing_native_task(kind):
    world, task, reference, args, snapshot, instance = inputs(kind)
    original = deepcopy(snapshot)
    result = ADAPTER.construct(world, {}, instance['parameters'], snapshot=snapshot)
    assert result == (task, reference, args['catalog'])
    start = {'kind': 'product', 'offer_id': task['offer_id']}
    records, public_start = ADAPTER.records(world, {}, *result, {}, start,
        'My own concise request.', snapshot=snapshot, instance=instance)
    assert records['episode.json']['manual_task']['user_message'] == 'My own concise request.'
    assert records['episode.json']['start'] == task['start']
    assert records['atomic-product-setup.private.json']['selected_offer_id'] == task['setup']['selected_offer_id']
    assert public_start == start and snapshot == original
    assert ADAPTER.metrics(reference) == {'status': 'ready', 'population': 1}


def test_default_scope_stays_whole_run_and_cannot_reuse_scoped_recorder():
    world, task, reference, args, snapshot, instance = inputs('read_listed_price')
    instance['parameters'].pop('scoring_scope')
    result = ADAPTER.construct(world, {}, instance['parameters'], snapshot=snapshot)
    with pytest.raises(ValueError, match='whole-run source'):
        ADAPTER.records(world, {}, *result, {}, {'kind': 'product', 'offer_id': task['offer_id']},
            'What is the price?', snapshot=snapshot, instance=instance)
    buffers = {name: value for name, value in snapshot[2].items()
               if name not in ('atomic-product-runtime-options.private.json', 'atomic-product-assets.private.json')}
    strict = (*snapshot[:2], buffers)
    records, _ = ADAPTER.records(world, {}, *result, {}, {'kind': 'product', 'offer_id': task['offer_id']},
        'What is the price?', snapshot=strict, instance=instance)
    assert records['atomic-product-scoring-scope.private.json'] == 'whole_run'


def test_unknown_or_hidden_fact_and_uncarried_offer_fail():
    world, task, _, _, snapshot, instance = inputs('read_public_fact')
    for changes in ({'fact': {'field': 'sku.facts.secret'}}, {'offer_id': 'shop/absent'}):
        with pytest.raises(ValueError):
            ADAPTER.construct(world, {}, {**instance['parameters'], **changes}, snapshot=snapshot)


def test_wrong_start_and_missing_read_extraction_fail():
    world, task, reference, args, snapshot, instance = inputs('read_public_fact')
    with pytest.raises(ValueError, match='exact target'):
        ADAPTER.records(world, {}, task, reference, args['catalog'], {}, {'kind': 'directory'},
            'Read it.', snapshot=snapshot, instance=instance)
    buffers = {**snapshot[2], 'execution.private.json': b'{"answer_grading":{"mode":"off"}}'}
    with pytest.raises(ValueError, match='automatic post-run'):
        ADAPTER.execution_overrides({'snapshot': (*snapshot[:2], buffers), 'task': task})


def test_recipe_requires_native_extension_and_panel_setting_is_bound():
    assert not ADAPTER.recipe_matches({'recipe': ADAPTER.recipe})
    assert ADAPTER.recipe_matches({'recipe': ADAPTER.recipe,
        'atomic_product_recipe': 'website-atomic-product-publication-v1'})
    world, task, reference, args, snapshot, instance = inputs('read_public_fact', product_details_open=False, product_details_heading='Care')
    records, _ = ADAPTER.records(world, {}, task, reference, args['catalog'], {},
        {'kind': 'product', 'offer_id': task['offer_id']}, 'Read it.', snapshot=snapshot, instance=instance)
    assert records['atomic-product-setup.private.json']['product_details_open'] is False
    assert records['atomic-product-setup.private.json']['product_details_heading'] == 'Care'
    instance['parameters']['product_details_heading'] = 'Secret panel'
    with pytest.raises(ValueError, match='actual native public fact panel'):
        ADAPTER.records(world, {}, task, reference, args['catalog'], {},
            {'kind': 'product', 'offer_id': task['offer_id']}, 'Read it.', snapshot=snapshot, instance=instance)


def test_reference_mass_assertion_requires_visible_basis_and_preserves_scalar():
    world, task, _, args, snapshot, instance = inputs('read_public_fact')
    row = args['catalog']['products'][0]['variants'][0]['details'][0]['facts'][0]
    row.clear()
    row.update(label='Reference size weight', slotId='tablet.reference', status='known',
        value='Reference configuration (Wi-Fi only / gray): weight 470 g.', assertions=[
            {'field': 'product.facts.reference_mass_g', 'value': 470, 'unit': 'g',
             'status': 'known', 'authority': 'catalog_fact', 'subject': {'kind': 'product', 'id': 'product'}},
            {'field': 'product.facts.reference_configuration', 'value': 'Wi-Fi only / gray',
             'status': 'known', 'authority': 'catalog_fact', 'subject': {'kind': 'product', 'id': 'product'}}])
    from . import atomic_product_task as native
    spec = {**task['spec'], 'fact': {'field': 'product.facts.reference_mass_g'}}
    projected = native.make(world, spec, **args)
    reference = native.reference(world, projected, **args)
    assert reference['expected_claims'] == {'value': 470, 'unit': 'g', 'qualifier': 'Wi-Fi only / gray'}
    for corrupt in ('basis', 'subject', 'both_subjects', 'missing_subjects', 'unit', 'duplicate', 'visible'):
        original = deepcopy(row)
        if corrupt == 'basis': row['assertions'].pop()
        elif corrupt == 'subject': row['assertions'][0]['subject']['id'] = 'other'
        elif corrupt == 'both_subjects':
            for a in row['assertions']: a['subject']['id'] = 'other'
        elif corrupt == 'missing_subjects':
            for a in row['assertions']: a.pop('subject')
        elif corrupt == 'unit': row['assertions'][0]['unit'] = 'kg'
        elif corrupt == 'duplicate': row['assertions'].append(deepcopy(row['assertions'][0]))
        elif corrupt == 'visible': row['value'] = 'A different configuration; weight 470 g.'
        with pytest.raises(ValueError): native.make(world, spec, **args)
        row.clear(); row.update(original)
