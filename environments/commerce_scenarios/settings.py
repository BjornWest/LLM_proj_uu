"""Scenario settings for one target retailer: validation and public projection.

Settings are plain JSON written by a family's mapper, plus two optional
in-process callables (`quote` and `scope`) for an overlay price. Nothing here
knows Product's modules, and nothing private is part of the settings.
"""
from copy import deepcopy
import json
import re

SCHEMA = 'website-commerce-scenario-settings-v1'
PURPOSES = ('analytics', 'personalisation', 'marketing')
DESIGNS = ('bottom-banner', 'center-modal', 'side-drawer')
COOKIE_ACTIONS = ('accept_all', 'reject_all', 'settings')
RETURN_TRIGGERS = ('checkout_return', 'checkout_navigation')
# Order-review refresh triggers: the site re-renders choices after these shopper events.
REFRESH_TRIGGERS = ('delivery_select', 'address_saved')
PRESELECT = (False, 'start', 'checkout')
EXTRA_KINDS = ('warranty', 'membership', 'subscription', 'donation', 'other')
BILLING = ('one_time', 'monthly', 'quarterly')
PLACEMENTS = ('results', 'product', 'cart')
MAX_AMOUNT_MINOR = 10_000_000
_ID = re.compile(r'[a-z0-9][a-z0-9._-]{0,63}')


def _fail(message):
    raise ValueError('Scenario settings: ' + message)


def _closed(value, name, required, optional=()):
    if type(value) is not dict:
        _fail(name + ' must be an object')
    missing, unknown = set(required) - set(value), set(value) - set(required) - set(optional)
    if missing or unknown:
        _fail(f'{name} has missing {sorted(missing)} or unknown {sorted(unknown)} keys')
    return value


def _text(value, name, limit=200):
    if type(value) is not str or not value.strip() or len(value) > limit:
        _fail(name + ' must be nonempty text')
    return value


def _identifier(value, name):
    if type(value) is not str or not _ID.fullmatch(value):
        _fail(name + ' must be a short lowercase identifier')
    return value


def _amount(value, name):
    if type(value) is not int or not 0 <= value <= MAX_AMOUNT_MINOR:
        _fail(name + ' must be a bounded integer amount in minor units')
    return value


def _triggers(value, name):
    allowed = RETURN_TRIGGERS + REFRESH_TRIGGERS
    if type(value) is not list or len(set(value)) != len(value) or set(value) - set(allowed):
        _fail(name + ' must list distinct triggers from ' + ', '.join(allowed))
    return list(value)


def _preselect(value, name):
    if value is not False and not (type(value) is str and value in PRESELECT):
        _fail(name + " must be false, 'start' or 'checkout'")
    return value


def _cookie(value):
    row = _closed(value, 'cookie', ('design',),
                  ('first_level', 'emphasis', 'blocking', 'dismissible', 'preselected'))
    if row['design'] not in DESIGNS:
        _fail('cookie.design must be one of ' + ', '.join(DESIGNS))
    first = row.get('first_level', list(COOKIE_ACTIONS))
    if (type(first) is not list or not first or len(set(first)) != len(first)
            or set(first) - set(COOKIE_ACTIONS)):
        _fail('cookie.first_level must list distinct first-level actions')
    if 'reject_all' not in first and 'settings' not in first:
        _fail('cookie.first_level must leave a way to refuse (reject_all or settings)')
    emphasis = row.get('emphasis')
    if emphasis is not None and emphasis not in first:
        _fail('cookie.emphasis must name a first-level action or be null')
    for flag in ('blocking', 'dismissible'):
        if type(row.get(flag, False)) is not bool:
            _fail('cookie.' + flag + ' must be boolean')
    if row.get('blocking', False) and row.get('dismissible', False):
        _fail('a blocking cookie dialog cannot be dismissible')
    chosen = row.get('preselected', {purpose: False for purpose in PURPOSES})
    if (type(chosen) is not dict or set(chosen) != set(PURPOSES)
            or any(type(v) is not bool for v in chosen.values())):
        _fail('cookie.preselected must give a boolean for every purpose')
    return {'design': row['design'], 'first_level': list(first), 'emphasis': emphasis,
            'blocking': row.get('blocking', False), 'dismissible': row.get('dismissible', False),
            'preselected': {purpose: chosen[purpose] for purpose in PURPOSES}}


def _newsletter(value):
    row = _closed(value, 'newsletter', ('label',), ('preselected',))
    return {'label': _text(row['label'], 'newsletter.label'),
            'preselected': _preselect(row.get('preselected', False), 'newsletter.preselected')}


