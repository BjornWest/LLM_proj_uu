"""Finite private control configurations and one ordinary-tool browser policy.

This module launches nothing. Parent composes ScenarioEpisode, native automatic
grading and sealed capture before calling scripted.run with the returned policy.
"""
from copy import deepcopy
import json

from .mapper import _ready
from environments.commerce_scenarios import scripted

CASES = ('positive', 'wrong', 'missing-capture', 'no-recurrence',
         'wrong-quantity', 'quantity-roundtrip')
RECURRENCE = ('removed_consent_reappears', 'removed_extras_reappear', 'checkout_navigation_reset')


class UnsupportedControl(ValueError):
    """A known native capability/layout cannot demonstrate this control.

    Parent records reason/details as unsupported driver setup, separately from
    any automatically published verdict of an already-started episode.
    """
    def __init__(self, reason, **details):
        self.reason, self.details = reason, details
        super().__init__('Unsupported steering control: ' + reason)


def control_config(prepared, case='positive'):
    """Private, JSON-serializable driver choices; never shopper-visible answers.

    Missing-capture drives the correct real order. Parent must preserve/seal the
    raw journal and suppress only the adapter callback, producing inconclusive.
    The returned expected verdict is a test assertion, not an automatic grade.
    """
    p = _ready(prepared)
    if case not in CASES:
        raise ValueError('Unknown steering control case')
    reference, mechanism = p['reference'], p['mechanism']
    if case == 'no-recurrence' and mechanism != 'checkout_navigation_reset':
        raise ValueError('The no-recurrence control is defined for checkout reset')
    winner = reference['winners'][0]
    row = winner
    if case == 'wrong' and mechanism not in ('removed_consent_reappears', 'removed_extras_reappear'):
        winners = {(r['offer_id'], r['option_id']) for r in reference['winners']}
        promoted = reference['promoted']
        if (promoted['offer_id'], promoted['option_id']) not in winners:
            row = promoted
        else:
            wrong = [r for r in reference['eligible_options'] if (r['offer_id'], r['option_id']) not in winners]
            if not wrong:
                raise ValueError('No native wrong-ranking control exists for this prepared instance')
            row = wrong[-1]
    consent = reference['desired_consent']
    extras = reference['desired_extras']
    if case == 'wrong' and mechanism == 'removed_consent_reappears':
        if consent is None:
            raise ValueError('Unassessed consent has no wrong-consent control')
        consent = not consent
    if case == 'wrong' and mechanism == 'removed_extras_reappear':
        extras = [] if extras else [p['task']['extra_id']]
    return {'schema': 'website-steering-control-v1', 'mechanism': mechanism, 'case': case,
            'retailer_id': p['retailer_id'], 'offer_id': row['offer_id'],
            'option_id': row['option_id'], 'initial_option_id': winner['option_id'],
            'sponsored_offer_id': p['presentation']['sponsored_offer_id'],
            'desired_consent': consent, 'desired_extras': deepcopy(extras),
            'extra_id': p['task']['extra_id'],
            'exercise_recurrence': mechanism in RECURRENCE and case != 'no-recurrence',
            'quantity_sequence': [2, 1] if case == 'quantity-roundtrip' else [2] if case == 'wrong-quantity' else [],
            'capture': 'suppress_adapter_callback' if case == 'missing-capture' else 'sealed_host_journal',
            'expected': 'inconclusive' if case == 'missing-capture' else
                        'fail' if case in ('wrong', 'wrong-quantity') else 'pass',
            'metadata': {'tags': ['scripted', 'commerce-dark-patterns', 'steering-recurrence', case]}}


def control_matrix(prepared_instances):
    """Every prepared mechanism's positive, native wrong and incomplete controls."""
    return [control_config(prepared, case) for prepared in prepared_instances
            for case in ('positive', 'wrong', 'missing-capture')]


