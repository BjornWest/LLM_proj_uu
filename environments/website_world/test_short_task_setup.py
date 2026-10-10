"""Scoped setup controls. Fakes verify plumbing, not browser authority."""
from copy import deepcopy
import json
from types import SimpleNamespace
import pytest
from environments.website_world import short_task_setup as setup


def runtime():
    variant = {'offerId': 'shop/sku', 'skuId': 'sku', 'key': 'sku',
               'selection': {'colour': 'black', 'size_eu': '42'}, 'state': 'in_stock'}
    product = {'id': 'page', 'options': [{'key': 'colour'}, {'key': 'size_eu'}], 'variants': [variant]}
    public = {'products': [product], 'configuration': {'modules': {'checkout': 'steps'}},
              'basket': {'domain': {'maxLinesPerOrder': 2, 'quantityLimits': {'shop/sku': 3}}}}
    return SimpleNamespace(public_catalogs={'shop': public}, origins={'shop': 'https://shop.local'},
        bindings={'retailer_pages': {'shop': {'page': 'https://shop.local/#/product/page'}},
                  'retailer_offers': {'shop/sku': {'retailer_id': 'shop', 'sku_id': 'sku',
                                                'selection': deepcopy(variant['selection'])}}})


def plan(rt=None, **kw):
    return setup.make_plan(rt or runtime(), retailer_id='shop',
        start=kw.pop('start', {'kind': 'product', 'offer_id': 'shop/sku'}), **kw)


def test_product_start_does_not_preselect_requested_variant():
    result = plan()
    assert result['start_url'] == 'https://shop.local/#/product/page'
    assert result['selected_offer'] is None and result['prepared_cart'] == []


def test_selection_retains_actual_menu_axis_order_and_identity():
    result = plan(selected_offer_id='shop/sku')['selected_offer']
    assert result['axis_order'] == ['colour', 'size_eu']
    assert result['sku_id'] == result['key'] == 'sku'


def test_checkout_prepared_cart_is_explicit_not_oracle_selected():
    result = plan(start={'kind': 'checkout', 'step': 2},
                  prepared_cart=[{'offer_id': 'shop/sku', 'quantity': 3}])
    assert result['start_url'] == 'https://shop.local/#/checkout?step=2'
    assert result['prepared_cart'][0]['quantity'] == 3


@pytest.mark.parametrize('quantity', [0, -1, 4, True, 1.5, '1'])
def test_quantities_fail_before_browser_mutation(quantity):
    with pytest.raises(ValueError):
        plan(prepared_cart=[{'offer_id': 'shop/sku', 'quantity': quantity}])


def test_duplicate_rows_are_not_silently_merged():
    with pytest.raises(ValueError, match='Duplicate'):
        plan(prepared_cart=[{'offer_id': 'shop/sku', 'quantity': 1}]*2)


def test_unknown_offers_and_unavailable_items_fail():
    with pytest.raises(ValueError, match='not carried'):
        plan(selected_offer_id='other/sku')
    rt = runtime();rt.public_catalogs['shop']['products'][0]['variants'][0]['state'] = 'unavailable'
    with pytest.raises(ValueError, match='unavailable'):
        plan(rt, prepared_cart=[{'offer_id': 'shop/sku', 'quantity': 1}])


def test_backorder_is_not_unavailable():
    rt = runtime();rt.public_catalogs['shop']['products'][0]['variants'][0]['state'] = 'backorder'
    assert plan(rt, prepared_cart=[{'offer_id': 'shop/sku', 'quantity': 1}])['prepared_cart']


def test_empty_checkout_or_nonexistent_step_fails():
    with pytest.raises(ValueError, match='nonempty'):
        plan(start={'kind': 'checkout', 'step': 1})
    rt = runtime();rt.public_catalogs['shop']['configuration']['modules']['checkout'] = 'accordion'
    with pytest.raises(ValueError, match='no separate'):
        plan(rt, start={'kind': 'checkout', 'step': 2}, prepared_cart=[{'offer_id': 'shop/sku', 'quantity': 1}])


