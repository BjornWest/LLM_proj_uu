import copy
from concurrent.futures import ThreadPoolExecutor

import pytest
from .catalog import FAMILIES, attribute_for
from .generator import atom, generate
from .semantics import BLOCKERS, RELATIONS, conflicts, entails, minimize, holds, review_catalog
from .clarification import answer_clarification, task_after_clarifications
from .oracle import grade_answer


def p(field, value, op='eq'):
    return {'field': field, 'value': value, 'operator': op}


def test_generic_contradictions_bounds_and_set_overlap():
    assert conflicts('laptops', [p('ram_gb', 32, 'ge'), p('ram_gb', 16, 'le')])
    assert conflicts('footwear', [p('size_eu', 40), p('size_eu', 42)])
    assert conflicts('moisturizers', [p('ingredients', 'glycerin', 'contains'), p('ingredients', 'glycerin', 'excludes')])
    assert not conflicts('moisturizers', [p('ingredients', 'glycerin', 'contains'), p('ingredients', 'lavender oil', 'excludes')])
    assert conflicts('board_games', [p('min_players', 6, 'ge'), p('max_players', 4, 'le')])
    assert conflicts('pet_harnesses', [p('chest_min_cm', 90), p('chest_max_cm', 60)])


def test_cookware_and_ssd_counterexamples():
    assert conflicts('cookware', [p('material', 'aluminium'), p('base', 'bare aluminium base'), p('induction', True)])
    assert not conflicts('cookware', [p('material', 'aluminium'), p('induction', True)])
    assert not entails('cookware', [p('material', 'stainless steel')], p('induction', True))
    assert entails('cookware', [p('base', 'magnetic stainless base')], p('induction', True))
    assert entails('cookware', [p('material', 'cast iron')], p('induction', True))
    assert conflicts('ssd', [p('form_factor', '2.5-inch'), p('interface', 'NVMe PCIe 4.0')])
    assert entails('ssd', [p('form_factor', '2.5-inch')], p('interface', 'SATA'))


def test_implications_and_equivalent_minimal_constraints():
    assert conflicts('dog_food', [p('recipe', 'chicken'), p('ingredients', 'chicken', 'excludes')])
    assert not entails('dog_food', [p('recipe', 'salmon')], p('ingredients', 'chicken', 'excludes'))
    assert entails('chargers', [p('protocols', 'USB PD PPS', 'contains')], p('protocols', 'USB PD', 'contains'))
    reduced, removed = minimize('laptops', [p('ram_gb', 32, 'ge'), p('ram_gb', 16, 'ge'), p('ram_gb', 64, 'le')])
    assert len(reduced) == 2 and len(removed) == 1
    for family, relations in RELATIONS.items():
        for relation in relations:
            for row in relation['rows']:
                original = [p(k, v) for k, v in zip(relation['fields'], row)]
                minimal, redundant = minimize(family, original)
                for other in relation['rows']:
                    facts = dict(zip(relation['fields'], other))
                    assert all(holds(x, facts[x['field']]) for x in original) == all(holds(x, facts[x['field']]) for x in minimal)
                assert all(entails(family, minimal, r['predicate']) for r in redundant)


def _hidden_family(family):
    for seed in range(12):
        b = generate(seed, family, hidden='blocker', memory='mixed', requirements=6)
        assert b['hidden_user_specifications']
        fields = []
        for h in b['hidden_user_specifications']:
            field = h['predicate']['field']
            fields.append((h['line_id'], field))
            assert field in BLOCKERS[family] and field not in ('colour', 'ingredients', 'materials')
            line = next(l for l in b['initial_accessible_task']['lines'] if l['id'] == h['line_id'])
            assert not any(p['field'] == field for p in line['requirements'])
            assert not entails(family, line['requirements'], h['predicate'])
            assert not any(m['predicate']['field'] == field for m in b['memory_facts'])
            assert answer_clarification(b, h['line_id'], field) == {'matched': True, 'reply': h['reply']}
            assert answer_clarification(b, h['line_id'], 'anything_else')['matched'] is False
        assert task_after_clarifications(b, []) == b['initial_accessible_task']
        assert task_after_clarifications(b, fields) == b['resolved_task']
        assert grade_answer(b['resolved_task'], [], {'status': 'selection'}, coverage_complete=True, effects=[])['structured_claims_correct'] is None
    return family


def test_hidden_allowlist_across_families():
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert set(pool.map(_hidden_family, BLOCKERS)) == set(BLOCKERS)
    with pytest.raises(ValueError, match='no authored blocking'):
        generate(0, 'moisturizers', hidden='blocker')
    assert set(review_catalog()) == set(FAMILIES)


def test_wording_variants_preserve_semantics_and_single_message():
    bundles = [generate(4, 'footwear', hidden='blocker', memory='none', requirements=5, prose_seed=i) for i in range(10)]
    assert len({b['semantic_sha256'] for b in bundles}) == 1
    assert len({b['public']['user_message'] for b in bundles}) >= 8
    for b in bundles:
        assert '\n' not in b['public']['user_message']
        assert 'Do not purchase' not in b['public']['user_message']
        assert ''.join(s['text'] for s in b['authoring']['message_segments']) == b['public']['user_message']
        assert set(b['public']) == {'user_message', 'memories', 'environment_context'}
        assert not any('size_eu' in source for s in b['authoring']['message_segments'] for source in s['sources'])
