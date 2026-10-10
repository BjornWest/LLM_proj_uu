"""Conditioning and fresh native generation checks; no inference or paid calls."""
from copy import deepcopy
from math import exp
from pathlib import Path
import json

import pytest

from environments.website_world import generation as pipeline
from environments.website_world import requirements as req


def request(**options):
    return {'schema': pipeline.VERSION, 'seed': 1, **options}


def condition(values, target=None, rid='difficulty'):
    return {'id': rid, 'target': target or {'kind': 'best_matching_retailers'}, 'conditions': values}


def fake_world(seed=1, scales=('small',), winners=None, form=None):
    return {'seed': seed, 'world_id': 'world-'+str(seed),
        'products': [], 'quote_as_of': '2026-10-03',
        'reference': {'winners': [{'retailer_id': sid} for sid in (winners or ['r0'])]},
        'retailers': [{'retailer_id': 'r'+str(i), 'scale': scale, 'offers': [],
            'initial_form': {'provenance': form or {'autofill': False, 'incorrect_values': False,
                'missing_fields': False, 'wrong_mode': None}}} for i, scale in enumerate(scales)]}


def test_completion_weights_change_upstream_profile_distribution():
    config = pipeline.compile_request(request(requirements=[condition({'site.search': ['false']})]))
    masses = []
    for scale in ('small', 'medium', 'large'):
        value = req.evaluate(fake_world(scales=(scale,)), config['requirements'], config['priors'])
        masses.append(exp(value['log_mass']))
    assert masses == pytest.approx([.15, .02, 0])
    # Equal upstream priors become 15/17, 2/17, 0, not a uniform viable choice.
    assert [v/sum(masses) for v in masses] == pytest.approx([15/17, 2/17, 0])
    assert exp(req.log_upper_bound(config['requirements'])) == pytest.approx(.15)


def test_all_ties_and_overlapping_scopes_are_counted_once():
    a = condition({'site.resetPolicy': ['services', 'delivery', 'checkout']})
    b = condition({'site.resetPolicy': ['services']}, {'kind': 'retailer_id', 'retailer_id': 'r0'}, 'overlap')
    config = pipeline.compile_request(request(requirements=[a, b]))
    world = fake_world(scales=('small', 'medium'), winners=['r0', 'r0', 'r1'])
    value = req.evaluate(world, config['requirements'], config['priors'])
    assert exp(value['log_mass']) == pytest.approx(.05*.1)
    assert value['resolved'][0]['retailer_ids'] == ['r0', 'r1']
    assert value['conditions']['r0']['site.resetPolicy'] == ['services']
    assert exp(req.log_upper_bound(config['requirements'])) == pytest.approx(.05)


def test_natural_forms_are_conditions_not_overrides(monkeypatch):
    a = condition({'site.url': ['none']})
    a['initial_form'] = {'autofill': [True], 'wrong_mode': ['previous_home']}
    config = pipeline.compile_request(request(requirements=[a]))
    world = fake_world(form={'autofill': True, 'incorrect_values': True, 'missing_fields': False,
                             'wrong_mode': 'previous_home'})
    monkeypatch.setattr(req, 'initial_home_delivery_available', lambda *args: True)
    before = deepcopy(world)
    assert exp(req.evaluate(world, config['requirements'], config['priors'])['log_mass']) == pytest.approx(1/3)
    assert world == before
    assert req.evaluate(fake_world(), config['requirements'], config['priors'])['reason'] == 'producer_form'
    monkeypatch.setattr(req, 'initial_home_delivery_available', lambda *args: False)
    assert req.evaluate(world, config['requirements'], config['priors'])['reason'] == 'native_stale_coverage'


def test_empty_targets_and_contradictions_have_zero_mass():
    config = pipeline.compile_request(request(requirements=[condition({'site.url': ['none']})]))
    world = fake_world(); world['reference']['winners'] = []
    assert req.evaluate(world, config['requirements'], config['priors'])['reason'] == 'empty_target'
    both = pipeline.compile_request(request(requirements=[condition({'site.url': ['none']}),
        condition({'site.url': ['all']}, rid='contradiction')]))
    assert req.evaluate(fake_world(), both['requirements'], both['priors'])['log_mass'] == float('-inf')


@pytest.mark.parametrize('options', [
    {'difficulty': {'coupon_opacity_probability': .2}},
    {'requirements': [condition({'site.opaque': ['true']})]},
    {'requirements': [condition({'site.search': [False]})]},
    {'requirements': [condition({'site.url': ['invalid']})]},
    {'requirements': [condition({'site.reset': ['false'], 'site.resetPolicy': ['services']})]},
    {'world': {'controls': {'world_size': float('nan')}}},
    {'realism': {'family_weights': {'typical': {'typical': 1}}}},
    {'episode': {'start': {'kind': 'best_store'}}},
    {'difficulty': {'address_probabilities': None}},
    {'difficulty': {'address_probabilities': {'autofill_probability': True}}},
    {'difficulty': {'address_probabilities': {'incorrect_probability': 1.1}}},
    {'difficulty': {'address_probabilities': {'missing_probability': -1}}},
    {'difficulty': {'address_probabilities': {'force': 'old'}}},
    {'surrounding_sites': None},
    {'surrounding_sites': {'retailer_pair_probability': 2}},
])
def test_bad_or_unsupported_requests_fail_before_generation(options):
    def forbidden(*args, **kwargs):
        pytest.fail('Producer was called for an invalid request')
    with pytest.raises(ValueError):
        pipeline.generate(request(**options), world_factory=forbidden)


