"""Mixed-family integration and disclosure, without per-concept guard routines."""
from copy import deepcopy

import pytest

from . import model, basket_quote, package_export
from .execution import Execution
from .catalog_registry import ADDITIONS, FIRST_ADDITIONS, DIRECT_ADDITIONS, TASK_LABELS
from environments.product_world.catalog_publication import export_catalog_content, inventory
from environments.product_world.product_package import ProductPackage
from environments.website_world import basic_offer_task

BRAND = {'brand_id': 'integration-brand', 'name': 'Aster',
         'positioning_weights': {'budget': 2, 'mainstream': 5, 'premium': 2},
         'emphasis_weights': {'cushioning': 1, 'lightness': 1, 'support': 1}}


@pytest.fixture(scope='module')
def execution():
    return Execution()


@pytest.mark.parametrize('cid', (*FIRST_ADDITIONS, *DIRECT_ADDITIONS))
def test_shared_graph_matches_authored_manufacture(execution, cid):
    item = execution.sample(7, cid, BRAND, 'integration/' + cid, review_count=2)
    # One offline comparison to the authored graph, not a production validator.
    package = ProductPackage.load(package_export.WIDTH / (cid + '.json'))
    inputs = {'brand': {k: deepcopy(v) for k, v in BRAND.items() if 'brand.' + k in package.fields},
              'product': {'product_id': 'integration/' + cid}}
    inputs['brand']['eligible_concepts'] = [cid]
    from .catalog_registry import input_defaults
    expected = package.sample(7, inputs=input_defaults(package.document, inputs))
    assert item['private']['sample']['entities'] == expected['entities']
    assert len(item['reviews']) == 2
    assert cid in TASK_LABELS
    full = export_catalog_content(item, sku_id=item['public']['skus'][0]['sku_id'],
            seed=7, retailer_id='retailer-test', selected_groups=list(inventory(cid)['groups']))
    for group in full['display_groups']:
        for slot in group['slots']:
            for claim in slot['assertions']:
                assert claim['status'] == 'known'
                assert claim['subject']['id'] in {item['public']['product_id'], full['sku_id']}
                assert not claim['field'].endswith('model_price_factor')


@pytest.fixture(scope='module')
def mixed_world():
    return Execution().generate(64, concept_ids=[
        'footwear.walking_shoes', 'footwear.road_running_shoes', 'jackets.rain_shells',
        'headphones.in_ear_earbuds', 'cat_food.dry_food', 'dog_food.wet_food',
        'phones.smartphones', 'phone_cases.shell_cases', 'chargers.plug_in_wall_chargers',
        'keyboards.desktop_keyboards'], tasks=['footwear.walking_shoes'],
        controls={'world_size': 1.8, 'product_concentration': 1.2,
                  'retailer_concentration': .5, 'within_store_task_concentration': 1.2},
        review_count=3)


def test_real_assortments_quotes_and_new_task_reference(mixed_world):
    world = mixed_world
    assert model.validate(world)['valid']
    assert len(world['summary']['families']) == 9
    plan = basket_quote.make_plan(world)
    for retailer in world['retailers']:
        for offer in retailer['offers'][:2]:
            quote = basket_quote.quote(world, retailer['retailer_id'],
                [{'line_id': offer['offer_id'], 'offer_id': offer['offer_id'], 'quantity': 1}], plan=plan)
            assert quote['retailer_id'] == retailer['retailer_id']
    task = basic_offer_task.make(world, {'kind': 'cheapest_available', 'concept_id': 'phones.smartphones'})
    reference = basic_offer_task.reference(world, task)
    assert 'smartphone' in task['user_message']
    eligible = [o['price_minor'] for r in world['retailers'] for o in r['offers']
                if o['product_id'] in {p['public']['product_id'] for p in world['products']
                    if p['public']['concept_id'] == 'phones.smartphones'}
                and (any(o['stock_by_source'].values()) or o['supplier_order']['enabled'])]
    assert reference['minimum_price_minor'] == min(eligible)


def test_empty_partial_unknown_and_retailer_profile(execution):
    item = execution.sample(7, 'headphones.in_ear_earbuds', BRAND, 'disclosure-product')
    sid = item['public']['skus'][0]['sku_id']; groups = list(inventory(item['public']['concept_id'])['groups'])
    args = dict(sku_id=sid, seed=7, retailer_id='retailer-test')
    empty = export_catalog_content(item, selected_groups=[], **args)
    assert empty['display_groups'] == empty['highlight_candidates'] == []
    partial = export_catalog_content(item, selected_groups=groups[:2], **args)
    assert all(s['group_key'] in groups[:2] for g in partial['display_groups'] for s in g['slots'])
    changed = deepcopy(item)
    changed['catalog_status']['product.facts.connection'] = 'unknown'
    hidden = export_catalog_content(changed, selected_groups=groups, **args)
    assert 'product.facts.connection' not in [a['field'] for g in hidden['display_groups']
        for s in g['slots'] for a in s['assertions']]
    retailer = {'retailer_id': 'retailer-test', 'template_id': 'electronics',
                'scale': 'large', 'specificity': 'balanced', 'price_preference': 'mainstream'}
    result = export_catalog_content(item, retailer=retailer, **args)
    assert result['retailer_disclosure']['retailer_id'] == retailer['retailer_id']
    assert result == export_catalog_content(item, retailer=retailer, **args)


def test_original_default_is_still_five_and_unadopted_packages_fail():
    assert len(package_export.CONCEPTS) == 5
    assert len(package_export.SUPPORTED_CONCEPTS) == len(package_export.CONCEPTS) + len(ADDITIONS)
    with pytest.raises(ValueError, match='supported'):
        Execution().generate(1, concept_ids=['furniture.fixed_height_desks'], tasks=[])
