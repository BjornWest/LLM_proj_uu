"""Current corpus parity, three authored structures and versioned sampling."""
from copy import deepcopy
import json
from pathlib import Path
from urllib.parse import urlsplit, parse_qsl, unquote
from html.parser import HTMLParser
import pytest
from environments.website_world.native_review_pages import NativeReviewPage, LAYOUTS
from environments.website_world import native_review_ecosystem as rich, rich_ecosystem as old, surrounding_config, catalog_adapter, unified_generation
from environments.website_world.adapter import ROOT


@pytest.fixture(scope='module')
def world():
    return json.loads((ROOT/'.local/accepted-catalog-commerce-pin-v2/world.private.json').read_text())


@pytest.fixture
def public():
    return {'p':{'product_id':'p','name':'Test Shirt','family_id':'tops','facts':{'cotton':False,'weight_g':0,'secret':None},
        'fact_status':{'secret':'unknown'},'skus':[{'sku_id':'s1','product_id':'p','size_label':'S'},{'sku_id':'s2','product_id':'p','size_label':'L'}],
        'reviews': [{'review_id':f'note-{n}','reviewer':f'Reader {n}','product_id':'p','sku_id':'s1' if n%2 else 's2','rating':5 if n%2 else 3,'text':f'Exact note {n} <raw>' if n<5 else ''} for n in range(7)],
        'rating_summary':{'rating_count':7,'written_review_count':5,'rating_only_count':2,'average_rating':3.86,'star_counts':{'1':0,'2':0,'3':4,'4':0,'5':3}}},
        'other':{'product_id':'other','name':'Other Shirt','family_id':'tops','facts':{},'skus':[], 'reviews':[],
        'rating_summary':{'rating_count':0,'written_review_count':0,'rating_only_count':0,'average_rating':None,'star_counts':dict.fromkeys('12345',0)}}}


def view(layout, public):
    site={'name':'Review Atlas','layout':layout,'families':['tops'],'family_labels':{'tops':'Tops'},'review_presentation':{'version':'native-review-presentation-v1','page_size':2}}
    bindings={'o':{'retailer_id':'shop','product_id':'p','sku_id':'s1','url':'http://localhost:7000/#/product/p?size=S','model_url':'http://localhost:7000/#/product/p'}}
    return NativeReviewPage(site,public,bindings,{'shop':'Shop'},None)


@pytest.mark.parametrize('layout',LAYOUTS)
def test_three_designs_keep_all_ratings_exact_comments_scope_and_pagination(public,layout):
    before=deepcopy(public);page=view(layout,public)
    q={'part':'readers'} if layout=='editorial-magazine' else {}
    html=page.page('/reviews/p',q)[1]
    assert '7 ratings; 5 written reviews, 2 ratings without comments' in html
    assert 'Model-wide rating summary' in html
    assert html.count('<blockquote>')==2
    assert 'Exact note 0 &lt;raw&gt;' in html
    assert 'note-5' not in html and 'note-6' not in html
    assert 'Unknown' not in html and 'secret' not in html and '<time>' not in html
    assert '/variants/s2' in html
    assert 'Next' in html
    filtered=page.page('/reviews/p',{**q,'stars':'5','sku':'s1'})[1]
    assert '2 matching written comments' in filtered
    assert '7 ratings; 5 written reviews' in filtered
    assert 'Exact note 0' not in filtered and 'Exact note 1' in filtered and 'Exact note 3' in filtered
    pages=[page.page('/reviews/p',{**q,'page':str(n)})[1] for n in (1,2,3)]
    assert sum(h.count('<blockquote>') for h in pages)==5
    note=page.page('/reviews/p/opinions/note-1',{})[1]
    assert 'Exact note 1' in note and '/variants/s1' in note
    option=page.page('/variants/s1',{})[1]
    assert 'http://localhost:7000/#/product/p?size=S' in option
    assert 'No customer ratings' in page.page('/reviews/other',q)[1]
    assert public==before


