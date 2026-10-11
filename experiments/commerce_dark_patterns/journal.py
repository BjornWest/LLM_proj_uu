"""One lossless host journal boundary, with projections to native family inputs.

The original journal is retained by the automatic adapter. Projection renumbers
filtered events, recording journal_seq; it never invents an action or completion.
"""
from copy import deepcopy
import json

VERSION = 'website-commerce-session-journal-v1'
KINDS = {'cookie_dialog', 'cookie_save', 'newsletter_change', 'extras_change',
    'site_preselect', 'basket_change', 'promotion_apply', 'promotion_remove',
    'delivery_select', 'checkout_enter', 'checkout_leave', 'order_submit'}
COMMITS = {'cookie_save', 'order_submit'}
PURPOSES = {'analytics', 'personalisation', 'marketing'}


class JournalError(ValueError):
    """Missing, incomplete or contradictory host evidence, not a task failure."""


def _require(condition, message):
    if not condition:
        raise JournalError(message)


def _preferences(value):
    _require(type(value) is dict and set(value) == PURPOSES
             and all(type(v) is bool for v in value.values()), 'invalid_cookie_preferences')


def _lines(value):
    _require(type(value) is list, 'invalid_basket')
    for row in value:
        _require(type(row) is dict and set(row) == {'offer_id', 'quantity'}
            and type(row['offer_id']) is str and bool(row['offer_id'])
            and type(row['quantity']) is int and row['quantity'] > 0, 'invalid_basket_line')
    ids = [r['offer_id'] for r in value]
    _require(ids == sorted(set(ids)), 'noncanonical_basket')


