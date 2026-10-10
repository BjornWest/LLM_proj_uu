"""Native coverage, source scope, real public routing and exposure checks."""
from copy import deepcopy
import json
from pathlib import Path
from urllib.request import urlopen
from urllib.error import HTTPError

import pytest

from environments.website_world import ecosystem
from environments.website_world.adapter import ROOT
from environments.website_world.runtime import Runtime


PIN = ROOT/'.local/website-e2e-address-adoption-v1/producer-example/pin'


@pytest.fixture(scope='module')
def world():
    return json.loads((PIN/'world.json').read_text())


def test_membership_ignores_task_rank_stock_reviews_and_layout(world):
    first = ecosystem.generate(world)
    changed = deepcopy(world)
    changed['task'] = {'unrelated': True}
    changed['reference'] = {'winners': []}
    for r in changed['retailers']:
        for offer in r['offers']:
            offer['stock_by_source'] = {sid: 0 for sid in offer['stock_by_source']}
    for p in changed['products']:
        p['reviews'] = []
    second = ecosystem.generate(changed, {'comparison_layout_weights': {'directory': 0, 'ledger': 1}})
    for a, b in zip(first['sites'], second['sites']):
        assert a['product_ids'] == b['product_ids']
        assert a.get('listings') == b.get('listings')
    assert ecosystem.digest(world) == first['source_world_sha256']


def test_snapshot_minimum_does_not_filter_size_stock_or_delivery(world):
    changed = deepcopy(world)
    r = next(r for r in changed['retailers'] if r['offers'])
    offer = r['offers'][0]
    offer['price_minor'] = 123
    offer['stock_by_source'] = {key: 0 for key in offer['stock_by_source']}
    sidecar = ecosystem.generate(changed, {'model_probability': 1, 'retailer_pair_probability': 1})
    rows = [row for row in sidecar['sites'][0]['listings'] if row['product_id'] == offer['product_id']
            and row['retailer_id'] == r['retailer_id']]
    assert rows[0]['price_minor'] == 123
    assert rows[0]['price_basis'] == ecosystem.PRICE_BASIS
    assert rows[0]['entry_offer_id'] == offer['offer_id']


def test_empty_membership_and_empty_offer_feeds_are_not_repaired(world):
    empty = ecosystem.generate(world, {'model_probability': 0})
    assert all(not s['product_ids'] and not s['listings'] for s in empty['sites'] if s['kind'] == 'aggregator')
    no_feed = ecosystem.generate(world, {'model_probability': 1, 'retailer_pair_probability': 0})
    assert all(len(s['product_ids']) == len(world['products']) and not s['listings']
               for s in no_feed['sites'] if s['kind'] == 'aggregator')
    assert empty['sites'][-1]['product_ids']  # Review coverage is independent.


def test_sidecar_binding_and_replay_reject_changes(world):
    sidecar = ecosystem.generate(world)
    ecosystem.validate(world, sidecar)
    other = deepcopy(world); other['world_id'] = 'other'
    with pytest.raises(ValueError, match='another world'):
        ecosystem.validate(other, sidecar)
    altered = deepcopy(sidecar); altered['sites'][0]['product_ids'].pop()
    with pytest.raises(ValueError, match='replay'):
        ecosystem.validate(world, altered)


def test_review_export_preserves_silent_ratings_subjects_and_deduplication(world):
    changed = deepcopy(world)
    changed['products'][0]['reviews'].append(deepcopy(changed['products'][0]['reviews'][0]))
    public = ecosystem.public_products(changed)
    for p in world['products']:
        pid = p['public']['product_id']
        result = public[pid]
        assert len(result['reviews']) == len(p['reviews'])
        assert result['rating_summary'] == p['rating_summary']
        assert sum(bool(r['text']) for r in result['reviews']) == p['rating_summary']['written_review_count']
        assert all(set(r) == {'review_id', 'reviewer', 'product_id', 'sku_id', 'rating', 'text'} for r in result['reviews'])
        assert all(r['sku_id'] in {s['sku_id'] for s in result['skus']} for r in result['reviews'])
        assert result['guidance']['authority'] == 'synthetic_editorial_guidance_not_review_vote_counts'
    text = json.dumps(public)
    assert 'overall_experience' not in text and 'expected_rating' not in text


@pytest.mark.parametrize('controls', [{'model_probability': True}, {'retailer_pair_probability': -1},
    {'comparison_count': 9}, {'review_count': -1}, {'enabled': 'yes'},
    {'comparison_layout_weights': {'directory': 1}}, {'coverage_seed': -1}])
def test_invalid_controls(controls):
    with pytest.raises(ValueError):
        ecosystem.options(controls)


def test_real_hosts_apply_membership_on_all_routes_and_index(world):
    sidecar = ecosystem.generate(world, {'model_probability': 0, 'comparison_count': 1})
    before = deepcopy(world['reference'])
    with Runtime(PIN, surrounding=sidecar) as runtime:
        assert runtime.world['reference'] == before
        assert 'product-reviews-00' in runtime.surrounding_origins
        assert all('merchant' not in s['kind'] for s in runtime.site_registry)
        pid = world['products'][0]['public']['product_id']
        with urlopen(runtime.index_origin + '/') as response:
            home = response.read().decode()
        assert 'Shopping directory' in home and 'Search products and pages' in home
        assert all(site['name'] in home and site['origin'] in home for site in runtime.site_registry)
        db = runtime.discovery.catalog
        assert db.search(q=world['products'][0]['public']['name'], kind='product_reviews')
        assert not db.search(q=world['products'][0]['public']['name'], kind='aggregator')
        assert not runtime.bindings['surrounding']['comparison_products'][pid]
        from environments.website_world.surrounding_pages import path
        comparator = runtime.surrounding_origins['comparison-00']
        with pytest.raises(HTTPError) as response:
            urlopen(comparator + path('models', pid))
        assert response.value.code == 404
        with pytest.raises(HTTPError) as response:
            urlopen(runtime.index_origin + '/search?page=-1')
        assert response.value.code == 400
        for sid, catalog in runtime.public_catalogs.items():
            for p in catalog['products']:
                assert p['reviewCorpus']['rating_summary'] == next(x for x in world['products']
                    if x['public']['product_id'] == p['canonicalProductId'])['rating_summary']
            with urlopen(runtime.origins[sid] + '/shop.js') as response:
                body = response.read().decode()
            assert 'customerReviews' in body
            assert all(origin not in body for origin in runtime.surrounding_origins.values())
        with pytest.raises(HTTPError) as response:
            urlopen(runtime.index_origin + '/surrounding.private.json')
        assert response.value.code == 404


def test_default_runtime_retains_legacy_directory_and_assets(world):
    with Runtime(PIN) as runtime:
        assert not runtime.surrounding_origins
        assert 'Shopping directory' in runtime.index_page('/', {})[1]
        with urlopen(next(iter(runtime.origins.values())) + '/shop.js') as response:
            assert 'customerReviews' not in response.read().decode()
