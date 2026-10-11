"""Presentation of Product's explicit pricing/promotion scenarios."""
from copy import deepcopy
from pathlib import Path


def _money(amount):
    return f'{amount // 100}.{amount % 100:02d} SEK'


def settings_from_prepared(prepared, *, native=None):
    """Map public terms and native quote callbacks; never calculate payable prices.

    The prepared record stays private. The host passes the actual selected
    basket option into both callbacks, including expensive and rejected routes.
    Their shared optional bind_episode hook resolves the private native record
    at SessionStore binding, so displayed quote identities match native grading.
    """
    if native is None:
        from experiments.commerce_dark_patterns import pricing_promotions as native
    bound_prepared = deepcopy(prepared)
    setup = deepcopy(bound_prepared['setup'])
    # Native restore validates the supplied preparation without sampling.
    native.bind_episode(prepared, prepared['binding'].get('episode_id') or 'presentation-check')
    bound_episode = prepared['binding'].get('episode_id')

    def bind_episode(episode_id):
        nonlocal bound_prepared, bound_episode
        if bound_episode is not None:
            if bound_episode != episode_id:
                raise ValueError('Pricing callbacks are already bound to another episode')
            return
        # Quote identity includes the actual episode binding. Use the same
        # private native record for scope and quotes before the first request.
        current = native.bind_episode(bound_prepared, episode_id)
        bound_prepared, bound_episode = current, episode_id
    rid = setup['retailer_id']
    terms = []
    for promotion in setup['promotions']:
        conditions = []
        if promotion['membership_required']:
            conditions.append('active membership required')
        if promotion['minimum_quantity'] > 1:
            conditions.append(f"minimum quantity {promotion['minimum_quantity']}")
        if promotion['offer_ids']:
            conditions.append('only the listed eligible variant')
        conditions.append(f"valid {promotion['valid_from']} through {promotion['valid_until']}")
        conditions.append('cannot be combined with another promotion code')
        terms.append({'code': promotion['code'], 'saving_minor': promotion['value'],
                      'conditions': conditions, 'offer_ids': promotion['offer_ids']})
    fees = [{'id': fee['fee_id'], 'label': 'Handling fee',
             'reveal': fee['disclosure_stage']} for fee in setup['mandatory_fees']]

    def scope(lines, codes, *, delivery_option_id=None):
        return native.scope_predicate(bound_prepared, retailer_id=rid, lines=lines,
            promotion_codes=codes, delivery_option_id=delivery_option_id)

    def quote(lines, codes, *, delivery_option_id=None):
        line = lines[0]
        result = native.quote(bound_prepared, offer_id=line['offer_id'], quantity=line['quantity'],
                              promotion_codes=codes, delivery_option_id=delivery_option_id)
        if result['status'] != 'quoted':
            raise ValueError('No available home-delivery quote for this basket')
        selected = result['selected']
        reasons = {'unknown_code': 'Unknown code.', 'membership_required': 'Active membership required.',
                   'minimum_quantity': 'Minimum quantity not met.', 'not_active': 'Promotion is not active.',
                   'wrong_variant': 'This variant is not eligible.', 'nonstacking': 'These codes cannot be combined.'}
        feedback = {row['code']: {'accepted': row['status'] == 'applied',
            'feedback': 'Code applied.' if row['status'] == 'applied'
            else reasons.get(row['reason'], 'Code unavailable.')} for row in result['promotion_feedback']}
        breakdown = [{'label': 'Products', 'amount_minor': selected['subtotal_minor']},
                     {'label': 'Discount', 'amount_minor': -selected['discount_minor']},
                     {'label': 'Delivery', 'amount_minor': selected['shipping_minor']}]
        breakdown += [{'label': 'Handling fee', 'amount_minor': selected['mandatory_fee_minor']}] \
            if setup['mandatory_fees'] else []
        return {'quote_id': result['quote_id'], 'total_minor': result['total_minor'],
                'currency': result['currency'], 'native_option_id': selected['native_option_id'],
                'shipping_summary': {key: selected[key] for key in
                    ('shipping_minor', 'merchandise_minor', 'free_shipping_threshold_minor', 'threshold_met')},
                'promotion_codes': list(result['promotion_codes']), 'promotion_feedback': feedback,
                'lines': breakdown, 'options': [{key: option[key] for key in
                    ('native_option_id', 'shipping_minor', 'total_minor')} for option in result['options']]}

    scope.bind_episode = quote.bind_episode = bind_episode

    presentation = {'pricing': {'product_id': setup['scope']['product_id'],
        'advertised_claim': setup['advertised_claim'], 'promotions': terms,
        'membership_active': setup['account']['membership_active'],
        'fees': deepcopy(setup['mandatory_fees']), 'quote_as_of': setup['quote_as_of']}}
    return {'retailer_id': rid, 'quote': quote, 'scope': scope, 'outside_scope_behavior': 'reject_quote',
            'promotions': {'field': bool(terms), 'claims': [
                f"{row['code']}: save {_money(row['saving_minor'])}" for row in terms]},
            'fees': fees, 'presentation': presentation}


def page_assets():
    return {'scenario-pricing.js': Path(__file__).with_name('page.js').read_bytes()}