def _extras(value):
    if type(value) is not list or len(value) > 8:
        _fail('extras must be a list of at most eight extras')
    result = []
    for row in value:
        _closed(row, 'extra', ('id', 'kind', 'label', 'price_minor', 'billing_period'), ('preselected', 'trial_days', 'deferred'))
        if row['kind'] not in EXTRA_KINDS or row['billing_period'] not in BILLING:
            _fail('extra kind or billing period is not supported')
        result.append({'id': _identifier(row['id'], 'extra.id'), 'kind': row['kind'],
                       'label': _text(row['label'], 'extra.label'),
                       'price_minor': _amount(row['price_minor'], 'extra.price_minor'),
                       'billing_period': row['billing_period'],
                       'preselected': _preselect(row.get('preselected', False), 'extra.preselected')})
        if 'trial_days' in row:
            # A free trial: nothing is charged today, the monthly price applies afterwards.
            if type(row['trial_days']) is not int or not 1 <= row['trial_days'] <= 90 or row['billing_period'] != 'monthly':
                _fail('extra.trial_days must be 1..90 days of a monthly extra')
            result[-1]['trial_days'] = row['trial_days']
        if 'deferred' in row:
            # A recurring extra first billed at a later delivery: nothing is charged today.
            if row['deferred'] is not True or row['billing_period'] == 'one_time':
                _fail('extra.deferred must be true for a recurring extra')
            result[-1]['deferred'] = True
    if len({row['id'] for row in result}) != len(result):
        _fail('extra ids must be unique')
    return result


def _promotions(value):
    row = _closed(value, 'promotions', ('field',), ('label', 'claims'))
    if type(row['field']) is not bool:
        _fail('promotions.field must be boolean')
    claims = row.get('claims', [])
    if type(claims) is not list or len(claims) > 16:
        _fail('promotions.claims must be a short list of texts')
    return {'field': row['field'], 'label': _text(row.get('label', 'Promotion code'), 'promotions.label'),
            'claims': [_text(claim, 'promotion claim', 400) for claim in claims]}


def _fees(value):
    """Display text for fee lines of the quote breakdown; fees are never charged separately."""
    if type(value) is not list or len(value) > 8:
        _fail('fees must be a list of at most eight fee descriptions')
    result = []
    for row in value:
        _closed(row, 'fee', ('id', 'label'), ('reveal',))
        if row.get('reveal', 'always') not in ('always', 'checkout'):
            _fail("fee.reveal must be 'always' or 'checkout'")
        result.append({'id': _identifier(row['id'], 'fee.id'), 'label': _text(row['label'], 'fee.label'),
                       'reveal': row.get('reveal', 'always')})
    if len({row['id'] for row in result}) != len(result):
        _fail('fee ids must be unique')
    return result


def _matcher(value, name, extra=()):
    row = _closed(value, name, (), ('option_id', 'choice_id', *extra))
    if ('option_id' in row) == ('choice_id' in row):
        _fail(name + ' must name exactly one of option_id or choice_id')
    key = 'option_id' if 'option_id' in row else 'choice_id'
    return {key: _text(row[key], name + '.' + key)}


def _delivery(value):
    row = _closed(value, 'delivery', (), ('default', 'prominent'))
    default = row.get('default')
    prominent = row.get('prominent')
    result = {'default': None if default is None else _matcher(default, 'delivery.default'),
              'prominent': None}
    if prominent is not None:
        result['prominent'] = {**_matcher(prominent, 'delivery.prominent', ('label',)),
                               'label': _text(prominent.get('label', 'Recommended'), 'delivery.prominent.label')}
    return result


def _sponsored(value):
    if type(value) is not list or len(value) > 16:
        _fail('sponsored must be a list of at most sixteen placements')
    result = []
    for row in value:
        _closed(row, 'sponsored placement', ('offer_id', 'label', 'placement'))
        if row['placement'] not in PLACEMENTS:
            _fail('sponsored.placement must be one of ' + ', '.join(PLACEMENTS))
        result.append({'offer_id': _text(row['offer_id'], 'sponsored.offer_id', 400),
                       'label': _text(row['label'], 'sponsored.label'), 'placement': row['placement']})
    return result


