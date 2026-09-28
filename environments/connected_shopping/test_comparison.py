"""Small contract fixtures; no private pin or generated-world sampling required."""
from copy import deepcopy
import pytest
from .comparison import build


def world():
    return {'public':{'products':[
        {'product_id':'s1','name':'Shoe 40 black','category':'footwear','attributes':{'size_eu':40,'colour':'black','activity':'running'}},
        {'product_id':'s2','name':'Shoe 42 blue','category':'footwear','attributes':{'size_eu':42,'colour':'blue','activity':'running'}},
        {'product_id':'l1','name':'Laptop 16 GB','category':'laptops','attributes':{'ram_gb':16}}],
        'product_groups':[{'group_id':'shoe','name':'Shoe','family':'footwear','axes':[{'field':'size_eu'},{'field':'colour'}],'variants':[{'product_id':'s1'},{'product_id':'s2'}]},
                          {'group_id':'laptop','name':'Laptop','family':'laptops','axes':[],'variants':[{'product_id':'l1'}]}],
        'offers':[{'retailer_id':'a','product_id':'s1','price_minor':10000,'stock_quantity':0},
                  {'retailer_id':'a','product_id':'s2','price_minor':11000,'stock_quantity':5},
                  {'retailer_id':'b','product_id':'s2','price_minor':12000,'stock_quantity':3}],
        'comparison_listings':[{'retailer_id':'a','model_id':'shoe','advertised_price_minor':10000,'entry_product_id':'s1'},
                               {'retailer_id':'b','model_id':'shoe','advertised_price_minor':10000,'entry_product_id':'s2'}]}}


def test_model_identity_and_unmodified_other_families():
    w=world();before=deepcopy(w);items=build(w)
    assert w==before and len(items)==2
    assert items[0]['attributes']=={'activity':'running'}
    assert items[0]['path']=='/models/shoe' and len(items[0]['listings'])==2
    assert items[1]['path']=='/products/l1' and items[1]['attributes']=={'ram_gb':16}


def test_advertised_price_not_recomputed_from_stock_or_surcharged_variants():
    w=world();before=build(w)
    for o in w['public']['offers']:o['price_minor']+=99999;o['stock_quantity']=0
    assert build(w)==before


def test_legacy_from_prices_are_explicit():
    w=world();del w['public']['comparison_listings'];item=build(w)[0]
    assert item['price_basis']=='legacy_from'
    assert [r['advertised_price_minor'] for r in item['listings']]==[10000,12000]


@pytest.mark.parametrize('mutation',['duplicate','missing','bad_entry','bad_model','float_price'])
def test_invalid_bindings_fail_closed(mutation):
    w=world();r=w['public']['comparison_listings']
    if mutation=='duplicate':r.append(deepcopy(r[0]))
    elif mutation=='missing':r.pop()
    elif mutation=='bad_entry':r[0]['entry_product_id']='l1'
    elif mutation=='bad_model':r[0]['model_id']='laptop'
    else:r[0]['advertised_price_minor']=10000.0
    with pytest.raises(ValueError):build(w)
