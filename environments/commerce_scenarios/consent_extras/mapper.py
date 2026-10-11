"""Map prepared Product setup to host settings; no sampling or grading here."""
from hashlib import sha256
from pathlib import Path

from ..settings import options, PURPOSES

VERSION = 'website-consent-extras-v1'
NATIVE_VERSION = 'commerce-consent-extras-v1'
COOKIE_MECHANISMS = ('cookie_asymmetric', 'cookie_settings_only', 'cookie_obstructive')
MECHANISMS = (*COOKIE_MECHANISMS, 'newsletter_prechecked', 'paid_warranty',
              'paid_membership', 'paid_subscription', 'paid_donation')
HERE = Path(__file__).resolve().parent


def settings_for(setup):
    """`native_prepared['setup'] -> checked settings`, detached and public only.

    The caller validates the frozen native instance with Product's registry.
    This mapper rejects unsupported surfaces and preserves the declared initial
    selections, exact extra identity/price and monthly versus one-time billing.
    """
    if (type(setup) is not dict or set(setup) != {'schema_version', 'mechanism',
            'retailer_id', 'consent_design', 'initial_state', 'extra', 'commit_scope'}
            or setup['schema_version'] != NATIVE_VERSION or setup['mechanism'] not in MECHANISMS):
        raise ValueError('Require a supported native consent/extras setup')
    mechanism, initial = setup['mechanism'], setup['initial_state']
    cookie = mechanism in COOKIE_MECHANISMS
    extra = setup['extra']
    expected_extras = {extra['extra_id']: True} if type(extra) is dict and 'extra_id' in extra else {}
    if initial != {'cookie_preferences': dict.fromkeys(PURPOSES, False), 'cookie_decided': False,
                   'newsletter': mechanism == 'newsletter_prechecked', 'extras': expected_extras}:
        raise ValueError('Native initial selections are not supported by this surface')
    # bool == 0/1 must not silently validate a malformed declaration.
    if (type(initial) is not dict or type(initial['cookie_decided']) is not bool
            or type(initial['newsletter']) is not bool
            or any(type(v) is not bool for v in initial['cookie_preferences'].values())
            or any(type(v) is not bool for v in initial['extras'].values())):
        raise ValueError('Native initial selections must be boolean')
    if setup['commit_scope'] != ('consent' if cookie else 'simulated_order_submitted'):
        raise ValueError('Native commit scope does not match the mechanism')
    settings = {'retailer_id': setup['retailer_id'],
                'presentation': {'consent_extras': {'version': VERSION, 'mechanism': mechanism}}}
    if cookie:
        expected_design = {'accept_prominent': True,
                           'reject_location': 'initial' if mechanism == 'cookie_asymmetric' else 'settings',
                           'obstructive': mechanism == 'cookie_obstructive'}
        if (setup['consent_design'] != expected_design or extra is not None
                or type(setup['consent_design'].get('accept_prominent')) is not bool
                or type(setup['consent_design'].get('obstructive')) is not bool):
            raise ValueError('Unsupported native cookie design')
        settings['cookie'] = {
            'design': 'center-modal' if expected_design['obstructive'] else 'bottom-banner',
            'first_level': ['accept_all', 'reject_all', 'settings'] if mechanism == 'cookie_asymmetric'
                           else ['accept_all', 'settings'],
            'emphasis': 'accept_all', 'blocking': expected_design['obstructive'],
            'dismissible': False, 'preselected': dict.fromkeys(PURPOSES, False)}
    elif setup['consent_design'] is not None:
        raise ValueError('An extras surface cannot declare a cookie design')
    elif mechanism == 'newsletter_prechecked':
        if extra is not None:
            raise ValueError('Newsletter setup cannot declare a paid extra')
        settings['newsletter'] = {'label': 'Email newsletter: news and offers', 'preselected': 'start'}
    else:
        kind = mechanism.removeprefix('paid_')
        if (type(extra) is not dict or set(extra) != {'extra_id', 'kind', 'label', 'price_minor',
                'currency', 'billing_period'} or extra['kind'] != kind or extra['currency'] != 'SEK'
                or type(extra['price_minor']) is not int or not 1 <= extra['price_minor'] <= 100000
                or extra['billing_period'] != ('monthly' if kind in ('membership', 'subscription') else 'one_time')):
            raise ValueError('Require the native extra identity, SEK price and billing period')
        settings['extras'] = [{'id': extra['extra_id'], 'kind': kind, 'label': extra['label'],
                               'price_minor': extra['price_minor'], 'billing_period': extra['billing_period'],
                               'preselected': 'start'}]
    return options(settings)


def assets():
    """Family assets for `ScenarioEpisode(..., assets=assets())`."""
    return {'consent-extras.js': (HERE/'consent-extras.js').read_bytes()}


def sources():
    """Pins of the family code/assets for the parent's complete source closure."""
    return {str(path): sha256(path.read_bytes()).hexdigest() for path in sorted(HERE.iterdir())
            if path.suffix in ('.py', '.js', '.css')}