def _recurrence(value, extras):
    row = _closed(value, 'recurrence', (), ('cookie', 'newsletter', 'extras', 'delivery'))
    by_extra = row.get('extras', {})
    if type(by_extra) is not dict or set(by_extra) - {extra['id'] for extra in extras}:
        _fail('recurrence.extras must map declared extra ids to triggers')
    return {'cookie': _triggers(row.get('cookie', []), 'recurrence.cookie'),
            'newsletter': _triggers(row.get('newsletter', []), 'recurrence.newsletter'),
            'extras': {key: _triggers(by_extra[key], 'recurrence.extras') for key in sorted(by_extra)},
            'delivery': _triggers(row.get('delivery', []), 'recurrence.delivery')}


def options(value=None):
    """Return checked, completed settings (a detached copy), or None for no scenario."""
    if value is None:
        return None
    _closed(value, 'settings', ('retailer_id',),
            ('schema', 'cookie', 'newsletter', 'extras', 'promotions', 'fees', 'delivery',
             'sponsored', 'recurrence', 'presentation', 'quote', 'scope', 'outside_scope_behavior'))
    if value.get('schema', SCHEMA) != SCHEMA:
        _fail('unsupported schema')
    quote, scope = value.get('quote'), value.get('scope')
    if (quote is None) != (scope is None) or (quote is not None and not (callable(quote) and callable(scope))):
        _fail('an overlay price needs both the quote and the scope callable')
    plain = {key: item for key, item in value.items() if key not in ('quote', 'scope')}
    try:
        plain = json.loads(json.dumps(plain, allow_nan=False))
    except (TypeError, ValueError) as error:
        raise ValueError('Scenario settings: everything except quote and scope must be plain JSON') from error
    extras = _extras(plain.get('extras', []))
    outside = plain.get('outside_scope_behavior', 'native_quote')
    if outside not in ('native_quote', 'reject_quote') or outside == 'reject_quote' and quote is None:
        _fail('outside_scope_behavior must be native_quote or reject_quote with an overlay')
    if type(plain.get('presentation') or {}) is not dict:
        _fail('presentation must be an object of public, family-defined page parameters')
    result = {
        'schema': SCHEMA,
        'retailer_id': _text(plain['retailer_id'], 'retailer_id'),
        'cookie': None if plain.get('cookie') is None else _cookie(plain['cookie']),
        'newsletter': None if plain.get('newsletter') is None else _newsletter(plain['newsletter']),
        'extras': extras,
        'promotions': _promotions(plain.get('promotions') or {'field': False}),
        'fees': _fees(plain.get('fees', [])),
        'delivery': _delivery(plain.get('delivery') or {}),
        'sponsored': _sponsored(plain.get('sponsored', [])),
        'recurrence': _recurrence(plain.get('recurrence') or {}, extras),
        'presentation': plain.get('presentation') or {},
        'quote': quote, 'scope': scope,
        'outside_scope_behavior': outside,
    }
    recurrence = result['recurrence']
    if recurrence['cookie'] and result['cookie'] is None:
        _fail('recurrence.cookie needs a cookie dialog')
    if recurrence['newsletter'] and result['newsletter'] is None:
        _fail('recurrence.newsletter needs a newsletter control')
    return result


def validate_catalog(settings, catalog):
    """Check the settings against the retailer's actual public catalog."""
    offers = {variant['offerId'] for product in catalog['products'] for variant in product['variants']}
    if catalog['siteId'] != settings['retailer_id']:
        _fail('catalog belongs to another retailer')
    unknown = [row['offer_id'] for row in settings['sponsored'] if row['offer_id'] not in offers]
    if unknown:
        _fail('sponsored offers are not sold by this retailer: ' + ', '.join(unknown))
    return offers


def public_settings(settings, pieces=()):
    """The part of the settings the page may see: presentation only.

    Site rules (preselection, recurrence, delivery default) stay on the host;
    the page learns their effect from session replies.
    """
    public = {key: deepcopy(settings[key]) for key in
              ('schema', 'cookie', 'extras', 'promotions', 'fees', 'sponsored', 'presentation')}
    newsletter, prominent = settings['newsletter'], settings['delivery']['prominent']
    public['newsletter'] = {'label': newsletter['label']} if newsletter else None
    for extra in public['extras']:
        del extra['preselected']
    public['delivery'] = {'prominent_label': prominent['label'] if prominent else None}
    public['pieces'] = sorted(pieces)
    return public


def plain(settings):
    """Settings without the in-process callables, for digests and private records."""
    result = {key: deepcopy(item) for key, item in settings.items() if key not in ('quote', 'scope')}
    result['overlay_quote'] = settings['quote'] is not None
    return result
