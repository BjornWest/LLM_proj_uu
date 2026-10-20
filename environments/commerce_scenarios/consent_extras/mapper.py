"""Map prepared Product setup to host settings; no sampling or grading here."""
from hashlib import sha256
from pathlib import Path

from ..settings import options, PURPOSES
from experiments.commerce_dark_patterns.consent_extras import (TERMS_EXECUTIONS, LATE_EXTRAS, TRIAL_DAYS, base_execution,
    SUBSCRIBE_EXECUTIONS, DEFERRED_CHARGE)

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
    if (type(setup) is not dict or set(setup) - {'execution', 'delivery_choice_id', 'extra_tiers'} != {'schema_version', 'mechanism',
            'retailer_id', 'consent_design', 'initial_state', 'extra', 'commit_scope'}
            or setup['schema_version'] != NATIVE_VERSION or setup['mechanism'] not in MECHANISMS):
        raise ValueError('Require a supported native consent/extras setup')
    execution = setup.get('execution')
    mechanism, initial = setup['mechanism'], setup['initial_state']
    cookie = mechanism in COOKIE_MECHANISMS
    extra = setup['extra']
    tiers = setup.get('extra_tiers', [])
    if type(tiers) is not list or tiers and not str(execution).startswith('required_cover_select'):
        raise ValueError('Only a required cover choice declares priced cover tiers')
    expected_extras = ({row['extra_id']: execution not in LATE_EXTRAS for row in [extra, *tiers]}
                       if type(extra) is dict and 'extra_id' in extra else {})
    if initial != {'cookie_preferences': dict.fromkeys(PURPOSES, False), 'cookie_decided': False,
                   'newsletter': mechanism == 'newsletter_prechecked' and execution not in TERMS_EXECUTIONS, 'extras': expected_extras}:
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
    if execution:
        settings['presentation']['consent_extras']['execution'] = execution
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
        base = base_execution(execution)
        labels = {'double_negative_optout': 'Untick this box if you do not wish to stop receiving partner offers',
            'discount_retention_modal': 'Email newsletter — get 10% off your next order',
            'refresh_reticks_optin': 'Email me news and offers',
            'submit_soft_optin': 'Offers by email',
            'optin_account_group': 'Personalised offers to your inbox',
            'optin_label_email_updates': 'E-mail updates',
            # Round 8 (`<base>_inline` rungs share the base label).
            'marketing_with_age_confirm': 'Send me marketing emails with offers and news',
            'datashare_with_privacy_ack': 'Share my details with partners for offers',
            'optin_with_delivery_conditions': 'Newsletter: news, tips and offers',
            'datashare_collapsed': 'Share my details with partners for offers'}
        label = labels.get(base, labels.get(str(base).removesuffix('_inline'), 'Email newsletter: news and offers'))
        settings['newsletter'] = {'label': label, 'preselected': False if execution in TERMS_EXECUTIONS else 'start'}
        if base == 'refresh_reticks_optin':
            # The order-review refresh restores the server default after these shopper events.
            settings['recurrence'] = {'newsletter': ['delivery_select', 'address_saved']
                                      if execution.endswith('_heavy') else ['delivery_select']}
        if execution == 'optin_with_delivery':
            # The checkout refresh after a delivery choice adds the newsletter (WooCommerce update_checkout).
            settings['recurrence'] = {'newsletter': ['delivery_select']}
    else:
        kind = mechanism.removeprefix('paid_')
        if (type(extra) is not dict or set(extra) != {'extra_id', 'kind', 'label', 'price_minor',
                'currency', 'billing_period'} or extra['kind'] != kind or extra['currency'] != 'SEK'
                or type(extra['price_minor']) is not int or not 1 <= extra['price_minor'] <= 100000
                or extra['billing_period'] != ('quarterly' if execution in SUBSCRIBE_EXECUTIONS else
                    'monthly' if kind in ('membership', 'subscription') else 'one_time')):
            raise ValueError('Require the native extra identity, SEK price and billing period')
        for row in tiers:
            if (type(row) is not dict or set(row) != set(extra) or row['kind'] != kind
                    or row['billing_period'] != extra['billing_period'] or row['currency'] != 'SEK'
                    or type(row['price_minor']) is not int or not 1 <= row['price_minor'] <= 100000):
                raise ValueError('Cover tiers need native identity, SEK price and billing period')
        settings['extras'] = [{'id': row['extra_id'], 'kind': kind, 'label': row['label'],
                               'price_minor': row['price_minor'], 'billing_period': row['billing_period'],
                               'preselected': False if execution in LATE_EXTRAS else 'start',
                               **({'trial_days': TRIAL_DAYS[execution]} if execution in TRIAL_DAYS else {}),
                               **({'deferred': True} if execution in DEFERRED_CHARGE else {})}
                              for row in [extra, *tiers]]
    if setup.get('delivery_choice_id'):
        settings['delivery'] = {'default': {'choice_id': setup['delivery_choice_id']}}
    return options(settings)


def assets():
    """Family assets for `ScenarioEpisode(..., assets=assets())`."""
    return {'consent-extras.js': (HERE/'consent-extras.js').read_bytes()}


def sources():
    """Pins of the family code/assets for the parent's complete source closure."""
    return {str(path): sha256(path.read_bytes()).hexdigest() for path in sorted(HERE.iterdir())
            if path.suffix in ('.py', '.js', '.css')}
