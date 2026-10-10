from copy import deepcopy
from hashlib import sha256
import json

import pytest

from environments.website_world.comparison_sku_task import make, reference
from environments.website_world.comparison_stock_grading import ComparisonStockGrader


def fixture(*, stock=2, kind='branch', shipping=True, supplier=False, tie=False,
            unsold=False, live_price=70000):
    skus = [{'sku_id': f'p-black-{size}', 'product_id': 'p', 'colour': 'black',
             'size_eu': size} for size in (42, 43)]
    world = {'world_id': 'w', 'quote_as_of': '2026-10-07', 'products': [
        {'public': {'product_id': 'p', 'name': 'Example Luma', 'skus': skus},
         'variant_fields': {'colour': {}, 'size_eu': {}}}], 'retailers': []}
    links = {}
    for rid, quantity in [('a', stock), ('b', 9)]:
        retailer = {'retailer_id': rid, 'name': rid.upper(), 'source_locations': [
            {'source_id': rid+'-source', 'kind': kind, 'shipping_enabled': shipping}], 'offers': []}
        for sku in skus:
            if rid == 'a' and unsold and sku['size_eu'] == 42:
                continue
            oid = rid+'/'+sku['sku_id']
            offer = {'offer_id': oid, 'product_id': 'p', 'sku_id': sku['sku_id'],
                     'price_minor': live_price, 'stock_by_source': {rid+'-source': quantity},
                     'supplier_order': {'enabled': supplier}}
            retailer['offers'].append(offer)
            links[oid] = {'retailer_id': rid, 'product_id': 'p', 'sku_id': sku['sku_id'],
                          'url': f'https://{rid}.test/#/product/luma',
                          'required_selection': {'colour': 'black', 'size_eu': str(sku['size_eu'])}}
        world['retailers'].append(retailer)
    sidecar = {'source_world_id': 'w', 'source_world_sha256': sha256(json.dumps(
        world, sort_keys=True, ensure_ascii=False).encode()).hexdigest(), 'sites': [
            {'site_id': 'comparison-00', 'kind': 'aggregator', 'name': 'Compare',
             'product_ids': ['p'], 'listings': [
                 {'product_id': 'p', 'retailer_id': 'a', 'price_minor': 50000},
                 {'product_id': 'p', 'retailer_id': 'b', 'price_minor': 50000 if tie else 60000}]}]}
    task = make(world, sidecar, comparison_site_id='comparison-00', sku_id='p-black-42')
    registry = [{'site_id': 'comparison-00', 'origin': 'https://compare.test'}]
    return world, task, reference(world, sidecar, task), {'retailer_offers': links}, sidecar, registry


def grader(**kw):
    world, task, ref, bindings, surrounding, registry = fixture(**kw)
    return ComparisonStockGrader(world, task, ref, bindings, surrounding=surrounding, site_registry=registry)


def answer(*, retailer='a', size='42', colour='black', status='in_stock', price='500',
           shop_only=True, comparison='https://compare.test/models/p', url=None):
    texts = {'in_stock': 'In stock.', 'not_in_stock': 'Not in stock.',
             'backorder': 'Supplier backorder only; not in stock.',
             'unavailable': 'Sold out.', 'variant_not_sold': 'The retailer does not sell this variant.',
             'uncertain': 'Stock could not be determined.'}
    url = url or f'https://{retailer}.test/#/product/luma'
    text = (f'Example Luma {colour} EU{size}. Checked {retailer.upper()}. '
            f'Advertised {price} SEK. {texts[status]} '
            + ('Stock is only at a physical branch. ' if shop_only is True else
               'Warehouse stock is available. ' if shop_only is False else '')
            + f'Comparison: {comparison} Retailer: {url}')
    def c(value, evidence=None):
        return {'value': value, 'evidence': evidence if value is not None else None}
    claims = {'interpretation': 'extracted', 'issues': [],
        'status': c(status, texts[status]), 'product_name': c('Example Luma', 'Example Luma'),
        'retailer_name': c(retailer.upper(), 'Checked '+retailer.upper()+'.'),
        'comparison_url': c(comparison, comparison), 'offer_url': c(url, url),
        'sku_id': c(None), 'variant': {'colour': c(colour, f'Example Luma {colour} EU{size}.'),
                                    'size_eu': c(size, f'Example Luma {colour} EU{size}.')},
        'shop_only': c(shop_only, 'Stock is only at a physical branch.' if shop_only else
                      'Warehouse stock is available.' if shop_only is not None else None),
        'total': {'amount': price, 'currency': 'SEK', 'evidence': f'Advertised {price} SEK.'},
        'source_urls': []}
    return text, claims


def grade(g, **kw):
    text, claims = answer(**kw)
    return g.grade(claims, text)


def test_advertised_price_differs_from_live_price_without_changing_rank():
    g = grader(live_price=70000)
    assert grade(g)['structured_claims_correct']
    bad = grade(g, price='700')
    assert bad['oracle_grade']['requirements']['live_exact_sku_stock']
    assert not bad['oracle_grade']['requirements']['advertised_item_price']