def _state(value):
    keys = {'cookie', 'newsletter', 'extras', 'basket', 'promotion_codes',
            'delivery_option_id', 'quote', 'checkout', 'committed'}
    _require(type(value) is dict and set(value) == keys, 'incomplete_host_state')
    cookie = value['cookie']
    _require(type(cookie) is dict and set(cookie) == {'decided', 'preferences', 'pending'}
             and type(cookie['decided']) is bool, 'invalid_cookie_state')
    _preferences(cookie['preferences'])
    if cookie['pending'] is not None:
        _preferences(cookie['pending'])
    _require(type(value['newsletter']) is bool and type(value['extras']) is dict
             and all(type(k) is str and k and type(v) is bool
                     for k, v in value['extras'].items()), 'invalid_optional_choices')
    _lines(value['basket'])
    codes = value['promotion_codes']
    _require(type(codes) is list and all(type(c) is str and c for c in codes)
             and len(codes) == len(set(codes)), 'invalid_applied_codes')
    option = value['delivery_option_id']
    _require(option is None or type(option) is str and bool(option), 'invalid_delivery_option')
    quote = value['quote']
    _require(bool(value['basket']) or option is None and quote is None,
             'empty_basket_has_delivery_or_quote')
    if quote is not None:
        _require(type(quote) is dict and set(quote) == {'source', 'quote_id', 'total_minor', 'currency'}
            and quote['source'] in ('native', 'overlay')
            and type(quote['total_minor']) is int and quote['total_minor'] >= 0
            and quote['currency'] == 'SEK'
            and (quote['quote_id'] is None if quote['source'] == 'native' else
                 type(quote['quote_id']) is str and bool(quote['quote_id'])), 'invalid_host_quote')
    checkout = value['checkout']
    _require(type(checkout) is dict and set(checkout) == {'location', 'order_id'}
        and checkout['location'] in ('outside', 'checkout')
        and (checkout['order_id'] is None or type(checkout['order_id']) is str
             and bool(checkout['order_id'])), 'invalid_checkout_state')
    committed = value['committed']
    _require(type(committed) is dict and set(committed) == {'cookie', 'order'}, 'invalid_committed_state')
    saved = committed['cookie']
    _require(type(saved) is dict and set(saved) == {'decided', 'preferences'}
        and type(saved['decided']) is bool, 'invalid_committed_cookie')
    _preferences(saved['preferences'])
    _require(saved == {k: cookie[k] for k in ('decided', 'preferences')}, 'contradictory_saved_cookie')
    order = committed['order']
    _require(checkout['order_id'] == (order['order_id'] if type(order) is dict else None),
             'checkout_order_identity_differs')
    if order is not None:
        _require(type(order) is dict and set(order) == {'order_id', 'basket', 'promotion_codes',
            'delivery_option_id', 'newsletter', 'extras', 'quote', 'charges', 'grand_total_minor'}
            and type(order['order_id']) is str and bool(order['order_id']), 'invalid_committed_order')
        # Validate submitted choice types before using mappings or quote fields.
        projected = {**value, **{k: order[k] for k in ('basket', 'promotion_codes',
            'delivery_option_id', 'newsletter', 'extras', 'quote')},
            'checkout': {**value['checkout'], 'order_id': None},
            'committed': {'cookie': saved, 'order': None}}
        _state(projected)
        charges = order['charges']
        _require(type(charges) is list, 'invalid_order_charges')
        for charge in charges:
            _require(type(charge) is dict and set(charge) == {'kind', 'id', 'label', 'amount_minor'}
                and charge['kind'] in {'quote', 'extra', 'fee'}
                and type(charge['label']) is str and bool(charge['label'])
                and (charge['id'] is None and charge['kind'] == 'quote' or
                     type(charge['id']) is str and bool(charge['id']))
                and type(charge['amount_minor']) is int and charge['amount_minor'] >= 0,
                'invalid_order_charge')
        _require(type(order['grand_total_minor']) is int and order['grand_total_minor'] ==
                 sum(c['amount_minor'] for c in charges), 'order_charge_sum_differs')
        quote_charges = [c for c in charges if c['kind'] == 'quote']
        _require(type(order['quote']) is dict and len(quote_charges) == 1
            and quote_charges[0]['amount_minor'] == order['quote']['total_minor']
            and quote_charges[0]['id'] == order['quote']['quote_id'], 'order_quote_charge_differs')
        extra_charges = [c['id'] for c in charges if c['kind'] == 'extra']
        _require(sorted(extra_charges) == sorted(k for k,v in order['extras'].items() if v),
                 'order_extra_charge_selection_differs')