def test_budget_exhaustion_is_not_unsat_and_never_returns_fallback():
    def impossible(seed, **kwargs):
        return fake_world(seed, scales=('large',))
    value = request(requirements=[condition({'site.search': ['false']})], budget={'max_proposals': 3})
    with pytest.raises(pipeline.SamplingBudgetExceeded) as result:
        pipeline.generate(value, world_factory=impossible)
    audit = result.value.audit
    assert audit['feasibility'] == 'unknown'
    assert len(audit['proposals']) == 3
    assert all(row['completion_mass'] == 0 and not row['accepted'] for row in audit['proposals'])


def test_reset_boolean_is_derived_and_unit_choice_does_not_change_site_prior():
    config = pipeline.compile_request(request(requirements=[condition({
        'site.reset': ['true'], 'site.resetPolicy': ['preserve', 'services']})]))
    assert config['requirements'][0]['conditions'] == {'site.resetPolicy': ['services']}
    assert exp(req.evaluate(fake_world(), config['requirements'], config['priors'])['log_mass']) == pytest.approx(.05)
    before = req.domains('typical', config['priors'])
    priors = deepcopy(config['priors'])
    priors['roles']['product']['typical'].append('extra-example')
    after = req.domains('typical', priors)
    assert before['site.url'] == after['site.url']
    assert sum(before['module.product'][u] for u in ('story', 'tabs', 'technical')) == pytest.approx(
        sum(after['module.product'][u] for u in ('story', 'tabs', 'technical', 'extra-example')))


def test_unique_best_offer_ignores_service_ties_but_rejects_another_offer():
    config = pipeline.compile_request(request(requirements=[{'id': 'unique-best',
        'target': {'kind': 'world_reference'}, 'best_offer_count': {'min': 1, 'max': 1}}]))
    world = fake_world()
    world['reference'].update(status='match', winners=[{'retailer_id': 'r0', 'offer_id': 'offer-a'},
                                                    {'retailer_id': 'r0', 'offer_id': 'offer-a'}])
    assert req.evaluate(world, config['requirements'], config['priors'])['log_mass'] == 0
    world['reference']['winners'].append({'retailer_id': 'r0', 'offer_id': 'offer-b'})
    assert req.evaluate(world, config['requirements'], config['priors'])['reason'] == 'best_offer_count'


def test_actual_rejection_sampler_preserves_conditional_profile_weights():
    # A declared toy upstream population with equal profile probabilities.
    # This checks the integrated acceptance/draw path, not just its mass helper.
    def factory(seed, **kwargs):
        return fake_world(seed, scales=(('small', 'medium', 'large')[seed % 3],))
    profiles = []
    for seed in range(450):
        result = pipeline.generate({'schema': pipeline.VERSION, 'seed': seed,
            'requirements': [condition({'site.search': ['false']})]}, world_factory=factory)
        profiles.append(result['world']['retailers'][0]['scale'])
        assert result['compositions']['r0']['config']['search'] is False
    assert 'large' not in profiles
    assert profiles.count('small')/len(profiles) == pytest.approx(15/17, abs=.055)


def test_weight_object_order_does_not_change_seeded_draws():
    weights = {'preserve': .9, 'services': .05, 'delivery': .03, 'checkout': .02}
    first = pipeline.compile_request(request(difficulty={'reset_weights': weights}))
    second = pipeline.compile_request(request(difficulty={'reset_weights': dict(reversed(list(weights.items())))}))
    assert list(first['resets']) == list(second['resets'])


def test_source_pin_covers_dependencies_and_excludes_unrelated_product_recipes():
    sources = pipeline.source_files()
    assert set(pipeline.QUOTE_SOURCES) <= set(sources)
    assert 'environments/product_world/footwear_context_pilot.py' in sources
    assert 'environments/product_world/data/footwear_context_pilot/spec.json' in sources
    assert 'intent_browser/connected_world_task.py' in sources
    assert 'environments/product_world/data/product_public_content/trousers.chinos.json' not in sources
    assert 'experiments/footwear_world_pilot/difficulty_generation.py' in sources


def test_address_parameters_are_validated_and_passed_before_any_draw():
    calls = []
    def factory(seed, **options):
        calls.append(options)
        return fake_world(seed)
    pipeline.generate(request(difficulty={'address_probabilities': {'autofill_probability': 0}}),
                      world_factory=factory)
    assert calls[0]['address_options'] == {
        'autofill_probability': 0, 'incorrect_probability': .2, 'missing_probability': .25}
    calls.clear()
    pipeline.generate(request(), world_factory=factory)
    assert 'address_options' not in calls[0]


