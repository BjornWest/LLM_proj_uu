"""Cross-family presentation regressions; no frozen world or live server required."""
from copy import deepcopy
from types import SimpleNamespace
import pytest
from . import pages
from .conformance import Document,table_rows


@pytest.mark.parametrize('family,attrs,expected',[
    ('laptops',{'ram_gb':16},{'16 GB'}),
    ('footwear',{'waterproof':False},{'No'}),
    ('wine',{'grape_varieties':[]},{'None listed'}),
])
def test_specs_and_cards_keep_units_and_typed_values(family,attrs,expected):
    product={'product_id':'a','name':'A < B','category':family,'attributes':attrs}
    original=deepcopy(product)
    owner=SimpleNamespace(origins={'store':'http://example.test'},offer_by_store={('store','a'):{'offer_id':'o','price_minor':1234,'stock_quantity':0}},quote=lambda _: {'eligible':False})
    facts=Document(pages.table(product)).root
    assert set(dict(table_rows(facts.one('table'))).values())==expected
    cards=Document(pages.cards(owner,'store',[product])).root
    assert all(v in cards.text() for v in expected)
    assert '12.34 SEK' in cards.text() and 'Unavailable for delivery' in cards.text()
    assert product==original
    assert cards.find('img')[0].attrs['alt']=='A < B — catalog illustration'


def test_related_models_are_diverse_without_changing_selection_or_stock():
    products=[{'product_id':x} for x in ['a1','a2','b1','b2','c1']]
    owner=SimpleNamespace(group_for={p['product_id']:{'group_id':p['product_id'][0]} for p in products},catalog=lambda site:{'products':products})
    assert pages.related_products(owner,'store','a2')==[products[2],products[4]]
    assert pages.related_products(owner,'store','a1',limit=1)==[products[2]]
    assert [p['product_id'] for p in products]==['a1','a2','b1','b2','c1']


def test_unitless_old_specification_is_no_longer_accepted():
    from .test_conformance import PRODUCT,P,O,G
    from .conformance import product_check
    from environments.product_review_sites.data import field_info
    html=PRODUCT.replace('<th>RAM</th>','<th>'+field_info('laptops','ram_gb')[0]+'</th>')
    with pytest.raises(AssertionError,match='product facts'):
        product_check(Document(html.replace('16 GB','16')).root,P,O,G,{'ram_gb':'ram-16'})