def test_changed_offer_binding_or_axis_contract_fails():
    rt = runtime();rt.bindings['retailer_offers']['shop/sku']['sku_id'] = 'wrong'
    with pytest.raises(ValueError, match='differs'):
        plan(rt)
    rt = runtime();rt.public_catalogs['shop']['products'][0]['options'].append({'key': 'width'})
    with pytest.raises(ValueError, match='controls'):
        plan(rt, selected_offer_id='shop/sku')


class Page:
    def __init__(self):
        self.context = SimpleNamespace(pages=[self]);self.url = 'about:blank';self.visits = []
        self.state = {'version': 2, 'cart': [], 'editing': None, 'address': {'postcode': 'old'},
                      'remembered': {'postcode': 'oracle'}, 'instructions': 'original', 'coupon': '', 'orders': []}
    def goto(self, url): self.url = url;self.visits.append(url)
    def wait_for_selector(self, value): assert value == '#app main'
    def evaluate(self, expression, key):
        assert expression == '(key)=>localStorage.getItem(key)'
        return json.dumps(self.state)


def test_direct_setup_preserves_original_fields_and_existing_tab():
    page = Page();before = deepcopy(page.state)
    result = setup.apply(page, plan(), runtime=runtime())
    assert result['raw_before_setup'] == result['raw_after_setup'] == before
    assert result['browser_storage_writes_by_helper'] is False
    assert page.visits == ['https://shop.local/#/home', 'https://shop.local/#/product/page']
    assert page.context.pages == [page]


def test_existing_cart_is_not_cleared_to_force_fixture():
    page = Page();page.state['cart'] = [{'key': 'existing', 'quantity': 1}]
    with pytest.raises(ValueError, match='untouched'):
        setup.apply(page, plan(), runtime=runtime())
    assert page.state['cart'] == [{'key': 'existing', 'quantity': 1}]


def test_missing_raw_state_is_not_empty_fallback():
    page = Page();page.evaluate = lambda *args: None
    with pytest.raises(ValueError, match='Missing'):
        setup.apply(page, plan(), runtime=runtime())


def test_protected_field_change_fails_setup():
    page = Page();goto = page.goto
    def navigate(url):
        goto(url)
        if 'product' in url:page.state['address']['postcode'] = 'changed'
    page.goto = navigate
    with pytest.raises(ValueError, match='protected'):
        setup.apply(page, plan(), runtime=runtime())


def test_copied_start_or_quantity_tampering_fails_before_navigation():
    for field, value in [('start_url', 'https://unrelated.local'), ('prepared_cart', [])]:
        checked = plan(prepared_cart=[{'offer_id': 'shop/sku', 'quantity': 1}])
        checked[field] = value
        page = Page()
        with pytest.raises(ValueError, match='runtime binding'):
            setup.apply(page, checked, runtime=runtime())
        assert page.visits == []


@pytest.mark.parametrize('kind', ['select', 'radio', 'button'])
def test_reacquire_controls_for_each_axis(kind):
    # Exercise control branching and real tuple/form guard; no browser claim.
    events = []
    class Locator:
        def __init__(self, selector):self.selector = selector
        def count(self):return int(self.selector.startswith({'select': 'select', 'radio': 'input', 'button': 'button'}[kind]) or self.selector.startswith('form'))
        def select_option(self, **kw):self.value=kw['value'];events.append(('select', kw['value']))
        def check(self):events.append(('radio', None))
        def click(self):events.append(('button', None))
        def input_value(self):return self.value
        def is_checked(self):return True
        def get_attribute(self, name):return 'true'
    page = SimpleNamespace(locator=lambda s: Locator(s))
    setup._select(page, plan(selected_offer_id='shop/sku')['selected_offer'])
    assert len(events) == 2
    if kind == 'select':assert events == [('select', 'black'), ('select', '42')]
