"""Contract tests: navigation changes must never change commercial facts."""
from copy import deepcopy
from urllib.parse import urlencode
from urllib.request import urlopen
import pytest
from environments.product_world.scenario import generate_scenario
from environments.product_world.interaction_patterns import generate_interaction_patterns
from environments.product_world.generator import digest
from .runtime import Runtime
from .pages import money
from .conformance import Document
from .test_comparison_designs import owner
from .comparison_designs import Design
from .comparison_alternatives import Ledger,Finder


def specimen():
    s=generate_scenario({'family':'footwear','destination_city':'malmo','hidden':'none'},
        {'seed':42,'models_per_store':1,'store_config':{'stockout_probability':0}}, {})
    data=generate_interaction_patterns(s['bundle'],s['locations'],seed=9,config={
        'search_sections_probability':1,'list_probability':1,'spec_expand_probability':1,
        'shipping_separate_probability':1,'offer_expand_probability':1,
        'destination_form_weights':{'none':0,'single':0,'split':1},'related_limits':[0]})
    # Explicit fixture variants; this is test coverage, not cherry-picked sampling.
    retailers=[r for r in data['sites'] if r['kind']=='retailer']
    retailers[1]['destination_form']='single'
    s['interaction_patterns']=data
    return s


@pytest.fixture(scope='module')
def rt():
    with Runtime(specimen(),consent=False) as runtime:yield runtime


def fetch(rt,sid,path):return urlopen(rt.origins[sid]+path).read().decode()


def destination(rt,sid):
    d=rt.interaction_patterns['destination']
    fields={'destination_country':d['country']}
    if rt.interaction_sites[sid]['destination_form']=='split':fields.update(zip(('postcode_1','postcode_2'),d['postcode_parts']))
    else:fields['postcode']=d['postcode']
    return fields


@pytest.mark.parametrize('cls,kwargs',[(Design,{}),(Design,{'layout':'specialist','family':'footwear'}),(Ledger,{}),(Finder,{'family':'footwear'})])
def test_comparison_ambiguity_and_offer_disclosure(owner,cls,kwargs):
    before=deepcopy(owner.comparisons)
    owner.interaction_sites={'aggregator':{'search_sections':True,'offer_disclosure':'expand'}}
    design=cls(owner,**kwargs)
    html=design.render('/search',{'q':'Shoe'})[1]
    assert 'Browse related departments' in html and 'Reading and advice' in html
    assert 'http://localhost:3/reviews/shoe' in html and '/models/shoe' in html
    assert '100.00 SEK' in html
    route='/retailers' if cls is Finder else '/models/shoe'
    args={'id':'shoe'} if cls is Finder else {}
    detail=design.render(route,args)[1]
    assert '<summary>Show retailer offers</summary>' in detail
    assert 'View offer at Store A' in detail
    assert owner.comparisons==before
    assert 'http://localhost:3/reviews/shoe' not in design.render('/search',{'q':'not-a-match'})[1]


def test_quote_gating_all_public_retail_paths(rt):
    for sid in list(rt.stores)[:2]:
        offer=next(o for o in rt.offers.values() if o['retailer_id']==sid)
        sku=offer['product_id']
        for path in ('/','/search','/products/'+sku,'/products/'+sku+'/details','/quote?'+urlencode({'offer_id':offer['offer_id']})):
            html=fetch(rt,sid,path)
            assert 'id="delivered-total"' not in html
            assert 'Available for delivery' not in html
            assert 'Delivery in ' not in html
        query={'offer_id':offer['offer_id'],**destination(rt,sid)}
        html=fetch(rt,sid,'/quote?'+urlencode(query))
        assert Document(html).root.one(id='delivered-total').text()==money(rt.quote(offer['offer_id'])['total_minor'])
        assert rt.provenance['interaction_patterns_sha256']==digest(rt.interaction_patterns)


def test_wrong_address_not_a_fabricated_quote(rt):
    sid='store-001';offer=next(o for o in rt.offers.values() if o['retailer_id']==sid)
    good={'offer_id':offer['offer_id'],**destination(rt,sid)}
    for bad in ({'destination_country':'US'},{'postcode_1':'999999'},{'postcode_2':''},{'postcode':rt.interaction_patterns['destination']['postcode'],'postcode_1':'','postcode_2':''}):
        html=fetch(rt,sid,'/quote?'+urlencode({**good,**bad}))
        assert 'id="delivered-total"' not in html
        assert 'no delivery quote' in html.lower()


def test_canonical_variant_and_related_bounds(rt):
    sid='store-001';offer=next(o for o in rt.offers.values() if o['retailer_id']==sid);sku=offer['product_id']
    before=digest(rt.world);html=fetch(rt,sid,'/products/'+sku)
    root=Document(html).root
    assert root.one(id='selected-sku').text()==sku
    assert '<details><summary>Product specifications</summary>' in html or 'Read full product details' in html
    assert 'No other listed products in this section.' in html
    assert not rt.snapshot()['commerce_mutations']
    assert digest(rt.world)==before


def test_defaults_preserve_legacy_delivery():
    s=specimen();del s['interaction_patterns']
    with Runtime(s,consent=False) as rt:
        o=next(iter(rt.offers.values()));html=fetch(rt,o['retailer_id'],'/products/'+o['product_id'])
        assert 'id="delivered-total"' in html
        assert 'interaction_patterns_sha256' not in rt.provenance


def test_foreign_sidecar_rejected_before_starting_servers():
    s=specimen();s['interaction_patterns']['source_world_sha256']='wrong'
    with pytest.raises(ValueError,match='another world'):Runtime(s,consent=False)


def test_explicit_controls_survive_every_retailer_base(rt):
    for sid in rt.stores:
        o=next(o for o in rt.offers.values() if o['retailer_id']==sid)
        listing=Document(fetch(rt,sid,'/search')).root
        assert listing.find('caption') and 'Product price list' in listing.text()
        html=fetch(rt,sid,'/products/'+o['product_id'])
        assert '<details><summary>Product specifications</summary>' in html
        assert 'Read full product details' not in html
