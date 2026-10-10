"""Joint parent/child completion and fresh recipe integration; no inference."""
from copy import deepcopy
from importlib.util import module_from_spec, spec_from_file_location
from math import exp
from pathlib import Path
import json
import subprocess

import pytest

from environments.website_drafts import component_sampling as components
from environments.website_drafts import variation_sampling as variations
from environments.website_world import generation, requirements, presentation, unified_generation

POLICY = {'split': False, 'policy': 'footer', 'qualification': 'basket', 'collectionPayment': 'online'}


def priors(**options):
    return variations.normalize({'enabled': True, **options}, components.factors('typical', components.load_priors()))


def sample(seed=41, conditions=None, variation_priors=None):
    return components.sample_components(seed, 'shop', profile='typical', policy=POLICY,
        variation_priors=variation_priors or priors(), conditions=conditions)


def test_navigation_grouping_is_conditional_and_weights_propagate():
    modules = components.factors('typical', components.load_priors())
    for choice, expected in [('shopping-services', 1/6), ('departments', 5/6)]:
        tables = variations.completion(modules, {'variation.site.navigationGrouping': [choice]}, priors())
        assert tables['mass'] == pytest.approx(expected)
        if choice == 'shopping-services':
            assert tables['site']['site.navigation'] == {'grouped': 1.}
        else:
            assert tables['site']['site.navigation'] == pytest.approx({'base': .4, 'flat': .4, 'grouped': .2})
    for seed in range(30):
        config = sample(seed, {'variation.site.navigationGrouping': ['shopping-services']})['config']
        assert config['variations']['site']['navigation'] == 'grouped'
        assert config['variations']['site']['navigationGrouping'] == 'shopping-services'


def test_unit_specific_child_weights_reweight_parent_before_draw():
    config = priors(unit_weights={'product': {'technical': {'product.facts': {'base': 0, 'definitions': 0, 'table': 1}}}})
    modules = components.factors('typical', components.load_priors())
    parent = modules['module.product']
    expected = parent['technical'] + (1-parent['technical'])/3
    tables = variations.completion(modules, {'variation.product.facts': ['table']}, config)
    assert tables['mass'] == pytest.approx(expected)
    assert tables['parents']['module.product']['technical'] == pytest.approx(parent['technical']/expected)
    for seed in range(30):
        assert sample(seed, {'variation.product.facts': ['table']}, config)['config']['variations']['product']['facts'] == 'table'
    joint = variations.completion(modules, {'module.product': ['technical'], 'variation.product.facts': ['table']}, config)
    assert joint['mass'] == pytest.approx(parent['technical'])


def test_upstream_mass_and_overlap_use_joint_dependency_once():
    config = generation.compile_request({'schema': generation.VERSION, 'seed': 1,
        'realism': {'page_variations': {'enabled': True, 'unit_weights': {'product': {
            'technical': {'product.facts': {'base': 0, 'definitions': 0, 'table': 1}}}}}},
        'requirements': [
            {'id': 'child', 'target': {'kind': 'all_retailers'}, 'conditions': {'variation.product.facts': ['table']}},
            {'id': 'parent', 'target': {'kind': 'retailer_id', 'retailer_id': 'r'}, 'conditions': {'module.product': ['technical']}}]})
    world = {'retailers': [{'retailer_id': 'r', 'scale': 'medium', 'initial_form': {'provenance': {}}}]}
    value = requirements.evaluate(world, config['requirements'], config['priors'], config['resets'], config['policies'], variation_priors=config['variation_priors'])
    parent = components.factors('typical', config['priors'])['module.product']['technical']
    assert exp(value['log_mass']) == pytest.approx(parent)
    masses = [exp(requirements.site_log_mass(profile, config['priors'], config['resets'], config['policies'],
        {'variation.product.facts': ['table']}, config['variation_priors'])) for profile in ('boutique', 'typical', 'huge')]
    expected = [1/3 + 2/3 * components.factors(profile, config['priors'])['module.product']['technical']
                for profile in ('boutique', 'typical', 'huge')]
    assert masses == pytest.approx(expected)
    assert masses[1] > masses[0]
    conflicting = deepcopy(config['requirements'])
    conflicting[1]['conditions'] = {'variation.product.facts': ['definitions']}
    assert requirements.evaluate(world, conflicting, config['priors'], variation_priors=config['variation_priors'])['log_mass'] == float('-inf')


def test_reset_policy_mass_matches_materialized_plan():
    config = generation.compile_request({'schema': generation.VERSION, 'seed': 1,
        'realism': {'page_variations': {'enabled': True}}, 'requirements': [{
        'id': 'joint', 'target': {'kind': 'retailer_id', 'retailer_id': 'r'}, 'conditions': {
            'site.reset': ['true'], 'site.resetPolicy': ['preserve', 'services'],
            'variation.site.navigationGrouping': ['shopping-services']}}]})
    cond = config['requirements'][0]['conditions']
    mass = requirements.site_log_mass('typical', config['priors'], config['resets'], config['policies'], cond, config['variation_priors'])
    world = {'world_id': 'w', 'seed': 1, 'retailers': [{'retailer_id': 'r', 'scale': 'medium'}]}
    request = {'schema': presentation.VERSION, 'world_id': 'w', 'component_priors': config['priors'],
        'variation_priors': config['variation_priors'], 'sites': {'r': {'conditions': cond}}}
    plan = presentation.site_plan(world, world['retailers'][0], request)
    assert plan['config']['resetPolicy'] == 'services'
    assert plan['presentation']['condition_mass'] == pytest.approx(exp(mass))
    assert exp(mass) == pytest.approx(.05/6)


