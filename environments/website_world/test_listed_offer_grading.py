from copy import deepcopy
import json

import pytest

from environments.website_world.adapter import digest
from environments.website_world.basic_offer_task import _make_bound, _reference_bound
from environments.website_world.listed_offer_grading import ListedOfferGrader


def fixture():
    skus = [{'sku_id': f'p-{colour}-{size}', 'product_id': 'p', 'colour': colour,
             'width': 'standard', 'size_eu': size} for colour in ('olive', 'brown') for size in (42, 43)]
    product = {'product_id': 'p', 'name': 'Sundmark Sira', 'concept_id': 'footwear.walking_shoes', 'skus': skus}
    world = {'world_id': 'fixture', 'seed': 0, 'config': {'concept_ids': ['footwear.walking_shoes']}, 'products': [
        {'public': product, 'variant_fields': {k: {} for k in ('size_eu', 'width', 'colour')}}], 'retailers': []}
    links = {}
    for rid, name, price in [('a', 'Veska', 74000), ('b', 'Virela', 80000), ('c', 'Sold Out', 63000), ('d', 'Tied Shop', 74000)]:
        retailer = {'retailer_id': rid, 'name': name, 'source_locations': [{'source_id': rid, 'shipping_enabled': True}], 'offers': []}
        for sku in skus:
            oid = rid + '/' + sku['sku_id']
            offer = {'offer_id': oid, 'sku_id': sku['sku_id'], 'product_id': 'p',
                     'price_minor': price, 'currency': 'SEK', 'stock_by_source': {rid: 0 if rid == 'c' else 7},
                     'supplier_order': {'enabled': False}}
            retailer['offers'].append(offer)
            links[oid] = {**{k: offer[k] for k in ('offer_id', 'sku_id', 'product_id')}, 'retailer_id': rid,
                          'url': f'https://{rid}.test/#/product/{sku["colour"]}?size_eu={sku["size_eu"]}',
                          'selection': {'size_eu': str(sku['size_eu'])}, 'required_selection': {}}
        world['retailers'].append(retailer)
    task = _make_bound(world, {'kind': 'cheapest_available', 'concept_id': 'footwear.walking_shoes'}, digest(world))
    return world, task, _reference_bound(world, task), {'retailer_offers': links}


def answer(name='Veska', price='740', size='42', colour='olive', url=None):
    url = url or f'https://a.test/#/product/{colour}'
    text = f'Cheapest: Sundmark Sira at {name}. {colour}, EU {size}, standard width. {price} SEK. {url}'
    c = lambda v: {'value': v, 'evidence': text if v is not None else None}
    return text, {'interpretation': 'extracted', 'issues': [], 'status': c('selection'),
                  'product_name': c('Sundmark Sira'), 'retailer_name': c(name), 'offer_url': c(url), 'sku_id': c(None),
                  'variant': {'colour': c(colour), 'size_eu': c(size), 'width': c('standard')},
                  'total': {'amount': price, 'currency': 'SEK', 'evidence': text}, 'source_urls': []}


def test_correct_ties_and_bare_product_link_with_explicit_size():
    grader = ListedOfferGrader(*fixture())
    for name, url in [('Veska', 'https://a.test/#/product/olive'), ('Tied Shop', 'https://d.test/#/product/olive?size_eu=42')]:
        text, claims = answer(name=name, url=url)
        assert grader.grade(claims, text)['structured_claims_correct'] is True


def test_wrong_price_and_nonoptimal_price_are_distinct():
    grader = ListedOfferGrader(*fixture())
    text, c = answer(price='700')
    checks = grader.grade(c, text)['oracle_grade']['requirements']
    assert checks['cheapest_listed_offer'] is True and checks['reported_price'] is False
    text, c = answer(name='Virela', price='800', url='https://b.test/#/product/olive')
    checks = grader.grade(c, text)['oracle_grade']['requirements']
    assert checks['reported_price'] is True and checks['cheapest_listed_offer'] is False


def test_sold_out_offer_has_correct_price_but_fails_eligibility():
    grader = ListedOfferGrader(*fixture())
    text, c = answer(name='Sold Out', price='630', url='https://c.test/#/product/olive')
    checks = grader.grade(c, text)['oracle_grade']['requirements']
    assert checks['reported_price'] is True and checks['task_eligible'] is False


def test_matching_amount_in_wrong_currency_and_missing_named_product_fail():
    grader = ListedOfferGrader(*fixture())
    text, c = answer()
    text = text.replace('SEK', 'USD')
    for field in ('status', 'product_name', 'retailer_name', 'offer_url'):
        c[field]['evidence'] = text
    for field in c['variant'].values(): field['evidence'] = text
    c['total'].update(currency='USD', evidence=text)
    grade = grader.grade(c, text)
    assert grade['oracle_grade']['requirements']['reported_price'] is True
    assert grade['oracle_grade']['requirements']['reported_currency'] is False
    text, c = answer()
    c['product_name'] = {'value': None, 'evidence': None}
    assert grader.grade(c, text)['oracle_grade']['requirements']['product_reported'] is False


