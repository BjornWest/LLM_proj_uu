"""Stock UI is bound to exact SKU/quantity, never retailer aggregate stock."""
from urllib.request import urlopen
from urllib.parse import urlencode
import pytest
from environments.product_world.test_branch_shipping import fixture
from .runtime import Runtime
from .conformance import Document


@pytest.mark.parametrize('enabled',[0,1])
def test_local_stock_without_warehouse_stock(enabled):
    scenario=fixture(enabled=enabled,stockout=1)
    with Runtime(scenario,consent=False) as rt:
        offer=next(iter(rt.offers.values()));sid=offer['retailer_id']
        html=urlopen(rt.origins[sid]+'/products/'+offer['product_id']).read().decode()
        root=Document(html).root
        disclosure=next(d for d in root.find('details') if d.attrs.get('id')=='store-stock')
        assert 'open' not in disclosure.attrs
        assert offer['product_id'] in disclosure.text()
        assert 'Available from stock at this store' in disclosure.text()
        assert ('Ships online orders: Yes' in disclosure.text())==bool(enabled)
        assert ('Availability: Available' in root.text())==bool(enabled)
        assert 'Online warehouse stock: 0' in root.text()
        q=rt.quote(offer['offer_id'])
        if enabled:
            assert q['source_kind']=='branch'
            branch=next(b for b in rt.merchants[sid]['branches'] if b['location']['location_id']==q['stock_source'])
            assert 'Ships from '+branch['location']['city'] in root.text()
        else:assert 'Ships from ' not in root.text()
        # Individual branch links retain exact item, retailer and requested quantity.
        links=[a.attrs['href'] for a in disclosure.find('a')]
        assert links and all('offer_id='+offer['offer_id'] in l and 'quantity=1' in l for l in links)
        large=urlopen(rt.origins[sid]+'/products/'+offer['product_id']+'?'+urlencode({'quantity':100})).read().decode()
        assert 'Availability: <strong>Unavailable' in large
        assert 'requested quantity: 100' in large


def test_option_change_updates_branch_stock_identity():
    with Runtime(fixture(),consent=False) as rt:
        offer=next(iter(rt.offers.values()));sid=offer['retailer_id'];sku=offer['product_id']
        group=rt.group_for[sku]
        other=next(v for v in group['variants'] if v['product_id']!=sku and (sid,v['product_id']) in rt.offer_by_store)
        # Canonical variant selection is the renderer's existing contract.
        target=urlopen(rt.origins[sid]+'/products/'+other['product_id']).read().decode()
        d=next(d for d in Document(target).root.find('details') if d.attrs.get('id')=='store-stock')
        assert 'Selected SKU: '+other['product_id'] in d.text()
        assert 'Selected SKU: '+sku not in d.text()
