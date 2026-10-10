"""Richer public presentation; multi-family fixtures are renderer-only evidence."""
from copy import deepcopy
from itertools import product
import json
from urllib.parse import urlencode
from urllib.request import urlopen
from urllib.error import HTTPError

import pytest

from environments.website_world import ecosystem, rich_ecosystem as rich, surrounding_config as config
from environments.website_world.adapter import ROOT
from environments.website_world.comparison_pages import ComparisonPage, LAYOUTS
from environments.website_world.runtime import Runtime

PIN=ROOT/'.local/website-e2e-address-adoption-v1/producer-example/pin'

@pytest.fixture(scope='module')
def world():return json.loads((PIN/'world.json').read_text())


def view(modules):
    # Explicit public view fixture, not evidence of released broader commerce.
    site={'name':'Fixture comparator','as_of':'2026-10-04','families':['footwear','tablets'],
        'family_labels':{'footwear':'Footwear','tablets':'Tablets'},
        'presentation':{'scope':'general','modules':dict(zip(('home','results','product'),modules)),
            'navigation':'disclosure','filters':{'attributes':{'footwear':['waterproof'],'tablets':['storage']},
                'price_ceiling':True,'sorting':True},
            'permutations':{'results':{'search_sections':True},'product':{'offer_disclosure':'expand'}}}}
    products={pid:{'name':name,'family_id':family,'facts':facts,'listings':[
        {'entry_offer_id':pid+'-offer','retailer_id':'store','price_minor':price,'advertised_price_minor':price}]}
        for pid,name,family,facts,price in [('shoe/one','Fixture Shoe','footwear',{'waterproof':True},12000),
            ('tablet/one','Fixture Tablet','tablets',{'storage':128},25000)]}
    bindings={pid+'-offer':{'retailer_id':'store','product_id':pid,'model_url':'http://localhost:1234/product/'+pid} for pid in products}
    return ComparisonPage(site,products,bindings,{'store':'Fixture Store'},'http://localhost:2345',{'shoe/one':'http://localhost:3456/reviews/shoe'})


@pytest.mark.parametrize('modules',list(product(LAYOUTS,repeat=3)))
def test_all_role_combinations_have_consistent_chrome_and_real_routes(modules):
    page=view(modules)
    pages=[page.page('/',{}),page.page('/search',{'category':'footwear'}),
        page.page('/models/shoe%2Fone',{}),page.page('/details',{'id':'shoe/one'}),
        page.page('/compare',{'pick0':'shoe/one','pick1':'tablet/one'})]
    headers=[body.split('<header>')[1].split('</header>')[0] for _,body,_ in pages]
    assert len(set(headers))==1
    assert all(status==200 for status,_,_ in pages)
    assert 'Fixture Tablet' in pages[0][1]
    assert 'Fixture Tablet' not in pages[1][1]
    assert '120.00 SEK' in pages[2][1]
    if modules[2]=='finder':
        offers=page.page('/retailers',{'id':'shoe/one'})[1]
        assert 'http://localhost:1234/product/shoe/one' in offers
    else:assert 'http://localhost:1234/product/shoe/one' in pages[2][1]
    assert '250.00 SEK' in pages[4][1]
    assert 'independent tests' not in pages[2][1]


def test_filters_match_known_values_and_reject_unavailable_controls():
    page=view(('finder','directory','ledger'))
    assert 'Fixture Shoe' in page.page('/search',{'category':'footwear','f_waterproof_0':'1','max_price':'120'})[1]
    assert 'Fixture Shoe' not in page.page('/search',{'category':'footwear','max_price':'119.99'})[1]
    assert 'Fixture Tablet' in page.page('/search',{'q':'tablet'})[1]
    with pytest.raises(ValueError):page.page('/search',{'category':'tablets','f_waterproof_0':'1'})
    with pytest.raises(KeyError):page.page('/models/hidden',{})
    with pytest.raises(ValueError):page.page('/models/shoe%2Fone',{'secret':'1'})


