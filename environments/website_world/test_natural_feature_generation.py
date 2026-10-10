"""Finite external-input and stage-binding controls, no genuine world sampling."""
from copy import deepcopy

import pytest

from experiments.accepted_catalog_commerce import natural_address as sampler
from experiments.accepted_catalog_commerce.execution import _bind
from experiments.address_checkout_pilot import model as addresses
from environments.website_world import natural_feature_generation as api
from environments.website_world.adapter import digest


def request(options=None, *, explicit=True):
    result = {'schema': 'website-world-generation-v2', 'seed': 88,
        'world': {'concept_ids': ['footwear.walking_shoes']},
        'task': {'kind': 'cheapest_matching_available',
                 'concept_id': 'footwear.walking_shoes',
                 'predicates': [{'field': 'sku.size_eu', 'operator': 'eq', 'value': 42}]}}
    if explicit:
        result['difficulty'] = {'address_probabilities': options}
    return result


@pytest.mark.parametrize('options', [None, [], {'unknown': 0.5},
    {'autofill_probability': True}, {'autofill_probability': float('nan')},
    {'incorrect_probability': 1.01}, {'missing_probability': -0.01}])
def test_malformed_prior_rejects_before_world_factory(options):
    calls = []
    with pytest.raises(ValueError):
        api.generate(request(options), world_factory=lambda *a, **k: calls.append(k))
    assert not calls


def test_compiler_removes_only_probability_field_without_mutating_request():
    original = request({'autofill_probability': 0.9})
    original['difficulty']['reset_weights'] = {
        'preserve': 0.9, 'services': 0.05, 'delivery': 0.03, 'checkout': 0.02}
    before = deepcopy(original)
    config = api.compile_request(original)
    assert original == before
    assert config['address_options'] == {
        'autofill_probability': 0.9, 'incorrect_probability': 0.2,
        'missing_probability': 0.25}
    assert config['proxy_request']['difficulty'] == {
        'reset_weights': original['difficulty']['reset_weights']}


def fake_generate(request, *, world_factory=None):
    world = world_factory(request['seed'], concept_ids=['footwear.walking_shoes'])
    return {'world': world, 'feature_offer_request': deepcopy(request),
        'resolved_configuration': {'request': deepcopy(request)},
        'audit': {'request_sha256': digest(request)}}


def test_external_factory_must_apply_the_declared_priors(monkeypatch):
    monkeypatch.setattr(api.conditioned_feature_generation, 'generate', fake_generate)
    calls = []
    def ignored(seed, **options):
        calls.append(options)
        return {'address_context': {'parameters': deepcopy(addresses.CONFIG)}}
    with pytest.raises(ValueError, match='ignored declared natural address'):
        api.generate(request({'autofill_probability': 0.9}), world_factory=ignored)
    assert calls[0]['address_options']['autofill_probability'] == 0.9


def test_factory_parameters_and_original_request_binding_are_retained(monkeypatch):
    monkeypatch.setattr(api.conditioned_feature_generation, 'generate', fake_generate)
    original = request({'autofill_probability': 0.9})
    calls = []
    world = {'address_context': {'parameters': addresses.parameters(
        original['difficulty']['address_probabilities'])}}
    def factory(seed, **options):
        calls.append(options)
        return world
    result = api.generate(original, world_factory=factory)
    assert result['world'] is world
    assert calls[0]['address_options'] == world['address_context']['parameters']
    assert result['feature_offer_request'] == original
    assert result['resolved_configuration']['request'] == original
    assert result['resolved_configuration']['address_options'] == calls[0]['address_options']
    assert result['audit']['request_sha256'] == digest(original)
    assert result['audit']['natural_address']['world_repaired'] is False


def test_boolean_factory_metadata_cannot_impersonate_probability_one(monkeypatch):
    monkeypatch.setattr(api.conditioned_feature_generation, 'generate', fake_generate)
    def factory(seed, **options):
        return {'address_context': {'parameters': {
            'autofill_probability': True, 'incorrect_probability': 0.2,
            'missing_probability': 0.25}}}
    with pytest.raises(ValueError):
        api.generate(request({'autofill_probability': 1}), world_factory=factory)


def test_absent_priors_pass_the_existing_factory_unchanged(monkeypatch):
    monkeypatch.setattr(api.conditioned_feature_generation, 'generate', fake_generate)
    calls = []
    original = request(explicit=False)
    def factory(seed, **options):
        calls.append(options)
        return {'authored_saved_world': True}
    result = api.generate(original, world_factory=factory)
    assert 'address_options' not in calls[0]
    assert result['audit']['natural_address']['explicit'] is False
    assert result['feature_offer_request'] == original


def retained_body(seed, city_id='uppsala', **options):
    return addresses.generate(seed, city_id)


class FakeExecution:
    """Isolate the actual dependency binding without invoking manufacture."""
    def __init__(self, *, validation):
        self._generate = _bind(retained_body)
        self.validation = validation

    def generate(self, seed=0, **options):
        return self._generate(seed, **options)

    def record(self):
        return {'validation': self.validation}


def test_prior_is_bound_at_original_stage_without_module_mutation(monkeypatch):
    calls = []
    def context(seed=0, city_id='uppsala', options=None):
        calls.append({'seed': seed, 'city_id': city_id, 'options': deepcopy(options)})
        return {'parameters': addresses.parameters(options)}
    monkeypatch.setattr(addresses, 'generate', context)
    monkeypatch.setattr(sampler, 'Execution', FakeExecution)
    options = {'autofill_probability': 0.9}
    engine = sampler.NaturalAddressExecution(address_options=options)
    options['autofill_probability'] = 0
    exposed = engine.parameters
    exposed['autofill_probability'] = 0
    assert engine.execution._generate.__code__ is retained_body.__code__
    assert addresses.generate is context
    assert engine.generate(88)['parameters']['autofill_probability'] == 0.9
    assert calls == [{'seed': 88, 'city_id': 'uppsala',
                      'options': {'autofill_probability': 0.9,
                                  'incorrect_probability': 0.2, 'missing_probability': 0.25}}]
    assert addresses.generate is context
    assert engine.record()['natural_address']['shipping_coverage_repaired'] is False


def test_sampler_without_options_retains_the_original_execution_binding(monkeypatch):
    monkeypatch.setattr(sampler, 'Execution', FakeExecution)
    engine = sampler.NaturalAddressExecution()
    assert engine.execution._generate.__globals__['addresses'] is addresses
    assert engine.record()['natural_address']['explicit'] is False
