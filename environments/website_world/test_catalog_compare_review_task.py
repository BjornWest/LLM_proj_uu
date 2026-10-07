"""Tiny authored joins exercise actual parent graders; no browser/model/world draw."""
from copy import deepcopy

import pytest
from jsonschema.exceptions import ValidationError
from environments.product_world.review_population import summarize_ratings
from environments.website_world import catalog_compare_review_task as native, ecosystem
from environments.website_world.catalog_compare_review_grading import CatalogCompareReviewGrader
from environments.website_world.test_catalog_comparison_task import fixture as comparison_fixture, answer as comparison_answer
from environments.website_world.test_catalog_review_task import fixture as review_fixture, claims_for


def fixture(operation='rating_summary'):
    w, _, _, bindings, inventory = comparison_fixture()
    review_world, _, _, _, _, ri = review_fixture()
    for item in w['products']:
        item['public']['facts']['fastening'] = 'laces'
        pid = item['public']['product_id']
        rows = deepcopy(review_world['products'][0]['reviews'])
        sku = item['public']['skus'][0]['sku_id']
        for row in rows:
            row.update(review_id=pid + '-' + row['review_id'], sku_id=sku)
            for s in row['evidence']['statements']: s['sku_id'] = sku
        item.update(reviews=rows, rating_summary=summarize_ratings(rows))
    spec = {'kind': native.KIND, 'concept_id': inventory.concept_id,
        'fields': ['product.facts.cushioning', 'product.facts.reference_mass_g', 'product.facts.fastening'],
        'review': {'operation': operation}}
    if operation == 'topic_counts':
        spec['review']['topic'] = {'aspect': 'walking_comfort',
            'context': {'activity': 'walking around town', 'duration': 'several hours'}}
    task = native.make(w, spec, inventory=inventory, review_inventory=ri)
    ref = native.reference(w, task, inventory=inventory, review_inventory=ri)
    surrounding = ecosystem.generate(w, {'comparison_count': 0, 'review_count': 2})
    registry = [{**{k: s[k] for k in ('kind', 'site_id', 'name')}, 'origin': 'https://reviews' + str(n) + '.test'}
                for n, s in enumerate(surrounding['sites'])]
    g = CatalogCompareReviewGrader(w, task, ref, bindings, registry,
        surrounding=surrounding, inventory=inventory, review_inventory=ri)
    text, compared = comparison_answer(w, task['comparison_task'], ref['comparison'], bindings)
    reviewed = {}
    for role, t in task['review_tasks'].items():
        fragment, reviewed[role] = claims_for(t, ref['reviews'][role])
        text += '\n\n' + fragment
    return w, task, ref, bindings, inventory, ri, g, text, {'comparison': compared, 'reviews': reviewed}


@pytest.mark.parametrize('operation', ['rating_summary', 'topic_counts'])
def test_conjunction_of_same_model_native_subgrades(operation):
    w, t, r, b, i, ri, g, text, claims = fixture(operation)
    result = g.grade(claims, text)
    assert result['structured_claims_correct']
    assert len(result['native_subreports']) == 3 and type(result['derivations']) is list
    assert {x['source_family'] for x in t['required_obligations']} == {'retailer', 'product_reviews'}
    assert {x['product_id'] for x in t['required_obligations']} == {m['product_id'] for m in t['comparison_task']['models']}
    assert len(t['required_obligations']) == (24 if operation == 'rating_summary' else 22)


@pytest.mark.parametrize('change', ['fact', 'review_count', 'foreign_review', 'swapped_reviews'])
def test_one_failed_part_fails_whole_task(change):
    *_, g, text, claims = fixture()
    if change == 'fact':
        c = claims['comparison']['rows'][0]['facts']['product.facts.reference_mass_g']
        text += '\n999 g';c['value'] = {'value': '999', 'evidence': '999 g'}
    elif change == 'review_count':
        claims['reviews']['model_1']['rating_count'] = {'value': None, 'evidence': None}
    elif change == 'foreign_review':
        text += '\nhttps://foreign.test/reviews/p'
        claims['reviews']['model_1']['review_url'] = {'value': 'https://foreign.test/reviews/p', 'evidence': 'https://foreign.test/reviews/p'}
    else:
        claims['reviews']['model_1'], claims['reviews']['model_2'] = claims['reviews']['model_2'], claims['reviews']['model_1']
    assert not g.grade(claims, text)['structured_claims_correct']


def test_missing_part_cannot_pass_and_reference_subject_drift_rejects():
    w, t, r, _, i, ri, g, text, claims = fixture()
    del claims['reviews']['model_2']
    with pytest.raises(ValidationError): g.grade(claims, text)
    t['review_tasks']['model_1']['subject']['product_id'] = 'foreign'
    with pytest.raises(ValueError): native.reference(w, t, inventory=i, review_inventory=ri)


