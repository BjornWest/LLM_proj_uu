import copy
from concurrent.futures import ThreadPoolExecutor

import pytest
from environments.procedural_commerce.product_controls import resolve
from .config import FAMILY_IDS, defaults, domains, token
from .generator import generate_catalog, summarize
from .validation import validate_catalog
from .tasks import generate_task


def only(family):
    return {'family_weights': {f: int(f == family) for f in FAMILY_IDS}}


def pin(field, value):
    return {token(v): int(v == value) for v in domains()[field]}


def test_determinism_prefix_and_existing_group_contract():
    a = generate_catalog(17, 8)
    assert a == generate_catalog(17, 8)
    b = generate_catalog(17, 12)
    assert b['public']['products'][:len(a['public']['products'])] == a['public']['products']
    assert b['public']['product_groups'][:8] == a['public']['product_groups']
    for g in a['public']['product_groups']:
        for v in g['variants']:
            assert resolve(g, v['product_id'], v['selection'])['product_id'] == v['product_id']
    assert set(a['public']) == {'products', 'product_groups'}


def test_weights_zero_extremes_and_axis_breadth():
    config = only('footwear')
    config['field_weights'] = {'footwear.colour': pin('footwear.colour', 'blue'),
                              'footwear.waterproof': pin('footwear.waterproof', False)}
    config['variant_omission_probability'] = 0
    b = generate_catalog(2, 10, config)
    assert set(summarize(b)['models_by_family']) == {'footwear'}
    assert all(p['attributes']['colour'] == 'blue' and p['attributes']['waterproof'] is False for p in b['public']['products'])
    assert all(len(g['variants']) == 6 for g in b['public']['product_groups'])
    config['variant_omission_probability'] = 1
    c = generate_catalog(2, 10, config)
    assert len(c['public']['products']) == 10
    assert summarize(c)['realized_nonanchor_omission_fraction'] == 1


def test_price_multiplier_does_not_change_catalog_structure_or_facts():
    a, b = generate_catalog(12, 12), generate_catalog(12, 12, {'reference_price_multiplier': 2})
    assert a['public']['product_groups'] == b['public']['product_groups']
    for x, y in zip(a['public']['products'], b['public']['products']):
        assert x['product_id'] == y['product_id'] and x['attributes'] == y['attributes']
        assert abs(2*x['reference_price_minor'] - y['reference_price_minor']) <= 100


def test_configuration_price_correlations_and_complete_recipe():
    for family in ('laptops', 'dog_food', 'cat_food', 'beer', 'wine'):
        config = {**only(family), 'variant_omission_probability': 0}
        b = generate_catalog(2, 6, config)
        for g in b['public']['product_groups']:
            products = [p for p in b['public']['products'] if p['product_id'] in {v['product_id'] for v in g['variants']}]
            for x in products:
                a = x['attributes']
                if family in ('dog_food', 'cat_food'): assert a['recipe'] in a['ingredients']
                ordered = ['ram_gb', 'storage_gb'] if family == 'laptops' else ['net_weight_kg'] if family in ('dog_food', 'cat_food') else ['pack_count', 'volume_ml']
                for y in products:
                    for field in ordered:
                        z = y['attributes']
                        if all(a[k] == z[k] for k in a if k != field) and a[field] < z[field]:
                            assert x['reference_price_minor'] < y['reference_price_minor']
                            if field in ('net_weight_kg', 'pack_count'):
                                assert x['reference_price_minor'] / a[field] >= y['reference_price_minor'] / z[field] - 1


def test_beer_product_discovery_and_location_dependencies():
    fields = {'beer.beer_style': pin('beer.beer_style', 'IPA'),
              'beer.unfiltered': pin('beer.unfiltered', True),
              'beer.marketed_bitterness': pin('beer.marketed_bitterness', 'low'),
              'beer.production_region': pin('beer.production_region', 'Uppsala')}
    b = generate_catalog(11, 5, {**only('beer'), 'field_weights': fields})
    for p in b['public']['products']:
        a = p['attributes']
        assert (a['beer_style'], a['unfiltered'], a['marketed_bitterness']) == ('IPA', True, 'low')
        assert (a['production_region'], a['origin_country']) == ('Uppsala', 'Sweden')
    fields['beer.origin_country'] = pin('beer.origin_country', 'Germany')
    with pytest.raises(ValueError, match='no coherent'): generate_catalog(11, 5, {'field_weights': fields})


def test_task_binding_and_no_feasibility_repair():
    catalog = generate_catalog(0, 5, only('beer'))
    a = generate_task(catalog, seed=2, family='beer', target='model', budget_sek=1)
    ids = {g['group_id'] for g in catalog['public']['product_groups']}
    assert a['resolved_task']['lines'][0]['model']['id'] in ids
    assert a['resolved_task']['constraints']['budget_minor'] == 100
    assert a['resolved_task']['lines'][0]['model']['name'] in a['public']['user_message']
    assert min(p['reference_price_minor'] for p in catalog['public']['products']) > 100
    catalog['private_provenance']['irrelevant_offers'] = [{'price': 1, 'winner': True}]
    assert a['semantic_sha256'] == generate_task(catalog, seed=2, family='beer', target='model', budget_sek=1)['semantic_sha256']
    b = generate_task(catalog, seed=2, family='beer', target='model', budget_sek=1, prose_seed=99)
    assert a['semantic_sha256'] == b['semantic_sha256']
    with pytest.raises(ValueError): generate_task(catalog, query='basket')
    with pytest.raises(ValueError): generate_task(catalog, family='laptops')


