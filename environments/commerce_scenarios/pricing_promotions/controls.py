"""Finite browser-tool controls for the native pricing action objective."""
from copy import deepcopy
import json


def control_config(prepared, case='positive'):
    if case not in ('positive', 'wrong', 'no-session'):
        raise ValueError('Unknown pricing control')
    setup, reference = prepared['setup'], prepared['reference']
    if reference['status'] != 'ready_native':
        raise ValueError('No native pricing witness; do not repair or resample')
    available = [q for q in reference['candidates'] if q['status'] == 'quoted']
    chosen = min(available, key=lambda q: (q['total_minor'], q['quote_id']))
    offer, quantity, codes = setup['intent']['offer_id'], setup['intent']['quantity'], chosen['promotion_codes']
    if case == 'wrong':
        mechanism = setup['mechanism']
        if mechanism == 'from_price_variant':
            offer = setup['advertised_claim']['offer_id']
        elif mechanism == 'quantity_condition':
            quantity = 2 if quantity != 2 else 1
            codes = [setup['promotions'][0]['code']]
        elif mechanism == 'variant_condition':
            offer = setup['promotions'][0]['offer_ids'][0]
            codes = [setup['promotions'][0]['code']]
        elif mechanism == 'nonstacking_promotions':
            codes = [p['code'] for p in setup['promotions']]
        elif mechanism == 'discount_shipping_loss':
            codes = [setup['promotions'][0]['code']]
        elif mechanism == 'truthful_offer' or reference['scenario_role'] == 'eligible_control':
            codes = []
    # The four default exposure-only mechanisms use explicit noncompletion as
    # their wrong control. This does not claim to discriminate price reasoning.
    exposure = reference['mechanism_discrimination'] == 'exposure_only_unverified'
    stop = reference['required_outcome'] == 'budget_stop'
    return {'case': case, 'mechanism': setup['mechanism'], 'offer_id': offer, 'quantity': quantity,
            'codes': list(codes), 'option_id': chosen['selected']['native_option_id'],
            'checkout': (not stop) if case != 'wrong' else (stop or not exposure),
            'expected': 'inconclusive' if case == 'no-session' else 'fail' if case == 'wrong' else 'pass',
            'mechanism_discrimination': reference['mechanism_discrimination']}


