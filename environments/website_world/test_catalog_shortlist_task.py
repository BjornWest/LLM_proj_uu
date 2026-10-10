from copy import deepcopy

import pytest

from environments.website_world import catalog_shortlist_task as api, catalog_shortlist_generation as generation
from environments.website_world.catalog_shortlist_grading import CatalogShortlistGrader
from environments.website_world.test_feature_offer_task import fixture as one_model
from environments.website_world.test_listed_offer_grading import answer


def fixture(limit=2, **options):
    world, _, _, links, inventory = one_model()
    # Three additional manufactured models; colours and retailers remain offers
    # of each model. Authored finite fixtures, not new genuine world samples.
    original = deepcopy(world['products'][0])
    for pid, name, price in [('q', 'Second Shoe', 80000), ('r', 'Third Shoe', 80000), ('s', 'Fourth Shoe', 90000)]:
        item = deepcopy(original)
        item['public'].update(product_id=pid, name=name)
        for sku in item['public']['skus']:
            sku['sku_id'] = sku['sku_id'].replace('p-', pid+'-', 1)
            sku['product_id'] = pid
        world['products'].append(item)
        for retailer in world['retailers']:
            for offer in deepcopy(retailer['offers'][:4]):
                oid = offer['offer_id']; binding = deepcopy(links['retailer_offers'][oid])
                offer.update(product_id=pid, sku_id=offer['sku_id'].replace('p-', pid+'-', 1),
                             offer_id=oid.replace('/p-', '/'+pid+'-', 1), price_minor=price)
                retailer['offers'].append(offer)
                binding.update(product_id=pid, sku_id=offer['sku_id'], offer_id=offer['offer_id'],
                               url=binding['url'].replace('/product/', '/product/'+pid+'/'))
                links['retailer_offers'][offer['offer_id']] = binding
    spec = {'kind': api.KIND, 'concept_id': 'footwear.walking_shoes', 'limit': limit,
            'predicates': [{'field': 'sku.size_eu', 'operator': 'eq', 'value': 42}], **options}
    task = api.make(world, spec, inventory=inventory)
    reference = api.reference(world, task, inventory=inventory)
    return world, task, reference, links, inventory


def grader():
    w, t, r, b, i = fixture()
    return CatalogShortlistGrader(w, t, r, b, inventory=i)


def row(pid='p', price=None):
    name = {'p': 'Sundmark Sira', 'q': 'Second Shoe', 'r': 'Third Shoe', 's': 'Fourth Shoe'}[pid]
    price = price or {'p': '740', 'q': '800', 'r': '800', 's': '900'}[pid]
    url = 'https://a.test/#/product/' + ('' if pid == 'p' else pid + '/') + 'olive'
    text, c = answer(price=price, url=url)
    text = text.replace('Sundmark Sira', name)
    for field in ('product_name', 'retailer_name', 'offer_url', 'status'):
        c[field]['evidence'] = text
    c['product_name']['value'] = name
    for field in c['variant'].values():
        if field['value'] is not None: field['evidence'] = text
    c['total']['evidence'] = text
    return text, {k: c[k] for k in ('product_name', 'retailer_name', 'offer_url', 'sku_id', 'variant', 'total')}


def claims(pids=('p', 'q', 'r')):
    values = [row(pid) for pid in pids]
    text = '\n'.join(v[0] for v in values)
    return text, {'interpretation': 'extracted', 'issues': [],
                  'status': {'value': 'shortlist', 'evidence': text},
                  'rows': [v[1] for v in values], 'source_urls': []}


def test_groups_models_and_includes_cutoff_ties():
    w, t, ref, _, _ = fixture()
    assert len(ref['all_models']) == 4 and len(ref['selected_models']) == 3
    assert ref['cutoff_price_minor'] == 80000
    assert {m['product_id'] for m in ref['selected_models']} == {'p', 'q', 'r'}
    assert len(ref['selected_models'][0]['winners']) == 4
    assert 'Find the cheapest available' not in t['user_message']
    assert 'different models' in t['user_message']


def test_correct_shortlist_and_equal_price_order():
    g = grader()
    for pids in [('p', 'q', 'r'), ('p', 'r', 'q')]:
        text, c = claims(pids)
        assert g.grade(c, text)['structured_claims_correct']


@pytest.mark.parametrize('pids', [('p', 'q'), ('p', 'q', 'q'), ('p', 'q', 'r', 's'), ('q', 'p', 'r')])
def test_missing_tie_duplicate_extra_or_bad_order_fails(pids):
    g = grader()
    text, c = claims(pids)
    assert not g.grade(c, text)['structured_claims_correct']


