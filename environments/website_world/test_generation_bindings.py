"""Generation-local hash reuse preserves public replay and mutation checks."""
from copy import deepcopy
import json

import pytest

from environments.website_world import catalog_checkout_domain as checkout, ecosystem, rich_ecosystem
from environments.website_world import surrounding_config, unified_generation, presentation
from environments.website_world.adapter import ROOT


@pytest.fixture(scope='module')
def world():
    return json.loads((ROOT / '.local/accepted-catalog-commerce-pin-v2/world.private.json').read_text())


@pytest.mark.parametrize('version', [ecosystem.VERSION, rich_ecosystem.VERSION])
def test_surrounding_bound_construction_replays_exactly(world, version):
    before = deepcopy(world)
    controls = surrounding_config.options({'version': version})
    saved = deepcopy(controls)
    expected = surrounding_config.generate(world, controls)
    actual = surrounding_config._generate_bound(world, controls, ecosystem.digest(world))
    assert actual == expected
    assert world == before and controls == saved
    surrounding_config.validate(world, actual)
    changed = deepcopy(world)
    changed['retailers'][0]['offers'][0]['price_minor'] += 1
    with pytest.raises(ValueError, match='another world'):
        surrounding_config.validate(changed, actual)


def test_checkout_retains_monetary_checks_and_independent_validation(world):
    before = deepcopy(world)
    actual = checkout.make(world, {'max_quantity_per_offer': 7})
    assert world == before
    changed = deepcopy(world)
    changed['retailers'][0]['offers'][0]['price_minor'] += 1
    with pytest.raises(ValueError, match='binding or limits changed'):
        checkout.validate(changed, actual)
    with pytest.raises(ValueError, match='quantity'):
        checkout.make(world, {'max_quantity_per_offer': 0})
    broken = deepcopy(world)
    broken['schema_version'] = 'invalid'
    with pytest.raises(ValueError):
        checkout.make(broken)


@pytest.mark.parametrize('conditions', [{}, {'site.url': ['none'], 'site.resetPolicy': ['services']}])
def test_unified_generation_reuses_only_its_local_checkout_binding(world, monkeypatch, conditions):
    config = {'schema': unified_generation.VERSION, 'seed': 1,
              'requirements': [] if not conditions else [{
                  'id': 'one', 'target': {'kind': 'retailer_id', 'retailer_id': world['retailers'][0]['retailer_id']}, 'conditions': conditions}],
              'budget': {'max_proposals': 200}}
    request_before = deepcopy(config)
    def forbidden(*args, **kwargs):
        pytest.fail('Generation redundantly serialized its bound world')
    hashes = []
    def checkout_hash(value):
        hashes.append(value)
        return original_digest(value)
    monkeypatch.setattr(checkout, 'digest', checkout_hash)
    monkeypatch.setattr(ecosystem, 'digest', lambda value: forbidden() if value is world else original_digest(value))
    result = unified_generation.generate(config, world_factory=lambda *args, **kwargs: world)
    assert len(hashes) == 1 and hashes[0] is world
    assert result['checkout_domain']['world_sha256'] == result['surrounding']['source_world_sha256']
    # Shipping deliberately retains its different compact-JSON hash format.
    assert result['basket_plan']['world_sha256'] != result['checkout_domain']['world_sha256']
    assert config == request_before
    if conditions:
        plan = result['compositions'][world['retailers'][0]['retailer_id']]
        assert plan['config']['url'] == 'none' and plan['config']['resetPolicy'] == 'services'


original_digest = ecosystem.digest


def test_supplied_component_priors_do_not_read_defaults(world, monkeypatch):
    from environments.website_drafts.component_sampling import load_priors
    priors = load_priors()
    before = deepcopy(priors)
    monkeypatch.setattr(presentation, 'load_priors', lambda: pytest.fail('Unnecessary default priors read'))
    presentation.site_plan(world, world['retailers'][0], {'component_priors': priors})
    assert priors == before
