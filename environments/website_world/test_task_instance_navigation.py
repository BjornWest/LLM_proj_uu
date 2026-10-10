"""Native semantic and saved-start controls; no browser or provider dispatch."""
from copy import deepcopy
from hashlib import sha256
import json

import pytest

from . import task_instance_navigation as adapters
from . import variant_link_capability as capability, variant_link_task as link_native
from . import variant_link_grading
from .test_variant_link_task import fixture as link_fixture
from .test_listed_offer_grading import fixture as offer_fixture
from . import ecosystem


def encoded(value):
    return json.dumps(value).encode()


@pytest.fixture
def accepted_link(tmp_path):
    # Synthetic acceptance envelope tests the actual validation/compiler path;
    # this is not evidence that a browser recipient was tested.
    world, spec, args = link_fixture('none')
    catalog, bindings, cap = args['catalog'], args['bindings'], args['navigation_capability']
    variants = catalog['products'][0]['variants']
    cases = []
    for variant in variants:
        for previous in [None, *[v['selection'] for v in variants]]:
            cases.append({'target_selection': variant['selection'], 'previous_selection': previous,
                'actual_selection': variant['selection'], 'status': 'pass',
                **{key: 'synthetic-state.json' for key in
                   ('before_state_file', 'after_state_file', 'dom_file', 'ax_file')}})
    records = {'world.private.json': world, 'catalog.private.json': catalog,
        'bindings.private.json': bindings, 'navigation-capability.private.json': cap,
        'served-assets.private.json': cap['asset_sha256'], 'recipient-cases.private.json': cases,
        'synthetic-state.json': {'classification': 'synthetic'}}
    for name, value in records.items():
        (tmp_path/name).write_bytes(encoded(value))
    manifest = {'schema': capability.VERSION, 'files': {
        name: sha256((tmp_path/name).read_bytes()).hexdigest() for name in records}}
    manifest_path = tmp_path/'manifest.json'
    manifest_path.write_bytes(encoded(manifest))
    pin = lambda path: {'path': str(path), 'sha256': sha256(path.read_bytes()).hexdigest()}
    approval_path = tmp_path/'approval.json'
    approval_path.write_bytes(encoded({'schema': capability.ACCEPTANCE, 'owner': 'Product',
        'status': 'accepted', 'capability_sha256': link_native.digest(cap),
        'evidence_manifest': pin(manifest_path)}))
    buffers = {name: encoded(value) for name, value in {
        'variant-link-catalog.private.json': catalog, 'variant-link-bindings.private.json': bindings,
        'variant-link-assets.private.json': cap['asset_sha256'],
        'variant-link-acceptance.private.json': pin(approval_path),
        'execution.private.json': {'answer_grading': {'mode': 'subscription-post-run',
            'model': 'authored', 'reasoning_effort': 'low'}}}.items()}
    return world, spec, args, (tmp_path, {}, buffers)


def test_product_only_link_uses_native_limited_url_and_manual_selection(accepted_link):
    world, spec, args, snapshot = accepted_link
    adapter = adapters.VariantLinkAdapter()
    task, reference, inventory = adapter.construct(world, {}, spec, snapshot=snapshot)
    assert task['url_behavior'] == 'none' and '?' not in reference['url']
    assert reference['manual_selection'] == {'size_eu': '38', 'colour': 'brown'}
    assert reference['recipient_must_select'] and not reference['link_encodes_full_selection']
    good = {key: deepcopy(reference[key]) for key in variant_link_grading.FIELDS}
    assert variant_link_grading.grade(world, task, reference, good, **args)['verdict'] == 'pass'
    for change in ({'manual_selection': {}}, {'url': reference['url']+'?size_eu=38&colour=brown'},
                   {'link_encodes_full_selection': True}):
        assert variant_link_grading.grade(world, task, reference, {**good, **change}, **args)['verdict'] == 'fail'
    records, start = adapter.records(world, {}, task, reference, inventory, {},
        task['start'], 'Send me these brown sandals in EU38.', snapshot=snapshot)
    assert start == task['start'] and records['episode.json']['manual_task']['user_message'] != task['user_message']
    assert task == link_native.make(world, spec, **args)


