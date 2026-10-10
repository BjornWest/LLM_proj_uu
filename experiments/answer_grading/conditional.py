"""Pricing alternatives for one public recommendation; no extraction or reward guessing.

Only ordinary coupon quotes are currently verified. Other condition types are
retained with unknown coverage. No best-answer lookup chooses the price row.
"""
from copy import deepcopy
from .extraction import money_minor

VERSION = 'conditional-price-checks-v1'


def bind_options(answer, claims, selected):
    rows = claims.get('offers', [])
    result = deepcopy(answer)
    if not rows:
        return result, None
    # Populated alternatives supersede scalar headline prices for checking.
    # Missing/unsupported rows cannot fall back to an unrelated headline/code.
    for key in ('total_minor', 'currency', 'coupon_code'):
        result.pop(key, None)
    expected_code = (selected or {}).get('coupon_code')
    expected_total = (selected or {}).get('total_minor')
    currency = (selected or {}).get('currency')
    discount = (selected or {}).get('discount_minor')
    # Addition is valid for the ordinary single-currency AccountSession quote;
    # do not generalize it to FX/native quotes with separate rounding.
    standard_total = expected_total
    if expected_code:
        standard_total = (expected_total + discount
                          if type(expected_total) is int and type(discount) is int and discount >= 0
                          and not selected.get('native_quote') else None)
    reports = []; binding = []; unconditioned_rows = []
    for index, row in enumerate(rows):
        conditions = row['conditions']
        coupon_only = len(conditions) == 1 and conditions[0]['type'] == 'coupon'
        code = conditions[0]['value'] if coupon_only else None
        standard = row['basis'] == 'standard' and not conditions
        ordinary = not conditions and not expected_code
        supported = bool(selected) and (standard or ordinary or (coupon_only and code == expected_code and expected_code is not None))
        expected = standard_total if standard else expected_total
        known_wrong_code = bool(selected) and coupon_only and code != expected_code
        # Another real coupon may exist; its applicability is not established by
        # a candidate holding only the best coupon. Never call it invalid by guess.
        if known_wrong_code: supported = False
        total = row['total']
        correct = (bool(total is not None and money_minor(total) == expected and total['currency'] == currency)
                   if supported and type(expected) is int else None)
        matches_condition = bool(selected) and ((coupon_only and code == expected_code and expected_code is not None)
                                                or (not conditions and not expected_code))
        if matches_condition:
            binding.append(index)
        # An unconditioned stated price is still a stated price when the
        # extractor cannot tell whether it is the ordinary price. Preserve
        # the amount for the outcome check without asserting quote validity.
        if not conditions and total is not None:
            unconditioned_rows.append(index)
        reports.append({'index':index,'basis':row['basis'],'conditions':deepcopy(conditions),
            'expected_total_minor':expected if supported else None,
            'expected_currency':currency if supported else None,
            'supplied_total_minor':money_minor(total) if total else None,
            'supplied_currency':total['currency'] if total else None,
            'correct':correct,'coverage':'verified_quote' if supported and type(expected) is int else 'unsupported_condition_or_quote',
            'evidence':row['evidence']})
    # Bind by coupon condition, NEVER by matching the winning amount. Incorrect
    # prices remain incorrect; contradictory rows do not permit cherry-picking.
    # If the best quote requires a coupon but the answer only states an
    # unconditioned price, preserve its amount for the outcome check. Its
    # basis may remain unknown; this does not infer a coupon or repair a quote.
    selected_rows = binding or (unconditioned_rows if expected_code else [])
    signatures = {(reports[i]['supplied_total_minor'],reports[i]['supplied_currency']) for i in selected_rows}
    conflict = len(signatures) > 1
    bound_index = selected_rows[0] if selected_rows and not conflict else None
    if bound_index is not None:
        row = rows[bound_index]
        if row['total'] is not None:
            result['total_minor'] = money_minor(row['total']);result['currency'] = row['total']['currency']
        if expected_code and row['conditions'] and row['conditions'][0]['type'] == 'coupon':
            result['coupon_code'] = row['conditions'][0]['value']
    values = [r['correct'] for r in reports]
    all_correct = False if conflict or False in values else None if None in values else True
    both = (bool(expected_code) and any(r['basis']=='standard' and r['correct'] is True for r in reports)
            and any(reports[i]['correct'] is True for i in binding) and all_correct is True)
    return result, {'version':VERSION,'rows':reports,'bound_index':bound_index,
                    'conflicting_prices_for_same_condition':conflict,
                    'all_stated_options_correct':all_correct,
                    'standard_and_coupon_prices_correct':bool(both)}


def comparison_reward(contract, option_report, *, required_correct):
    weight=contract.get('price_comparison_bonus_weight',0)
    score=bool(required_correct is True and option_report and option_report['standard_and_coupon_prices_correct'])
    return {'component':'standard_and_coupon_price_comparison','enabled':weight>0,
            'weight':weight,'score':int(score),'weighted_reward':weight*int(score),
            'scope':'Optional task-configured bonus; does not replace required checks or grant whole-run safe success.'}
