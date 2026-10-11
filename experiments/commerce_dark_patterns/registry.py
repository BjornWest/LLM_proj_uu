"""One preparation/grade router for the disjoint commercial mechanism families.

Native families own commercial truth; Website owns presentation and actual capture.
This module does not sample a new population, certify evidence or launch a browser.
"""
from copy import deepcopy
from importlib import import_module
import json

VERSION = 'commerce-dark-pattern-instance-v1'
FAMILIES = {
    'consent_extras': (
        'cookie_asymmetric', 'cookie_settings_only', 'cookie_obstructive',
        'newsletter_prechecked', 'paid_warranty', 'paid_membership',
        'paid_subscription', 'paid_donation'),
    'pricing_promotions': (
        'from_price_variant', 'stale_advertised_price', 'late_mandatory_fee',
        'membership_condition', 'quantity_condition', 'expired_promotion',
        'variant_condition', 'nonstacking_promotions', 'discount_shipping_loss',
        'truthful_offer'),
    'steering_recurrence': (
        'recommended_expensive_delivery', 'default_expensive_shipping',
        'sponsored_alternative', 'removed_consent_reappears',
        'removed_extras_reappear', 'checkout_navigation_reset'),
}
MECHANISMS = {mechanism: family for family, names in FAMILIES.items() for mechanism in names}


def _module(mechanism):
    if type(mechanism) is not str or mechanism not in MECHANISMS:
        raise ValueError('Unsupported commercial mechanism')
    return import_module('.' + MECHANISMS[mechanism], __package__)


def _json(value):
    # Construction/export boundary only, not repeated world validation.
    json.dumps(value, allow_nan=False, ensure_ascii=False)
    return deepcopy(value)


def prepare(seed, *, mechanism, world=None, retailer_id=None, parameters=None,
            user_message=None):
    """Reuse one family's seeded native constructor; keep its binding unchanged."""
    if type(seed) is not int or not 0 <= seed <= 2**63 - 1:
        raise ValueError('Seed must be a bounded nonnegative integer')
    if parameters is not None and type(parameters) is not dict:
        raise ValueError('Mechanism parameters must be an object')
    if user_message is not None and (type(user_message) is not str or not user_message.strip()):
        raise ValueError('Authored public request must be nonempty')
    prepared = _module(mechanism).prepare(seed, mechanism=mechanism, world=world,
        retailer_id=retailer_id, parameters=deepcopy(parameters), user_message=user_message)
    if type(prepared) is not dict:
        raise ValueError('Native family must produce a prepared object')
    return _json({'schema_version': VERSION, 'family': MECHANISMS[mechanism],
                  'mechanism': mechanism, 'prepared': prepared})


def _prepared(instance):
    if (type(instance) is not dict or set(instance) != {
            'schema_version', 'family', 'mechanism', 'prepared'}
            or instance['schema_version'] != VERSION
            or type(instance['mechanism']) is not str
            or instance['mechanism'] not in MECHANISMS
            or MECHANISMS[instance['mechanism']] != instance['family']
            or type(instance['prepared']) is not dict):
        raise ValueError('Invalid prepared commercial instance')
    return _module(instance['mechanism']), instance['prepared']


def validate_ready(instance):
    """Check usable native witness and construction/source integrity at launch."""
    _, native = _prepared(instance)
    family = instance['family']
    ready = (native.get('witness_status') == 'world_bound' if family == 'consent_extras' else
             native.get('reference', {}).get('status') == 'ready_native' if family == 'pricing_promotions' else
             native.get('status') == 'ready')
    if not ready:
        raise ValueError('Native scenario lacks a world-bound usable witness')
    # All family binders validate the frozen source/reference and never sample.
    episode = native.get('binding', {}).get('episode_id') or 'source-readiness-check'
    bind_episode(instance, episode)
    return instance


def grade(instance, evidence, *, answer=None):
    """Native outcome only; caller must supply its actual bound capture/answer."""
    module, prepared = _prepared(instance)
    result = module.grade(prepared, evidence, answer=answer)
    if type(result) is not dict or result.get('status') not in ('pass', 'fail', 'inconclusive'):
        raise ValueError('Native grade must explicitly distinguish missing evidence')
    return _json(result)


def bind_episode(instance, episode_id):
    """Bind a frozen reusable scenario once the harness creates its actual trace."""
    module, prepared = _prepared(instance)
    if type(episode_id) is not str or not episode_id.strip():
        raise ValueError('Actual episode identity required')
    return _json({**instance, 'prepared': module.bind_episode(prepared, episode_id)})


def quote(instance, **selection):
    """Central explicit promotion quote, with no arithmetic in the renderer."""
    module, prepared = _prepared(instance)
    if instance['family'] != 'pricing_promotions':
        raise ValueError('Only pricing/promotions exposes this scoped quote')
    return _json(module.quote(prepared, **selection))


def project(native, binding=None):
    """Canonical harness outcome without claiming whole-run authorization."""
    from intent_browser.evaluation import Evaluation
    if type(native) is not dict or native.get('status') not in ('pass', 'fail', 'inconclusive'):
        raise ValueError('Invalid native commercial grade')
    assessed = native.get('task_completion_assessed', True)
    if type(assessed) is not bool:
        raise ValueError('Task completion scope must be explicit boolean')
    completed = {'pass': True, 'fail': False, 'inconclusive': None}[native['status']] if assessed else None
    return Evaluation('commerce-dark-pattern-native', VERSION,
        trust='scoped_native_reference_and_capture', task_completed=completed,
        authorization_satisfied=None, unauthorized_effects=None,
        limitations=['Only the declared mechanism and captured retailer are graded.',
                     'Whole-run effects and authorization outside that scope remain unknown.'])
