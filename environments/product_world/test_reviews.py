import copy
from datetime import date
import pytest

from .generator import digest
from .reviews import generate_reviews, statistics
from .stores import generate_store_world


@pytest.fixture(scope='module')
def world(): return generate_store_world(seed=42)


def test_deterministic_complete_corpus_and_public_boundary(world):
    result = generate_reviews(world)
    assert result == generate_reviews(world)
    assert set(result['public']) == {'as_of', 'companies'}
    assert len(result['public']['companies']) == len(world['public']['retailers'])
    for company, store in zip(result['public']['companies'], world['public']['retailers']):
        assert company['company_id'] == store['retailer_id']
        assert company['website_url'] == store['site_url']
        reviews = company['reviews']
        assert len(reviews) == 24
        assert len({r['review_id'] for r in reviews}) == 24
        assert company['statistics'] == statistics(reviews)
        for r in reviews:
            assert 1 <= r['stars'] <= 5
            assert r['experience_date'] <= r['published_date'] <= result['public']['as_of']
            date.fromisoformat(r['experience_date'])
            if r['company_reply']:
                assert r['published_date'] <= r['company_reply']['published_date'] <= result['public']['as_of']
        assert 'config' not in company and 'quality' not in company


def test_prefix_and_store_order_independence(world):
    a = generate_reviews(world, reviews_per_store=2)['public']['companies']
    larger = generate_reviews(world, reviews_per_store=10)['public']['companies']
    changed = copy.deepcopy(world)
    changed['public']['retailers'].reverse()
    changed['world_sha256'] = digest(changed['public'])
    reordered = {c['company_id']: c for c in generate_reviews(changed, reviews_per_store=2)['public']['companies']}
    for small, big in zip(a, larger):
        assert small['reviews'] == big['reviews'][:2]
        assert reordered[small['company_id']] == small


def test_empty_corpus_is_null_not_zero(world):
    for company in generate_reviews(world, reviews_per_store=0)['public']['companies']:
        assert company['statistics'] == {'review_count': 0, 'star_counts': {str(n): 0 for n in range(1,6)}, 'mean_stars': None}


def test_company_priors_and_reply_extremes(world):
    result = generate_reviews(world, config={'star_weights': {'1': 0, '2': 0, '3': 0, '4': 0, '5': 1},
        'company_star_weights': {'store-001': {'1': 1, '5': 0}}, 'reply_probability': 1})
    for c in result['public']['companies']:
        assert c['statistics']['mean_stars'] == (1 if c['company_id'] == 'store-001' else 5)
        assert all(r['company_reply'] is not None for r in c['reviews'])
    assert all(r['company_reply'] is None for c in generate_reviews(world, config={'reply_probability': 0})['public']['companies'] for r in c['reviews'])


@pytest.mark.parametrize('options', [{'reviews_per_store': 201}, {'reviews_per_store': True}, {'as_of': 'tomorrow'},
    {'config': {'star_weights': {str(i): 0 for i in range(1,6)}}}, {'config': {'company_star_weights': {'unknown': {}}}},
    {'config': {'reply_probability': 1.1}}])
def test_invalid_configuration(world, options):
    with pytest.raises(ValueError): generate_reviews(world, **options)