def test_sampler_replay_scope_independent_modules_and_unchanged_prices(world):
    controls={'scope_weights':{'general':1,'specialist':0}}
    sidecar=rich.generate(world,controls)
    rich.validate(world,sidecar)
    before=ecosystem.generate(world)
    for old,new in zip(before['sites'][:2],sidecar['sites'][:2]):
        assert new['product_ids']==old['product_ids']
        assert new['listings']==old['listings']
        assert set(new['presentation']['modules'])=={'home','results','product'}
    changed=deepcopy(world);changed['task']={'irrelevant':True};changed['reference']={}
    other=rich.generate(changed,controls)
    assert other['sites']==sidecar['sites']
    broken=deepcopy(sidecar);broken['sites'][0]['presentation']['modules']['home']='broken'
    with pytest.raises(ValueError,match='replay'):rich.validate(world,broken)


def test_specialist_scope_comes_from_actual_family_not_footwear_literal(world):
    fixture=deepcopy(world)
    # Sampler-only metadata substitution; never mounted as native commerce.
    fixture['products'][0]['public']['family_id']='tablets'
    sidecar=rich.generate(fixture,{'scope_weights':{'general':0,'specialist':1},'family_weights':{'footwear':0,'tablets':1}})
    for s in sidecar['sites'][:2]:
        assert s['families']==['tablets']
        assert s['product_ids']==[fixture['products'][0]['public']['product_id']]


def test_version_routing_retains_v1_explicit_controls(world):
    assert config.options()['version']==rich.VERSION
    controls=config.options({'comparison_layout_weights':{'directory':1,'ledger':0}})
    assert config.generate(world,controls)['schema_version']==ecosystem.VERSION
    assert config.options({'version':ecosystem.VERSION})['version']==ecosystem.VERSION
    with pytest.raises(ValueError):config.options({'version':'unknown'})


@pytest.mark.parametrize('controls',[{'module_weights':{'home':{'finder':1}}},
    {'scope_weights':{'general':0,'specialist':0}},{'navigation_weights':{'categories':float('nan'),'disclosure':1,'search-first':1}},
    {'scope_weights':{'general':1e308,'specialist':1e308}},{'sorting_probability':True},{'family_weights':{'tablets':-1}}])
def test_invalid_controls(controls):
    with pytest.raises(ValueError):rich.options(controls)


def test_empty_coverage_is_not_repaired(world):
    sidecar=rich.generate(world,{'model_probability':0})
    assert all(not s['product_ids'] and not s['listings'] for s in sidecar['sites'][:2])


def test_real_host_index_category_search_details_and_quote_boundary(world):
    sidecar=rich.generate(world,{'model_probability':1,'retailer_pair_probability':1,
        'scope_weights':{'general':1,'specialist':0},'module_weights':{
            role:{k:int(k==layout) for k in LAYOUTS} for role,layout in
                [('home','finder'),('results','directory'),('product','ledger')]}})
    with Runtime(PIN,surrounding=sidecar) as runtime:
        origin=runtime.surrounding_origins['comparison-00']
        site=sidecar['sites'][0];pid=site['product_ids'][0]
        assert 'Footwear' in urlopen(origin+'/').read().decode()
        body=urlopen(origin+'/search?'+urlencode({'category':'footwear','q':pid})).read().decode()
        assert ecosystem.public_products(world)[pid]['name'] in body
        path=runtime.bindings['surrounding']['comparison_products'][pid][0]
        assert 'Retailer price list' in urlopen(path).read().decode()
        assert runtime.world['reference']==world['reference']
        assert runtime.discovery.catalog.search(q=ecosystem.public_products(world)[pid]['name'],kind='aggregator')
        with pytest.raises(HTTPError) as response:urlopen(origin+'/models/hidden')
        assert response.value.code==404
        with pytest.raises(HTTPError) as response:urlopen(origin+'/surrounding.private.json')
        assert response.value.code==404
