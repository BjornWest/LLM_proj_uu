"""Review presentation preserves silent ratings, attribution and exact filters."""
from copy import deepcopy
import pytest
from environments.website_world.surrounding_pages import ReviewPage, path
from environments.website_world.test_rich_surrounding import view


@pytest.fixture
def product():
    return {'name':'Aster Shoe','facts':{'waterproof':False},'skus':[
        {'sku_id':'s1','product_id':'p','size_eu':39}, {'sku_id':'s2','product_id':'p','size_eu':42}],
        'reviews':[
            {'review_id':'one','reviewer':'Reader One','sku_id':'s1','rating':5,'text':'Good <fit>.'},
            {'review_id':'two','reviewer':'Reader Two','sku_id':'s2','rating':3,'text':'Wide.'},
            {'review_id':'silent','reviewer':'Reader Three','sku_id':'s2','rating':5,'text':''}],
        'rating_summary':{'rating_count':3,'written_review_count':2,'rating_only_count':1,
            'average_rating':4.33,'star_counts':{'1':0,'2':0,'3':1,'4':0,'5':2}},
        'guidance':{'fit_text':'Editorial sizing guidance.'}}


@pytest.mark.parametrize('layout',['journal','community'])
def test_review_summary_filters_identity_and_source_preservation(product,layout):
    before=deepcopy(product)
    page=ReviewPage({'name':'Readers','layout':layout,'families':['footwear']},{'p':product},{},{},None)
    html=page.page(path('reviews','p'),{})[1]
    assert 'Review publication' in html and 'All recorded ratings, including ratings without comments' in html
    assert '3 ratings; 2 written reviews, 1 ratings without comments' in html
    assert 'Reader One' in html and 'Reader Two' in html and 'Reader Three' not in html
    assert 'Good &lt;fit&gt;.' in html and 'False' not in html and 'No' in html
    assert 'Editorial guidance, separate from customer votes' in html
    selected=page.page(path('reviews','p'),{'stars':'5','sku':'s1'})[1]
    assert 'Reader One' in selected and 'Reader Two' not in selected
    assert 'stars=3&amp;sku=s1' in selected
    assert 'same source' in page.page('/about',{})[1]
    assert product==before
    page.index_origin='http://localhost:9876'
    assert 'http://localhost:9876/' in page.page('/',{})[1]
    del product['rating_summary']['star_counts']
    other=ReviewPage({'name':'Other','layout':layout},{'p':product},{},{},None)
    assert '<table>' not in other.page(path('reviews','p'),{})[1]


def test_inconsistent_histogram_rejects(product):
    product['rating_summary']['star_counts']['5']=3
    page=ReviewPage({'name':'Readers','layout':'community'},{'p':product},{},{},None)
    with pytest.raises(ValueError):page.page(path('reviews','p'),{})


@pytest.mark.parametrize('modules', [('directory','ledger','finder'),('finder','directory','ledger')])
def test_comparison_tool_mode_omits_index_links_preserves_routes(modules):
    page=view(modules)
    for child in page.views.values():child.index_origin=None
    for route,query in [('/',{}),('/search',{'q':'absent'}),('/models/shoe%2Fone',{}),('/about',{})]:
        status,html,_=page.page(route,query)
        assert status==200 and 'http://localhost:2345' not in html
    assert 'http://localhost:1234/product/shoe/one' in page.page('/retailers',{'id':'shoe/one'})[1] if modules[2]=='finder' else '120.00 SEK' in page.page('/models/shoe%2Fone',{})[1]
