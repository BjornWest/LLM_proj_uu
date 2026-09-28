from copy import deepcopy
import json

from .extraction import messages, validate_claims
from .robustness import cases, compare
from .test_grading import blank


def fixtures():
    public = {'user_message': 'Find shoes', 'memories': {'profile': []}}
    return public, cases(public, '[product](https://shop.example/products/a) [quote](https://shop.example/quote?a=1)')


def test_fixture_isolation_and_private_expectations():
    public, rows = fixtures()
    assert len(rows) == 10 and len({r['id'] for r in rows}) == 10
    assert public['memories']['profile'] == []
    assert rows[0]['public_task']['memories']['profile'] == []
    assert rows[1]['public_task']['memories']['profile']
    for row in rows:
        payload = json.loads(messages(row['public_task'], row['answer'])[1]['content'])
        assert set(payload) == {'public_task', 'final_answer'}
        assert 'expected' not in payload and 'oracle_checks' not in payload


def test_assertions_distinguish_missing_null_and_bool():
    assert not compare({}, {'total': None})['total']['passed']
    assert compare({'total': None}, {'total': None})['total']['passed']
    assert not compare({'count': True}, {'count': 1})['count']['passed']
    assert not compare({'total': None}, {'total.amount': None})['total.amount']['passed']


def test_context_canary_is_absent_from_answer():
    _, rows = fixtures()
    row = rows[1]
    for token in ('571.25', 'SAVE1-25', 'secret-context-sku'):
        assert token in json.dumps(row['public_task']) and token not in row['answer']


def test_literal_grounding_does_not_prove_semantic_attribution():
    # Deliberately record a validator limitation. The authored suite, not lexical
    # matching, must detect a price lifted from a rejected alternative.
    answer = 'I recommend this. Another rejected offer costs 352.00 SEK.'
    claims = blank()
    claims['total'] = {'amount': '352.00', 'currency': 'SEK', 'evidence': '352.00 SEK'}
    assert validate_claims(claims, answer) == claims
    assert not compare(claims, {'total': None})['total']['passed']
