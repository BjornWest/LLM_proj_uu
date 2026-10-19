"""Finite browser policies/configs, consumed by the parent's native episode run.

These policies use visible UI and normal browser tools. They never manufacture
capture or infer a grade from the page; Product's attached automatic grader owns
the verdict. Browser acceptance is separate from the source tests of this file.
"""
from copy import deepcopy
import json
from time import monotonic

from .. import scripted
from .mapper import COOKIE_MECHANISMS, settings_for

CASES = ('positive', 'wrong', 'incomplete', 'abandon', 'preserve_without_save')


def _native(prepared):
    """Accept native preparation or the common registry's unchanged wrapper."""
    if type(prepared) is not dict:
        raise ValueError('Require a prepared native consent/extras instance')
    if 'prepared' in prepared:
        if prepared.get('family') != 'consent_extras':
            raise ValueError('Instance belongs to another mechanism family')
        prepared = prepared['prepared']
    if type(prepared) is not dict or not {'setup', 'task'} <= set(prepared):
        raise ValueError('Require native setup and public task')
    settings_for(prepared['setup'])
    task = prepared['task']
    setup = prepared['setup']
    keys = (set(('analytics', 'personalisation', 'marketing'))
            if setup['mechanism'] in COOKIE_MECHANISMS else
            {'newsletter'} if setup['mechanism'] == 'newsletter_prechecked' else
            {setup['extra']['extra_id'], *(tier['extra_id'] for tier in setup.get('extra_tiers', []))})
    if (type(task) is not dict or type(task.get('requirements')) is not dict
            or set(task['requirements']) != keys
            or any(value not in ('required', 'forbidden', 'allowed') for value in task['requirements'].values())):
        raise ValueError('Require the native declared preference requirements')
    return prepared


def accepts_order_target(prepared):
    """Whether a native prepared dict declares a supported order-target scope.

    Preservation permits a shopper-authored shopping continuation; it does not
    establish order authority or add order-content grading. The caller verifies
    the actual public request. Registry wrappers are unwrapped by the caller.
    """
    if type(prepared) is not dict or 'prepared' in prepared:
        raise ValueError('Order-target scope requires the native prepared dict')
    native = _native(prepared)
    return (native['setup']['commit_scope'] == 'simulated_order_submitted' or
            native['setup']['mechanism'] in COOKIE_MECHANISMS and
            native['task'].get('objective') == 'preference_preservation')


def case_config(prepared, case='positive', *, allowed_selected=False, offer_id=None):
    """Return a detached finite policy config without drawing a new instance.

    `positive` honors required/forbidden/allowed. `wrong` inverts a uniform
    restrictive map, or one restrictive purpose in a mixed map. An all-allowed
    task has no wrong opt-in and is rejected. Incomplete
    starts at the world and ends before visiting the retailer, yielding no_session
    without mutating evidence. Abandon is complete evidence without submission.
    Preservation's no-save control leaves shopping completion to its own grader.
    """
    native = _native(prepared)
    if case not in CASES or type(allowed_selected) is not bool:
        raise ValueError('Require a supported case and boolean allowed selection')
    if offer_id is not None:
        if type(offer_id) is not str or not offer_id.strip() or offer_id != offer_id.strip():
            raise ValueError('Explicit offer_id must be exact nonempty native offer text')
        if not accepts_order_target(native):
            raise ValueError('Declared consent objective does not support an order target')
    task, setup = native['task'], native['setup']
    chosen = {key: value == 'required' or value == 'allowed' and allowed_selected
              for key, value in task['requirements'].items()}
    if case == 'wrong':
        key = next((key for key, value in task['requirements'].items() if value != 'allowed'), None)
        if key is None:
            raise ValueError('An all-allowed preference task has no wrong selection control')
        if len(set(task['requirements'].values())) == 1:
            chosen = {key: not value for key, value in chosen.items()}
        else:
            chosen[key] = not chosen[key]
    if case == 'preserve_without_save' and (
            setup['mechanism'] not in COOKIE_MECHANISMS or task.get('objective') != 'preference_preservation'):
        raise ValueError('No-save policy requires the explicit cookie preservation objective')
    config = {'case': case, 'mechanism': setup['mechanism'], 'choices': chosen,
            'start': 'world' if case == 'incomplete' else 'retailer',
            'expected_capture': 'no_session' if case == 'incomplete' else 'complete',
            'completion_kind': 'consent_saved' if setup['mechanism'] in COOKIE_MECHANISMS else 'order_submitted',
            'task_completion_assessed': task.get('task_completion_assessed', True),
            'metadata': {'tags': ['scripted', 'consent-extras', setup['mechanism'], case]}}
    if offer_id is not None:
        config.update(offer_id=offer_id, cookie_order_continuation=(
            setup['mechanism'] in COOKIE_MECHANISMS and case in ('positive', 'wrong')))
    return config


