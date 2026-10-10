from copy import deepcopy
from types import SimpleNamespace

import pytest

from environments.website_world import natural_feature_publication as api
from environments.website_world.test_natural_feature_generation import request


@pytest.mark.parametrize('options', [None, [], {'unknown': 0.3},
    {'autofill_probability': True}, {'incorrect_probability': 1.1},
    {'missing_probability': float('nan')}])
def test_invalid_prior_rejects_before_producer(options, monkeypatch):
    def forbidden(*a, **kw):
        raise AssertionError('Producer must not run')
    monkeypatch.setattr(api.native, 'generate', forbidden)
    with pytest.raises(ValueError):
        api.generate(request(options))


def test_native_forms_and_metadata_are_retained_without_repair(monkeypatch):
    r = request({'autofill_probability': 0.8,
                 'incorrect_probability': 0.5, 'missing_probability': 0.4})
    config = api.compile_request(r)
    result = {'world': {'retailers': [{'initial_form': {'street': '',
        'provenance': {'autofill': True, 'incorrect_values': True,
                       'missing_fields': True, 'authoring_override': None}}}]},
        'presentation': {'sites': {'shop': {'initial_form': 'producer'}}},
        'compositions': {'shop': {'config': {'resetPolicy': 'preserve'}}},
        'audit': {'natural_address': {'parameters': config['address_options'], 'world_repaired': False}},
        'feature_offer_reference': {'status': 'no_match', 'winners': []},
        'episode': {'original': True}}
    before = deepcopy(result)
    calls = []
    def native(req, *, world_factory=None):
        calls.append((req, world_factory))
        assert compile_request(req)['address_options'] == config['address_options']
        return deepcopy(before)
    monkeypatch.setattr(api.native, 'generate', native)
    sentinel = object()
    published = api.generate(r, world_factory=sentinel)
    assert calls == [(r, sentinel)]
    assert {k: v for k, v in published.items() if k != 'feature_field_inventory'} == before


def test_freezer_factory_forwards_seed_and_preserves_declared_priors(monkeypatch):
    calls = []
    class Engine:
        def __init__(self, *, address_options, validation):
            self.parameters = api.native.parameters(address_options)
            calls.append(('init', deepcopy(address_options), validation))
            self.execution = SimpleNamespace(freeze=lambda *a: ('frozen', a))
        def generate(self, seed, **kw):
            calls.append(('generate', seed, kw))
            return {'address_context': {'parameters': deepcopy(self.parameters)}}
        def record(self):
            return {'priors': deepcopy(self.parameters)}
    monkeypatch.setattr(api, 'NaturalAddressExecution', Engine)
    options = {'autofill_probability': 0.8, 'incorrect_probability': 0.5, 'missing_probability': 0.4}
    execution = api._publication_execution(address_options=options, validation='off')
    w = execution.generate(89, address_options=options, concept_ids=['footwear.walking_shoes'])
    assert w['address_context']['parameters'] == options
    assert calls[-1] == ('generate', 89, {'concept_ids': ['footwear.walking_shoes']})
    assert execution.freeze('original') == ('frozen', ('original',))
    assert execution.record()['priors'] == options
    with pytest.raises(ValueError):
        execution.generate(89, address_options={**options, 'missing_probability': 0})
    assert len(calls) == 2


def test_absent_controls_keep_the_existing_default_sampler(monkeypatch):
    calls = []
    class Engine:
        def __init__(self, *, address_options, validation):
            calls.append(address_options)
            self.execution = SimpleNamespace(freeze=lambda *a: None)
        def generate(self, seed, **kw):
            return {'seed': seed, 'options': kw}
        def record(self):
            return {}
    monkeypatch.setattr(api, 'NaturalAddressExecution', Engine)
    config = api.compile_request(request(explicit=False))
    execution = api._publication_execution(address_options=config['address_options'], validation='off')
    assert execution.generate(89) == {'seed': 89, 'options': {}}
    assert calls == [None]