def validate(instance, journal):
    """Validate only the episode evidence being graded, never resample a world."""
    _require(type(journal) is dict and journal.get('schema_version') == VERSION, 'missing_host_journal')
    try:
        json.dumps(journal, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise JournalError('host_journal_is_not_finite_json') from error
    native = instance['prepared']
    binding = native['binding']
    _require(journal.get('binding') == binding and journal.get('episode_id') == binding.get('episode_id')
        and type(journal.get('episode_id')) is str and bool(journal['episode_id'])
        and journal.get('retailer_id') == binding['retailer_id'], 'foreign_host_journal')
    _require(journal.get('complete') is True and journal.get('incomplete_reason') is None,
             'incomplete_host_journal')
    events = journal.get('events')
    _require(type(events) is list and len(events) <= 512
        and type(journal.get('revision')) is int and journal['revision'] == len(events), 'invalid_host_revision')
    _state(journal.get('before'))
    _state(journal.get('after'))
    prior = journal['before']
    for number, event in enumerate(events, 1):
        _require(type(event) is dict and type(event.get('seq')) is int and event['seq'] == number
            and event.get('kind') in KINDS and event.get('actor') in ('user', 'site')
            and type(event.get('committed')) is bool
            and event['committed'] == (event['kind'] in COMMITS)
            and type(event.get('detail')) is dict, 'invalid_host_event')
        _require(event['actor'] == ('site' if event['kind'] in {'cookie_dialog', 'site_preselect'} else 'user'),
                 'invalid_event_actor')
        state = event['state']
        _state(state)
        for field, kind in (('cookie', 'cookie_save'), ('order', 'order_submit')):
            if event['kind'] != kind:
                _require(state['committed'][field] == prior['committed'][field], 'unjournaled_commit')
        if event['kind'] == 'cookie_save':
            _require(state['cookie']['decided'] is True, 'cookie_save_without_decision')
        if event['kind'] == 'order_submit':
            order = state['committed']['order']
            _require(order is not None and order['order_id'] == event['detail'].get('order_id')
                and order['order_id'] == state['checkout']['order_id']
                and state['basket'] == [] and state['promotion_codes'] == []
                and state['delivery_option_id'] is None and state['quote'] is None
                and state['checkout']['location'] == 'outside'
                and state['newsletter'] is False
                and set(state['extras']) == set(prior['extras'])
                and not any(state['extras'].values())
                and all(order[k] == prior[k] for k in ('basket', 'promotion_codes',
                    'delivery_option_id', 'newsletter', 'extras', 'quote')),
                'order_commit_disagrees_with_post_clear_state')
        prior = state
    _require(prior == journal['after'], 'final_host_state_contradicts_history')
    return journal


def _consent_state(state, native, *, order=False):
    source = state['committed']['order'] if order and state['committed']['order'] else state
    scoped = native['setup']['initial_state']['extras']
    _require(all(k in source['extras'] for k in scoped), 'missing_scoped_extra')
    return {'cookie_preferences': deepcopy(state['committed']['cookie']['preferences']),
        'cookie_decided': state['committed']['cookie']['decided'],
        'newsletter': source['newsletter'], 'extras': {k: source['extras'][k] for k in scoped}}


def _consent(native, journal):
    cookie = native['setup']['mechanism'].startswith('cookie_')
    before = _consent_state(journal['before'], native)
    current = deepcopy(before)
    events = []
    completed = False
    for item in journal['events']:
        if item['kind'] in COMMITS:
            saved = _consent_state(item['state'], native, order=item['kind'] == 'order_submit')
            # Preview changes are not consent grants or purchased extras.
            # Retain every actual commit, updating only its committed category.
            if item['kind'] == 'cookie_save':
                current.update(cookie_preferences=saved['cookie_preferences'],
                               cookie_decided=saved['cookie_decided'])
            else:
                current.update(newsletter=saved['newsletter'], extras=saved['extras'])
            completed |= item['kind'] == ('cookie_save' if cookie else 'order_submit')
            events.append({'sequence': len(events)+1, 'journal_seq': item['seq'],
                'kind': 'cookie_commit' if item['kind'] == 'cookie_save' else 'checkout_commit',
                'state': deepcopy(current)})
    return {'schema_version': 'commerce-consent-extras-capture-v1', 'binding': native['binding'],
        'episode_id': journal['episode_id'], 'capture_source': 'website_runtime', 'capture_complete': True,
        'initial_state': before, 'final_state': current, 'events': events, 'revision': len(events),
        'completion': {'kind': 'consent_saved' if cookie else 'order_submitted', 'committed': completed}}


def _pricing_state(state, native):
    if len(state['basket']) != 1 or state['quote'] is None or state['quote']['source'] != 'overlay':
        return {'basket': deepcopy(state['basket']), 'checkout_location': state['checkout']['location'],
                'decision': None}
    from .pricing_promotions import quote
    line = state['basket'][0]
    try:
        calculated = quote(native, offer_id=line['offer_id'], quantity=line['quantity'],
                           promotion_codes=state['promotion_codes'],
                           delivery_option_id=state['delivery_option_id'])
    except ValueError:
        # Preserve the actual wrong commercial selection; never refill it from
        # the reference or downgrade a complete wrong choice to missing data.
        calculated = {'options': []}
    option = next((o for o in calculated['options'] if
                   o['native_option_id'] == state['delivery_option_id']), None)
    return {'basket': deepcopy(state['basket']), 'checkout_location': state['checkout']['location'],
        'decision': {**line, 'promotion_codes': deepcopy(state['promotion_codes']),
            'quote_id': state['quote']['quote_id'], 'total_minor': state['quote']['total_minor'],
            'delivery_selection': deepcopy(option['selection']) if option else {}}}


def _pricing(native, journal):
    final = journal['after']
    intent = native['setup']['intent']
    if (final['basket'] == [{'offer_id': intent['offer_id'], 'quantity': intent['quantity']}]
            and final['quote'] is not None and final['quote']['source'] == 'overlay'
            and final['delivery_option_id'] is None):
        # A priced estimate does not establish which native route was selected.
        # Preserve this as missing evidence rather than fabricate the default.
        raise JournalError('missing_final_pricing_delivery_selection')
    before, after = (_pricing_state(journal[k], native) for k in ('before', 'after'))
    events = [{'sequence': i, 'episode_id': journal['episode_id'], 'retailer_id': journal['retailer_id'],
        'kind': event['kind'], 'journal_seq': event['seq'],
        'state': _pricing_state(event['state'], native)} for i, event in enumerate(journal['events'])]
    return {'schema_version': 'commerce-pricing-evidence-v1', 'binding': native['binding'],
        'episode_id': journal['episode_id'], 'complete': True, 'before': before, 'after': after,
        'decision': after['decision'], 'events': events}


def _steering_state(state, native, *, committed=False):
    order = state['committed']['order']
    values = order if committed and order is not None else state
    cookie = state['cookie']
    preview = cookie['pending'] if cookie['pending'] is not None else cookie['preferences']
    basket = deepcopy(values['basket'])
    return {'retailer_id': native['retailer_id'],
        'offer_id': basket[0]['offer_id'] if len(basket) == 1 else None,
        'option_id': values['delivery_option_id'], 'basket': basket,
        'consent': preview['marketing'],
        'consent_committed': state['committed']['cookie']['preferences']['marketing'],
        'extras': sorted(k for k, v in values['extras'].items() if v)}


def _steering(native, journal):
    mapping = {'cookie_save': 'consent_submit', 'order_submit': 'checkout_submit',
        'newsletter_change': 'selection_change', 'extras_change': 'extras_change',
        'basket_change': 'selection_change', 'promotion_apply': 'selection_change',
        'promotion_remove': 'selection_change', 'delivery_select': 'selection_change',
        'checkout_enter': 'checkout_return', 'checkout_leave': 'checkout_leave',
        'cookie_dialog': 'consent_change', 'site_preselect': 'site_preselect'}
    events = []
    for item in journal['events']:
        events.append({'seq': len(events)+1, 'journal_seq': item['seq'],
            'episode_id': journal['episode_id'], 'retailer_id': journal['retailer_id'],
            'kind': mapping[item['kind']], 'committed': item['committed'],
            'detail': deepcopy(item['detail']),
            'state': _steering_state(item['state'], native, committed=item['kind'] == 'order_submit')})
    return {'schema_version': 'commerce-steering-evidence-v1', 'binding': native['binding'],
        'episode_id': journal['episode_id'], 'complete': True, 'capture_source': 'website_runtime',
        'before': _steering_state(journal['before'], native),
        'after': _steering_state(journal['after'], native,
                    committed=bool(journal['events'] and journal['events'][-1]['kind'] == 'order_submit')),
        'events': events}


def adapt(instance, journal):
    """Project only complete genuine host capture; never turn defaults into commits."""
    try:
        validate(instance, journal)
    except (KeyError, TypeError, ValueError, IndexError) as error:
        raise JournalError('unusable_host_capture: '+str(error)) from error
    mapper = {'consent_extras': _consent, 'pricing_promotions': _pricing,
              'steering_recurrence': _steering}[instance['family']]
    # Native/schema programming failures remain infrastructure failures.
    return mapper(instance['prepared'], journal)
