from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from environments.website_world import catalog_memory as memory, memory_offer_task as api
from environments.website_world.catalog_predicates import PredicateSet
from environments.website_world.feature_offer_task import FieldInventory
from environments.website_world.memory_offer_grading import MemoryOfferGrader
from environments.website_world.test_feature_offer_task import fixture as feature_fixture
from environments.website_world.test_listed_offer_grading import answer


def record(value=42, *, subject='self', field='sku.size_eu', scope=None, id='size', channel='profile', operator='eq', **extra):
    return {'id': id, 'subject': subject, 'scope': scope or {'concept_ids': ['footwear.walking_shoes']},
            'channel': channel, 'predicates': [{'field': field, 'operator': operator, 'value': value, **extra}]}


def fixture(records=None, explicit=None, recipient='self'):
    w, _, _, b, i = feature_fixture()
    spec = {'kind': api.KIND, 'concept_id': i.concept_id, 'recipient': recipient,
            'memory_records': records or [record()], 'predicates': explicit or []}
    t = api.make(w, spec, inventory=i)
    return w, t, api.reference(w, t, inventory=i), b, i


def test_native_outcome_uses_memory_without_repeating_it_as_current_request():
    w, t, r, b, i = fixture()
    assert '42' not in t['user_message'] and '42' in t['memories'][0]
    assert t['selection_task']['predicates'] == [record()['predicates'][0]]
    assert len(r['selection_reference']['winners']) == 4
    grade = MemoryOfferGrader(w, t, r, b, inventory=i).grade(*reversed(answer()))
    assert grade['structured_claims_correct']
    assert grade['grading_version'] == 'website-memory-feature-grading-v1'
    assert 'does not establish actual memory' in grade['limitations'][-1]


def test_explicit_same_field_override_is_local_and_retains_provenance():
    original = record(43); before = deepcopy(original)
    _, t, r, _, _ = fixture(records=[original], explicit=[record(42)['predicates'][0]])
    assert original == before and t['memory_records'][0] == before
    assert '42' in t['user_message'] and '43' in t['memories'][0]
    assert t['memory_resolution']['provenance'][0]['status'] == 'overridden_by_request'
    assert len(r['selection_reference']['winners']) == 4


def test_override_is_per_field_and_can_replace_default_operator():
    _, t, _, _, _ = fixture(records=[record(43, operator='ge'), record('olive', id='colour', field='sku.colour')],
                            explicit=[record(42)['predicates'][0]])
    assert t['selection_task']['predicates'] == [record('olive', field='sku.colour')['predicates'][0], record()['predicates'][0]]


def test_self_defaults_do_not_transfer_to_known_other_recipient():
    records = [record(43), record(42, subject='alex', id='alex-size', channel='episodic')]
    _, t, r, _, _ = fixture(records=records, recipient='alex')
    assert 'This is for alex.' in t['user_message'] and len(t['memories']) == 2
    assert [p['status'] for p in t['memory_resolution']['provenance']] == ['irrelevant_recipient', 'active']
    assert len(r['selection_reference']['winners']) == 4


def test_other_scope_is_structurally_checked_but_not_used():
    other = record('M', field='sku.size_label', scope={'concept_ids': ['tops.t_shirts']}, id='shirt-size')
    _, t, _, _, _ = fixture(records=[record(), other])
    assert t['memory_resolution']['provenance'][1]['status'] == 'irrelevant_scope'
    assert 'M' in t['memories'][1]


@pytest.mark.parametrize('recipient', [None, 'unspecified'])
def test_unknown_recipient_is_clarification_not_no_stock(recipient):
    with pytest.raises(memory.ClarificationRequired, match='recipient'): fixture(recipient=recipient)


@pytest.mark.parametrize('second', [record(43, id='second'), record(42, id='second', operator='ne')])
def test_conflicting_applicable_defaults_require_clarification(second):
    with pytest.raises(memory.ClarificationRequired) as error:
        fixture(records=[record(), second])
    assert error.value.fields == ('sku.size_eu',)


def test_duplicate_memory_meaning_deduplicates_without_losing_provenance():
    _, t, _, _, _ = fixture(records=[record(), record(id='second')])
    assert len(t['memory_resolution']['resolved_predicates']) == 1
    assert len(t['memory_resolution']['provenance']) == 2


@pytest.mark.parametrize('corruption', ['duplicate_id', 'unit', 'type', 'scope', 'inactive_object', 'inactive_nan', 'inactive_unit'])
def test_malformed_record_rejects(corruption):
    records = [record()]
    if corruption == 'duplicate_id': records.append(record())
    elif corruption == 'unit': records[0]['predicates'][0]['unit'] = 'cm'
    elif corruption == 'type': records[0]['predicates'][0]['value'] = True
    elif corruption == 'scope': records[0]['scope']['concept_ids'] = ['unadopted.concept']
    elif corruption == 'inactive_object': records.append(record({'nested': 42}, subject='alex', id='inactive'))
    elif corruption == 'inactive_nan': records.append(record(float('nan'), subject='alex', id='inactive'))
    else: records.append(record(42, subject='alex', id='inactive', unit='cm'))
    with pytest.raises(ValueError): fixture(records=records)


