from copy import deepcopy

import pytest

from environments.website_world import conditioned_feature_publication as api
from environments.website_world.test_feature_offer_generation import request


@pytest.mark.parametrize('change', [
    lambda r: r.update(requirements='bad'),
    lambda r: r.update(requirements=[{'id': 'bad', 'target': {'kind': 'invented'}}]),
    lambda r: r['task']['predicates'][0].update(field='product.facts.model_price_factor'),
    lambda r: r['task']['predicates'][0].update(value=True),
])
def test_invalid_declarations_fail_before_producer(change, monkeypatch):
    r = request()
    change(r)
    def forbidden(*a, **kw):
        raise AssertionError('Generation must not start')
    monkeypatch.setattr(api.native, 'generate', forbidden)
    with pytest.raises(ValueError):
        api.generate(r)


@pytest.mark.parametrize('status', ['match', 'no_match'])
def test_producer_records_preserved_without_second_sampling(status, monkeypatch):
    r = request()
    r['requirements'] = []
    config = api.compile_request(r)
    result = {'world': {'world_id': 'unmodified'},
        'presentation': {'sites': {'tied-a': {'conditions': {'site.resetPolicy': ['checkout']}},
                                   'tied-b': {'conditions': {'site.resetPolicy': ['checkout']}}}},
        'compositions': {'tied-a': {'resetPolicy': 'checkout'}, 'tied-b': {'resetPolicy': 'checkout'}},
        'audit': {'task_conditioning': {'selectors': [], 'world_reference_added_to_world': False}},
        'feature_offer_task': {'predicates': r['task']['predicates']},
        'feature_offer_reference': {'status': status, 'winners': ['a', 'b'] if status == 'match' else []},
        'episode': {'manual_task': {'user_message': 'original'}},
        'surrounding': {'sites': ['unsold-model', 'review']}}
    original = deepcopy(result)
    calls = []
    def producer(req, *, world_factory=None):
        calls.append((req, world_factory))
        assert compile_request(req)['inventory'].concept_id == config['inventory'].concept_id
        return deepcopy(original)
    monkeypatch.setattr(api.native, 'generate', producer)
    sentinel = object()
    published = api.generate(r, world_factory=sentinel)
    assert calls == [(r, sentinel)]
    assert {k: v for k, v in published.items() if k != 'feature_field_inventory'} == original
    assert published['feature_field_inventory']['source_hashes'] == config['inventory'].source_hashes
    assert r['requirements'] == []
