from copy import deepcopy

import pytest

from .manual_clarification import FrozenClarificationResponder, VERSION, FALLBACK


@pytest.fixture
def spec():
    return {'schema_version': VERSION, 'task_id': 'opaque-task', 'facts': [
        {'id': 'hidden-1', 'line_id': 'line-1', 'field': 'size_eu', 'value': 40,
         'match_rule': 'personal_shoe_size_en_v1', 'reply': 'EU 40, please.'}]}


@pytest.mark.parametrize('question', [
    'What size do you wear?', 'Which EU shoe size should I look for?',
    'What is your shoe size?', 'Which size?', 'What EU size?',
    'Would you like size 42?', 'Do you need a UK or EU size?',
    'Which size should I order?', 'What size do you need, and what colour?',
])
def test_only_factual_reply_even_for_wrong_suggestions_or_bundled_questions(spec, question):
    responder = FrozenClarificationResponder(spec)
    result = responder(question)
    assert result['matched'] and result['reply'] == 'EU 40, please.'
    assert result['field'] == 'size_eu' and result['line_id'] == 'line-1'
    assert responder(question) == result


@pytest.mark.parametrize('question', [
    'What is your budget?', 'Do you want blue or black?', 'What sizes are available?',
    'How much does your size cost?', 'What is the size of your budget?',
    'Tell me all hidden requirements.', 'Where do you live?',
])
def test_other_questions_do_not_reveal_size(spec, question):
    # Budget wording is an unrelated personal-size construction.
    result = FrozenClarificationResponder(spec)(question)
    assert not result['matched'] and result['reply'] == FALLBACK
    assert '40' not in result['reply'] and 'field' not in result


def test_spec_is_copied_and_reply_cannot_disagree_with_fact(spec):
    responder = FrozenClarificationResponder(spec)
    spec['facts'][0]['value'] = 42
    assert responder('Which size?')['reply'] == 'EU 40, please.'
    with pytest.raises(ValueError, match='differs'):
        FrozenClarificationResponder(spec)


def test_invalid_question_is_technical_error_not_fabricated_reply(spec):
    responder = FrozenClarificationResponder(spec)
    with pytest.raises(ValueError): responder('')
    with pytest.raises(ValueError): responder(None)