def exact_fixture():
    world, task, ref, bindings = fixture()
    sku = world['products'][0]['public']['skus'][0]
    task.update(kind='cheapest_available_exact_sku', sku_id=sku['sku_id'], product_id='p', selection=deepcopy(sku))
    ref['candidates'] = [r for r in ref['candidates'] if r['sku_id'] == sku['sku_id']]
    ref['winners'] = [r for r in ref['winners'] if r['sku_id'] == sku['sku_id']]
    ref['unavailable_offer_ids'] = [o for o in ref['unavailable_offer_ids'] if o.endswith('/' + sku['sku_id'])]
    return world, task, ref, bindings


def test_wrong_colour_and_wrong_size_are_not_repaired_by_task_or_matching_price():
    grader = ListedOfferGrader(*exact_fixture())
    for change in ({'colour': 'brown'}, {'size': '43'}):
        text, c = answer(**change)
        grade = grader.grade(c, text)
        assert grade['oracle_grade']['requirements']['public_selection_identity'] is True
        assert grade['oracle_grade']['requirements']['reported_price'] is True
        assert grade['oracle_grade']['requirements']['task_eligible'] is False


def test_missing_size_stays_ambiguous_even_with_one_task_sku_and_matching_price():
    grader = ListedOfferGrader(*exact_fixture())
    text, c = answer()
    c['variant']['size_eu'] = {'value': None, 'evidence': None}
    grade = grader.grade(c, text)
    assert len(grade['identity_resolution']['offer_ids']) == 2
    assert grade['structured_claims_correct'] is False


@pytest.mark.parametrize('url', ['https://evil.test/#/product/olive', 'https://a.test/',
    'https://a.test/#/product/olive?size_eu=43',
    'https://a.test/#/product/olive?size_eu=42&size_eu=42', 'https://a.test/#/product/olive?invented=42'])
def test_wrong_or_conflicting_urls_do_not_resolve(url):
    grader = ListedOfferGrader(*fixture())
    text, c = answer(url=url)
    assert grader.grade(c, text)['structured_claims_correct'] is False


def test_extractor_grounding_rejects_task_copied_fact_and_fabricated_quote():
    grader = ListedOfferGrader(*fixture())
    text, c = answer()
    c['variant']['size_eu'] = {'value': '43', 'evidence': text}
    with pytest.raises(ValueError, match='absent'): grader.grade(c, text)
    c['variant']['size_eu'] = {'value': '42', 'evidence': 'Invented EU 42'}
    with pytest.raises(ValueError, match='quote'): grader.grade(c, text)


def test_no_match_and_uncertain_do_not_pass_a_world_with_candidates():
    grader = ListedOfferGrader(*fixture())
    for status in ('no_match', 'uncertain'):
        text, c = answer()
        c['status']['value'] = status
        assert grader.grade(c, text)['structured_claims_correct'] is False


def test_genuine_empty_domain_and_supplier_only_availability():
    world, task, ref, bindings = fixture()
    for r in world['retailers']:
        for o in r['offers']: o['stock_by_source'] = {r['retailer_id']: 0}
    task = _make_bound(world, {'kind': 'cheapest_available', 'concept_id': task['concept_id']}, digest(world))
    grader = ListedOfferGrader(world, task, _reference_bound(world, task), bindings)
    c = {'interpretation': 'extracted', 'status': {'value': 'no_match', 'evidence': 'None available.'}}
    assert grader.grade(c, 'None available.')['structured_claims_correct'] is True
    world['retailers'][0]['offers'][0]['supplier_order']['enabled'] = True
    task = _make_bound(world, {'kind': 'cheapest_available', 'concept_id': task['concept_id']}, digest(world))
    grader = ListedOfferGrader(world, task, _reference_bound(world, task), bindings)
    text, c = answer()
    assert grader.grade(c, text)['structured_claims_correct'] is True


def test_reference_and_url_identity_corruption_reject_at_construction():
    for target in ('reference', 'links', 'task'):
        world, task, ref, links = fixture()
        if target == 'reference': ref['minimum_price_minor'] = 1
        elif target == 'links': next(iter(links['retailer_offers'].values()))['sku_id'] = 'foreign'
        else: task['quantity'] = True
        with pytest.raises(ValueError): ListedOfferGrader(world, task, ref, links)


def test_contract_does_not_include_expectations_and_does_not_change_for_execution():
    grader = ListedOfferGrader(*fixture())
    before = deepcopy(grader.schema)
    text, c = answer()
    grader.grade(c, text)
    assert grader.schema == before
    assert all(v not in json.dumps(grader.schema) for v in ('Sundmark', 'Veska', '74000', 'p-olive'))
