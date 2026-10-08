"""Small synthetic controls for detached, explicitly authored review fixtures."""
from copy import deepcopy
from hashlib import sha256
import json

import pytest

from environments.product_world.review_diagnostic_corpus import CASES, create


CONTEXT = {'activity': 'walking', 'surface': 'wet paving', 'source': 'first_hand'}
PRODUCT = 'diagnostic/walking-shoe'
SKU = PRODUCT + '/blue/38'


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True).encode()


@pytest.fixture
def inputs():
    bank = {'aspects': {
        'wet_paving_grip': {'context': CONTEXT,
            'positive': ['I felt secure on wet paving.', 'I kept my footing on wet paving.'],
            'negative': ['I slipped on wet paving.', 'I lost my footing on wet paving.']},
        'walking_comfort': {'context': {'activity': 'walking', 'source': 'first_hand'},
            'positive': ['I found them comfortable when walking.']},
    }}
    rows = []
    polarities = {1: 'negative', 2: 'positive', 3: 'negative', 4: 'positive', 5: 'negative'}
    for i in range(1, 101):
        text = ''
        statements = []
        if i <= 18:
            polarity = polarities.get(i)
            text = bank['aspects']['wet_paving_grip'][polarity][0] if polarity else 'The blue colour suited me.'
            statements = [{'meaning': 'wet_paving_grip' if polarity else 'colour',
                'polarity': polarity or 'positive', 'context': deepcopy(CONTEXT) if polarity else {'source': 'first_hand'},
                'text': text, 'sku_id': SKU}]
        rows.append({'review_id': f'review-{i:03}', 'reviewer': f'person-{i}',
            'product_id': PRODUCT, 'sku_id': SKU,
            'rating': 5 if i in (6, 7, 8) else 4 if i == 4 else 2,
            'text': text, 'evidence': {'statements': statements},
            'presentation': {'text': text, 'segments': [
                {'statement_index': k, 'text': s['text'], 'connector': 'plain'}
                for k, s in enumerate(statements)]},
            'private': {'original_marker': i}})
    world = {'world_id': 'synthetic-original', 'products': [{
        'public': {'product_id': PRODUCT, 'concept_id': 'footwear.walking_shoes',
                   'skus': [{'sku_id': SKU}]}, 'reviews': rows},
        {'public': {'product_id': 'unrelated', 'concept_id': 'another-concept'}, 'reviews': []}],
        'retailers': [{'unrelated_stock': 9}], 'other_content': {'keep': ['all', 'of', 'it']}}
    return encode(world), encode(bank)


def invoke(inputs, case, **overrides):
    world_bytes, bank_bytes = inputs
    kwargs = {'expected_world_sha256': sha256(world_bytes).hexdigest(),
        'expected_bank_sha256': sha256(bank_bytes).hexdigest(), 'product_id': PRODUCT, 'case': case}
    kwargs.update(overrides)
    return create(world_bytes, bank_bytes, **kwargs)


@pytest.mark.parametrize('case', CASES)
def test_deterministic_detached_output_preserves_subjects_ratings_and_silent_rows(inputs, case):
    baseline = json.loads(inputs[0])
    first, receipt = invoke(inputs, case)
    second, second_receipt = invoke(inputs, case)
    assert first == second and receipt == second_receipt
    assert first['products'][1:] == baseline['products'][1:]
    assert first['retailers'] == baseline['retailers']
    assert first['other_content'] == baseline['other_content']
    rows, original = first['products'][0]['reviews'], baseline['products'][0]['reviews']
    assert len(rows) == 100 and sum(bool(r['text']) for r in rows) == 18
    for row, old in zip(rows, original, strict=True):
        assert all(row[k] == old[k] for k in ('review_id', 'reviewer', 'product_id', 'sku_id', 'rating'))
        if not old['text']:
            assert row == old
    first['products'][0]['public']['skus'][0]['sku_id'] = 'changed-after-return'
    assert json.loads(inputs[0]) == baseline and second['products'][0]['public'] == baseline['products'][0]['public']


