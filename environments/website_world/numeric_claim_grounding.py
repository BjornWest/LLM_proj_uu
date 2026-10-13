"""Typed normalized numbers and exact quote provenance; no answer interpretation."""
from decimal import Decimal, InvalidOperation

from experiments.answer_grading.extraction import _quote


def validate_mean_claim(claim, answer):
    """Require a finite typed mean and its authentic quote, without prose parsing."""
    if claim['value'] is None:
        if claim['evidence'] is not None:
            raise ValueError('Absent claim must have null evidence')
        return
    if type(claim['value']) is not str:
        raise ValueError('Invalid extracted mean rating')
    try:
        amount = Decimal(claim['value'])
    except InvalidOperation:
        raise ValueError('Invalid extracted mean rating')
    if not amount.is_finite():
        raise ValueError('Nonfinite extracted mean rating')
    _quote(claim['evidence'], answer)


def undefined_rating_in_quote(evidence, answer):
    """Compatibility provenance check only; interpretation belongs to extractor."""
    _quote(evidence, answer)
    return True
