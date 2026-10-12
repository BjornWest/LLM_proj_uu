"""Task-owned normalized numeric values; no inference or native arithmetic."""
from decimal import Decimal, InvalidOperation
import re

from experiments.answer_grading.extraction import _decimal, _quote


def number_in_quote(expected, evidence, answer):
    """A whole numeral in the actual answer must fit inside the exact quote.

    Keep its sign/grouping even when the formatter quotes only part of a token.
    Decimal presentation may differ from the canonical structured claim.
    """
    _quote(evidence, answer)
    spans = [m.span() for m in re.finditer(re.escape(evidence), answer)]
    pattern = (r'(?<![\w.,+\-\u2212])(?:[+\-\u2212][ \u00a0\u202f]*)?'
               r'(?:\d{1,3}(?:[ \u00a0\u202f]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d+)*)'
               r'(?!\w|[.,]\d)')
    for match in re.finditer(pattern, answer):
        try:
            number = _decimal(match.group().replace('−', '-'))
        except InvalidOperation:
            continue
        if number == expected and any(q0 <= match.start() and match.end() <= q1 for q0, q1 in spans):
            return True
    return False


def validate_mean_claim(claim, answer):
    """Mechanical finite decimal and complete numeral grounding only."""
    if claim['value'] is None:
        return
    try:
        amount = Decimal(claim['value'])
    except InvalidOperation:
        raise ValueError('Invalid quoted mean rating')
    if not amount.is_finite():
        raise ValueError('Nonfinite quoted mean rating')
    if not number_in_quote(amount, claim['evidence'], answer):
        raise ValueError('Mean rating missing from its answer quote')


def undefined_rating_in_quote(evidence, answer):
    """Compatibility provenance check only; interpretation belongs to extractor.

    New native callers use shared semantic-field validation directly. This
    function proves an exact quote exists, not that its prose means undefined.
    """
    _quote(evidence, answer)
    return True
