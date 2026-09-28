from copy import deepcopy
import json
from urllib.parse import urlencode
from urllib.request import urlopen, Request
from urllib.error import HTTPError

import pytest

from .product_controls import validate_groups, resolve
from .product_fixture import footwear_fixture
from .presentation import SHOWCASE
from .runtime import Runtime


@pytest.fixture
def bundle():
    return footwear_fixture()


def test_resolution_preserves_both_axes_and_distinguishes_states(bundle):
    world, groups = bundle
    group = validate_groups(groups, world)[0]
    assert resolve(group, 'shoe-42-black')['product_id'] == 'shoe-42-black'
    assert resolve(group, 'shoe-42-black', {'size_eu':'eu475', 'colour':'black'})['product_id'] == 'shoe-475-black'
    assert resolve(group, 'shoe-42-black', {'size_eu':'eu475', 'colour':'blue'}) == {
        'status':'unlisted', 'selection':{'size_eu':'eu475','colour':'blue'}, 'product_id':None}
    assert resolve(group, 'shoe-42-black', {'colour':'blue'})['status'] == 'incomplete'
    assert resolve(group, 'shoe-42-black', {'size_eu':'eu42', 'colour':'blue'})['product_id'] == 'shoe-42-blue'
    with pytest.raises(ValueError): resolve(group, 'shoe-42-black', {'size_eu':'EU 42','colour':'black'})
    with pytest.raises(ValueError): resolve(group, 'shoe-42-black', {'unknown':'x'})


@pytest.mark.parametrize('defect', ['duplicate-tuple','duplicate-sku','wrong-fact','unknown-option','private-field','bool-size','duplicate-value'])
def test_rejects_ambiguous_or_mislabeled_contract(bundle, defect):
    world, groups = bundle
    group = groups[0]
    if defect == 'duplicate-tuple': group['variants'][1]['selection'] = deepcopy(group['variants'][0]['selection'])
    if defect == 'duplicate-sku': group['variants'][1]['product_id'] = group['variants'][0]['product_id']
    if defect == 'wrong-fact': world['products'][-1]['attributes']['size_eu'] = 44
    if defect == 'unknown-option': group['variants'][0]['selection']['colour'] = 'red'
    if defect == 'private-field': group['answer'] = 'shoe-42-black'
    if defect == 'bool-size': group['axes'][0]['options'][0]['value'] = True
    if defect == 'duplicate-value': group['axes'][0]['options'][1]['value'] = 42.0
    with pytest.raises(ValueError): validate_groups(groups, world)


def runtime_for(bundle):
    world, groups = bundle
    return Runtime(world, retailer_designs=SHOWCASE, product_groups=groups,
                   checkout_flows={s:'express' for s in SHOWCASE}, cart_navigation={s:'inline' for s in SHOWCASE},
                   cart_addition={s:'increment' for s in SHOWCASE})


def get(url):
    with urlopen(url, timeout=5) as r:return r.geturl(), r.read().decode()


def post(origin, fields):
    return get_request(Request(origin+'/cart/set', data=urlencode(fields).encode()))


def get_request(request):
    with urlopen(request, timeout=5) as r:return r.geturl(), r.read().decode()


def test_http_get_readonly_stale_selection_and_inventory_guard(bundle):
    with runtime_for(bundle) as runtime:
        origin = runtime.origins['nordhem']
        fields = {'offer_id':'offer-shoe-42-black-nordhem','option_size_eu':'eu475','option_colour':'black','quantity':'1'}
        url, html = post(origin, fields)
        assert 'selection_changed' in url and '990.00 SEK' in html
        assert runtime.snapshot()['carts']['nordhem'] is None
        fields['offer_id'] = 'offer-shoe-475-black-nordhem'
        fields['quantity'] = '2'
        post(origin, fields)
        before = runtime.snapshot()
        assert before['carts']['nordhem']['quantity'] == 2
        # Repeat Add would exceed the exact SKU's stock; reject before mutation.
        fields['quantity'] = '1'
        url, html = post(origin, fields)
        assert 'ineligible_quote' in url
        assert runtime.snapshot()['carts'] == before['carts']
        for query in ['option_size_eu=&option_colour=black', 'option_size_eu=eu475&option_colour=blue']:
            _, html = get(origin+'/products/shoe-42-black?'+query)
            assert 'Add to cart' not in html
            assert runtime.snapshot() == before
        with pytest.raises(HTTPError) as exc:
            get(origin+'/products/shoe-42-black?option_size_eu=bogus&option_colour=black')
        assert exc.value.code == 400
        # Different browser/retailer cannot buy this merchant's hidden offer.
        with pytest.raises(HTTPError):
            get(origin+'/products/shoe-42-black?option_colour=black&option_colour=blue')
        post(runtime.origins['teknikgarden'], fields)
        assert runtime.snapshot()['carts']['teknikgarden'] is None


def test_same_layout_supports_swapped_control_types_and_no_runtime_mutation(bundle):
    world, groups = bundle
    original = deepcopy((world, groups))
    with Runtime(world, retailer_designs=SHOWCASE, product_groups=groups,
                 product_control_styles={'nordhem':{'size_eu':'radio','colour':'select'}}) as runtime:
        _, html = get(runtime.origins['nordhem']+'/products/shoe-42-black')
        assert 'type="radio" name="option_size_eu"' in html
        assert '<select name="option_colour">' in html
        assert 'commerce-product-controls-v1' not in html
    assert (world, groups) == original
