"""Task-owned normalized numeric values; no inference or native arithmetic."""
from decimal import InvalidOperation
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


def undefined_rating_in_quote(evidence, answer):
    """Explicit undefined/no-ratings wording, retaining nearby negation."""
    _quote(evidence, answer)
    clauses = []
    for match in re.finditer(re.escape(evidence), answer):
        q0, q1 = match.span()
        left = max(answer.rfind(mark, 0, q0) for mark in ('.', ';', '!', '?', '\n')) + 1
        right = min([pos for mark in ('.', ';', '!', '?', '\n')
                     if (pos := answer.find(mark, q1)) >= 0] or [len(answer)])
        clauses.append(answer[left:right])
    context = ' '.join(' '.join(clauses).casefold().split())
    quote = ' '.join(evidence.casefold().split())
    phrase = r'\b(?:undefined|not defined|no observations|no (?:published |star )?ratings)\b'
    # The accepted phrases contain their own lexical negatives ("not defined",
    # "no ratings"). Mask those before looking for an outer denial, retaining
    # the containing clause even when the formatter crops its evidence quote.
    remainder = re.sub(phrase, '\x00', context)
    negator = (r"not|never|no longer|cannot|"
               r"(?:isn|aren|wasn|weren|doesn|don|can|couldn)['’]t")
    gap = r"(?:(?:[\s,:\"'’“-]+)(?!(?:but|because|so)\b)\w+)*[\s,:\"'’“-]*"
    # Deny the assertion itself or its truth, not a different preceding predicate:
    # "cannot be computed because there are no ratings" supports an undefined mean.
    truth_denial = (r"(?:not|never|(?:isn|aren|wasn|weren)['’]t)\s+(?:true|correct|accurate|the case)|"
                    r"(?:cannot|(?:can|couldn)['’]t)\s+(?:be\s+)?(?:true|correct|accurate)|"
                    r"(?:false|untrue|incorrect)\s+(?:that|to (?:say|claim|assert))")
    contradicted = re.search(
        r"\b(?:" + negator + r")[\s,:\"'’“-]*(?:(?:\w+ly|be|been|being|even|ever|yet|very|quite|rather|at all|close to)\s+){0,3}\x00|"
        r"\b(?:" + truth_denial + r")" + gap + r"\x00|"
        r"\x00[\"'’”]*\s+(?:(?:is|was|would be)\s+(?:false|untrue|incorrect|not (?:true|correct|accurate))|"
        r"(?:isn|wasn)['’]t\s+(?:true|correct|accurate))\b", remainder)
    contradicted = contradicted or re.search(
        r"\b(?:mean[ _])?undefined[\"']?\s*[:=]\s*false\b", context)
    explicit = re.search(phrase, quote)
    return bool(explicit) and not contradicted
