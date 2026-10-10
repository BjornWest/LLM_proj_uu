"""Use saved worlds for integration parity; no authoring-cohort regeneration."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from . import model, package_export
from .execution import Execution
from environments.website_world.execution_generation import generate
from experiments.world_sampling_defaults.execution import PopulationExecution
from experiments.world_sampling_defaults import model as population_model
from environments.product_world.shared_state import freeze
from environments.product_world import retailer_naming
from .catalog_registry import naming_profile
from .execution import _bind

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / '.local/tshirt-website-integration-20261005-v1'


def canonical(value):
    return json.loads(json.dumps(value))


def test_no_process_global_rebinding():
    globals_before = dict(model.generate.__globals__)
    export_before = dict(package_export.sample.__globals__)
    a, b = Execution(), Execution(validation='full')
    assert a._generate.__globals__ is not b._generate.__globals__
    assert model.generate.__globals__ == globals_before
    assert package_export.sample.__globals__ == export_before


def test_source_gate_is_cached_and_does_not_expose_mutable_cache(monkeypatch):
    calls = []
    monkeypatch.setattr(package_export, 'source_gate', lambda cid: calls.append(cid) or {'sources': {'x': 'hash'}})
    e = Execution()
    first = e.source_gate('example')
    first['sources']['x'] = 'changed'
    assert e.source_gate('example')['sources']['x'] == 'hash'
    assert calls == ['example']


@pytest.mark.parametrize('seed', [1, 2])
def test_fresh_off_mode_matches_complete_frozen_tshirt_world(seed):
    if not BASELINE.exists():
        pytest.skip('Local frozen T-shirt evidence is absent')
    request = json.loads((BASELINE / ('request.json' if seed == 1 else 'request-seed2.json')).read_text())
    folder = 'generated' if seed == 1 else 'generated-seed2'
    expected = json.loads((BASELINE / folder / 'pin/world.private.json').read_text())
    # This historical fixture predates the separately accepted realistic-name
    # recipe. Update only its display naming expectation, preserving every
    # historical product/offer/stock/review value and the archived fixture bytes.
    names = retailer_naming.allocate(seed, [{
        'retailer_id': r['retailer_id'], 'profile': naming_profile(r['template_id']),
        'country': r['geography']['headquarters']['country'],
        'city_id': r['geography']['headquarters']['city_id']}
        for r in expected['retailers']])
    for r in expected['retailers']:
        r['name'] = names[r['retailer_id']]
    expected['provenance']['retailer_naming_version'] = retailer_naming.VERSION
    expected.pop('world_id')
    expected['world_id'] = model.native.digest(expected)
    result = generate(request)
    assert canonical(result['world']) == expected
    assert model.validate(result['world'])['valid']
    assert result['execution']['validation'] == 'off'


@pytest.mark.parametrize('mode', ['off', 'full'])
def test_world_input_validation_remains(mode):
    e = Execution(validation=mode)
    with pytest.raises(ValueError):
        e.generate(True)
    with pytest.raises(ValueError):
        e.generate(1, concept_ids=['foreign'], tasks=[])


def test_mode_is_explicit_and_invalid_values_rejected():
    with pytest.raises(ValueError):
        Execution(validation=True)


def test_population_config_and_registry_are_loaded_and_resolved_once(monkeypatch):
    calls = []
    registry = type('Registry', (), {'concepts': lambda self: calls.append('concepts') or [{'id': 'x'}]})()
    monkeypatch.setattr(population_model, 'load', lambda: calls.append('load') or ({'schema_version': 'test'}, registry))
    owner = PopulationExecution(_bind)
    config, snapshot = owner.load()
    assert owner.load()[0] is config
    assert snapshot.concepts() is snapshot.concepts()
    assert calls == ['load', 'concepts']
    with pytest.raises(TypeError):
        config['schema_version'] = 'changed'
    with pytest.raises(TypeError):
        snapshot.concepts()[0]['id'] = 'changed'


def test_tshirt_compilation_reused_but_identity_and_stage_configuration_are_local():
    if not BASELINE.exists():
        pytest.skip('Local frozen T-shirt evidence is absent')
    world = json.loads((BASELINE / 'generated/pin/world.private.json').read_text())
    source = world['products'][0]['private']['sample']['entities']
    owner = Execution()
    def inputs(pid, women):
        brand = deepcopy(source['brand'])
        brand['market_range_weights'] = {'women': int(women), 'men': int(not women), 'unisex': 0}
        return {'brand': brand, 'product': {'product_id': pid, 'concept_id': 'tops.t_shirts'}}
    a = owner._package('tops.t_shirts', inputs('a', True))
    b = owner._package('tops.t_shirts', inputs('b', True))
    c = owner._package('tops.t_shirts', inputs('c', False))
    assert a.document is b.document and a.fields is b.fields
    assert a.document is not c.document
    for package, pid, women in ((a, 'a', True), (b, 'b', True), (c, 'c', False)):
        result = package._sample_trusted(1, inputs=inputs(pid, women))
        assert result['entities']['private']['market_stage']['product_id'] == pid
        assert result['entities']['product']['facts']['market_range'] == ('women' if women else 'men')
    assert len(owner.packages) == 2


def test_review_and_description_consumers_share_completed_manufacture(monkeypatch):
    if not BASELINE.exists():
        pytest.skip('Local frozen T-shirt evidence is absent')
    from environments.product_world.execution import TraversalPackage
    seen = []
    original = TraversalPackage._sample_trusted
    def sample(self, seed, *, inputs=None, overrides=None):
        result = original(self, seed, inputs=inputs, overrides=overrides)
        if 'review' in result['entities'] and inputs is not None and 'product' in inputs:
            seen.append((result['entities']['product']['skus'], inputs['product']['skus']))
        return result
    monkeypatch.setattr(TraversalPackage, '_sample_trusted', sample)
    request = json.loads((BASELINE / 'request.json').read_text())
    generate(request)
    assert seen and all(output is source for output, source in seen)
