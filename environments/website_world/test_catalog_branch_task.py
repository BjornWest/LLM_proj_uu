from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from environments.website_world import catalog_branch_task as api, catalog_branch_generation as generation
from environments.website_world.catalog_branch_grading import CatalogBranchGrader
from environments.website_world.test_feature_offer_task import fixture as features
from environments.website_world.test_listed_offer_grading import answer


def fixture(**options):
    w, _, _, links, inventory = features()
    for retailer in w['retailers']:
        rid = retailer['retailer_id']
        retailer['source_locations'][0]['kind'] = 'warehouse'
        branches = []
        for suffix, city, enabled in [('central', 'Uppsala', True),
                                      ('remote', 'Stockholm', True),
                                      ('disabled', 'Uppsala', False)]:
            bid = rid+'/'+suffix
            location = {'city': city, 'country': 'SE'}
            branches.append({'branch_id': bid, 'name': suffix.capitalize(),
                             'location': location, 'pickup_enabled': enabled})
            retailer['source_locations'].append({'source_id': bid, 'kind': 'branch',
                                                'location': location, 'shipping_enabled': False})
            for offer in retailer['offers']:
                offer['stock_by_source'][bid] = 3 if suffix != 'central' or rid in ('b', 'd') else 0
        retailer['geography'] = {'branches': branches}
    spec = {'kind': api.KIND, 'concept_id': inventory.concept_id,
            'predicates': [{'field': 'sku.size_eu', 'operator': 'eq', 'value': 42}],
            'city': 'Uppsala', **options}
    task = api.make(w, spec, inventory=inventory)
    return w, task, api.reference(w, task, inventory=inventory), links, inventory


def branch_answer(rid='d', name='Central', city='Uppsala', branch_id=None, size='42'):
    retailer = {'a': 'Veska', 'b': 'Virela', 'c': 'Sold Out', 'd': 'Tied Shop'}[rid]
    text, claims = answer(name=retailer, url=f'https://{rid}.test/#/product/olive',
                          price='800' if rid == 'b' else '630' if rid == 'c' else '740', size=size)
    text += ' Collect at '+name+', '+city+'.'+(' Branch ID '+branch_id+'.' if branch_id else '')
    for field, value in [('branch_name', name), ('branch_city', city), ('branch_id', branch_id),
                         ('branch_country', None)]:
        claims[field] = {'value': value, 'evidence': text if value is not None else None}
    return text, claims


def test_physical_local_enabled_branch_before_price_and_all_ties():
    w, t, r, b, i = fixture()
    assert {o['retailer_id'] for o in r['winners']} == {'d'}
    assert r['minimum_price_minor'] == 74000 and len(r['branch_winners']) == 2
    assert all(o['branch_id'] == 'd/central' for o in r['branch_winners'])
    assert len(r['branch_inventory']['a']) == 3  # retain ineligible branches
    g = CatalogBranchGrader(w, t, r, b, inventory=i)
    text, c = branch_answer()
    assert g.grade(c, text)['structured_claims_correct']
    for rid, name, city in [('a', 'Central', 'Uppsala'), ('d', 'Disabled', 'Uppsala'),
                             ('d', 'Remote', 'Stockholm'), ('b', 'Central', 'Uppsala')]:
        text, c = branch_answer(rid, name, city)
        result = g.grade(c, text)
        assert result['oracle_grade']['requirements']['public_branch_identity']
        assert not result['structured_claims_correct']


def test_branch_shipping_capability_not_required_for_local_stock():
    w, t, r, b, i = fixture()
    assert all(not s['shipping_enabled'] for s in w['retailers'][3]['source_locations'] if s['kind'] == 'branch')
    assert r['status'] == 'match'


def test_supplier_or_warehouse_transfers_cannot_supply_branch_stock():
    w, t, _, _, i = fixture()
    for retailer in w['retailers']:
        retailer['warehouse_to_branch_transfer'] = True
        for offer in retailer['offers']:
            offer['supplier_order']['enabled'] = True
            for source in retailer['source_locations']:
                if source['kind'] == 'branch':
                    offer['stock_by_source'][source['source_id']] = 0
    t = api.make(w, api.selection(t), inventory=i)
    assert api.reference(w, t, inventory=i)['status'] == 'no_match'


def test_city_country_cap_and_named_city_normalization():
    assert fixture(city='  uPPSALA  ')[2]['status'] == 'match'
    assert fixture(city='Stockholm')[2]['minimum_price_minor'] == 63000
    assert fixture(country='NO')[2]['status'] == 'no_match'
    assert fixture(max_price_minor=73999)[2]['status'] == 'no_match'
    assert fixture(max_price_minor=74000)[2]['status'] == 'match'


@pytest.mark.parametrize('status', ['unknown', 'not_applicable'])
def test_unknown_na_never_satisfy_negative_requirement(status):
    w, t, _, _, i = fixture()
    w['products'][0]['catalog_status']['product.facts.cushioning'] = status
    spec = {**api.selection(t), 'predicates': [
        {'field': 'product.facts.cushioning', 'operator': 'ne', 'value': 'firm'}]}
    t = api.make(w, spec, inventory=i)
    assert api.reference(w, t, inventory=i)['status'] == 'no_match'