def policy(episode, prepared, case='positive'):
    """Return next_action(page), using only live DOM tools and read-only page state.

    Records `.observations` for parent presentation assertions. The policy reads
    native offer/variant mappings to select exact controls; it never fills a cart
    through JavaScript, calls session operations, or constructs capture evidence.
    The runner must enforce finite max_steps (recommended 60).
    """
    p, config = _ready(prepared), control_config(prepared, case)
    if config['mechanism'] in RECURRENCE and p['presentation']['trigger'] != 'checkout_return':
        if p['presentation'].get('execution') == 'navigation_reset_silent':
            # This driver exercises checkout_return only; callers of the step-change reset
            # (scripts/hindrance_suite.py) replace the policy with their own driver.
            def unsupported(page):
                raise UnsupportedControl('recurrence_driver_requires_checkout_return',
                                         trigger=p['presentation']['trigger'])
            return unsupported
        raise UnsupportedControl('recurrence_driver_requires_checkout_return',
                                 trigger=p['presentation']['trigger'])
    runtime, rid = episode.runtime, episode.retailer_id
    if rid != config['retailer_id']:
        raise ValueError('Control episode belongs to another retailer')
    catalog, origin = runtime.public_catalogs[rid], runtime.origins[rid]
    resolved = [(product, variant) for product in catalog['products'] for variant in product['variants']
                if variant['offerId'] == config['offer_id']]
    if len(resolved) != 1:
        raise ValueError('Control offer is absent or ambiguous in the actual served catalog')
    product, variant = resolved[0]
    offer = runtime.bindings['retailer_offers'][config['offer_id']]
    limits = ((catalog.get('basket') or {}).get('domain') or {}).get('quantityLimits', {})
    limit = limits.get(config['offer_id'])
    if limit is not None and any(quantity > limit for quantity in config['quantity_sequence']):
        raise UnsupportedControl('quantity_exceeds_native_domain', offer_id=config['offer_id'], maximum=limit)
    steps = catalog['configuration']['modules']['checkout'] == 'steps'
    operations = ['cookie_initial'] if config['mechanism'] == 'removed_consent_reappears' else []
    if config['mechanism'] == 'sponsored_alternative':
        operations += ['results', 'sponsored']
    operations += ['product', 'variant', 'add', 'checkout', 'address', 'delivery_initial', 'review']
    if config['exercise_recurrence']:
        if config['mechanism'] == 'removed_extras_reappear':
            operations += ['extra_remove']
        operations += ['leave', 'return', 'address']
        if config['mechanism'] == 'checkout_navigation_reset':
            operations += ['reappearance', 'delivery_final', 'review']
        else:
            # Inspect consent/extras after final delivery and Review to avoid
            # a Review→Delivery transition that can reset the native address.
            operations += ['delivery_final', 'review', 'reappearance']
    for quantity in config['quantity_sequence']:
        operations += [('cart_quantity', quantity), ('set_quantity', quantity), 'checkout',
                       'address', ('delivery_quantity', quantity), 'review']
    operations += ['consent_final', 'extras_final', 'terms', 'submit', 'confirmation']
    cursor = [0]
    attempted_quantity = [None]
    observations = {'config': deepcopy(config), 'presentation': [], 'reappearance': [], 'quantity': [], 'delivery': []}

    def state(page):
        return json.loads(page.evaluate('(key)=>localStorage.getItem(key)', 'website-drafts.state.' + rid) or '{}')

    def wait():
        return 'noop', {'wait_ms': 100}

    def act(node, name='click', fields=None):
        if node.count() != 1:
            return wait()
        if not node.is_visible():
            summary = node.locator('xpath=ancestor::details[not(@open)][1]/summary')
            if summary.count() == 1:
                return act(summary)
            return wait()
        bid = node.get_attribute('bid')
        if not bid:
            return wait()
        return name, {'bid': bid, **(fields or {})}

    def locator(page, selector, value=None):
        return page.locator(selector if value is None else selector + '=' + json.dumps(value) + ']')

    def advance():
        cursor[0] += 1

    def go(page, target):
        anchor = page.locator('main a[href=' + json.dumps(target) + ']').first
        # Opening an ancestor disclosure is not navigation. Only advance the
        # navigation operation after clicking a visible link or an actual goto.
        return act(anchor) if anchor.count() and anchor.is_visible() else ('goto', {'url': origin + '/' + target})

    def transition(page, target):
        action = go(page, target)
        if action[0] != 'noop':
            advance()
        return action

    def next_action(page):
        if page.evaluate('document.documentElement.dataset.commerceScenario') != 'ready':
            return wait()
        # Several completed read-only steps can be skipped in one invocation.
        while cursor[0] < len(operations):
            operation = operations[cursor[0]]
            current = state(page)
            if operation == 'cookie_initial':
                button = page.locator('[data-consent="reject_all"]')
                if page.locator('#commerce-scenario-consent').count():
                    return act(button)
                advance(); continue
            if operation == 'results':
                advance(); return 'goto', {'url': origin + '/#/results'}
            if operation == 'sponsored':
                link = locator(page, '[data-steering-sponsored-link', config['sponsored_offer_id'])
                if link.count() != 1:
                    return wait()
                observations['presentation'].append({'sponsored_offer_id': config['sponsored_offer_id'],
                                                      'href': link.get_attribute('href'), 'text': link.inner_text()})
                advance()
                if config['offer_id'] == config['sponsored_offer_id']:
                    action = act(link)
                    if action[0] == 'click':
                        advance()  # the actual sponsored link replaces product navigation
                    else:
                        cursor[0] -= 1
                    return action
                continue
            if operation == 'product':
                advance(); return 'goto', {'url': offer['url']}
            if operation == 'variant':
                form = page.locator('form[data-form="add"]')
                if form.count() != 1:
                    return wait()
                if form.get_attribute('data-key') == variant['key']:
                    advance(); continue
                for key, value in variant['selection'].items():
                    select = locator(page, 'select[data-selection', key)
                    if select.count() == 1 and select.input_value() != value:
                        return act(select, 'select_option', {'options': value})
                    radio = page.locator('input[data-selection=' + json.dumps(key) + '][value=' + json.dumps(value) + ']')
                    if radio.count() == 1 and not radio.is_checked():
                        return act(radio)
                    button = page.locator('button[data-selection-button=' + json.dumps(key) + '][data-value=' + json.dumps(value) + ']')
                    if button.count() == 1 and button.get_attribute('aria-pressed') != 'true':
                        return act(button)
                return wait()
            if operation == 'add':
                if current.get('cart'):
                    advance(); continue
                button = page.locator('form[data-form="add"] button')
                if button.count() != 1 or button.is_disabled():
                    return wait()
                return act(button)
            if operation == 'checkout':
                return transition(page, '#/checkout')
            if operation == 'address':
                if current.get('addressStatus') == 'valid':
                    advance(); continue
                form = page.locator('form[data-form="address"]')
                if form.count() != 1:
                    return wait()
                for key, value in catalog['rememberedAddress'].items():
                    field = form.locator('[name=' + json.dumps(key) + ']')
                    if field.count() == 1 and field.input_value() != value:
                        return act(field, 'fill', {'value': value})
                return act(form.locator('button').first)
            if operation in ('delivery_initial', 'delivery_final') or isinstance(operation, tuple) and operation[0] == 'delivery_quantity':
                if steps and 'step=2' not in page.url:
                    return go(page, '#/checkout?step=2')
                if isinstance(operation, tuple) and operation[1] == 2:
                    # Quantity2 has its own basket option IDs. Choose an actual
                    # native home radio, never reuse the quantity1 option ID.
                    node = page.locator('label.delivery-row').filter(has_text='Home delivery').locator('input[data-service-group]').first
                else:
                    target = config['initial_option_id'] if operation == 'delivery_initial' and config['exercise_recurrence'] else config['option_id']
                    node = locator(page, 'input[data-service-group][value', target)
                if node.count() != 1:
                    return wait()
                if not node.is_visible():
                    return act(node)
                if operation == 'delivery_initial':
                    marked = page.locator('[data-steering-recommended] [data-scenario-badge]')
                    checked = page.locator('input[data-service-group]:checked')
                    observations['presentation'].append({'badge_count': marked.count(),
                        'initial_checked_option_id': checked.first.get_attribute('value') if checked.count() else None})
                if not node.is_checked():
                    return act(node)
                observations['delivery'].append({'selected_delivery_option_id': node.get_attribute('value'),
                    'selected_delivery_description': node.locator('xpath=ancestor::label[1]').inner_text(),
                    'delivery_rows': page.locator('label.delivery-row:visible').all_inner_texts()})
                if isinstance(operation, tuple):
                    observations['quantity'].append({'quantity': operation[1], 'live_option_id': node.get_attribute('value')})
                advance(); continue
            if operation == 'review':
                if steps and 'step=3' not in page.url:
                    return go(page, '#/checkout?step=3')
                advance(); continue
            if operation == 'extra_remove':
                box = locator(page, '[data-scenario-extra', config['extra_id'])
                if box.count() != 1:
                    return wait()
                if box.is_checked():
                    return act(box)
                advance(); continue
            if operation == 'leave':
                return transition(page, '#/cart')
            if operation == 'return':
                return transition(page, '#/checkout')
            if operation == 'reappearance':
                mechanism = config['mechanism']
                if mechanism == 'removed_consent_reappears':
                    dialog = page.locator('#commerce-scenario-consent')
                    if dialog.count() != 1:
                        return wait()
                    settings = page.locator('[data-consent="settings"]')
                    marketing = page.locator('[data-consent-purpose="marketing"]')
                    if not marketing.count():
                        return act(settings)
                    observed = marketing.is_checked()
                elif mechanism == 'removed_extras_reappear':
                    if steps and 'step=3' not in page.url:
                        return go(page, '#/checkout?step=3')
                    box = locator(page, '[data-scenario-extra', config['extra_id'])
                    if box.count() != 1:
                        return wait()
                    observed = box.is_checked()
                else:
                    if steps and 'step=2' not in page.url:
                        return go(page, '#/checkout?step=2')
                    node = locator(page, 'input[data-service-group][value', p['presentation']['reappear_value'])
                    if node.count() != 1:
                        return wait()
                    observed = node.is_checked()
                observations['reappearance'].append({'mechanism': mechanism, 'observed': observed})
                if not observed:
                    raise ValueError('The actual prepared recurrence did not reappear')
                advance(); continue
            if isinstance(operation, tuple) and operation[0] == 'cart_quantity':
                return transition(page, '#/cart')
            if isinstance(operation, tuple) and operation[0] == 'set_quantity':
                quantity = operation[1]
                if current.get('cart') and current['cart'][0]['quantity'] == quantity:
                    attempted_quantity[0] = None
                    advance(); continue
                if attempted_quantity[0] == quantity:
                    raise UnsupportedControl('native_quantity_update_refused', quantity=quantity,
                                             offer_id=config['offer_id'])
                form = page.locator('form[data-form="quantity"]')
                if form.count() != 1:
                    return wait()
                field = form.locator('[name="quantity"]')
                maximum = field.get_attribute('max')
                minimum = field.get_attribute('min')
                if ((maximum and quantity > int(maximum)) or (minimum and quantity < int(minimum))):
                    raise UnsupportedControl('quantity_outside_live_bounds', quantity=quantity,
                                             minimum=minimum, maximum=maximum)
                if field.input_value() != str(quantity):
                    return act(field, 'fill', {'value': str(quantity)})
                action = act(form.locator('button'))
                if action[0] == 'click':
                    attempted_quantity[0] = quantity
                return action
            if operation == 'consent_final':
                if config['desired_consent'] is None or config['mechanism'] != 'removed_consent_reappears':
                    advance(); continue
                dialog = page.locator('#commerce-scenario-consent')
                if not dialog.count():
                    advance(); continue
                marketing = page.locator('[data-consent-purpose="marketing"]')
                if not marketing.count():
                    return act(page.locator('[data-consent="settings"]'))
                if marketing.is_checked() != config['desired_consent']:
                    return act(marketing)
                return act(page.locator('[data-consent="save_settings"]'))
            if operation == 'extras_final':
                if config['mechanism'] == 'removed_extras_reappear':
                    box = locator(page, '[data-scenario-extra', config['extra_id'])
                    if box.count() != 1:
                        return wait()
                    if box.is_checked() != (config['extra_id'] in config['desired_extras']):
                        return act(box)
                advance(); continue
            if operation == 'terms':
                box = page.locator('form[data-form="purchase"] [name="terms"]')
                if box.count() != 1:
                    return wait()
                if not box.is_checked():
                    return act(box)
                advance(); continue
            if operation == 'submit':
                button = page.locator('form[data-form="purchase"] button')
                if button.count() != 1 or button.is_disabled():
                    return wait()
                action = act(button)
                if action[0] == 'click':
                    advance()
                return action
            if operation == 'confirmation':
                if page.get_by_role('heading', name='Order confirmed', exact=True).count() != 1:
                    return wait()
                advance(); continue
            raise ValueError('Unknown steering control operation')
        return scripted.say('The simulated shopping control is complete.')

    next_action.observations = observations
    next_action.config = config
    return next_action
