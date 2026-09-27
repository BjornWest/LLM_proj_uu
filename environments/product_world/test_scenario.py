from concurrent.futures import ThreadPoolExecutor
import pytest

from . import scenario
from .config import FAMILY_IDS
from .generator import generate_catalog
from .stores import SPECIALIST


def test_task_complete_before_world_and_only_scope_crosses_boundary(monkeypatch):
    expected = scenario.sample_task(seed=2, family='footwear', memory='mixed', hidden='blocker')
    original = scenario.generate_store_world
    def checked(**kwargs):
        assert kwargs == {'focus_families': ['footwear'], 'model_references': {}}
        # Capture the task completed before this call, rather than reconstructing
        # an intent from a generated catalog afterward.
        assert completed == [expected]
        return original(**kwargs)
    sample = scenario.sample_task
    completed = []
    def record(**kwargs):
        result = sample(**kwargs); completed.append(result); return result
    monkeypatch.setattr(scenario, 'sample_task', record)
    monkeypatch.setattr(scenario, 'generate_store_world', checked)
    result = scenario.generate_scenario({'seed': 2, 'family': 'footwear', 'memory': 'mixed', 'hidden': 'blocker'})
    assert result['task'] == expected
    assert result['private_provenance']['generation_order'][0] == 'structured_task_and_memories'


def test_world_changes_do_not_rewrite_task_memories_hidden_or_named_identity():
    task = {'seed': 2, 'family': 'footwear', 'target': 'model', 'memory': 'mixed', 'hidden': 'blocker'}
    a = scenario.generate_scenario(task, {'seed': 10})
    b = scenario.generate_scenario(task, {'seed': 11, 'store_config': {'stockout_probability': 1}})
    assert a['task'] == b['task'] == scenario.sample_task(**task)
    assert a['task']['memory_facts'] and a['task']['hidden_user_specifications']
    assert a['bundle']['world_sha256'] != b['bundle']['world_sha256']
    assert all(o['stock_quantity'] == 0 for o in b['bundle']['public']['offers'])
    model = a['task']['request']['lines'][0]['model']
    for s in (a,b):
        group = next(g for g in s['bundle']['public']['product_groups'] if g['group_id'] == model['id'])
        assert group['name'] == model['name']


def test_identity_reservation_does_not_condition_catalog_facts():
    normal = generate_catalog(8, 1, model_families=['laptops'])
    named = generate_catalog(8, 1, model_families=['laptops'], model_identities=[{'id': 'named-laptop', 'name': 'Named laptop'}])
    assert [p['attributes'] for p in normal['public']['products']] == [p['attributes'] for p in named['public']['products']]
    assert [p['reference_price_minor'] for p in normal['public']['products']] == [p['reference_price_minor'] for p in named['public']['products']]


def test_all_family_and_query_scopes():
    def check(pair):
        family, query = pair
        s = scenario.generate_scenario({'family': family, 'query': query})
        assert s['bundle']['private_provenance']['family_scope'] == [family]
        assert sum(r['profile_id'] == SPECIALIST[family] for r in s['bundle']['public']['retailers']) >= 2
        assert 'request' not in s['bundle']['public']
        if query == 'average':
            model = s['task']['request']['lines'][0]['model']
            assert any(g['group_id'] == model['id'] for g in s['bundle']['public']['product_groups'])
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(check, [(f,q) for f in FAMILY_IDS for q in ('cheapest','fastest','average')]))


def test_random_queries_never_autofill_unrelated_baskets():
    for seed in range(60):
        task = scenario.sample_task(seed=seed, query='random')
        assert len(task['request']['lines']) == 1
        assert task['request']['lines'][0]['family_id'] in FAMILY_IDS
    for query in ('basket', 'split_basket'):
        with pytest.raises(ValueError, match='explicitly chosen'):
            scenario.sample_task(family='footwear', query=query)
        task = scenario.generate_scenario({'family': 'footwear,laptops,dog_food', 'query': query})
        assert len(task['task']['request']['lines']) == 3


@pytest.mark.parametrize('options', [
    {'world_options': {'focus_families': ['laptops']}},
    {'task_options': {'family': 'skincare'}},
    {'task_options': {'family': 'footwear'}, 'world_options': {'store_count': 1}},
    {'task_options': {'family': 'wine'}, 'world_options': {'config': {'family_weights': {'wine': 0}}}},
])
def test_conflicting_or_unsupported_configuration_is_not_silently_repaired(options):
    with pytest.raises(ValueError): scenario.generate_scenario(**options)
