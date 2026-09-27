"""Private, bounded reply mapping for the first manually reviewed shopping batch.

This is a deterministic English shoe-size responder, not an NLP user simulator.
Only the returned reply belongs in policy context. Matching metadata is host-side.
"""
from copy import deepcopy
import re

from .generator import digest

VERSION = 'manual-shopping-clarification-v1'
FALLBACK = 'I cannot add any more information on that. Please use the details I have already given you.'


def _personal_size_question(question):
    text = ' '.join(question.casefold().split())
    # Questions about inventory/prices are for the shops, not personal fit replies.
    if re.search(r'\b(stock|available|availability|price|cost|cheapest|retailer|inventory|budget)\b', text):
        return False
    size = re.search(r'\b(size|sizing)\b', text)
    personal = re.search(r'\b(you|your|yours|wear|need|usual|preferred|prefer)\b', text)
    short = re.fullmatch(r'(?:what|which)\s+(?:(?:shoe|eu|european)\s+)?size\??', text)
    ordering = re.search(r'\b(?:what|which)\b.*\bsize\b.*\b(?:should i|shall i)\b', text)
    return bool(size and (personal or short or ordering))


class FrozenClarificationResponder:
    """Host callback: question -> {reply, audit_id, matched, ...private metadata}.

The host must deliver only ``reply`` through ask_user, never serialize this object
or the input specification into the initial prompt or public tool schema. Repeated
questions yield the same factual reply. Unsupported questions do not reveal facts.
"""

    def __init__(self, specification):
        spec = deepcopy(specification)
        if spec.get('schema_version') != VERSION or not isinstance(spec.get('task_id'), str):
            raise ValueError('Invalid private clarification specification')
        facts = spec.get('facts')
        if not isinstance(facts, list) or len(facts) != 1:
            raise ValueError('First manual batch supports one hidden shoe-size fact')
        fact = facts[0]
        if (fact.get('field') != 'size_eu' or fact.get('match_rule') != 'personal_shoe_size_en_v1'
                or type(fact.get('value')) is not int or not 20 <= fact['value'] <= 55
                or not all(isinstance(fact.get(k), str) and fact[k] for k in ('id', 'line_id'))):
            raise ValueError('Invalid hidden shoe-size fact')
        expected = f'EU {fact["value"]}, please.'
        if fact.get('reply') != expected:
            raise ValueError('Clarification reply differs from its structured fact')
        self._spec = spec

    def __call__(self, question):
        if not isinstance(question, str) or not question.strip():
            raise ValueError('A nonempty user question is required')
        fact = self._spec['facts'][0]
        matched = _personal_size_question(question)
        result = {'reply': fact['reply'] if matched else FALLBACK, 'matched': matched,
                  'audit_id': 'clarification-' + digest([VERSION, self._spec, question, matched])[:24]}
        if matched:
            result.update(clarification_id=fact['id'], line_id=fact['line_id'], field=fact['field'])
        return result