def test_explicit_address_options_match_the_released_native_example_and_preserve_commerce():
    from hashlib import sha256
    receipt_path = pipeline.ROOT/'.local/coordination/website-e2e-address-controls-v1/manifest.json'
    receipt = json.loads(receipt_path.read_text())
    stage_file = pipeline.ROOT/'experiments/footwear_world_pilot/difficulty_generation.py'
    assert sha256(stage_file.read_bytes()).hexdigest() == receipt['source_sha256'][str(stage_file.relative_to(pipeline.ROOT))]
    example = pipeline.ROOT/receipt['frozen_world']
    base_path = pipeline.ROOT/receipt['base_world']
    assert sha256(example.read_bytes()).hexdigest() == receipt['frozen_world_sha256']
    assert sha256(base_path.read_bytes()).hexdigest() == receipt['base_world_sha256']
    expected, base = json.loads(example.read_text()), json.loads(base_path.read_text())
    spec = {'schema': pipeline.VERSION, 'seed': receipt['world_seed'],
            'difficulty': {'address_probabilities': receipt['address_options']}}
    result = pipeline.generate(spec)
    world = result['world']
    assert pipeline.digest(world) == pipeline.digest(expected)
    assert world['reference'] == base['reference']
    assert pipeline.digest(world['products']) == pipeline.digest(base['products'])
    assert world['address_context']['addresses'] == base['address_context']['addresses']
    for actual, old in zip(world['retailers'], base['retailers']):
        assert pipeline.digest({k:v for k,v in actual.items() if k != 'initial_form'}) == pipeline.digest(
            {k:v for k,v in old.items() if k != 'initial_form'})
    assert result['audit']['natural_address_parameters'] == receipt['address_options']
    pipeline.producer.validate(world)


def test_native_fresh_generation_replays_and_runtime_consumes_pinned_plans(tmp_path):
    spec = request(world={'concept_id': 'footwear.walking_sandals'}, requirements=[condition({
        'site.resetPolicy': ['services', 'delivery', 'checkout'], 'site.url': ['none']})])
    output = tmp_path/'generated'
    pipeline.prepare(spec, output)
    world = json.loads((output/'pin/world.json').read_text())
    audit = json.loads((output/'sampling-audit.private.json').read_text())
    # Selected native proposal is unchanged, not a task-chosen fixture rewrite.
    assert pipeline.digest(world) == pipeline.digest(pipeline.producer.generate(
        audit['selected_seed'], concept_id='footwear.walking_sandals'))
    replay = pipeline.generate(spec)
    assert pipeline.digest(replay['world']) == pipeline.digest(world)
    assert replay['compositions'] == json.loads((output/'compositions.private.json').read_text())
    with pipeline.GeneratedEpisode(output) as episode:
        assert episode.public['start_url'] == episode.runtime.index_origin+'/'
        assert episode.task.policy_navigation_origins
        assert episode.task.supports_observation_pipeline == 'native_full_only'
        for winner in world['reference']['winners']:
            sid = winner['retailer_id']
            config = episode.runtime.compositions[sid]['config']
            assert config['resetPolicy'] != 'preserve' and config['url'] == 'none'
            binding = episode.runtime.bindings['retailer_offers'][winner['offer_id']]
            assert binding['required_selection']
        public = json.dumps(episode.public)
        assert 'resetPolicy' not in public and 'best_score' not in public and 'winners' not in public
    (output/'presentation.json').write_text('{}')
    with pytest.raises(ValueError, match='artifact changed'):
        pipeline.load(output)


@pytest.mark.parametrize('explicit_basket', [False, True])
def test_native_composition_uses_default_or_explicit_basket_policy(monkeypatch, explicit_basket):
    world = fake_world()
    world['schema_version'] = pipeline.producer.VERSION
    policies = {'retailer_policies': [{'retailer_id': 'r0', 'optional_split': False,
                                     'qualification_scope': 'checkout'}]}
    calls = []
    def make_plan(actual):
        assert actual is world
        calls.append(actual)
        return deepcopy(policies)
    monkeypatch.setattr(pipeline.basket_quote, 'make_plan', make_plan)
    spec = request(basket_shipping={'enabled': explicit_basket})
    result = pipeline.generate(spec, world_factory=lambda *_args, **_kwargs: world)
    retailer = world['retailers'][0]
    expected = pipeline.site_plan(world, retailer, result['presentation'],
        basket_policy=pipeline.basket_quote.public_policy(policies, 'r0'))
    assert result['compositions']['r0'] == expected
    assert result['compositions']['r0'] != pipeline.site_plan(world, retailer, result['presentation'])
    assert len(calls) == 1
    assert result['order_set_task'] is None and result['checkout_domain'] is None
    assert result['world'] is world and 'basket_plan' not in result


def test_synthetic_noncommerce_factory_does_not_create_native_basket(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError('Synthetic finite sampling fixture has no native commerce envelope')
    monkeypatch.setattr(pipeline.basket_quote, 'make_plan', forbidden)
    assert pipeline.generate(request(), world_factory=lambda *_args, **_kwargs: fake_world())['compositions']