def test_shared_apparel_default_has_one_record_and_explicit_unisex_allowance():
    i = FieldInventory('tops.t_shirts')
    shared = record(['women', 'unisex'], field='product.facts.market_range', operator='in',
                    scope={'domain': 'clothing_footwear'})
    r = memory.resolve(recipient='self', concept_id=i.concept_id, explicit=[], records=[shared], inventory=i)
    assert len(r['records']) == 1 and r['resolved_predicates'][0]['value'] == ['women', 'unisex']
    assert memory.applies(shared['scope'], 'footwear.walking_shoes')
    assert not memory.applies(shared['scope'], 'fragrance.eau_de_parfum')
    assert not memory.applies(shared['scope'], 'packs.hiking_packs')
    assert not memory.applies(shared['scope'], 'sleeping_bags.backpacking')
    p = PredicateSet(i.fields, r['resolved_predicates'])
    for value, state in [('men', 'mismatch'), ('women', 'match'), ('unisex', 'match')]:
        result = p.evaluate({'product_id': 'p', 'facts': {'market_range': value}}, {'product_id': 'p'},
                           catalog_status={'product.facts.market_range': 'known'}, sku_status={})
        assert result['state'] == state
    assert p.evaluate({'product_id': 'p', 'facts': {}}, {'product_id': 'p'},
                      catalog_status={}, sku_status={})['state'] == 'indeterminate'


def test_shared_domain_does_not_invent_undeclared_footwear_range():
    i = FieldInventory('footwear.walking_shoes')
    shared = record('women', field='product.facts.market_range', scope={'domain': 'clothing_footwear'})
    with pytest.raises(ValueError, match='declared'):
        memory.resolve(recipient='self', concept_id=i.concept_id, explicit=[], records=[shared], inventory=i)


def test_shared_domain_rejects_universal_sizes():
    with pytest.raises(ValueError, match='market-range'):
        fixture(records=[record(scope={'domain': 'clothing_footwear'})])


@pytest.mark.parametrize('what', ['words', 'resolution', 'reference', 'recipient', 'selection'])
def test_source_resolution_and_public_prose_tampering_rejects(what):
    w, t, r, b, i = fixture()
    if what == 'words': t['memories'][0] = 'I wear EU 43.'
    elif what == 'resolution': t['memory_resolution']['resolved_predicates'][0]['value'] = 43
    elif what == 'reference': r['selection_reference']['minimum_price_minor'] = 1
    elif what == 'recipient': t['recipient'] = 'alex'
    else: t['selection_task']['predicates'][0]['value'] = 43
    with pytest.raises(ValueError): MemoryOfferGrader(w, t, r, b, inventory=i)


def test_wrong_sku_not_repaired_from_memory_and_missing_size_stays_ambiguous():
    w, t, r, b, i = fixture(); g = MemoryOfferGrader(w, t, r, b, inventory=i)
    assert not g.grade(*reversed(answer(size='43')))['structured_claims_correct']
    text, claims = answer(); claims['variant']['size_eu'] = {'value': None, 'evidence': None}
    assert not g.grade(claims, text)['structured_claims_correct']


def test_formatter_receives_only_public_memory_and_contract(tmp_path):
    from experiments.answer_grading import task_answer
    w, t, r, b, i = fixture(); g = MemoryOfferGrader(w, t, r, b, inventory=i)
    text, claims = answer(); events = []
    class Backend:
        def complete(self, messages):
            events.append(messages)
            public = messages[1]['content']
            assert t['memories'][0] in public
            assert 'memory_resolution' not in public and 'selection_reference' not in public
            assert 'predicate_evaluations' not in public and '74000' not in public
            content = json.dumps(claims)
            return SimpleNamespace(text=content, request={'messages': messages}, raw={
                'model': 'scripted', 'provider': 'offline', 'usage': {},
                'choices': [{'finish_reason': 'stop', 'message': {'content': content}}]})
    grade = task_answer.extract_and_grade(g, {'user_message': t['user_message'], 'memories': t['memories']},
                                         text, tmp_path/'extraction', Backend())
    assert grade['structured_claims_correct'] and len(events) == 1
    assert grade['grading_version'] == 'website-memory-feature-grading-v1'


@pytest.mark.parametrize('kind,operators,bad', [
    ('number', [('ge', 3), ('lt', 3)], True),
    ('number', [('ge', 3), ('le', 3)], False),
    ('number', [('ge', 3), ('le', 3), ('ne', 3)], True),
    ('number', [('gt', 3), ('lt', 4)], False),
    ('integer', [('gt', 3), ('lt', 4)], True),
    ('integer', [('ge', 3), ('le', 4), ('not_in', [3, 4])], True),
    ('integer', [('ge', 3), ('le', 5), ('not_in', [3, 4])], False),
    ('enum', [('in', ['a', 'b']), ('not_in', ['a', 'b'])], True),
    ('enum', [('in', ['a', 'b']), ('ne', 'a')], False),
    ('boolean', [('ne', True), ('ne', False)], True),
    ('set', [('contains', 'a'), ('excludes', 'a')], True),
    ('set', [('contains', 'a'), ('excludes', 'b')], False),
])
def test_local_contradiction_detector_does_not_enumerate_product_population(kind, operators, bad):
    definition = {'type': kind}
    if kind == 'enum': definition['values'] = ['a', 'b', 'c']
    if kind == 'set': definition['items'] = {'type': 'string'}
    predicates = [{'field': 'product.facts.x', 'operator': op, 'value': value} for op, value in operators]
    PredicateSet({'product.facts.x': definition}, predicates)
    assert bool(memory.conflicts({'product.facts.x': definition}, predicates)) == bad


def test_sampler_bounds_do_not_turn_unlikely_requirements_into_clarification():
    definition = {'type': 'integer', 'min': 1, 'max': 5}
    predicates = [{'field': 'product.facts.x', 'operator': 'ge', 'value': 99}]
    PredicateSet({'product.facts.x': definition}, predicates)
    assert memory.conflicts({'product.facts.x': definition}, predicates) == []
