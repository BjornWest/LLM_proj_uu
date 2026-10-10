"""Explicit short-task starts and prepared carts through ordinary page controls.

This setup helper supplies no task truth, grading or effect authority. Bind it
before the initial policy observation and capture the resulting raw baseline.
Native atomic/link/review/benefit contracts remain separate producer APIs.
"""
from copy import deepcopy
import json
from time import monotonic

VERSION = 'website-short-task-setup-v1'
PROTECTED = ('address', 'remembered', 'instructions', 'coupon', 'orders')


def make_plan(runtime, *, retailer_id, start, prepared_cart=None, selected_offer_id=None):
    """Resolve only explicit offer IDs; do not pick a task winner or mutate truth.

    Product starts identify the page containing an offer, not a preselected SKU.
    An optional selected_offer_id requests ordinary UI selection during setup.
    Prepared cart rows are {offer_id, quantity}; unknown/duplicate rows fail.
    """
    if retailer_id not in runtime.public_catalogs or type(start) is not dict:
        raise ValueError('Declare an existing retailer and a direct start')
    public = runtime.public_catalogs[retailer_id]
    offers = {}
    for product in public['products']:
        for variant in product['variants']:
            oid = variant['offerId']
            if oid in offers:
                raise ValueError('Ambiguous public offer identity')
            binding = runtime.bindings['retailer_offers'][oid]
            if (binding['retailer_id'] != retailer_id or binding['sku_id'] != variant['skuId']
                    or binding['selection'] != variant['selection']):
                raise ValueError('Offer binding differs from public merchant tuple')
            offers[oid] = (product, variant)
    kind = start.get('kind')
    if kind == 'product' and set(start) == {'kind', 'offer_id'}:
        if start['offer_id'] not in offers:
            raise ValueError('Product start offer is not carried by this retailer')
        start_product = offers[start['offer_id']][0]['id']
        start_url = runtime.bindings['retailer_pages'][retailer_id][start_product]
    elif kind == 'cart' and set(start) == {'kind'}:
        start_product = None
        start_url = runtime.origins[retailer_id] + '/#/cart'
    elif kind == 'checkout' and set(start) == {'kind', 'step'}:
        step = start['step']
        if type(step) is not int or not 1 <= step <= 3:
            raise ValueError('Checkout step must be 1..3')
        if step != 1 and public['configuration']['modules']['checkout'] != 'steps':
            raise ValueError('This checkout has no separate requested step')
        start_product = None
        start_url = runtime.origins[retailer_id] + '/#/checkout?step=' + str(step)
    else:
        raise ValueError('Use an explicit product, cart or checkout start')

    def action(oid):
        if oid not in offers:
            raise ValueError('Setup offer is not carried by this retailer')
        product, variant = offers[oid]
        axes = [o['key'] for o in product['options']]
        if set(axes) != set(variant['selection']) or len(axes) != len(set(axes)):
            raise ValueError('Selection must match actual merchant controls')
        return {'offer_id': oid, 'page_id': product['id'], 'sku_id': variant['skuId'],
                'key': variant['key'], 'selection': deepcopy(variant['selection']),
                'axis_order': axes,
                'url': runtime.bindings['retailer_pages'][retailer_id][product['id']]}

    rows = [] if prepared_cart is None else deepcopy(prepared_cart)
    if type(rows) is not list:
        raise ValueError('Prepared cart must be explicit rows')
    basket = public.get('basket')
    domain = basket.get('domain') if basket else None
    limit = domain['maxLinesPerOrder'] if domain else 64 if basket else 1
    if len(rows) > limit:
        raise ValueError('Prepared cart exceeds the public line domain')
    items, seen = [], set()
    for row in rows:
        if type(row) is not dict or set(row) != {'offer_id', 'quantity'}:
            raise ValueError('Prepared cart needs offer_id and quantity')
        oid, quantity = row['offer_id'], row['quantity']
        item = action(oid)
        maximum = domain['quantityLimits'][oid] if domain else 20 if basket else 1
        if type(quantity) is not int or not 1 <= quantity <= maximum or oid in seen:
            raise ValueError('Duplicate offer or quantity outside the public domain')
        if offers[oid][1]['state'] == 'unavailable':
            raise ValueError('An unavailable SKU cannot be prepared in a cart')
        seen.add(oid)
        items.append({**item, 'quantity': quantity})
    if kind == 'checkout' and not items:
        raise ValueError('Checkout starts require a declared nonempty prepared cart')
    selected = action(selected_offer_id) if selected_offer_id is not None else None
    if selected is not None and (kind != 'product' or selected['page_id'] != start_product):
        raise ValueError('Initial selection must belong to the declared product start')
    return {'schema': VERSION, 'retailer_id': retailer_id,
            'request': {'retailer_id': retailer_id, 'start': deepcopy(start),
                        'prepared_cart': rows, 'selected_offer_id': selected_offer_id},
            'storage_key': 'website-drafts.state.' + retailer_id,
            'home_url': runtime.origins[retailer_id] + '/#/home',
            'start_url': start_url, 'prepared_cart': items, 'selected_offer': selected}


