"""Manufacture, assortment and source stock joins for a single population."""
from copy import deepcopy
import pytest
from . import model,package_export,basket_quote

@pytest.fixture(scope='module')
def generated():
    return model.generate(1,concept_ids=['footwear.walking_shoes','footwear.casual_trainers','tablets.everyday_media_tablets'],
                          controls={'world_size':.4},review_count=0)

def test_one_population_has_independent_retailer_prices_and_canonical_manufacture(generated):
    w=generated;assert model.validate(w)['valid']
    assert {p['public']['family_id'] for p in w['products']}=={'footwear','tablets'}
    assert all(p['public']['facts']==p['private']['sample']['entities']['product']['facts']
               for p in w['products'] if 'sample' in p['private'])
    assert any(not r['price_trace']['matched_reference_draw'] for s in w['retailers'] for r in s['offers'])
    assert all(p['sku_status'] or p['status_provenance'].startswith('ported') for p in w['products'])

def test_exact_SKU_reference_basis_used_for_configuration_prices(generated):
    w=generated;products={p['public']['product_id']:p['public'] for p in w['products']}
    # Product allocation may legitimately leave the tablet unlisted. Test its
    # commercial price rule directly, without repairing that population draw.
    tablets=[p for p in products.values() if p['family_id']=='tablets']
    assert tablets
    for p in tablets:
        for sku in p['skus']:
            price,trace=model._offer_price(1,'price-rule-fixture',p,sku,w['config']['retailer_price'])
            assert trace['reference_basis']=='exact_sku'
            assert trace['reference_minor']==round(sku['reference_price_sek']*100)

@pytest.mark.parametrize('kind',['nonexistent_sku','foreign_source','negative_stock','missing_page'])
def test_broken_joins_rejected(generated,kind):
    w=deepcopy(generated);r=next(r for r in w['retailers'] if r['offers']);o=r['offers'][0]
    if kind=='nonexistent_sku':o['sku_id']='no-such-manufactured-SKU'
    elif kind=='foreign_source':o['stock_by_source']['foreign']=1
    elif kind=='negative_stock':o['stock_by_source'][next(iter(o['stock_by_source']))]=-1
    else:r['catalog']=[]
    with pytest.raises(ValueError):model.validate(w)

def test_new_world_has_real_basket_options_without_requiring_task_success(generated):
    w=generated;p=basket_quote.make_plan(w);quoted=0
    for r in w['retailers']:
        for o in r['offers'][:1]:
            q=basket_quote.quote(w,r['retailer_id'],[dict(line_id=o['offer_id'],offer_id=o['offer_id'],quantity=1)],plan=p)
            assert q['world_id']==w['world_id'];quoted+=1
    assert quoted

def test_task_concentration_and_unaccepted_slice_rejected():
    with pytest.raises(ValueError):model.generate(1,concept_ids=['tablets.everyday_media_tablets'])
    with pytest.raises(ValueError):model.generate(1,concept_ids=['office_chairs.office_task_chairs'],tasks=[])

def test_sparse_empty_world_is_retained():
    w=model.generate(1,concept_ids=['footwear.casual_trainers'],tasks=[],controls={'world_size':0},review_count=0)
    assert w['summary']['products']==0 and w['summary']['retailers']==0