def test_no_outcome_based_selection_input_mutation_or_empty_fixture():
    w, t, _, _, i, ri, *_ = fixture(); original = deepcopy(w)
    native.make(w, t['spec'], inventory=i, review_inventory=ri)
    assert w == original
    for retailer in w['retailers']:
        for offer in retailer['offers']:
            offer['price_minor'] += 100000
            offer['stock_by_source'] = {k: 0 for k in offer['stock_by_source']}
    other = native.make(w, t['spec'], inventory=i, review_inventory=ri)
    assert other['comparison_task']['models'] == t['comparison_task']['models']
    for retailer in w['retailers']: retailer['offers'] = []
    with pytest.raises(ValueError, match='two carried'): native.make(w, t['spec'], inventory=i, review_inventory=ri)


@pytest.mark.parametrize('change', ['duplicate', 'private', 'sku', 'topic', 'rating_topic', 'min_assessed', 'absent_concept'])
def test_pre_sampling_declaration_reuses_parent_contracts(change):
    _, task, _, _, i, ri, *_ = fixture()
    spec = deepcopy(task['spec']); concepts = [i.concept_id]
    if change == 'duplicate': spec['fields'][1] = spec['fields'][0]
    elif change == 'private': spec['fields'][1] = 'product.private.hidden'
    elif change == 'sku': spec['fields'][1] = 'sku.size'
    elif change == 'topic': spec['review'] = {'operation': 'topic_counts', 'topic': {'aspect': 'foreign', 'context': {}}}
    elif change == 'rating_topic': spec['review']['topic'] = {'aspect': 'foreign', 'context': {}}
    elif change == 'min_assessed': spec['review'] = {'operation': 'topic_counts', 'topic': ri.topics[0], 'min_assessed': False}
    else: concepts = []
    with pytest.raises(ValueError):
        native.resolve(spec, inventory=i, review_inventory=ri, concept_ids=concepts)


@pytest.mark.parametrize('coverage', ['both', 'one', 'no_models'])
def test_generation_retains_unsupported_world_without_proxy_task_or_retry(monkeypatch, coverage):
    from environments.website_world import catalog_compare_review_generation as generation
    w, task, _, _, i, ri, *_ = fixture()
    spec = task['spec']; original = deepcopy(w)
    surrounding = {'sites': [{'kind': 'product_reviews', 'site_id': 'r',
        'product_ids': [m['product_id'] for m in task['comparison_task']['models']]}]}
    if coverage == 'one': surrounding['sites'][0]['product_ids'].pop()
    if coverage == 'no_models':
        for retailer in w['retailers']: retailer['offers'] = []
        original = deepcopy(w)
    calls = []
    monkeypatch.setattr(generation, 'FieldInventory', lambda _: i)
    monkeypatch.setattr(generation, 'ReviewInventory', lambda _: ri)
    monkeypatch.setattr(generation.unified_generation, 'compile_request', lambda _:
        {'world': {'concept_ids': [i.concept_id]}, 'surrounding_options': {'enabled': True, 'review_count': 1}})
    def sampled(request, *, world_factory):
        calls.append((deepcopy(request), world_factory))
        return {'world': w, 'surrounding': surrounding, 'episode': {},
                'resolved_configuration': {}, 'audit': {'request_sha256': 'proxy'}}
    monkeypatch.setattr(generation.unified_generation, 'generate', sampled)
    request = {'schema': generation.unified_generation.VERSION, 'seed': 1, 'task': spec}
    request_copy = deepcopy(request); sentinel = object()
    result = generation.generate(request, world_factory=sentinel)
    assert len(calls) == 1 and calls[0][1] is sentinel
    assert request == request_copy and w == original
    assert result['audit']['proxy_request_sha256'] == 'proxy'
    assert result['audit']['request_sha256'] == generation.unified_generation.shared.digest(request)
    assert result['compare_review_task_binding']['world_repaired'] is False
    assert result['compare_review_task_binding']['status'] == {
        'both': 'bound', 'one': 'unsupported_no_review_publication',
        'no_models': 'unsupported_fewer_than_two_carried_models'}[coverage]
    if coverage == 'both':
        assert result['episode']['manual_task']['user_message'] == result['catalog_compare_review_task']['user_message']
    else:
        assert result['episode']['manual_task'] is None


def test_compile_rejects_disabled_review_publications_before_sampling(monkeypatch):
    from environments.website_world import catalog_compare_review_generation as generation
    _, task, _, _, i, ri, *_ = fixture()
    monkeypatch.setattr(generation, 'FieldInventory', lambda _: i)
    monkeypatch.setattr(generation, 'ReviewInventory', lambda _: ri)
    monkeypatch.setattr(generation.unified_generation, 'compile_request', lambda _:
        {'world': {'concept_ids': [i.concept_id]}, 'surrounding_options': {'enabled': True, 'review_count': 0}})
    with pytest.raises(ValueError, match='Enable review'):
        generation.compile_request({'schema': generation.unified_generation.VERSION, 'task': task['spec']})