def validate_plan(runtime, plan):
    if type(plan) is not dict or plan.get('schema') != VERSION or type(plan.get('request')) is not dict:
        raise ValueError('Not a checked short-task setup plan')
    if plan != make_plan(runtime, **plan['request']):
        raise ValueError('Setup plan differs from current runtime binding')


def _attribute(value):
    # CSS quoted attribute values; no unescaped native IDs in selectors.
    return '"' + ''.join('\\' + format(ord(c), 'x') + ' ' for c in str(value)) + '"'


def _state(page, key):
    raw = page.evaluate('(key)=>localStorage.getItem(key)', key)
    state = json.loads(raw) if isinstance(raw, str) else None
    if type(state) is not dict or state.get('version') != 2 or type(state.get('cart')) is not list:
        raise ValueError('Missing actual version2 renderer state')
    if any(field not in state for field in PROTECTED):
        raise ValueError('Incomplete baseline state')
    return state


def _wait(page, predicate, message):
    # wait_for_function compiles a string in the page and can violate its CSP.
    # Locators and read-only CDP storage reads retain ordinary page restrictions.
    deadline = monotonic() + 10
    while not predicate():
        if monotonic() >= deadline:
            raise ValueError(message)
        page.wait_for_timeout(25)


def _select(page, item):
    for key in item['axis_order']:
        value = item['selection'][key]
        select = page.locator(f'select[data-selection={_attribute(key)}]')
        radio = page.locator(f'input[type="radio"][data-selection={_attribute(key)}][value={_attribute(value)}]')
        button = page.locator(f'button[data-selection-button={_attribute(key)}][data-value={_attribute(value)}]')
        if select.count() == 1:
            select.select_option(value=value)
            ready = lambda: select.count() == 1 and select.input_value() == value
        elif radio.count() == 1:
            radio.check()
            ready = lambda: radio.count() == 1 and radio.is_checked()
        elif button.count() == 1:
            button.click()
            ready = lambda: button.count() == 1 and button.get_attribute('aria-pressed') == 'true'
        else:
            raise ValueError('Exact native option is not selectable in this page')
        # Every action can replace the buying panel. Reacquire on the next axis.
        _wait(page, ready, 'Native selection did not settle')
    form = page.locator(f'form[data-form="add"][data-key={_attribute(item["key"])}]')
    if form.count() != 1:
        raise ValueError('Actual selected SKU differs from setup target')
    return form


def apply(page, plan, *, runtime):
    """Ordinary UI setup in the existing tab; never write browser storage.

    A nonempty/edited initial cart fails rather than being silently cleared.
    Partial failures must discard the episode; this helper never retries.
    Return raw before/after setup states for a caller-owned pre-policy receipt.
    """
    validate_plan(runtime, plan)
    original_pages = list(page.context.pages)
    actions = []
    page.goto(plan['home_url'])
    page.wait_for_selector('#app main')
    before = _state(page, plan['storage_key'])
    if before['cart'] or before.get('editing') is not None:
        raise ValueError('Prepared setup requires an untouched empty cart')
    for item in plan['prepared_cart']:
        page.goto(item['url']);page.wait_for_selector('#app main')
        form = _select(page, item)
        quantity = form.locator('input[name="quantity"]')
        if int(quantity.get_attribute('max')) < item['quantity']:
            raise ValueError('Live quantity limit differs from checked setup domain')
        quantity.fill(str(item['quantity']))
        form.locator('button').click()
        _wait(page, lambda: any(line['key'] == item['key'] and line['quantity'] == item['quantity']
                               for line in _state(page, plan['storage_key'])['cart']),
              'Actual prepared cart did not settle')
        actions.append({'operation': 'add_via_ui', **deepcopy(item)})
    page.goto(plan['start_url']);page.wait_for_selector('#app main')
    if plan['selected_offer'] is not None:
        _select(page, plan['selected_offer'])
        actions.append({'operation': 'select_via_ui', **deepcopy(plan['selected_offer'])})
    after = _state(page, plan['storage_key'])
    actual = sorted((line['key'], line['quantity']) for line in after['cart'])
    expected = sorted((line['key'], line['quantity']) for line in plan['prepared_cart'])
    if actual != expected or any(before[k] != after[k] for k in PROTECTED):
        raise ValueError('Actual cart or protected original fields changed unexpectedly')
    if list(page.context.pages) != original_pages:
        raise ValueError('Setup changed the retained browser tabs')
    return {'schema': VERSION, 'plan': deepcopy(plan), 'actions': actions,
            'raw_before_setup': before, 'raw_after_setup': after, 'actual_start_url': page.url,
            'browser_storage_writes_by_helper': False,
            'scope': 'Pre-policy setup evidence, not model actions or native grading authority'}