def test_fixed_gallery_and_disabled_variation_conditions_fail_early():
    for realism in ({}, {'page_variations': {'enabled': False}}, {'page_variations': {'enabled': True}}):
        with pytest.raises(ValueError):
            generation.compile_request({'schema': generation.VERSION, 'seed': 1, 'realism': realism,
                'requirements': [{'id': 'media', 'target': {'kind': 'all_retailers'},
                                  'conditions': {'variation.product.gallery': ['featured']}}]})
    assert sample()['config']['variations']['product']['gallery'] == 'stacked'


@pytest.mark.parametrize('options', [
    {'enabled': 1}, {'enabled': False, 'weights': {}}, {'enabled': True, 'weights': {'missing': {}}},
    {'enabled': True, 'weights': {'product.facts': {'table': 1}}},
    {'enabled': True, 'weights': {'product.facts': {'base': True, 'definitions': 1, 'table': 1}}},
    {'enabled': True, 'weights': {'product.facts': {'base': float('nan'), 'definitions': 1, 'table': 1}}},
    {'enabled': True, 'unit_weights': {'navbar': {}}},
    {'enabled': True, 'unit_weights': {'product': {'technical': {'site.navigation': {'base': 1, 'flat': 1, 'grouped': 1}}}}},
])
def test_invalid_weights_and_ownership_are_rejected(options):
    with pytest.raises(ValueError):
        variations.normalize(options, components.factors('typical', components.load_priors()))


def test_seeded_replay_unrelated_streams_and_browser_registry():
    plans = [sample(seed) for seed in range(35)]
    assert plans[4] == sample(4)
    changed = priors(weights={'home.sectionOrder': {'base': 0, 'showcase-first': 1, 'services-first': 0}})
    other = sample(4, variation_priors=changed)
    assert plans[4]['config']['modules'] == other['config']['modules']
    for role, values in plans[4]['config']['variations'].items():
        if role != 'home': assert values == other['config']['variations'][role]
    for plan in plans:
        fields = plan['config']['variations']
        assert {f'{role}.{key}' for role, values in fields.items() for key in values} == set(variations.AXES)
    program = """import fs from 'node:fs';import {validateConfiguration} from './environments/website_drafts/manifest.js';
    for(const config of JSON.parse(fs.readFileSync(0,'utf8')))validateConfiguration(config);"""
    subprocess.run(['node', '--input-type=module', '-e', program], input=json.dumps([p['config'] for p in plans]), text=True, check=True)


def test_legacy_sample_is_unchanged_without_opt_in():
    # Read the archived implementation from before ordinary variation sampling.
    before = Path('.local/website-variation-sampling-20261006-v1/before/component_sampling.py')
    if not before.exists(): pytest.skip('Local before snapshot unavailable')
    spec = spec_from_file_location('old_component_sampling', before)
    old = module_from_spec(spec); spec.loader.exec_module(old)
    for seed in range(35):
        kwargs = dict(profile='typical', policy=POLICY, priors=components.load_priors())
        assert old.sample_components(seed, 'shop', **kwargs) == components.sample_components(seed, 'shop', **kwargs)


def test_selected_content_is_a_catalog_recipe_flag():
    with pytest.raises(ValueError, match='accepted-catalog'):
        generation.compile_request({'schema': generation.VERSION, 'seed': 1, 'realism': {'selected_content': True}})
    for invalid in (None, 'true', 1):
        with pytest.raises(ValueError):
            unified_generation.compile_request({'schema': unified_generation.VERSION, 'seed': 1, 'realism': {'selected_content': invalid}})
    assert unified_generation.compile_request({'schema': unified_generation.VERSION, 'seed': 1,
        'realism': {'selected_content': True}})['selected_content'] is True


def test_integrated_rejection_retains_module_conditioned_profile_weights():
    def factory(seed, **kwargs):
        scale = ('small', 'medium', 'large')[seed % 3]
        return {'world_id': f'world-{seed}', 'seed': seed, 'products': [], 'quote_as_of': '2026-10-06',
            'reference': {'winners': [{'retailer_id': 'shop'}]},
            'retailers': [{'retailer_id': 'shop', 'scale': scale,
                           'initial_form': {'provenance': {}}, 'offers': []}]}
    base = {'schema': generation.VERSION, 'seed': 1, 'realism': {'page_variations': {
        'enabled': True, 'weights': {'product.facts': {'base': 1, 'definitions': 0, 'table': 0}},
        'unit_weights': {'product': {'technical': {'product.facts': {'base': 0, 'definitions': 0, 'table': 1}}}}}},
        'requirements': [{'id': 'table', 'target': {'kind': 'best_matching_retailers'},
                          'conditions': {'variation.product.facts': ['table']}}]}
    config = generation.compile_request(base)
    # The child can be satisfied only by technical, whose family prior is
    # .2/.65/.2 across these profiles. Upstream proposals must reflect that.
    observed = []
    for seed in range(240):
        result = generation.generate({**base, 'seed': seed}, world_factory=factory)
        observed.append(result['world']['retailers'][0]['scale'])
        selected = result['compositions']['shop']['config']
        assert selected['modules']['product'] == 'technical'
        assert selected['variations']['product']['facts'] == 'table'
    expected = [.2/1.05, .65/1.05, .2/1.05]
    assert [observed.count(scale)/240 for scale in ('small', 'medium', 'large')] == pytest.approx(expected, abs=.075)
    assert exp(requirements.log_upper_bound(config['requirements'])) == pytest.approx(.65/3)