def test_stock_price_or_requirements_cannot_repair_branch_or_sku_identity():
    w, t, r, b, i = fixture()
    # Empty twin has identical public name/city; stock must not disambiguate it.
    duplicate = deepcopy(w['retailers'][3]['geography']['branches'][0])
    duplicate['branch_id'] = 'd/twin'
    w['retailers'][3]['geography']['branches'].append(duplicate)
    w['retailers'][3]['source_locations'].append({'source_id': 'd/twin', 'kind': 'branch',
                                                'location': duplicate['location'], 'shipping_enabled': False})
    for offer in w['retailers'][3]['offers']:offer['stock_by_source']['d/twin'] = 0
    t = api.make(w, api.selection(t), inventory=i);r = api.reference(w, t, inventory=i)
    g = CatalogBranchGrader(w, t, r, b, inventory=i)
    text, c = branch_answer()
    result = g.grade(c, text)
    assert not result['structured_claims_correct'] and len(result['identity_resolution']['branch_ids']) == 2
    text, c = branch_answer(branch_id='d/central')
    assert g.grade(c, text)['structured_claims_correct']
    text, c = branch_answer(branch_id='d/twin')
    assert not g.grade(c, text)['structured_claims_correct']
    text, c = branch_answer(branch_id='d/central');c['variant']['size_eu'] = {'value': None, 'evidence': None}
    assert not g.grade(c, text)['structured_claims_correct']
    text, c = branch_answer(branch_id='d/central', size='43')
    assert not g.grade(c, text)['structured_claims_correct']


def test_missing_or_foreign_branch_not_inferred_from_request():
    w, t, r, b, i = fixture();g = CatalogBranchGrader(w, t, r, b, inventory=i)
    text, c = branch_answer()
    for key in ['branch_name', 'branch_city']:
        missing = deepcopy(c);missing[key] = {'value': None, 'evidence': None}
        assert not g.grade(missing, text)['structured_claims_correct']
    text, c = branch_answer(branch_id='b/central')
    assert not g.grade(c, text)['structured_claims_correct']


def test_no_match_and_contradictory_branch_claim():
    w, t, r, b, i = fixture(city='Nowhere');g = CatalogBranchGrader(w, t, r, b, inventory=i)
    text = 'No qualifying local branch. Uppsala.'
    c = {'interpretation': 'extracted', 'status': {'value': 'no_match', 'evidence': text}}
    assert g.grade(c, text)['structured_claims_correct']
    c['branch_city'] = {'value': 'Uppsala', 'evidence': text}
    assert not g.grade(c, text)['structured_claims_correct']


def test_branch_grounding_and_reference_binding():
    w, t, r, b, i = fixture();g = CatalogBranchGrader(w, t, r, b, inventory=i)
    text, c = branch_answer();c['branch_name']['value'] = 'Absent'
    with pytest.raises(ValueError):g.grade(c, text)
    bad = deepcopy(r);bad['branch_candidates'].clear()
    with pytest.raises(ValueError):CatalogBranchGrader(w, t, bad, b, inventory=i)
    bad = deepcopy(t);bad['city'] = 'Stockholm'
    with pytest.raises(ValueError):api.reference(w, bad, inventory=i)


@pytest.mark.parametrize('options', [{'city': ''}, {'city': True}, {'city': 'x'*81},
    {'country': 'se'}, {'country': 'SWE'}, {'country': True}, {'availability': 'purchasable'},
    {'opening_time': '09:00'}, {'kind': 'wrong'}, {'max_price_minor': True}])
def test_bad_notation_before_sampling(options):
    request = {'schema': 'website-world-generation-v2', 'seed': 91,
        'world': {'concept_ids': ['footwear.walking_shoes']}, 'task': {
        'kind': api.KIND, 'concept_id': 'footwear.walking_shoes', 'city': 'Uppsala',
        'predicates': [{'field': 'sku.size_eu', 'operator': 'eq', 'value': 42}], **options}}
    def forbidden(*args, **kwargs):raise AssertionError('No world draw')
    with pytest.raises(ValueError):generation.generate(request, world_factory=forbidden)


def test_generation_delegates_once_and_preserves_world_and_original_request(monkeypatch):
    w, t, _, _, _ = fixture();original = deepcopy(w)
    seen = []
    def saved(request, **kwargs):
        seen.append(deepcopy(request))
        return {'world': w, 'surrounding': None, 'episode': {}, 'resolved_configuration': {},
                'audit': {'request_sha256': 'native-feature'}}
    monkeypatch.setattr(generation.feature_generation, 'generate', saved)
    request = {'schema': 'website-world-generation-v2', 'seed': 91,
        'world': {'concept_ids': ['footwear.walking_shoes']}, 'task': api.selection(t)}
    initial = deepcopy(request);result = generation.generate(request)
    assert len(seen) == 1 and seen[0]['task']['availability'] == 'positive_stock'
    assert w == original and request == initial and result['resolved_configuration']['request'] == request
    assert result['episode']['task_id'] == result['catalog_branch_task']['task_id']


def test_shared_formatter_receives_only_public_task_and_exact_schema(tmp_path):
    from experiments.answer_grading import task_answer
    w, t, r, b, i = fixture();g = CatalogBranchGrader(w, t, r, b, inventory=i)
    text, c = branch_answer();calls = []
    class Backend:
        def complete(self, messages):
            payload = json.loads(messages[1]['content'])
            assert set(payload) == {'public_task', 'final_answer'}
            assert 'branch_candidates' not in messages[0]['content']+messages[1]['content']
            calls.append(messages)
            content = json.dumps(c)
            return SimpleNamespace(text=content, request={'messages': messages}, raw={
                'model': 'scripted', 'provider': 'offline', 'usage': {},
                'choices': [{'finish_reason': 'stop', 'message': {'content': content}}]})
    result = task_answer.extract_and_grade(g, {'user_message': t['user_message'], 'memories': []},
                                         text, tmp_path/'grade', Backend())
    assert result['structured_claims_correct'] and len(calls) == 1