def test_wine_review_reproduction_has_coherent_complete_compositions():
    catalog = generate_catalog(42, 36, model_families=list(FAMILY_IDS) * 6)
    wines = [p for p in catalog['public']['products'] if p['category'] == 'wine']
    assert wines
    for product in wines:
        facts = product['attributes']
        if facts['wine_colour'] in ('red', 'rosé'):
            assert set(facts['grapes']) & {'Pinot Noir', 'Cabernet Sauvignon'}


def test_wine_conditional_sampling_respects_explicit_zero_weights():
    fields = {'wine.grapes': pin('wine.grapes', 'Riesling')}
    catalog = generate_catalog(42, 12, {**only('wine'), 'field_weights': fields})
    assert all(p['attributes']['wine_colour'] == 'white' for p in catalog['public']['products'])
    fields['wine.wine_colour'] = pin('wine.wine_colour', 'red')
    with pytest.raises(ValueError, match='no coherent composition'):
        generate_catalog(42, 1, {**only('wine'), 'field_weights': fields})
    fields = {'wine.grapes': pin('wine.grapes', 'Pinot Noir'),
              'wine.wine_colour': pin('wine.wine_colour', 'white')}
    catalog = generate_catalog(42, 2, {**only('wine'), 'field_weights': fields})
    assert all(p['attributes']['wine_colour'] == 'white' and p['attributes']['grapes'] == ['Pinot Noir']
               for p in catalog['public']['products'])


def test_wine_validation_distinguishes_complete_composition_from_partial_requirements():
    from .generator import digest
    from environments.shopping_intent.semantics import conflicts
    catalog = generate_catalog(42, 1, {**only('wine'), 'field_weights': {
        'wine.wine_colour': pin('wine.wine_colour', 'red')}})
    for product in catalog['public']['products']:
        product['attributes']['grapes'] = ['Riesling']
    catalog['catalog_sha256'] = digest(catalog['public'])
    with pytest.raises(ValueError, match='complete grape composition'):
        validate_catalog(catalog)
    for product in catalog['public']['products']:
        product['attributes']['grapes'] = ['Riesling', 'Pinot Noir']
    catalog['catalog_sha256'] = digest(catalog['public'])
    assert validate_catalog(catalog)['valid']
    assert not conflicts('wine', [{'field': 'wine_colour', 'operator': 'eq', 'value': 'red'},
                                  {'field': 'grapes', 'operator': 'contains', 'value': 'Riesling'}])


def test_bad_catalog_data_is_rejected():
    b = generate_catalog(0, 2, {**only('dog_food'), 'variant_omission_probability': 0})
    c = copy.deepcopy(b);c['public']['products'][0]['attributes']['ingredients'] = ['rice']
    with pytest.raises(ValueError, match='protein missing'): validate_catalog(c)
    c = copy.deepcopy(b);c['public']['products'][0]['reference_price_minor'] = True
    with pytest.raises(ValueError): validate_catalog(c)
    c = copy.deepcopy(b);c['public']['products'].append(c['public']['products'][0])
    with pytest.raises(ValueError, match='Duplicate'): validate_catalog(c)
    c = copy.deepcopy(b);c['public']['products'][0]['attributes']['complete_food'] = 'yes'
    with pytest.raises(ValueError): validate_catalog(c)


@pytest.mark.parametrize('patch', [
    {'family_weights': {f: 0 for f in FAMILY_IDS}}, {'family_weights': {'foo': 1}},
    {'family_weights': {'beer': True}}, {'family_weights': {'beer': float('nan')}},
    {'field_weights': {'beer.beer_style': {'lager': -1}}}, {'field_weights': {'beer.quality': {'good': 1}}},
    {'variant_omission_probability': 1.1}, {'axis_option_counts': {'footwear.size_eu': 0}},
    {'reference_price_multiplier': float('inf')}, {'outcome_success_probability': 1},
])
def test_bad_probability_config_fails(patch):
    with pytest.raises(ValueError): generate_catalog(0, 1, patch)


def _audit(seed):
    b = generate_catalog(seed, 24)
    validate_catalog(b)
    report = summarize(b)
    return report


def test_bounded_distribution_and_semantic_audit():
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(_audit, range(50)))
    total = sum(r['models'] for r in results)
    for family in FAMILY_IDS:
        rate = sum(r['models_by_family'].get(family, 0) for r in results)/total
        assert abs(rate - 1/len(FAMILY_IDS)) < .05
    omitted = sum(r['omitted_combinations'] for r in results)
    trials = sum(r['omission_eligible_combinations'] for r in results)
    assert abs(omitted/trials - defaults()['variant_omission_probability']) < .03
