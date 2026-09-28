"""Presentation choices must stay private, deterministic and commerce-independent."""
import copy
import pytest
from environments.procedural_commerce.presentation import resolve_presentations,SHOWCASE
from environments.procedural_commerce.generator import generate_world,retailer_view
from environments.procedural_commerce.renderers import render_page,_search_products
from environments.procedural_commerce.runtime import Runtime


def test_seeded_options_stable_without_mutating_world():
    world=generate_world(7);before=copy.deepcopy(world)
    sites=list(SHOWCASE)
    a=resolve_presentations(7,sites,SHOWCASE)
    assert a==resolve_presentations(7,sites,SHOWCASE)
    b=resolve_presentations(7,sites,SHOWCASE,{'nordhem':{'image_count':2}})
    assert {k:v for k,v in a[1]['nordhem'].items() if k!='image_count'}=={k:v for k,v in b[1]['nordhem'].items() if k!='image_count'}
    assert a[1]['vardagslagret']==b[1]['vardagslagret']
    assert world==before


@pytest.mark.parametrize('options',[{'nordhem':{'image_count':True}},{'nordhem':{'nav_expanded':1}},{'nordhem':{'title_style':'oracle'}},{'foreign':{}},{'nordhem':{'secret':42}}])
def test_bad_presentation_options_rejected(options):
    with pytest.raises((ValueError,TypeError)):resolve_presentations(7,list(SHOWCASE),SHOWCASE,options)


def test_all_words_search_is_order_independent_with_empty_and_no_match():
    products=[{'product_id':'sku-001','name':'Nordvale Halo Table Lamp','category':'lighting','attributes':{'room':'indoor'}}]
    assert _search_products(products,{'q':'lamp Nordvale'})==products
    assert _search_products(products,{'q':'  INDOOR table '})==products
    assert _search_products(products,{'q':''})==products
    assert not _search_products(products,{'q':'lamp toaster'})
    assert not _search_products(products,{'q':'lamp','category':'kitchen'})


def test_legacy_style_transfer_preserves_brand_and_links():
    world=generate_world(7);catalog=retailer_view(world,'nordhem')
    origins={site:'http://localhost:'+str(19000+i) for i,site in enumerate(['aggregator',*SHOWCASE])}
    pages=[]
    for style in ('catalog','boutique','specifications'):
        ctx={'catalog':catalog,'layout_variant':'compact','presentation_options':{'legacy_style':style}}
        p=render_page('nordhem','/search',{},ctx,origins);pages.append(p)
        assert 'Nordhem' in p
        assert origins['nordhem']+'/products/' in p
        assert origins['vardagslagret'] not in p
    assert '<table' in pages[0]
    assert '<ol' in pages[1]
    assert 'spec-first-results' in pages[2]
