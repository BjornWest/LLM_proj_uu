"""Optional seeded comparator browsing; synthetic coverage, no model/draw."""
from copy import deepcopy
from itertools import product

import pytest

from . import rich_ecosystem as rich, native_review_ecosystem as reviews
from .comparison_pages import LAYOUTS
from .test_rich_surrounding import view


def world():
    return {'seed':73,'world_id':'synthetic-comparison-search','quote_as_of':'2026-09-30',
        'products':[{'public':{'product_id':'shoe','family_id':'footwear','facts':{'waterproof':True}}}],
        'retailers':[{'retailer_id':'shop','offers':[{'product_id':'shoe',
            'offer_id':'shop/shoe','price_minor':12000,'currency':'SEK'}]}]}


@pytest.mark.parametrize('producer',[rich,reviews])
def test_omitted_option_preserves_legacy_sidecar_and_optional_flag_is_only_delta(producer):
    source=world();before=deepcopy(source)
    legacy=producer.generate(source)
    assert 'comparison_search_probability' not in legacy['controls']
    assert all('catalog_search' not in s.get('presentation',{}) for s in legacy['sites'])
    disabled=producer.generate(source,{'comparison_search_probability':0})
    producer.validate(source,disabled)
    enabled=producer.generate(source,{'comparison_search_probability':1})
    for sidecar,flag in ((disabled,False),(enabled,True)):
        inverse=deepcopy(sidecar);del inverse['controls']['comparison_search_probability']
        for site in inverse['sites']:
            if site['kind']=='aggregator':assert site['presentation'].pop('catalog_search') is flag
        assert inverse==legacy
    assert source==before


def test_interior_probability_has_both_finite_outcomes_and_replays():
    outcomes=set()
    for seed in range(8):
        source=world();source['seed']=seed
        value=reviews.generate(source,{'comparison_search_probability':.5})
        assert reviews.generate(source,{'comparison_search_probability':.5})==value
        outcomes.update(s['presentation']['catalog_search'] for s in value['sites'] if s['kind']=='aggregator')
    assert outcomes=={False,True}


@pytest.mark.parametrize('bad',[True,None,-.1,1.1,float('nan'),float('inf'),'0.5'])
def test_probability_rejects_malformed_values(bad):
    with pytest.raises(ValueError):reviews.options({'comparison_search_probability':bad})


@pytest.mark.parametrize('modules',list(product(LAYOUTS,repeat=3)))
def test_browsing_only_profile_retains_complete_category_models_and_merchant_links(modules):
    page=view(modules)
    page.site['presentation']['catalog_search']=False
    # Reconstruct the actual renderer units from the same complete public corpus.
    page=type(page)(page.site,{
        'shoe/one':{'name':'Fixture Shoe','family_id':'footwear','facts':{'waterproof':True},'listings':[
            {'entry_offer_id':'shoe/one-offer','retailer_id':'store','price_minor':12000,'advertised_price_minor':12000}]},
        'tablet/one':{'name':'Fixture Tablet','family_id':'tablets','facts':{'storage':128},'listings':[
            {'entry_offer_id':'tablet/one-offer','retailer_id':'store','price_minor':25000,'advertised_price_minor':25000}]}},
        {pid+'-offer':{'retailer_id':'store','product_id':pid,'model_url':'http://localhost:1234/product/'+pid}
         for pid in ('shoe/one','tablet/one')},{'store':'Fixture Store'},'http://localhost:2345',{})
    for route,query in (('/',{}),('/search',{}),('/search',{'category':'footwear'}),
                        ('/models/shoe%2Fone',{})):
        status,html,_=page.page(route,query)
        assert status==200
        assert 'name="q"' not in html
    full=page.page('/search',{})[1]
    assert 'Fixture Shoe' in full and 'Fixture Tablet' in full
    assert '/search?category=footwear' in page.page('/',{})[1]
    retailer_html=page.page('/retailers',{'id':'shoe/one'})[1] if modules[2]=='finder' else page.page('/models/shoe%2Fone',{})[1]
    assert 'http://localhost:1234/product/shoe/one' in retailer_html
    assert 'name="q"' not in retailer_html
    assert 'Fixture Shoe' in page.page('/search',{'category':'footwear','f_waterproof_0':'1','max_price':'120'})[1]
    with pytest.raises(ValueError,match='unavailable filter'):
        page.page('/search',{'q':'tablet'})