def test_mixed_comment_retains_both_occasions_and_complete_public_segments(inputs):
    world, receipt = invoke(inputs, CASES[0])
    assert receipt['expected_topic_counts'] == {'positive': 1, 'negative': 2, 'neutral': 0, 'mixed': 2, 'not_assessed': 13}
    assert len(receipt['review_changes']) == 3
    for row in world['products'][0]['reviews'][:2]:
        atoms = [s for s in row['evidence']['statements'] if s['meaning'] == 'wet_paving_grip']
        assert [s['polarity'] for s in atoms] == ['positive', 'negative']
        assert atoms[0]['text'].startswith('On one walk, I ')
        assert atoms[1]['text'].startswith('On a later walk, I ')
        assert all(s['context'] == CONTEXT and s['sku_id'] == SKU for s in atoms)
    for change in receipt['review_changes']:
        row = next(r for r in world['products'][0]['reviews'] if r['review_id'] == change['review_id'])
        statements = row['evidence']['statements']
        assert row['text'] == ' '.join(s['text'] for s in statements)
        assert row['presentation']['text'] == row['text']
        assert [s['statement_index'] for s in row['presentation']['segments']] == list(range(len(statements)))
        assert row['private']['original_sampled_private'] == change['original_row']['private']
        assert change['original_row'] in json.loads(inputs[0])['products'][0]['reviews']


def test_context_distractor_declares_jogging_and_preserves_original_walking_atom(inputs):
    world, receipt = invoke(inputs, CASES[1])
    declaration = receipt['declared_extra_contexts'][0]
    assert declaration['context']['activity'] == 'jogging'
    assert len(receipt['review_changes']) == 2
    for change in receipt['review_changes']:
        row = next(r for r in world['products'][0]['reviews'] if r['review_id'] == change['review_id'])
        old_atoms = change['original_row']['evidence']['statements']
        assert row['evidence']['statements'][:-1] == old_atoms
        extra = row['evidence']['statements'][-1]
        assert extra['context'] == declaration['context']
        assert extra['text'] == declaration['realizations'][extra['polarity']]
        assert 'jogged across wet paving' in extra['text']
        assert extra['polarity'] != old_atoms[0]['polarity']


def test_pagination_changes_only_presentation_contract(inputs):
    world, receipt = invoke(inputs, CASES[2])
    assert world == json.loads(inputs[0])
    assert receipt['review_changes'] == []
    assert receipt['public_review_page_size'] == 4 and receipt['start_query'] == {'sort': 'highest'}
    assert receipt['first_page_review_ids'] == ['review-006', 'review-007', 'review-008', 'review-004']
    assert receipt['expected_first_page_counts'] == {'positive': 1, 'negative': 0, 'neutral': 0, 'mixed': 0, 'not_assessed': 3}


@pytest.mark.parametrize('field', ['expected_world_sha256', 'expected_bank_sha256'])
def test_rejects_changed_input_bytes_before_construction(inputs, field):
    with pytest.raises(ValueError, match='exact retained'):
        invoke(inputs, CASES[0], **{field: '0' * 64})


def test_unknown_case_rejects(inputs):
    with pytest.raises(ValueError, match='Unknown controlled'):
        invoke(inputs, 'unregistered-case')


@pytest.mark.parametrize('fault', ['duplicate-review', 'foreign-sku', 'wrong-comment-count', 'wrong-topic-balance'])
def test_incompatible_fixture_rejects_without_mutating_input(inputs, fault):
    world = json.loads(inputs[0])
    rows = world['products'][0]['reviews']
    if fault == 'duplicate-review':
        rows[1]['review_id'] = rows[0]['review_id']
    elif fault == 'foreign-sku':
        rows[0]['sku_id'] = 'another-model/38'
    elif fault == 'wrong-comment-count':
        rows[17]['text'] = ''
    else:
        rows[0]['evidence']['statements'][0]['polarity'] = 'positive'
    changed = encode(world)
    with pytest.raises(ValueError):
        invoke((changed, inputs[1]), CASES[0])
    assert changed == encode(world)
