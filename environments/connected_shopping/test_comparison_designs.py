from types import SimpleNamespace
from urllib.request import urlopen
from urllib.error import HTTPError
import pytest
from .test_comparison import world
from .comparison import build
from .comparison_designs import Design
from .http import Site


@pytest.fixture
def owner():
    w=world();p=w['public']
    return SimpleNamespace(comparisons=build(w),offers={str(i):o for i,o in enumerate(p['offers'])},stores={'a':{'name':'Store A'},'b':{'name':'Store B'}},group_for={v['product_id']:g for g in p['product_groups'] for v in g['variants']},families=['footwear','laptops'],origins={'a':'http://localhost:1','b':'http://localhost:2','reviews-footwear':'http://localhost:3','reviews-laptops':'http://localhost:4','merchant-reviews':'http://localhost:5'},index_origin='http://localhost:6')


@pytest.mark.parametrize('layout',['directory','specialist'])
def test_semantics_price_and_structure(owner,layout):
    d=Design(owner,layout=layout,family='footwear' if layout=='specialist' else None)
    _,html=d.render('/models/shoe',{})
    assert '100.00 SEK' in html and '110.00 SEK' not in html
    assert 'Shoe 40 black' not in html and 'Shoe 42 blue' not in html
    assert html.count('View offer at Store A')==1 and html.count('View offer at Store B')==1
    assert ('<caption>Advertised item prices' in html)==(layout=='directory')
    assert ('<details class="offer"' in html)==(layout=='specialist')


def test_real_filters_and_limits(owner):
    d=Design(owner)
    assert d.filtered({'category':'footwear','f_activity_0':'1'})[0][0]['id']=='shoe'
    assert not d.filtered({'category':'footwear','max_price':'99.99'})[0]
    assert len(d.filtered({'category':'footwear','max_price':'100'})[0])==1
    for q in [{'max_price':'NaN'},{'max_price':'-1'},{'max_price':'1.001'},{'category':'unknown'},{'f_size_eu_0':'1'},{'sort':'magic'}]:
        with pytest.raises(ValueError):d.filtered(q)


def test_multi_select_or_within_field_and_across_fields(owner):
    item=dict(owner.comparisons[0],id='other',name='Other',attributes={'activity':'walking','waterproof':True});owner.comparisons[0]['attributes']['waterproof']=False
    owner.comparisons.append(item);d=Design(owner)
    assert len(d.filtered({'category':'footwear','f_activity_0':'1','f_activity_1':'1'})[0])==2
    assert len(d.filtered({'category':'footwear','f_activity_0':'1','f_activity_1':'1','f_waterproof_1':'1'})[0])==1


def test_specialist_reuse_and_scope(owner):
    for family in owner.families:
        d=Design(owner,layout='specialist',family=family)
        assert all(x['category']==family for x in d.items)
        _,html=d.render('/search',{'category':family});assert '<summary>Filter this collection' in html
    with pytest.raises(ValueError):Design(owner,layout='specialist',family='wine')
    with pytest.raises(ValueError):Design(owner,layout='specialist',family='footwear').filtered({'category':'laptops'})


def test_comparison_missing_and_private_routes(owner):
    d=Design(owner)
    assert 'Compare product facts' in d.render('/compare',{'pick0':'shoe','pick1':'l1'})[1]
    assert 'Not specified' in d.render('/compare',{'pick0':'shoe','pick1':'l1'})[1]
    with Site(d.render) as s:
        for path in ['/','/search','/models/shoe','/products/l1','/details?id=shoe','/about','/compare?pick0=shoe&pick1=l1']:
            assert urlopen(s.origin+path).status==200
        for path in ['/scenario.private.json','/api/state','/reference','/models/nope']:
            with pytest.raises(HTTPError) as error:urlopen(s.origin+path)
            assert error.value.code==404


def test_model_stock_is_not_entry_size_stock(owner):
    d=Design(owner);item=d.by_id['shoe'];row=d.offers(item)[0]
    assert row['entry_product_id']=='s1'  # sold out, while a different size is stocked
    assert d.stock(item,row)=='some_options'
    assert 'check your size' in d.stock_text(item,row)
    before=d.price(item)
    for o in owner.offers.values():o['stock_quantity']=0
    assert d.stock(item,row)=='out_of_stock' and d.price(item)==before
    owner.offers['0']['stock_quantity']=None
    assert d.stock(item,row)=='unknown'


def test_lowest_retailer_ties_preserve_advertised_price(owner):
    d=Design(owner);item=d.by_id['shoe'];card=d.card(item)
    assert [r['retailer_id'] for r in d.lowest_retailers(item)]==['a','b']
    assert 'href="http://localhost:1/products/s1"' in card
    assert 'href="http://localhost:2/products/s2"' in card
    assert '100.00 SEK' in card and '120.00 SEK' not in card
    assert 'Lowest advertised at:' in card and 'delivered' not in card


def test_exact_stock_and_empty_search_are_clear(owner):
    owner.offers['3']={'retailer_id':'a','product_id':'l1','price_minor':10000,'stock_quantity':2}
    d=Design(owner);item=d.by_id['l1'];row=d.offers(item)[0]
    assert d.stock_text(item,row)=='In stock'
    owner.offers['3']['stock_quantity']=0
    assert d.stock_text(item,row)=='Out of stock'
    page=d.search({'q':'NONEXISTENT'})
    assert 'No products match these filters' in page
    assert 'Compare selected products</button>' not in page
    # Category changes use navigation, so old field-specific selections cannot be submitted into another category.
    page=d.search({'category':'footwear','f_activity_0':'1'})
    assert '<select name="category"' not in page
    assert 'name="category" value="footwear"' in page