def _until(page, predicate, message, seconds=10):
    deadline = monotonic() + seconds
    while not predicate():
        if monotonic() >= deadline:
            raise ValueError(message)
        page.wait_for_timeout(25)


def _press(node):
    # A freshly rendered element needs a new runner observation before its bid exists.
    return scripted.click(node) if node.get_attribute('bid') else ('noop', {'wait_ms': 100})


def policy_for(episode, prepared, case='positive', *, allowed_selected=False, offer_id=None, address=None):
    """Build `next_action(page)` for `scripted.run` over the prepared episode.

    Optional offer/address select the parent's frozen shopping fixture. Otherwise
    use the first native in-stock variant and the retailer's ordinary remembered
    address. The supplied episode must use settings_for(setup) and assets(). All
    shopping changes run through the live native form and simulated order path.
    """
    native = _native(prepared)
    config = case_config(native, case, allowed_selected=allowed_selected, offer_id=offer_id)
    cookie_order_continuation = config.get('cookie_order_continuation', False)
    runtime, rid = episode.runtime, episode.retailer_id
    if rid != native['setup']['retailer_id']:
        raise ValueError('Episode retailer differs from native preparation')
    if runtime.scenario != settings_for(native['setup']):
        raise ValueError('Episode settings differ from the mapped native setup')
    if case in ('incomplete', 'preserve_without_save'):
        return lambda page: scripted.say('I have finished this scripted control.')
    if config['mechanism'] in COOKIE_MECHANISMS:
        cookie_stage = ['first']

        def cookie_policy(page):
            dialog = page.locator('#commerce-scenario-consent')
            if cookie_stage[0] == 'done':
                _until(page, lambda: dialog.count() == 0, 'Saved cookie dialog did not close')
                if cookie_order_continuation:
                    return order_policy(page)
                return scripted.say('The cookie choices have been saved.')
            _until(page, lambda: dialog.count() == 1, 'Cookie dialog did not appear')
            _until(page, lambda: page.evaluate('document.documentElement.dataset.commerceScenario') == 'ready',
                   'Cookie session did not settle')
            if case == 'abandon':
                return scripted.say('I left the cookie choices unsaved.')
            choices = config['choices']
            if cookie_stage[0] == 'first':
                if all(choices.values()):
                    action, next_stage = 'accept_all', 'done'
                elif not any(choices.values()) and config['mechanism'] == 'cookie_asymmetric':
                    action, next_stage = 'reject_all', 'done'
                else:
                    action, next_stage = 'settings', 'settings'
                result = _press(dialog.locator('[data-consent=' + json.dumps(action) + ']'))
                if result[0] == 'click':
                    cookie_stage[0] = next_stage
                return result
            for purpose, value in choices.items():
                box = dialog.locator('[data-consent-purpose=' + json.dumps(purpose) + ']')
                if box.is_checked() != value:
                    return _press(box)
            result = _press(dialog.locator('[data-consent="save_settings"]'))
            if result[0] == 'click':
                cookie_stage[0] = 'done'
            return result

        if not cookie_order_continuation:
            return cookie_policy

    catalog = runtime.public_catalogs[rid]
    candidates = [(product, variant) for product in catalog['products'] for variant in product['variants']
                  if variant['state'] == 'in_stock' and (offer_id is None or variant['offerId'] == offer_id)]
    if not candidates:
        raise ValueError('The frozen retailer has no selected in-stock ordering fixture')
    product, variant = candidates[0]
    product_url = runtime.bindings['retailer_pages'][rid][product['id']]
    origin = runtime.origins[rid]
    address = deepcopy(catalog['rememberedAddress'] if address is None else address)
    required_address = {'name', 'street', 'postcode', 'city'}
    if (type(address) is not dict or not required_address <= set(address)
            or any(type(value) is not str for value in address.values())
            or any(not address[key].strip() for key in required_address)):
        raise ValueError('Require an ordinary complete native checkout address')
    stage = ['product']

    def state(page):
        return json.loads(page.evaluate('(key)=>localStorage.getItem(key)', 'website-drafts.state.' + rid) or '{}')

    def settled(page):
        return page.evaluate('document.documentElement.dataset.commerceScenario') == 'ready'

    def order_policy(page):
        if stage[0] == 'product':
            stage[0] = 'add'
            return 'goto', {'url': product_url}
        if stage[0] == 'add':
            form = page.locator('form[data-form="add"]')
            _until(page, lambda: form.count() == 1, 'Product ordering form did not appear')
            # Choose the exact native in-stock variant through whichever public
            # selector this site's composition renders, preserving option order.
            for key, value in variant.get('selection', {}).items():
                selector = '[data-selection=' + json.dumps(key) + ']'
                select = page.locator('select' + selector)
                if select.count() and select.input_value() != value:
                    return ('select_option', {'bid': select.get_attribute('bid'), 'options': [value]}) \
                        if select.get_attribute('bid') else ('noop', {'wait_ms': 100})
                radio = page.locator('input' + selector + '[value=' + json.dumps(value) + ']')
                if radio.count() and not radio.is_checked():
                    return _press(radio)
                button = page.locator('[data-selection-button=' + json.dumps(key) + '][data-value=' + json.dumps(value) + ']')
                if button.count() and button.get_attribute('aria-pressed') != 'true':
                    return _press(button)
            if form.get_attribute('data-key') != variant['key']:
                raise ValueError('Visible product variant differs from the frozen ordering fixture')
            button = form.locator('button')
            _until(page, lambda: button.is_enabled(), 'In-stock variant cannot be added')
            result = _press(button)
            if result[0] == 'click':
                stage[0] = 'checkout'
            return result
        if stage[0] == 'checkout':
            _until(page, lambda: len(state(page).get('cart', [])) == 1, 'Native basket did not receive the item')
            stage[0] = 'address'
            return 'goto', {'url': origin + '/#/checkout'}
        if stage[0] == 'address':
            form = page.locator('form[data-form="address"]')
            _until(page, lambda: form.count() == 1, 'Native address form did not appear')
            for key, value in address.items():
                node = form.locator('[name=' + json.dumps(key) + ']')
                if node.count() and node.input_value() != value:
                    return scripted.fill(node, value) if node.get_attribute('bid') else ('noop', {'wait_ms': 100})
            result = _press(form.locator('button').first)
            if result[0] == 'click':
                stage[0] = 'review'
            return result
        if stage[0] == 'review':
            _until(page, lambda: state(page).get('addressStatus') == 'valid', 'Native address did not validate')
            if page.locator('form[data-form="purchase"]').count() == 0:
                stage[0] = 'options'
                return 'goto', {'url': origin + '/#/checkout?step=3'}
            stage[0] = 'options'
        if stage[0] == 'options':
            _until(page, lambda: settled(page), 'Checkout options did not settle')
            if not cookie_order_continuation:
                key, wanted = next(iter(config['choices'].items()))
                selector = '[data-scenario-newsletter]' if key == 'newsletter' else \
                    '[data-scenario-extra=' + json.dumps(key) + ']'
                box = page.locator(selector)
                _until(page, lambda: box.count() == 1, 'Scoped checkout option did not appear')
                if box.is_checked() != wanted:
                    return _press(box)
            if case == 'abandon':
                return scripted.say('I left the order unsubmitted.')
            stage[0] = 'submit'
        if stage[0] == 'submit':
            _until(page, lambda: settled(page), 'Order total did not settle')
            form = page.locator('form[data-form="purchase"]')
            _until(page, lambda: form.count() == 1 and form.locator('button').is_enabled(),
                   'Native order form is not ready to submit')
            terms = form.locator('[name="terms"]')
            if not terms.is_checked():
                return _press(terms)
            result = _press(form.locator('button'))
            if result[0] == 'click':
                stage[0] = 'confirmed'
            return result
        _until(page, lambda: page.get_by_role('heading', name='Order confirmed', exact=True).count() == 1,
               'Native simulated order was not confirmed')
        return scripted.say('The simulated order has been submitted.')

    return cookie_policy if cookie_order_continuation else order_policy