@pytest.mark.parametrize('shipping', [False, True])
def test_branch_only_includes_shipping_enabled_branches(shipping):
    g = grader(shipping=shipping)
    assert grade(g)['structured_claims_correct']
    assert not grade(g, shop_only=None)['structured_claims_correct']
    assert not grade(g, shop_only=False)['structured_claims_correct']


def test_warehouse_stock_cannot_be_reported_as_branch_only():
    g = grader(kind='warehouse')
    assert grade(g, shop_only=False)['structured_claims_correct']
    assert grade(g, shop_only=None)['structured_claims_correct']
    assert not grade(g, shop_only=True)['structured_claims_correct']


@pytest.mark.parametrize('status', ['backorder', 'not_in_stock'])
def test_supplier_order_is_not_stock_and_cheapest_does_not_move(status):
    g = grader(stock=0, supplier=True)
    assert grade(g, status=status, shop_only=None)['structured_claims_correct']
    assert not grade(g)['structured_claims_correct']
    expensive = grade(g, retailer='b', shop_only=None)
    assert not expensive['oracle_grade']['requirements']['minimum_advertised_retailer']


@pytest.mark.parametrize('status', ['unavailable', 'not_in_stock'])
def test_unavailable_cheapest_is_a_valid_report(status):
    assert grade(grader(stock=0), status=status, shop_only=None)['structured_claims_correct']


@pytest.mark.parametrize('rid', ['a', 'b'])
def test_every_minimum_advertised_tie_is_accepted(rid):
    assert grade(grader(tie=True), retailer=rid)['structured_claims_correct']


@pytest.mark.parametrize('status', ['variant_not_sold', 'not_in_stock'])
def test_unsold_manufactured_target_uses_carried_model_route_without_fabricating_offer(status):
    g = grader(unsold=True)
    good = grade(g, status=status, shop_only=None)
    assert good['structured_claims_correct']
    assert good['selected_candidate_assessment']['sku_id'] == 'p-black-42'
    assert not grade(g)['structured_claims_correct']


def test_same_price_default_sibling_does_not_repair_missing_size():
    g = grader()
    text, claims = answer()
    claims['variant'].pop('size_eu')
    result = g.grade(claims, text)
    assert not result['structured_claims_correct']
    assert len(result['identity_resolution']['candidates']) == 2
    assert not grade(g, size='43')['oracle_grade']['requirements']['exact_manufactured_sku']


def test_public_url_selectors_resolve_identity_but_conflicts_reject():
    g = grader()
    text, claims = answer(url='https://a.test/#/product/luma?size_eu=42&colour=black')
    claims['variant'] = {}
    assert g.grade(claims, text)['structured_claims_correct']
    assert not grade(g, size='43', url='https://a.test/#/product/luma?size_eu=42')['structured_claims_correct']
    assert not grade(g, url='https://a.test/#/product/luma?size_eu=42&size_eu=43')['structured_claims_correct']


@pytest.mark.parametrize('kw', [
    {'comparison': 'https://compare.test/'},
    {'comparison': 'https://other.test/models/p'},
    {'comparison': 'https://compare.test/models/other'},
    {'url': 'https://a.test/'},
    {'url': 'https://other.test/#/product/luma'},
    {'colour': 'blue'}, {'status': 'uncertain'},
])
def test_wrong_links_variants_and_unknown_stock_are_not_successes(kw):
    assert not grade(grader(), **kw)['structured_claims_correct']


def test_fabricated_evidence_is_an_extraction_error_not_an_answer_grade():
    text, claims = answer()
    claims['status']['evidence'] = 'This sentence is absent.'
    with pytest.raises(ValueError):
        grader().grade(claims, text)


@pytest.mark.parametrize('mutation', ['world', 'task', 'reference', 'binding'])
def test_changed_native_or_public_bindings_reject_before_grading(mutation):
    world, task, ref, bindings, surrounding, registry = fixture()
    if mutation == 'world': world['retailers'][0]['offers'][0]['stock_by_source']['a-source'] = 0
    if mutation == 'task': task['selectors']['size_eu'] = 43
    if mutation == 'reference': ref['winners'][0]['in_stock'] = False
    if mutation == 'binding': bindings['retailer_offers']['a/p-black-42']['sku_id'] = 'p-black-43'
    with pytest.raises(ValueError):
        ComparisonStockGrader(world, task, ref, bindings, surrounding=surrounding, site_registry=registry)


def test_inputs_remain_isolated_from_later_mutations():
    world, task, ref, bindings, surrounding, registry = fixture()
    g = ComparisonStockGrader(world, task, ref, bindings, surrounding=surrounding, site_registry=registry)
    world['products'][0]['public']['name'] = 'changed'
    ref['winners'].clear(); task['sku_id'] = 'wrong'; bindings['retailer_offers'].clear()
    assert grade(g)['structured_claims_correct']
