"""Ordering/replay contracts; all populations below are finite synthetic fixtures."""
from copy import deepcopy
from hashlib import sha256
import json

import pytest

from environments.website_drafts import component_sampling as components
from environments.website_drafts import variation_sampling as variations

POLICY = {'split': True, 'policy': 'footer', 'qualification': 'basket',
          'collectionPayment': 'collection'}


def shuffled(value):
    if isinstance(value, dict):
        return {key: shuffled(item) for key, item in reversed(list(value.items()))}
    if isinstance(value, list):
        return [shuffled(item) for item in reversed(value)]
    return value


def sample(seed, profile, priors, **kwargs):
    return components.sample_components(seed, f'retailer-{seed % 7}',
        profile=profile, policy=POLICY, priors=priors, **kwargs)


def test_exact_historical_240_plan_digest_including_variations():
    # Captured on unmodified 23cb594, before the v2 source delta. Covers all
    # profiles, module/variant choices, constrained draws and prior identities.
    plans = []
    for profile in ('boutique', 'typical', 'huge'):
        for seed in range(40):
            for enabled in (False, True):
                priors = components.load_priors()
                variation = variations.normalize({'enabled': True},
                    components.factors(profile, priors)) if enabled else None
                conditions = {'site.global': ['guided'],
                    'module.product': ['technical', 'tabs']} if seed % 2 else None
                plans.append(sample(seed, profile, priors, conditions=conditions,
                                    variation_priors=variation))
    assert sha256(components.canonical(plans).encode()).hexdigest() == (
        'dfbae8dfca3ce0b225e12a939fed1914045816c0f1bc95034a6a4515efb02e9a')
    assert components.load_priors() == components.load_priors(version=1)


@pytest.mark.parametrize('profile', ['boutique', 'typical', 'huge'])
def test_v2_dict_and_unit_order_are_irrelevant_to_complete_plans(profile):
    priors = components.load_priors(version=2)
    # Uneven orders of magnitude also exercise canonical summation, rather
    # than merely getting lucky with equal outcome weights.
    priors['site_choices']['global'] = {'standard': 1e16, 'guided': 1., 'concise': 2.}
    reordered = shuffled(priors)
    persisted = json.loads(components.canonical(reordered))
    original = deepcopy(reordered)
    variation = variations.normalize({'enabled': True,
        'unit_weights': {'product': {'technical': {'product.facts': {
            'base': 0, 'definitions': 0, 'table': 1}}}}},
        components.factors(profile, priors))
    for enabled in (False, True):
        for seed in range(40):
            options = {'variation_priors': variation} if enabled else {}
            expected = sample(seed, profile, priors, **options)
            assert sample(seed, profile, reordered, **options) == expected
            assert sample(seed, profile, persisted, **options) == expected
            assert expected['component_priors_schema'] == 'website-component-priors-v2'
    assert reordered == original  # No caller-owned mutation.


@pytest.mark.parametrize('profile', ['boutique', 'typical', 'huge'])
def test_v2_joint_condition_mass_and_supported_draws(profile):
    priors = components.load_priors(version=2)
    modules = components.factors(profile, priors)
    vp = variations.normalize({'enabled': True, 'unit_weights': {'product': {
        'technical': {'product.facts': {'base': 0, 'definitions': 0, 'table': 1}}}}}, modules)
    conditions = {'site.global': ['guided'], 'variation.product.facts': ['table'],
                  'variation.site.navigationGrouping': ['shopping-services']}
    parent = modules['module.product']['technical']
    expected = (1 / 3) * (parent + (1 - parent) / 3) * (1 / 6)
    posterior, mass = components.conditioned_factors(profile, priors=priors,
        conditions=conditions, variation_priors=vp)
    assert mass == pytest.approx(expected)
    assert posterior['module.product']['technical'] == pytest.approx(
        parent / (parent + (1 - parent) / 3))
    other, reordered_mass = components.conditioned_factors(profile,
        priors=shuffled(priors), conditions=conditions, variation_priors=vp)
    assert other == posterior
    assert reordered_mass == mass
    for seed in range(20):
        plan = sample(seed, profile, priors, conditions=conditions, variation_priors=vp)
        assert plan == sample(seed, profile, shuffled(priors),
                              conditions=conditions, variation_priors=vp)
        assert plan['condition_mass'] == mass
        assert plan['config']['global'] == 'guided'
        assert plan['config']['variations']['product']['facts'] == 'table'
        assert plan['config']['variations']['site']['navigation'] == 'grouped'
    with pytest.raises(ValueError, match='zero supported variation mass'):
        sample(1, profile, priors, variation_priors=vp,
               conditions={'variation.product.gallery': ['featured']})