def policy(episode, prepared, case='positive'):
    """Only ordinary tool calls; private choices never become browser state."""
    from environments.commerce_scenarios import scripted
    config = control_config(prepared, case)
    if case == 'no-session':
        return lambda page: scripted.say('I did not visit the retailer.')
    rid, runtime = episode.retailer_id, episode.runtime
    catalog = runtime.public_catalogs[rid]
    pairs = [(p, v) for p in catalog['products'] for v in p['variants'] if v['offerId'] == config['offer_id']]
    if len(pairs) != 1:
        raise ValueError('Pricing offer does not resolve to exactly one public variant')
    product, variant = pairs[0]
    binding = runtime.bindings['retailer_offers'][variant['offerId']]
    if binding['retailer_id'] != rid:
        raise ValueError('Pricing URL belongs to a different retailer')
    url = binding['url']
    origin = runtime.origins[rid]
    steps = catalog['configuration']['modules']['checkout'] == 'steps'
    operations = ['product', 'variant', 'quantity', 'add', 'cart', *[('code', c) for c in config['codes']],
                  'checkout', 'address', 'delivery', 'finish']
    cursor = [0]
    observations = []

    def wait():
        return 'noop', {'wait_ms': 100}

    def act(node, tool='click', **fields):
        if node.count() != 1 or not node.is_visible() or not node.get_attribute('bid'):
            return wait()
        return tool, {'bid': node.get_attribute('bid'), **fields}

    def select(page, selector, value):
        return page.locator(selector+'='+json.dumps(value)+']')

    def next_action(page):
        if page.evaluate('document.documentElement.dataset.commerceScenario') != 'ready':
            return wait()
        while cursor[0] < len(operations):
            operation = operations[cursor[0]]
            state = json.loads(page.evaluate('(k)=>localStorage.getItem(k)', 'website-drafts.state.'+rid) or '{}')
            if operation in ('product', 'cart', 'checkout'):
                cursor[0] += 1
                return 'goto', {'url': url if operation == 'product' else origin+'/#/'+operation}
            if operation == 'variant':
                form = page.locator('form[data-form="add"]')
                if form.count() != 1:
                    return wait()
                if form.get_attribute('data-key') == variant['key']:
                    closed = page.locator('[data-pricing-terms] details:not([open]) > summary')
                    if closed.count() == 1:
                        return act(closed)
                    observations.append({'product_offers': page.locator('[data-pricing-terms]').inner_text()})
                    cursor[0] += 1; continue
                for axis, value in variant['selection'].items():
                    choice = select(page, 'select[data-selection', axis)
                    if choice.count() and choice.input_value() != str(value):
                        return act(choice, 'select_option', options=str(value))
                    radio = page.locator('input[data-selection='+json.dumps(axis)+'][value='+json.dumps(str(value))+']')
                    if radio.count() and not radio.is_checked():
                        return act(radio)
                    button = page.locator('button[data-selection-button='+json.dumps(axis)+'][data-value='+json.dumps(str(value))+']')
                    if button.count() and button.get_attribute('aria-pressed') != 'true':
                        return act(button)
                return wait()
            if operation == 'quantity':
                field = page.locator('form[data-form="add"] input[name="quantity"]')
                if field.count() != 1:
                    return wait()
                if field.input_value() != str(config['quantity']):
                    return act(field, 'fill', value=str(config['quantity']))
                cursor[0] += 1; continue
            if operation == 'add':
                if state.get('cart'):
                    cursor[0] += 1; continue
                return act(page.locator('form[data-form="add"] button'))
            if isinstance(operation, tuple):
                code = operation[1]
                form = page.locator('form[data-scenario-form="promotion"]')
                field = form.locator('[name="code"]')
                if field.count() != 1:
                    return wait()
                if field.input_value() != code:
                    return act(field, 'fill', value=code)
                action = act(form.locator('button'))
                if action[0] != 'noop':
                    cursor[0] += 1
                return action
            if operation == 'address':
                if state.get('addressStatus') == 'valid':
                    cursor[0] += 1; continue
                form = page.locator('form[data-form="address"]')
                if form.count() != 1:
                    return wait()
                for key, value in catalog['rememberedAddress'].items():
                    field = form.locator('[name='+json.dumps(key)+']')
                    if field.count() == 1 and field.input_value() != value:
                        return act(field, 'fill', value=value)
                return act(form.locator('button').first)
            if operation == 'delivery':
                if steps and 'step=2' not in page.url:
                    return 'goto', {'url': origin+'/#/checkout?step=2'}
                if config['offer_id'] == prepared['setup']['intent']['offer_id'] and config['quantity'] == prepared['setup']['intent']['quantity']:
                    node = select(page, 'input[data-service-group][value', config['option_id'])
                else:
                    node = page.locator('label.delivery-row').filter(has_text='Home delivery').locator('input[data-service-group]').first
                if node.count() != 1:
                    return wait()
                if not node.is_checked():
                    return act(node)
                observations.append({'selected_delivery_option_id': node.get_attribute('value'),
                    'delivery_rows': page.locator('label.delivery-row').all_inner_texts(),
                    'totals': page.locator('[data-scenario-part="totals"]').first.inner_text()})
                cursor[0] += 1; continue
            if operation == 'finish':
                if not config['checkout'] and '#/cart' not in page.url:
                    return 'goto', {'url': origin+'/#/cart'}
                if config['checkout'] and steps and 'step=3' not in page.url:
                    return 'goto', {'url': origin+'/#/checkout?step=3'}
                observations.append({'totals': page.locator('[data-scenario-part="totals"]').first.inner_text()})
                return scripted.say('I have checked the basket and the current delivered total.')
        raise ValueError('Pricing control exhausted without final response')

    next_action.observations = observations
    next_action.config = deepcopy(config)
    return next_action