@pytest.mark.parametrize('layout',LAYOUTS)
def test_native_discovery_routes_real_covered_records_and_no_fabricated_fields(public,layout):
    page=view(layout,public)
    for route,q in [('/',{}),('/catalog',{}),('/search',{'q':'shirt'}),('/activity',{'stars':'3'}),('/members',{}),('/members/Reader%201',{}),('/compare',{'left':'p','right':'other'}),('/methodology',{})]:
        status,html,_=page.page(route,q)
        assert status==200 and 'Product Reader' not in html
        assert '<time>' not in html and 'Newest' not in html and 'Recent' not in html
        assert 'model_price_factor' not in html
    if layout=='lab-directory':assert 'Review contents' in page.page('/reviews/p',{})[1]
    elif layout=='editorial-magazine':
        assert 'Article pages' in page.page('/reviews/p',{})[1]
        assert '<blockquote>' not in page.page('/reviews/p',{})[1]
        assert 'weight g' in page.page('/reviews/p',{'part':'specifications'})[1].casefold()
        assert 'part=readers' in page.page('/reviews/p',{'part':'readers'})[1]
    else:assert 'class="feed"' in page.page('/',{})[1]
    page.index_origin='http://localhost:9999'
    assert 'http://localhost:9999/' in page.page('/',{})[1]
    for bad in [{'sort':'newest'},{'sku':'unknown'},{'page':'0'},{'stars':'9'},{'private':'yes'}]:
        with pytest.raises(ValueError):page.page('/reviews/p',bad)
    with pytest.raises(KeyError):page.page('/reviews/p/opinions/note-5',{})


def test_versioned_sampling_distinct_layouts_independent_names_and_explicit_weights(world):
    before=deepcopy(world)
    sidecar=rich.generate(world,{'review_count':3})
    rich.validate(world,sidecar)
    reviews=[s for s in sidecar['sites'] if s['kind']=='product_reviews']
    assert {s['layout'] for s in reviews}==set(LAYOUTS)
    assert len({s['name'] for s in reviews})==3
    assert all(s['product_ids']==sorted(p['public']['product_id'] for p in world['products']) for s in reviews)
    forced=rich.generate(world,{'review_count':3,'review_layout_weights':dict(zip(LAYOUTS,[0,1,0]))})
    assert {s['layout'] for s in forced['sites'] if s['kind']=='product_reviews'}=={'editorial-magazine'}
    assert [s['name'] for s in forced['sites'] if s['kind']=='product_reviews']==[s['name'] for s in reviews]
    legacy=old.generate(world)
    assert [s for s in sidecar['sites'] if s['kind']=='aggregator']==[s for s in legacy['sites'] if s['kind']=='aggregator']
    changed=deepcopy(world);changed['task']={'private':'unrelated'};changed['reference']={}
    assert rich.generate(changed,{'review_count':3})['sites']==sidecar['sites']
    assert world==before
    assert surrounding_config.options({'version':rich.VERSION,'review_count':3})['version']==rich.VERSION
    unified_generation.compile_request({'schema':unified_generation.VERSION,'seed':1,'surrounding_sites':{'version':rich.VERSION,'review_count':3}})
    broken=deepcopy(sidecar);broken['sites'][-1]['layout']='bad'
    with pytest.raises(ValueError):rich.validate(world,broken)


def test_fresh_defaults_adopt_rich_reviews_historic_requests_remain_v2():
    request = {'schema':unified_generation.VERSION,'seed':1}
    assert unified_generation.compile_request(request)['surrounding_options']['version']==rich.VERSION
    assert unified_generation.compile_request({**request,'surrounding_sites':{'review_layout_weights':{'journal':1,'community':0}}})['surrounding_options']['version']==old.VERSION
    assert unified_generation.compile_request({**request,'surrounding_sites':{'version':old.VERSION}})['surrounding_options']['version']==old.VERSION


@pytest.mark.parametrize('options',[{'review_page_size':0},{'review_page_size':True},{'review_assignment':'bad'},
    {'review_assignment':'distinct','review_count':4},{'review_count':3,'review_assignment':'distinct','review_layout_weights':dict(zip(LAYOUTS,[0,1,0]))}])
def test_impossible_or_unknown_configuration_rejects(options):
    with pytest.raises(ValueError):rich.options(options)