def test_all_mode_fewer_than_limit_and_natural_empty():
    assert len(fixture(None)[2]['selected_models']) == 4
    assert len(fixture(10)[2]['selected_models']) == 4
    w, t, r, b, i = fixture(max_price_minor=1)
    assert r['status'] == 'no_match'
    g = CatalogShortlistGrader(w, t, r, b, inventory=i)
    text = 'No matching models are available.'
    c = {'interpretation': 'extracted', 'issues': [], 'status': {'value': 'no_match', 'evidence': text},
         'rows': [], 'source_urls': []}
    assert g.grade(c, text)['structured_claims_correct']
    c['status']['value'] = 'uncertain'
    assert not g.grade(c, text)['structured_claims_correct']


def test_no_identity_or_price_repair_from_expected_list():
    g = grader()
    text, c = claims()
    c['rows'][1]['variant']['size_eu'] = {'value': None, 'evidence': None}
    assert not g.grade(c, text)['structured_claims_correct']
    text, c = claims()
    c['rows'][1]['total'] = None
    assert not g.grade(c, text)['structured_claims_correct']
    text, c = claims()
    c['rows'][1]['product_name'] = {'value': None, 'evidence': None}
    assert not g.grade(c, text)['structured_claims_correct']


def test_eligible_model_at_nonminimum_retailer_price_fails():
    g = grader()
    text, c = claims()
    bad_text, full = answer(name='Virela', price='800', url='https://b.test/#/product/olive')
    text = bad_text + '\n' + '\n'.join(row(pid)[0] for pid in ('q', 'r'))
    c['status']['evidence'] = text
    c['rows'][0] = {k: full[k] for k in ('product_name', 'retailer_name', 'offer_url', 'sku_id', 'variant', 'total')}
    result = g.grade(c, text)
    assert not result['structured_claims_correct'] and not result['oracle_grade']['requirements']['row_0']


def test_wrong_grounding_and_stale_reference_reject():
    g = grader()
    text, c = claims()
    c['rows'][1]['variant']['size_eu'] = {'value': '43', 'evidence': text}
    with pytest.raises(ValueError): g.grade(c, text)
    w, t, r, b, i = fixture()
    r['selected_models'].pop()
    with pytest.raises(ValueError): CatalogShortlistGrader(w, t, r, b, inventory=i)


@pytest.mark.parametrize('limit', [True, 0, -1, 11, 2.5, '2'])
def test_invalid_limit_pre_sampling(limit, monkeypatch):
    request = {'schema': 'website-world-generation-v2', 'seed': 80,
        'world': {'concept_ids': ['footwear.walking_shoes']},
        'task': {'kind': api.KIND, 'concept_id': 'footwear.walking_shoes', 'limit': limit,
                 'predicates': [{'field': 'sku.size_eu', 'operator': 'eq', 'value': 42}]}}
    def forbidden(*args, **kwargs): raise AssertionError('No draw')
    monkeypatch.setattr(generation.feature_generation, 'generate', forbidden)
    with pytest.raises(ValueError): generation.generate(request)


def test_generation_retains_population_and_natural_no_match(monkeypatch):
    w, _, _, _, _ = fixture()
    before = deepcopy(w)
    def saved(*args, **kwargs):
        return {'world': w, 'surrounding': None, 'episode': {}, 'resolved_configuration': {},
                'audit': {'request_sha256': 'feature'}}
    monkeypatch.setattr(generation.feature_generation, 'generate', saved)
    request = {'schema': 'website-world-generation-v2', 'seed': 80,
        'world': {'concept_ids': ['footwear.walking_shoes']},
        'task': {'kind': api.KIND, 'concept_id': 'footwear.walking_shoes', 'limit': 3,
                 'predicates': [{'field': 'sku.size_eu', 'operator': 'eq', 'value': 99}]}}
    result = generation.generate(request)
    assert w == before and result['catalog_shortlist_reference']['status'] == 'no_match'
    assert result['episode']['task_id'] == result['catalog_shortlist_task']['task_id']


def test_task_neutral_formatter_uses_exact_row_schema_and_no_reference(tmp_path):
    import json
    from types import SimpleNamespace
    from experiments.answer_grading import task_answer
    g = grader()
    text, c = claims()
    events = []
    class Backend:
        def complete(self, messages):
            payload = json.loads(messages[1]['content'])
            assert set(payload) == {'public_task', 'final_answer'}
            assert payload['final_answer'] == text
            assert 'selected_models' not in messages[0]['content']
            assert 'feature_reference' not in messages[1]['content']
            events.append(messages)
            content = json.dumps(c)
            return SimpleNamespace(text=content, request={'messages': messages}, raw={
                'model': 'scripted', 'provider': 'offline', 'usage': {},
                'choices': [{'finish_reason': 'stop', 'message': {'content': content}}]})
    result = task_answer.extract_and_grade(g, {'user_message': g.task['user_message'], 'memories': []},
        text, tmp_path/'extract', Backend())
    assert result['structured_claims_correct'] and len(events) == 1
    assert isinstance(result['derivations'], list)
