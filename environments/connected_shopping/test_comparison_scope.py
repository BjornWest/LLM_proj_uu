from copy import deepcopy
import pytest
from .test_comparison_designs import owner
from .comparison_designs import Design
from .comparison_alternatives import Ledger,Finder
from .comparison_scope import membership


def covered():
    return {'site_id':'example','families':['footwear'],'comparison_ids':['shoe'],'listings':[{'comparison_id':'shoe','retailer_id':'b'}]}


@pytest.mark.parametrize('base',['directory','specialist','ledger','finder'])
def test_all_surfaces_obey_membership(owner,base):
    config={'attributes':{'footwear':['activity']},'price_ceiling':False,'sorting':False}
    if base in ('directory','specialist'):d=Design(owner,layout=base,family='footwear' if base=='specialist' else None,coverage=covered(),filter_config=config)
    else:d=(Ledger if base=='ledger' else Finder)(owner,family='footwear' if base=='finder' else None,coverage=covered(),filter_config=config)
    item=d.by_id['shoe'];assert d.lowest_retailers(item)[0]['retailer_id']=='b'
    assert {r['retailer_id'] for r in d.offers(item)}=={'b'}
    for path,q in [('/',{}),('/search',{}),('/models/shoe',{}),('/details',{'id':'shoe'})]:
        html=d.render(path,q)[1]
        assert 'Store A' not in html and 'Laptop 16 GB' not in html
        assert 'name="max_price"' not in html and 'name="sort"' not in html
    for q in [{'max_price':'1000'},{'sort':'price_asc'},{'f_colour_0':'1'}]:
        with pytest.raises(ValueError):d.filtered(q)
    for path,q in [('/products/l1',{}),('/details',{'id':'l1'}),('/compare',{'pick0':'shoe','pick1':'l1'})]:
        with pytest.raises(KeyError):d.render(path,q)
    if base=='finder':
        with pytest.raises(KeyError):d.render('/retailers',{'id':'l1'})


def test_tracked_without_listings_is_not_global_unavailable(owner):
    c=covered();c['listings']=[];d=Design(owner,coverage=c)
    assert d.price(d.by_id['shoe']) is None
    assert 'No matching retailer listings on this comparison site' in d.detail(d.by_id['shoe'],{})
    assert 'Store A' not in d.card(d.by_id['shoe'])
    assert len(owner.offers)==3


def test_empty_site_and_unknown_scope_fail_closed(owner):
    c=covered();c['comparison_ids']=[];c['listings']=[]
    d=Design(owner,coverage=c);assert not d.items and 'No products match' in d.search({})
    c=covered();c['comparison_ids'].append('not-in-world')
    with pytest.raises(ValueError):membership(owner,c)
    c=covered();c['listings'].append(dict(c['listings'][0]))
    with pytest.raises(ValueError):membership(owner,c)


def test_layout_does_not_determine_filters_or_coverage(owner):
    c=covered();before=deepcopy(owner.comparisons)
    a=Design(owner,coverage=c,filter_config={'attributes':{'footwear':['activity']},'price_ceiling':True,'sorting':False})
    b=Design(owner,coverage=c,filter_config={'attributes':{},'price_ceiling':False,'sorting':True})
    assert a.items==b.items and a.price(a.items[0])==b.price(b.items[0])
    assert a.facet_options('footwear') and not b.facet_options('footwear')
    assert owner.comparisons==before


def test_second_specialist_accepts_both_product_families(owner):
    for family in ['footwear','laptops']:
        d=Finder(owner,family=family)
        for item in d.items:
            assert d.render(item['path'],{})[0]==200
            assert d.render('/retailers',{'id':item['id']})[0]==200
