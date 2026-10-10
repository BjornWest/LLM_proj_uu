from copy import deepcopy

import pytest

from environments.website_world import quote_offer_publication as publication
from environments.website_world.test_quote_offer_generation import request
from environments.website_world.test_quote_offer_task import fixture


def test_invalid_features_fail_before_any_world_draw(monkeypatch):
    r = request()
    r['task']['predicates'][0]['field'] = 'product.facts.model_price_factor'
    def forbidden(*args, **kwargs): raise AssertionError('World draw forbidden')
    monkeypatch.setattr(publication.native.unified_generation, 'generate', forbidden)
    with pytest.raises(ValueError): publication.generate(r)


def test_comparison_home_requires_identical_enabled_scope():
    r = request()
    r['episode'] = {'start': {'kind': 'comparison_home', 'comparison_site_id': 'comparison-00'}}
    with pytest.raises(ValueError, match='task scope'): publication.compile_request(r)
    r['task']['comparison_site_id'] = 'comparison-00'
    config = publication.compile_request(r)
    assert config['requested_start'] == r['episode']['start']
    assert config['proxy_request']['episode']['start'] == {'kind': 'directory'}
    r['surrounding_sites'] = {'enabled': False}
    with pytest.raises(ValueError): publication.compile_request(r)


def test_no_match_is_saved_without_repair_or_redraw(monkeypatch):
    world, _, _, _, _, _ = fixture()
    before = deepcopy(world)
    calls = []
    def generated(proxy, *, world_factory):
        calls.append(proxy)
        return {'world': world, 'surrounding': None, 'resolved_configuration': {},
                'audit': {'request_sha256': 'proxy'}, 'episode': {}, 'basket_plan': {}, 'delivery_plan': {'admitted': True}}
    monkeypatch.setattr(publication.native.unified_generation, 'generate', generated)
    from environments.website_world.test_quote_offer_task import Quotes
    def prepare(world, *, plan, admission_plan):
        assert admission_plan == {'admitted': True}
        return Quotes(world, admitted='express-only')
    monkeypatch.setattr(publication.native, 'prepare', prepare)
    r = request()
    r['task']['predicates'][0]['value'] = 99
    result = publication.generate(r)
    assert world == before and len(calls) == 1
    assert result['quote_offer_reference']['status'] == 'no_match'
    assert result['quote_offer_task']['predicates'] == r['task']['predicates']
    assert result['quote_field_inventory']['source_hashes'] == result['quote_offer_task']['field_source_sha256']
    assert result['resolved_configuration']['quote_offer_selection']['predicates'] == r['task']['predicates']


def test_required_disclosure_is_not_inferred_from_native_match(monkeypatch):
    world, _, _, _, _, _ = fixture()
    def generated(proxy, *, world_factory):
        return {'world': world, 'surrounding': None, 'resolved_configuration': {},
                'audit': {'request_sha256': 'proxy'}, 'episode': {}, 'basket_plan': {}, 'delivery_plan': {'admitted': True}}
    monkeypatch.setattr(publication.native.unified_generation, 'generate', generated)
    from environments.website_world.test_quote_offer_task import Quotes
    def prepare(world, *, plan, admission_plan):
        assert admission_plan == {'admitted': True}
        return Quotes(world, admitted='express-only')
    monkeypatch.setattr(publication.native, 'prepare', prepare)
    result = publication.generate(request())
    assert result['quote_offer_reference']['status'] == 'match'
    assert result['quote_offer_reference']['evidence_coverage'] == 'native_truth_does_not_establish_public_disclosure_or_visits'