def test_v2_scoped_streams_and_hash_bind_domains_and_version():
    priors = components.load_priors(version=2)
    expanded = deepcopy(priors)
    expanded['roles']['home']['typical'].append('future-home')
    for seed in range(35):
        a = sample(seed, 'typical', priors)
        b = sample(seed, 'typical', expanded)
        assert a['priors_sha256'] != b['priors_sha256']
        for role in priors['roles']:
            if role != 'home':
                assert a['config']['modules'][role] == b['config']['modules'][role]
                assert a['unit_permutations'][role] == b['unit_permutations'][role]
        assert a['priors_sha256'] != sample(seed, 'typical',
                                          components.load_priors())['priors_sha256']
    with pytest.raises(ValueError, match='Unknown allowed value'):
        sample(1, 'typical', priors, conditions={'module.product': ['missing']})


@pytest.mark.parametrize('version', [0, 3, True, None, '2'])
def test_unknown_prior_versions_rejected(version):
    with pytest.raises(ValueError, match='Unsupported component priors version'):
        components.load_priors(version=version)


def test_native_and_unified_compilers_forward_explicit_mode_only():
    from environments.website_world import generation, unified_generation
    for compiler in (generation, unified_generation):
        req = {'schema': compiler.VERSION, 'seed': 1}
        original = compiler.compile_request(req)
        explicit = compiler.compile_request({**req, 'realism': {'component_ordering': 'legacy-v1'}})
        assert original['priors'] == explicit['priors']
        assert original['priors']['schema'] == 'website-component-priors-v1'
        canonical = compiler.compile_request({**req, 'realism': {'component_ordering': 'canonical-v2'}})
        assert canonical['priors']['schema'] == 'website-component-priors-v2'
        assert original['world'] == canonical['world']
        assert original['requirements'] == canonical['requirements']
        for bad in (None, True, 'canonical-v1', 2, []):
            with pytest.raises(ValueError, match='Unknown component ordering mode'):
                compiler.compile_request({**req, 'realism': {'component_ordering': bad}})


@pytest.mark.parametrize('enabled', [False, True])
def test_materialized_presentation_replays_canonical_priors(enabled):
    from environments.website_world import generation, presentation
    def fixture(seed, **kwargs):
        return {'seed': seed, 'world_id': f'fixture-{seed}', 'products': [],
            'quote_as_of': '2026-10-03', 'reference': {'winners': [{'retailer_id': 'shop'}]},
            'retailers': [{'retailer_id': 'shop', 'scale': 'medium', 'offers': [],
                          'initial_form': {'provenance': {}}}]}
    request = {'schema': generation.VERSION, 'seed': 41,
        'realism': {'component_ordering': 'canonical-v2',
                    'page_variations': {'enabled': enabled}},
        'requirements': [{'id': 'guided', 'target': {'kind': 'all_retailers'},
                          'conditions': {'site.global': ['guided']}}]}
    result = generation.generate(request, world_factory=fixture)
    world = result['world']
    # Reconstruct from persisted presentation, rather than calling a mocked
    # sampler. Real native manufacture is intentionally not involved.
    spec = result['presentation']
    assert spec['component_priors']['schema'] == 'website-component-priors-v2'
    first = presentation.site_plan(world, world['retailers'][0], spec)
    reloaded = json.loads(components.canonical(spec))
    reloaded['component_priors'] = shuffled(reloaded['component_priors'])
    assert presentation.site_plan(world, world['retailers'][0], reloaded) == first
    assert first == result['compositions']['shop']
    assert first['config']['global'] == 'guided'
