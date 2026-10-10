"""Optional public inputs cannot leave empty sections or orphan navigation."""
from copy import deepcopy
from urllib.parse import unquote
import pytest
from bs4 import BeautifulSoup
from environments.website_world.comparison_pages import ComparisonPage, LAYOUTS
from environments.website_world.surrounding_pages import ComparisonPage as LegacyComparison, ReviewPage, facts
from environments.website_world.test_rich_surrounding import view


def sparse_comparison(layout, shape):
    original=view((layout,layout,layout))
    products={'shoe/one':deepcopy(original.products['shoe/one'])}
    if shape=='missing':products['shoe/one'].pop('facts')
    elif shape=='null':products['shoe/one']['facts']=None
    elif shape=='blank':products['shoe/one']['facts']={'empty':None,'blank':'  ','list':[],'group':{}}
    else:products['shoe/one']['facts']={}
    bindings={'shoe/one-offer':{'retailer_id':'store','product_id':'shoe/one','model_url':'http://localhost:1234/product/shoe/one'}}
    return ComparisonPage(original.site,products,bindings,{'store':'Fixture Store'},'http://localhost:2345',{}),products


def no_empty_fact_shells(body):
    soup=BeautifulSoup(body,'html.parser')
    assert not [x for x in soup.select('dl,p,li,tbody') if not x.get_text(strip=True) and not x.find(['input','a','button'])]
    for a in soup.select('a[href^="#"]'):
        assert soup.find(id=unquote(a['href'][1:])) is not None,a
    return soup


@pytest.mark.parametrize('layout',LAYOUTS)
@pytest.mark.parametrize('shape',['empty','missing','null','blank'])
def test_sparse_product_has_no_spec_related_review_shells_or_orphan_links(layout,shape):
    page,source=sparse_comparison(layout,shape);before=deepcopy(source)
    body=page.page('/models/shoe%2Fone',{})[1];soup=no_empty_fact_shells(body)
    assert not soup.select('a[href^="/details"],#specifications,#related')
    assert not any(h.get_text(strip=True) in ('Related products','Other products in this department','More in this collection','Customer experiences','What this product offers','Product specifications') for h in soup.select('h2'))
    assert '120.00 SEK' in body
    assert 'http://localhost:1234/product/shoe/one' in body or '/retailers?id=shoe%2Fone' in body
    details=no_empty_fact_shells(page.page('/details',{'id':'shoe/one'})[1])
    assert details.find('table') is None
    assert 'No product specifications are published here.' in details.get_text()
    search=page.page('/search',{'category':'footwear'})[1]
    assert 'waterproof' not in search.casefold()
    assert source==before


@pytest.mark.parametrize('layout',LAYOUTS)
def test_nonempty_facts_and_related_and_reviews_remain(layout):
    page=view((layout,layout,layout));body=page.page('/models/shoe%2Fone',{})[1]
    assert 'Waterproof' in body and ('Yes' in body or 'True' in body)
    assert '120.00 SEK' in body and 'http://localhost:3456/reviews/shoe' in body
    assert 'Full' in body or 'Specifications' in body or 'What this product offers' in body
    no_empty_fact_shells(body)


@pytest.mark.parametrize('layout',LAYOUTS)
def test_empty_facet_domain_drops_controls_without_dropping_other_known_values(layout):
    page=view((layout,layout,layout));design=page.views[layout]
    shoe=design.by_id['shoe/one'];shoe['attribute_status']={'waterproof':'unknown'}
    assert design.facet_options('footwear')=={}
    filtered=BeautifulSoup(page.page('/search',{'category':'footwear'})[1],'html.parser')
    assert not filtered.select('input[name="f_waterproof_0"]')
    shoe['attributes']['waterproof']=False;shoe['attribute_status']['waterproof']='known'
    assert design.facet_options('footwear')=={'waterproof':['False']}


def review_product(value):
    product={'name':'Fixture Shoe','family_id':'footwear','skus':[{'sku_id':'sku','size_eu':42}],
        'reviews':[],'rating_summary':{'average_rating':None,'rating_count':0,'written_review_count':0,'rating_only_count':0},
        'guidance':{'fit_text':'  '},'listings':[]}
    if value!='missing':product['facts']=value
    return product


@pytest.mark.parametrize('layout',['community','editorial'])
@pytest.mark.parametrize('value',[{},None,'missing'])
def test_review_omits_missing_facts_guidance_and_retailer_links(layout,value):
    source={'shoe':review_product(value)};before=deepcopy(source)
    page=ReviewPage({'name':'Reader','layout':layout,'families':['footwear']},source,{}, {},'http://localhost:2345')
    body=page.page('/reviews/shoe',{})[1];no_empty_fact_shells(body)
    assert 'Published model facts' not in body and 'Editorial fit guidance' not in body and 'Retailer pages' not in body
    assert 'No written comments match these filters.' in body and 'size eu: 42' in body
    assert source==before


@pytest.mark.parametrize('layout',['directory','ledger'])
@pytest.mark.parametrize('value',[{},None,'missing'])
def test_legacy_comparator_omits_missing_specification_wrapper(layout,value):
    page=LegacyComparison({'name':'Prices','layout':layout,'as_of':'2026-10-05'},
        {'shoe':review_product(value)}, {}, {},'http://localhost:2345',{})
    body=page.page('/models/shoe',{})[1];no_empty_fact_shells(body)
    assert 'Model specifications' not in body
    assert 'No retailer offers are tracked' in body
    no_empty_fact_shells(page.page('/',{})[1])


def test_false_zero_and_explicit_unknown_displays_are_not_empty_data():
    body=facts({'pockets':False,'mass':0,'material':'Not provided','absent':None,'blank':'   '})
    soup=BeautifulSoup(body,'html.parser')
    assert [x.text for x in soup.select('dt')]==['Pockets','Mass','Material']
    assert [x.text for x in soup.select('dd')]==['No','0','Not provided']


def test_malformed_optional_fact_container_is_not_silently_erased():
    with pytest.raises(TypeError,match='must be a mapping'):facts([])


@pytest.mark.parametrize('layout',LAYOUTS)
def test_no_offers_or_related_products_preserves_working_empty_state(layout):
    page,_=sparse_comparison(layout,'empty')
    for design in page.views.values():design.items[0]['listings']=[]
    route='/retailers' if layout=='finder' else '/models/shoe%2Fone'
    query={'id':'shoe/one'} if layout=='finder' else {}
    body=page.page(route,query)[1];soup=no_empty_fact_shells(body)
    assert not soup.select('table,select[name="merchant"]')
    assert 'No matching retailer listings' in body or 'No retailer listings' in body or 'no tracked retailer listings' in body