def test_link_acceptance_tampering_fails_before_task_release(accepted_link):
    world, spec, _, snapshot = accepted_link
    pin = json.loads(snapshot[2]['variant-link-acceptance.private.json'])
    with open(pin['path'], 'ab') as stream:
        stream.write(b' ')
    with pytest.raises(ValueError, match='Pinned capability evidence changed'):
        adapters.VariantLinkAdapter().construct(world, {}, spec, snapshot=snapshot)


def test_link_cannot_supply_capability_as_parameter_or_override_start(accepted_link):
    world, spec, args, snapshot = accepted_link
    adapter = adapters.VariantLinkAdapter()
    with pytest.raises(ValueError, match='Declare link_exact_variant'):
        adapter.construct(world, {}, {**spec, 'navigation_capability': args['navigation_capability']}, snapshot=snapshot)
    task, ref, inventory = adapter.construct(world, {}, spec, snapshot=snapshot)
    with pytest.raises(ValueError, match='accepted native product page'):
        adapter.records(world, {}, task, ref, inventory, {}, {'kind': 'directory'}, 'Links please')
    assert adapter.execution_overrides({'snapshot': snapshot})['answer_grading']['mode'] == 'subscription-post-run'
    with pytest.raises(ValueError, match='authenticated saved recipe'):
        adapter.construct(world, {}, spec)


def test_offer_comparison_scope_keeps_sidecar_and_full_eligible_domain(monkeypatch):
    world, _, _, _ = offer_fixture()
    world['quote_as_of'] = '2026-10-10'
    # Fixture omits producer-only fields; native task/reference and sidecar
    # semantics run unchanged, with full world-schema validation isolated.
    monkeypatch.setattr(adapters.basic_offer_task.model, 'validate', lambda world: None)
    surrounding = ecosystem.generate(world, {'comparison_count': 1, 'review_count': 0,
        'model_probability': 1, 'retailer_pair_probability': 1})
    spec = {'kind': 'cheapest_available', 'concept_id': 'footwear.walking_shoes',
            'comparison_site_id': 'comparison-00'}
    original = deepcopy(surrounding)
    adapter = adapters.BasicOfferAdapter()
    task, ref, inventory = adapter.construct(world, surrounding, spec)
    assert surrounding == original and ref['minimum_price_minor'] == 74000
    assert len(ref['candidates']) == 12 and len(ref['winners']) == 8
    start = {'kind': 'comparison_home', 'comparison_site_id': 'comparison-00'}
    records, public_start = adapter.records(world, surrounding, task, ref, inventory,
        {'old': True}, start, 'Which walking shoes are cheapest here?')
    assert public_start == start and records['episode.json']['readable_origins'] is True
    assert records['episode.json']['manual_task']['user_message'] == task['user_message']
    assert adapter.metrics(ref) == {'status': 'match', 'population': 12}
    with pytest.raises(ValueError, match='native comparison scope'):
        adapter.records(world, surrounding, task, ref, inventory, {}, {'kind': 'directory'}, 'Cheapest?')


@pytest.mark.parametrize('adapter,consumer', [(adapters.VariantLinkAdapter(), adapters.variant_link_execution),
                                            (adapters.BasicOfferAdapter(), adapters.basic_offer_saved_answer)])
def test_adapter_dispatches_existing_consumer_with_options(monkeypatch, adapter, consumer):
    calls = []
    monkeypatch.setattr(consumer, 'run', lambda *args, **kwargs: calls.append((args, kwargs)) or {'native': True})
    assert adapter.run('recipe', 'destination', runner_options={'max_steps': None}) == {'native': True}
    assert calls == [(('recipe', 'destination'), {'runner_options': {'max_steps': None}})]
