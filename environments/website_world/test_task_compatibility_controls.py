"""Fixture authenticity and precise money; actual native controls are separate."""
from decimal import Decimal
from types import SimpleNamespace
import json
import pytest
from .task_compatibility_controls import controls


def test_supplied_price_control_preserves_exact_minor_units_and_authentic_quotes():
    scalar={'type':'object','properties':{'value':{'type':['string','null']},'evidence':{'type':['string','null']}}}
    props={name:scalar for name in ['status','product_name','retailer_name','offer_url','sku_id']}
    props.update(interpretation={'enum':['extracted']},issues={'type':'array'},source_urls={'type':'array'},
        variant={'type':'object','properties':{'size':scalar}},
        total={'anyOf':[{'type':'object','properties':{'amount':{'type':'string'},'currency':{'type':'string'},'evidence':{'type':'string'}}},{'type':'null'}]})
    grader=SimpleNamespace(schema={'type':'object','properties':props},task={},reference={'status':'match','winners':[{'offer_id':'offer'}]})
    world={'products':[{'public':{'product_id':'product','name':'Model','concept_id':'example','skus':[{'sku_id':'sku','size':'M'}]},'variant_fields':{'size':{}}}],
           'retailers':[{'name':'Shop','offers':[{'offer_id':'offer','product_id':'product','sku_id':'sku','price_minor':29}]}]}
    fixtures=controls(grader,'feature_offer',world,bindings={'retailer_offers':{'offer':{'url':'https://shop.test/product'}}})
    assert Decimal(fixtures[0]['claims']['total']['amount'])==Decimal('0.29')
    assert Decimal(fixtures[1]['claims']['total']['amount'])==Decimal('1.29')
    for fixture in fixtures:
        parsed=json.loads(fixture['answer'])
        assert parsed['total']['amount']==fixture['claims']['total']['amount']
        assert fixture['claims']['offer_url']['evidence'] in fixture['answer']
        assert fixture['claims']['total']['evidence'] in fixture['answer']
    grader.reference={'status':'no_match'};grader.task={'concept_id':'example'}
    no_match=controls(grader,'feature_offer',world,bindings={'retailer_offers':{'offer':{'url':'https://shop.test/product'}}})
    wrong=next(f for f in no_match if f['control']=='wrong');assert wrong['claims']['offer_url']['value']=='https://shop.test/product';assert wrong['claims']['sku_id']['value']=='sku'
    with pytest.raises(ValueError):controls(grader,'feature_offer',world)
