"""Check sampler probabilities, constraints and the actual browser registry."""
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import subprocess

import pytest

from environments.website_drafts.component_sampling import (
    conditioned_factors, factors, load_priors, sample_components)

POLICY = {'split': True, 'policy': 'footer', 'qualification': 'basket',
          'collectionPayment': 'collection'}


def sample(seed=41, site='retailer-1', **kwargs):
    return sample_components(seed, site, profile='typical', policy=POLICY, **kwargs)


def test_registry_matches_browser_and_configs_validate():
    root = Path(__file__).resolve().parents[2]
    plans = [sample(seed, f'retailer-{seed}')['config'] for seed in range(12)]
    program = """
      import fs from 'node:fs';
      import {typicalUnits,hugeUnits,boutiqueUnits,globals,validateConfiguration}
        from './environments/website_drafts/manifest.js';
      const input=JSON.parse(fs.readFileSync(0,'utf8'));
      for(const conf of input.plans) validateConfiguration(conf);
      const groups={typical:typicalUnits,huge:hugeUnits,boutique:boutiqueUnits};
      const roles=Object.fromEntries(Object.keys(typicalUnits).map(role=>[role,
        Object.fromEntries(Object.entries(groups).filter(([,u])=>u[role])
          .map(([family,u])=>[family,u[role].map(c=>c[0])]))]));
      process.stdout.write(JSON.stringify({roles,globals:Object.keys(globals)}));
    """
    result = subprocess.run(['node', '--input-type=module', '-e', program], cwd=root,
                            input=json.dumps({'plans': plans}), text=True,
                            capture_output=True, check=True)
    registry = json.loads(result.stdout)
    priors = load_priors()
    assert registry['roles'] == priors['roles']
    assert set(registry['globals']) == set(priors['site_choices']['global'])


def test_exact_family_mass_not_number_of_designs():
    priors = load_priors()
    for profile in priors['profiles']:
        distributions = factors(profile, priors)
        for role, families in priors['roles'].items():
            weights = priors['profiles'][profile]['family_weights']
            total = sum(weights[family] for family in families)
            for family, units in families.items():
                assert sum(distributions['module.' + role][u] for u in units) == pytest.approx(weights[family] / total)
        assert sum(distributions['module.checkout'].values()) == pytest.approx(1)


def test_constraint_mass_and_weight_propagation_to_upstream_profile():
    # Condition on a specific boutique PDP and radio-control convention.
    constraints = {'module.product': ['atelier'], 'site.global': ['guided']}
    masses = {}
    for profile in ('boutique', 'typical', 'huge'):
        posterior, mass = conditioned_factors(profile, conditions=constraints)
        family_mass = load_priors()['profiles'][profile]['family_weights']['boutique']
        assert mass == pytest.approx(family_mass / 2 / 3)
        assert posterior['module.product'] == {'atelier': 1}
        assert posterior['site.global'] == {'guided': 1}
        masses[profile] = mass
    # Equal upstream profile priors become 75/20/5 after this restriction.
    assert {k: v / sum(masses.values()) for k, v in masses.items()} == pytest.approx(
        {'boutique': .75, 'typical': .20, 'huge': .05})
    for seed in range(20):
        conf = sample(seed, conditions=constraints)['config']
        assert conf['modules']['product'] == 'atelier'
        assert conf['global'] == 'guided'


def test_permutations_do_not_change_base_or_unrelated_draws():
    first = sample()
    assert first == sample()  # Replay is exact.
    second = sample(site='retailer-2')
    assert first['config']['seed'] != second['config']['seed']
    assert first['unit_permutations'] != second['unit_permutations']
    priors = load_priors()
    changed = deepcopy(priors)
    changed['roles']['home']['typical'].append('future-home')
    third = sample(priors=changed)
    assert {k: v for k, v in first['config'].items() if k not in ('modules','unitPermutations')} == {
        k: v for k, v in third['config'].items() if k not in ('modules','unitPermutations')}
    for role in priors['roles']:
        if role != 'home':
            assert first['config']['modules'][role] == third['config']['modules'][role]
            assert first['unit_permutations'][role] == third['unit_permutations'][role]
    for role, binding in first['unit_permutations'].items():
        assert binding['unit'] == first['config']['modules'][role]
    assert first['config']['qualification'] == POLICY['qualification']


def test_soft_mixing_and_weighted_frequencies():
    counts = Counter()
    mixed = 0
    priors = load_priors()
    family_for = {u: f for f, units in priors['roles']['product'].items() for u in units}
    for seed in range(2000):
        conf = sample(seed)['config']
        counts[family_for[conf['modules']['product']]] += 1
        mixed += conf['modules']['home'] != conf['modules']['product']
    assert mixed > 0
    for family, expected in priors['profiles']['typical']['family_weights'].items():
        assert abs(counts[family] / 2000 - expected) < .035


@pytest.mark.parametrize('conditions', [
    {'module.product': ['missing']}, {'module.missing': ['atelier']},
    {'module.home': []}, {'module.home': ['atelier', 'atelier']},
])
def test_bad_constraints_fail_without_fallback(conditions):
    with pytest.raises(ValueError):
        sample(conditions=conditions)


def test_zero_prior_constraints_and_invalid_weights_fail():
    with pytest.raises(ValueError, match='zero prior mass'):
        conditioned_factors('huge', conditions={'site.search': ['false']})
    for invalid in (-1, float('nan'), float('inf'), True):
        priors = load_priors()
        priors['profiles']['typical']['family_weights']['huge'] = invalid
        with pytest.raises(ValueError):
            sample(priors=priors)


def test_policy_cannot_be_missing_or_resampled():
    for policy in ({}, {**POLICY, 'split': 1}, {**POLICY, 'qualification': 'invented'}):
        with pytest.raises(ValueError):
            sample_components(41, 'retailer-1', profile='typical', policy=policy)
    assert all(sample(seed)['config']['split'] for seed in range(20))
